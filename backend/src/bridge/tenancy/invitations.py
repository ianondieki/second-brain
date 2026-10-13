"""Inviting people into an organisation (REQ-TEN-02; docs/platform/tasks/P28.md track C; revision 0015's call order).

- **Invite** (``invite``, an owner or admin): one invitation per address and organisation, for the roles the inviter
  may grant (only an owner invites an owner or a signatory: 403 ``protected_role``, revision 0001's rule). Under a
  transaction advisory lock per organisation: an active member's address is 409 ``already_member``; an expired open
  invitation to the address is revoked first (an index cannot read the clock, so it would block the address); an
  unexpired open one is 409 ``already_invited`` (resend it instead); at most ``MAX_OPEN`` unexpired open invitations per
  organisation (409 ``too_many_invitations``). The token is ``TOKEN_BYTES`` random bytes (``bridge.auth.crypto``,
  URL-safe base64); only its SHA-256 is stored, and it expires ``VALID_DAYS`` days on the shared clock. The token is
  returned to the router for the email only, never in a response, an audit row or a log line.
- **Resend** (``resend``): the open invitation is revoked and a new one inserted for the same address and roles, in
  one transaction (a new id, token, creation time and expiry: revision 0015's ``expires_within_30_days`` counts from
  the creation, so an in-place token update would fail on an old invitation); the old link dies at once. An expired
  one counts against the cap again. **Revoke** (``revoke``): ``revoked_at`` (the database's clock). A closed (accepted
  or revoked) invitation is 409 ``invitation_closed``; another organisation's or an unknown one 404.
- **Preview** (``preview``, anyone holding the link): the organisation's name and the roles of an open invitation
  (``app_invitation_preview``), else nothing.
- **Accept** (``accept``, signed in): ``app_accept_invitation`` checks that the invitation is open and that the user's
  verified address is the invitation's (case-insensitive), then inserts or reactivates the membership. Unknown, spent,
  revoked, resent-over or expired: 404; another address or an unverified one: 403 ``invitation_email_mismatch``;
  already an active member: 409 ``already_member``.

Each step is audited on the organisation's chain by ids (the invitation, the membership) and roles: never the token
and never the address.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth.crypto import new_token, token_hash
from bridge.auth.models import User
from bridge.auth.sessions import LiveSession
from bridge.errors import ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.models.enums import MembershipStatus, OrgRole
from bridge.notifications.email import is_mailbox
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.invitation_email import VALID_DAYS
from bridge.tenancy.models import Invitation, Membership, Organization
from bridge.tenancy.team import PROTECTED, open_invitations
from bridge.tenancy.team_schemas import InvitationAccepted, InvitationPreview, OrgInvitation

MAX_OPEN: Final = 20  # unexpired open invitations per organisation
TOKEN_CHARS: Final = 43  # bridge.auth.crypto.new_token: URL-safe base64 of 32 random bytes, unpadded
_TOKEN: Final = re.compile(rf"[A-Za-z0-9_-]{{{TOKEN_CHARS}}}")
_LOCK: Final = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_EXPIRY: Final = func.app_clock_now() + func.make_interval(0, 0, 0, VALID_DAYS)
_PREVIEW: Final = text("SELECT org_name, CAST(roles AS text[]) AS roles FROM app_invitation_preview(:hash)")
_ACCEPT: Final = text("SELECT app_accept_invitation(:hash, :user)")
# [[COPY-REVIEW]] the API's refusals (the web app shows its own words).
PROTECTED_ROLE: Final = "Only an owner can invite an owner or a signatory."
ALREADY_MEMBER: Final = "This person is already a member of the organisation."
ALREADY_INVITED: Final = "This address already has an open invitation. Resend it instead."
TOO_MANY: Final = f"The organisation has {MAX_OPEN} open invitations. Revoke one or wait for answers first."
CLOSED: Final = "This invitation was already accepted or revoked."
MISMATCH: Final = "This invitation is for another email address. Sign in with the address it was sent to."
NO_INVITATION: Final = "This invitation link is not valid any more. Ask for a new one."
INVALID_EMAIL: Final = "Enter one plain email address."


@dataclass(frozen=True, slots=True)
class Issued:
    """An invitation as its owner or admin reads it, with the link's token (for the email only)."""

    invitation: OrgInvitation
    token: str


def normalise_email(email: str) -> str:
    return email.strip().lower()


def token_digest(token: str) -> bytes | None:
    """The SHA-256 a well-formed token stands for; None for anything else (no database read for it)."""
    if not _TOKEN.fullmatch(token):
        return None
    return token_hash(token)


def check_grantable(org: OrgContext, roles: set[OrgRole]) -> None:
    """403 ``protected_role`` when the roles include owner or signatory and the caller is not an owner."""
    if roles & PROTECTED and OrgRole.OWNER not in org.roles:
        raise forbidden("protected_role", PROTECTED_ROLE)


def _sqlstate(exc: DBAPIError) -> str | None:
    state: str | None = getattr(exc.orig, "sqlstate", None)
    return state


async def _lock(db: AsyncSession, org_id: UUID) -> None:
    await db.execute(_LOCK, {"key": f"invitations:{org_id}"})


def _open() -> list[ColumnElement[bool]]:
    return [Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None)]


async def _open_unexpired(db: AsyncSession, org_id: UUID, *, email: str | None = None) -> int:
    query = (
        select(func.count())
        .select_from(Invitation)
        .where(Invitation.org_id == org_id, *_open(), Invitation.expires_at > func.app_clock_now())
    )
    if email is not None:
        query = query.where(Invitation.email == email)
    return int(await db.scalar(query) or 0)


async def _one(db: AsyncSession, org_id: UUID, invitation_id: UUID) -> OrgInvitation:
    [shown] = await open_invitations(db, org_id, only=invitation_id)
    return shown


async def _insert(db: AsyncSession, org: OrgContext, address: str, roles: set[OrgRole]) -> tuple[UUID, str]:
    """Insert an open invitation from the caller with a new token (the database stamps ``created_at``); its id and
    token. ``uq_invitations_open`` is the race of two invitations to one address: 409 ``already_invited``."""
    token, invitation_id = new_token(), uuid7()
    try:
        await db.execute(
            insert(Invitation).values(
                id=invitation_id,
                org_id=org.org_id,
                email=address,
                roles=sorted(roles),
                token_hash=token_hash(token),
                invited_by=org.live.user.id,
                expires_at=_EXPIRY,
            )
        )
    except DBAPIError as exc:
        if _sqlstate(exc) == "23505":
            raise ApiError(409, "already_invited", ALREADY_INVITED) from exc
        raise
    return invitation_id, token


async def invite(db: AsyncSession, org: OrgContext, email: str, roles: list[OrgRole]) -> Issued:
    """Create the invitation (see the module docstring), in the caller's transaction (the router commits)."""
    wanted = set(roles)
    check_grantable(org, wanted)
    address = normalise_email(email)
    if not is_mailbox(address):  # the mailer sends to one bare address only
        raise ApiError(422, "invalid_email", INVALID_EMAIL)
    await _lock(db, org.org_id)
    member = await db.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.org_id == org.org_id, Membership.status == MembershipStatus.ACTIVE, User.email == address)
    )
    if member is not None:
        raise ApiError(409, "already_member", ALREADY_MEMBER)
    await db.execute(  # an expired open invitation would block the address (uq_invitations_open): revoke it first
        update(Invitation)
        .where(
            Invitation.org_id == org.org_id,
            Invitation.email == address,
            *_open(),
            Invitation.expires_at <= func.app_clock_now(),
        )
        .values(revoked_at=func.now())
        .execution_options(synchronize_session=False)
    )
    if await _open_unexpired(db, org.org_id, email=address):
        raise ApiError(409, "already_invited", ALREADY_INVITED)
    if await _open_unexpired(db, org.org_id) >= MAX_OPEN:
        raise ApiError(409, "too_many_invitations", TOO_MANY, limit=MAX_OPEN)
    invitation_id, token = await _insert(db, org, address, wanted)
    await audit(
        db,
        "org.invitation_created",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="invitation",
        subject_id=invitation_id,
        payload={"invitation_id": str(invitation_id), "roles": sorted(r.value for r in wanted)},
    )
    return Issued(await _one(db, org.org_id, invitation_id), token)


async def _open_invitation(db: AsyncSession, org: OrgContext, invitation_id: UUID) -> Invitation:
    """The organisation's invitation (404 otherwise), open (409 ``invitation_closed`` otherwise), whose roles the caller
    may grant (403 ``protected_role``)."""
    found: Invitation | None = await db.scalar(
        select(Invitation).where(Invitation.id == invitation_id, Invitation.org_id == org.org_id)
    )
    if found is None:
        raise not_found()
    if found.accepted_at is not None or found.revoked_at is not None:
        raise ApiError(409, "invitation_closed", CLOSED)
    check_grantable(org, {OrgRole(r) for r in found.roles})
    return found


async def resend(db: AsyncSession, org: OrgContext, invitation_id: UUID) -> Issued:
    """Replace an open invitation with a new one (a new id, token, creation and expiry: revision 0015's 30-day CHECK
    counts from the creation), in the caller's transaction (the router commits): the old link dies with it."""
    await _lock(db, org.org_id)
    found = await _open_invitation(db, org, invitation_id)
    expired = bool(await db.scalar(select(func.app_clock_now() >= found.expires_at)))
    if expired and await _open_unexpired(db, org.org_id) >= MAX_OPEN:
        raise ApiError(409, "too_many_invitations", TOO_MANY, limit=MAX_OPEN)
    if not await _close(db, found.id):  # accepted or revoked meanwhile
        raise ApiError(409, "invitation_closed", CLOSED)
    new_id, token = await _insert(db, org, str(found.email), {OrgRole(r) for r in found.roles})
    await audit(
        db,
        "org.invitation_resent",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="invitation",
        subject_id=new_id,
        payload={"invitation_id": str(new_id), "replaces": str(found.id)},
    )
    return Issued(await _one(db, org.org_id, new_id), token)


async def _close(db: AsyncSession, invitation_id: UUID) -> bool:
    """Revoke an open invitation (the database stamps ``revoked_at``); False when it was no longer open."""
    changed = await db.execute(
        update(Invitation)
        .where(Invitation.id == invitation_id, *_open())
        .values(revoked_at=func.now())
        .returning(Invitation.id)
        .execution_options(synchronize_session=False)
    )
    return changed.first() is not None


async def revoke(db: AsyncSession, org: OrgContext, invitation_id: UUID) -> None:
    """Revoke an open invitation, in the caller's transaction (the router commits)."""
    found = await _open_invitation(db, org, invitation_id)
    if not await _close(db, found.id):
        raise ApiError(409, "invitation_closed", CLOSED)
    await audit(
        db,
        "org.invitation_revoked",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="invitation",
        subject_id=found.id,
        payload={"invitation_id": str(found.id)},
    )


async def preview(db: AsyncSession, token: str) -> InvitationPreview | None:
    """The organisation's name and the roles of the open invitation ``token`` opens, else None."""
    digest = token_digest(token)
    if digest is None:
        return None
    row = (await db.execute(_PREVIEW, {"hash": digest})).one_or_none()
    if row is None:
        return None
    return InvitationPreview(org_name=row.org_name, roles=sorted(OrgRole(r) for r in row.roles))


async def accept(db: AsyncSession, live: LiveSession, token: str) -> InvitationAccepted:
    """Accept the invitation ``token`` opens as the signed-in user, in the caller's transaction (the router commits)."""
    digest = token_digest(token)
    if digest is None:
        raise not_found(NO_INVITATION)
    try:
        org_id: UUID = await db.scalar(_ACCEPT, {"hash": digest, "user": live.user.id})
    except DBAPIError as exc:
        state = _sqlstate(exc)
        await db.rollback()
        if state == "P0002":  # no_data_found: unknown, spent, revoked, resent-over or expired
            raise not_found(NO_INVITATION) from exc
        if state == "42501":  # insufficient_privilege: another address, or an unverified one
            raise forbidden("invitation_email_mismatch", MISMATCH) from exc
        if state == "23505":  # unique_violation: already an active member
            raise ApiError(409, "already_member", ALREADY_MEMBER) from exc
        raise
    joined = (
        await db.execute(
            select(Membership.id, Membership.roles, Organization.legal_name)
            .join(Organization, Organization.id == Membership.org_id)
            .where(Membership.org_id == org_id, Membership.user_id == live.user.id)
        )
    ).one()
    roles = sorted(OrgRole(r) for r in joined.roles)
    await audit(
        db,
        "org.invitation_accepted",
        actor_user_id=live.user.id,
        org_id=org_id,
        subject_type="membership",
        subject_id=joined.id,
        payload={"user_id": str(live.user.id), "roles": [r.value for r in roles]},
    )
    return InvitationAccepted(org_id=org_id, org_name=joined.legal_name, roles=roles)
