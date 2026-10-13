"""The organisation's Team API (REQ-TEN-02; docs/platform/tasks/P28.md track C). Non-members get 404, members lacking a
role 403 (``bridge.tenancy.deps``).

- ``GET /api/orgs/{org_id}/team`` (any member): ``OrgTeam``.
- ``POST /api/orgs/{org_id}/invitations`` ``{email, roles}`` (an owner or admin, a fresh second factor, an organisation
  at least E1): 201 and the invitation link emailed (``bridge.tenancy.invitation_email``) after the commit. 403
  ``protected_role`` (an admin inviting, or re-inviting over, an owner or a signatory), ``org_not_verified``,
  ``step_up_required``; 409 ``already_member``, ``already_invited``, ``too_many_invitations``; 402 ``plan_limit``
  (``seats``); 422 ``invalid_email``; 429 ``rate_limited`` with ``Retry-After`` (``bridge.tenancy.invitation_limits``).
- ``POST /api/orgs/{org_id}/invitations/{invitation_id}/resend`` (the same, and 409 ``already_member``): the invitation
  is replaced by a new one (a new ``id``, the response's) and its link emailed; the old link is dead.
- ``DELETE /api/orgs/{org_id}/invitations/{invitation_id}`` (an owner or admin): 204. 409 ``invitation_closed``.
- ``DELETE /api/orgs/{org_id}/members/{user_id}`` (an owner or admin, a fresh second factor): 204. 403
  ``protected_member``, 409 ``last_owner``; their open assignments are closed.
- ``PUT /api/orgs/{org_id}/niche-defaults`` ``{items: [{niche_slug, user_id}]}`` (an owner or admin): the set. 422
  ``unknown_niche``, ``duplicate_niche``, ``invalid_default_reviewer``.
- ``PUT /api/orgs/{org_id}/escalation-contact`` ``{user_id|null}`` (an owner or admin). 422 ``invalid_member``.
- ``GET /api/invitations/{token}`` (public, no session, no cookie, ``no-store``): ``InvitationPreview``; one 404 for a
  malformed, unknown, spent, revoked or expired link. At most ``PREVIEWS_PER_MINUTE`` reads a minute per visitor's
  global address, or ``SHARED_PREVIEWS_PER_MINUTE`` for all visitors behind a shared one (429 ``rate_limited``).
- ``POST /api/invitations/{token}/accept`` (signed in): ``InvitationAccepted``. 404, 403
  ``invitation_email_mismatch``, 409 ``already_member``, 402 ``plan_limit`` (``seats``, re-checked with the joiner).

Public demo (REQ-FND-04): the membership changes are locked (``bridge.public_demo.LOCKED``: invite, resend, revoke,
accept, remove); the niche defaults, the escalation contact and the reads stay open. The token is a path segment, so
the access log redacts it (``bridge.logging.SECRET_SEGMENTS``).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth import throttle
from bridge.auth.deps import CurrentSession, Db, EmailDep, SettingsDep, client_ip, ensure_step_up
from bridge.auth.models import User
from bridge.config import Settings
from bridge.engagements.calendar import local_date
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.notifications.email import EmailProvider
from bridge.public_demo import LOCKED
from bridge.tenancy import invitation_email, invitations, team, team_settings
from bridge.tenancy.deps import OrgAdmin, OrgContext, OrgMember
from bridge.tenancy.models import Organization
from bridge.tenancy.team_schemas import (
    EscalationContact,
    EscalationContactIn,
    InvitationAccepted,
    InvitationPreview,
    NicheDefault,
    NicheDefaultsIn,
    OrgInvitation,
    OrgInvitationIn,
    OrgTeam,
)

router = APIRouter(tags=["organisations"], responses=ERROR_RESPONSES)
ORG: Final = "/api/orgs/{org_id}"
PREVIEW_PURPOSE: Final = "invitation-preview"
SHARED_PREVIEW_PURPOSE: Final = "invitation-preview-shared"
PREVIEWS_PER_MINUTE: Final = 30  # per visitor's global address
SHARED_PREVIEWS_PER_MINUTE: Final = 300  # all visitors behind a non-global or trusted-proxy address, together
NO_STORE: Final = "no-store"


async def allow_preview(db: AsyncSession, settings: Settings, ip: str) -> bool:
    """Count one preview (the caller commits) and say whether it is within the minute's limit: per address when the
    address tells visitors apart (``throttle.per_visitor``, the persona sign-in's rule), else in one shared, larger
    bucket, so a client behind a shared address cannot lock every visitor out with a few requests."""
    secret = settings.secret_key.get_secret_value()
    if throttle.per_visitor(ip, settings.trusted_proxies):
        keys, limit = throttle.ip_keys(secret, PREVIEW_PURPOSE, ip), PREVIEWS_PER_MINUTE
    else:
        keys, limit = throttle.ip_keys(secret, SHARED_PREVIEW_PURPOSE, "shared"), SHARED_PREVIEWS_PER_MINUTE
    if await throttle.ip_blocked(db, keys, limit=limit):
        return False
    throttle.record(db, keys, succeeded=True)
    return True


@router.get(f"{ORG}/team")
async def get_team(db: Db, org: OrgMember) -> OrgTeam:
    """Members with their roles, open invitations (owners and admins), the default reviewer per niche and the
    escalation contact."""
    return await team.team_view(db, org)


async def _email_link(
    db: AsyncSession,
    background: BackgroundTasks,
    request: Request,
    settings: Settings,
    provider: EmailProvider,
    org: OrgContext,
    issued: invitations.Issued,
) -> None:
    """Queue the invitation email (sent after the response, once the invitation has committed)."""
    org_name = await db.scalar(select(Organization.legal_name).where(Organization.id == org.org_id))
    invitee_locale = await db.scalar(select(User.locale).where(User.email == issued.invitation.email))
    locale = invitation_email.locale_of(invitee_locale or org.live.user.locale)
    facts = invitation_email.InvitationFacts(
        product=settings.product_name,
        inviter=org.live.user.display_name,
        org_name=str(org_name or ""),
        roles=issued.invitation.roles,
        base_url=settings.public_base_url,
        token=issued.token,
        expires_on=local_date(issued.invitation.expires_at),
    )
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    background.add_task(
        invitation_email.deliver,
        factory,
        provider,
        org_id=org.org_id,
        inviter_id=org.live.user.id,
        address=issued.invitation.email,
        wording=invitation_email.render(facts, locale),
    )


@router.post(f"{ORG}/invitations", status_code=201, dependencies=[LOCKED])  # not in the public demo (REQ-FND-04)
async def post_invitation(
    body: OrgInvitationIn,
    request: Request,
    background: BackgroundTasks,
    db: Db,
    settings: SettingsDep,
    provider: EmailDep,
    org: OrgAdmin,
) -> OrgInvitation:
    """Invite someone by email with roles: a link valid for 7 days is emailed to them."""
    ensure_step_up(org.live, settings)
    issued = await invitations.invite(db, settings, org, str(body.email), body.roles, client_ip(request))
    await _email_link(db, background, request, settings, provider, org, issued)
    await db.commit()
    return issued.invitation


@router.post(f"{ORG}/invitations/{{invitation_id}}/resend", dependencies=[LOCKED])
async def resend_invitation(
    invitation_id: UUID,
    request: Request,
    background: BackgroundTasks,
    db: Db,
    settings: SettingsDep,
    provider: EmailDep,
    org: OrgAdmin,
) -> OrgInvitation:
    """Replace the invitation with a new one (a new id) and email its link (valid for 7 days); the previous link stops
    working at once."""
    ensure_step_up(org.live, settings)
    issued = await invitations.resend(db, settings, org, invitation_id, client_ip(request))
    await _email_link(db, background, request, settings, provider, org, issued)
    await db.commit()
    return issued.invitation


@router.delete(f"{ORG}/invitations/{{invitation_id}}", status_code=204, dependencies=[LOCKED])
async def revoke_invitation(invitation_id: UUID, db: Db, org: OrgAdmin) -> Response:
    """Revoke an open invitation: its link stops working."""
    await invitations.revoke(db, org, invitation_id)
    await db.commit()
    return Response(status_code=204)


@router.delete(f"{ORG}/members/{{user_id}}", status_code=204, dependencies=[LOCKED])
async def remove_member(user_id: UUID, db: Db, settings: SettingsDep, org: OrgAdmin) -> Response:
    """Remove a member: their open assignments are cleared, and so are their niche defaults and escalation seat."""
    ensure_step_up(org.live, settings)
    await team.remove_member(db, org, user_id)
    await db.commit()
    return Response(status_code=204)


@router.put(f"{ORG}/niche-defaults")  # open in the public demo: no membership change
async def put_niche_defaults(body: NicheDefaultsIn, db: Db, org: OrgAdmin) -> list[NicheDefault]:
    """Replace the default reviewer per niche (a reviewer, signatory or admin); niches left out lose theirs."""
    out = await team_settings.set_niche_defaults(db, org, body.items)
    await db.commit()
    return out


@router.put(f"{ORG}/escalation-contact")  # open in the public demo: no membership change
async def put_escalation_contact(body: EscalationContactIn, db: Db, org: OrgAdmin) -> EscalationContact | None:
    """Name the member who hears of escalations with the admins, or nobody (``user_id`` null)."""
    out = await team_settings.set_escalation_contact(db, org, body.user_id)
    await db.commit()
    return out


@router.get("/api/invitations/{token}", openapi_extra={"security": []})  # no session: the token is the capability
async def get_invitation(
    token: str, request: Request, response: Response, db: Db, settings: SettingsDep
) -> InvitationPreview:
    """What an invitation link offers before sign-in: the organisation's name and the roles. Every request counts
    against its client address first (a malformed token included); then one 404 for any link that opens nothing."""
    response.headers["Cache-Control"] = NO_STORE
    allowed = await allow_preview(db, settings, client_ip(request))
    await db.commit()
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many requests from this address. Wait a minute and try again.")
    found = await invitations.preview(db, token)  # None for a malformed, unknown, spent, revoked or expired token
    if found is None:
        raise not_found(invitations.NO_INVITATION)
    return found


@router.post("/api/invitations/{token}/accept", dependencies=[LOCKED])  # not in the public demo (REQ-FND-04)
async def accept_invitation(
    token: str, response: Response, db: Db, settings: SettingsDep, live: CurrentSession
) -> InvitationAccepted:
    """Join the organisation with the invitation's roles (signed in with the address it was sent to)."""
    response.headers["Cache-Control"] = NO_STORE
    out = await invitations.accept(db, settings, live, token)
    await db.commit()
    return out
