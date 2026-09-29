"""Who may open a proposal's Tier 2: ``can_view_tier2`` (REQ-REPO-01, REQ-SEC-01; docs/spec/06 6.1, docs/spec/10).

One predicate, one answer: the first condition that fails, or the access with what the render needs. In order:

1. ``FEATURE_TIER2_ENABLED`` (403 ``tier2_disabled``);
2. the proposal is published, clear of moderation holds and has a registered current version (else 404, as for its
   teaser); its owner may always open their own Tier 2 (a render of the owner is never logged);
3. the viewer is an active member of the organisation named in the path (else 404: its existence is not confirmed);
4. the organisation is E2 and not suspended;
5. the viewer holds the reviewer, signatory or admin role; their email address is verified and at exactly the
   organisation's verified domain; TOTP is enrolled and the session's second factor is at most
   ``STEP_UP_MAX_AGE_HOURS`` old (the step-up);
6. the current Master Enterprise Terms were accepted for the organisation;
7. a live Tier-2 ``disclosure_grant`` for (proposal, organisation) from the owner's policy, never revoked;
8. no ``WITHDRAWN``, ``DECLINED`` or ``TERMINATED`` engagement for (proposal, organisation) (as
   ``app_tier2_granted``: an ``EXPIRED`` or ``CLOSED`` engagement, also ended, keeps the access);
9. this person accepted the current Evaluation NDA for this proposal under this organisation.

The NDA is last because it is the one condition the viewer meets on their own: the NDA step is offered only when
nothing else is missing (accepting it needs conditions 1 to 8, ``check_nda=False``). The facts are read under the
viewer's own Row-Level Security; then the database half, ``app_tier2_granted(proposal, version, org)`` (revision
0002), must agree. It also requires that the Master Enterprise Terms were accepted by the organisation's approved E2
claimant or an active signatory; RLS hides the claims from a reviewer, so this module checks only that the current
version was accepted, and a refusal by the database after every condition here passed is reported as that condition.

Every refusal answers 403 (404 for 2 and 3) and appends a ``tier2.access_denied`` audit event naming the condition,
committed before the error is raised. Every route tagged ``tier2`` runs ``tier2_gate`` first: a session waiting
for its second factor gets 401 ``mfa_required``; then tenancy, then the flag (a signed-in non-member of the path's
organisation gets 404 as on every organisation route, AC-SEC-1; anyone else gets 403 ``tier2_disabled`` while the flag
is off, whatever their NDA state, AC-SEC-2). Nothing Tier-2 is read
before the predicate passes, and the Tier-2 row itself is then read as ``tier2_reader``, whose policy is
``app_tier2_granted`` again. On the owner's own route (no organisation in the path) the owner is the only viewer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth import sessions
from bridge.auth.deps import Db, SettingsDep, optional_session
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.errors import ApiError
from bridge.models.enums import EngagementState, GrantStatus, OrgRole, OrgVerification

DENIED: Final = "tier2.access_denied"
VIEWER_ROLES: Final = frozenset({OrgRole.REVIEWER, OrgRole.SIGNATORY, OrgRole.ADMIN})
ENDED_STATES: Final = frozenset({EngagementState.WITHDRAWN, EngagementState.DECLINED, EngagementState.TERMINATED})
# The owner's display name replaces their handle on a render once the organisation approved to proceed (docs/spec/06
# 6.1: "pseudonymous handle until INTEREST_CONFIRMED"): once the engagement's event chain (revision 0003) has entered
# one of these states, whatever state it is in now (a pause, a dispute or an expiry after it keeps the name). Not
# PROCUREMENT_ROUTE: a public entity determines its route before it approves to proceed.
REVEALED_STATES: Final = frozenset(
    {
        EngagementState.INTEREST_CONFIRMED,
        EngagementState.CONTACT_MADE,
        EngagementState.NDA_PENDING,
        EngagementState.NDA_SIGNED,
        EngagementState.NEGOTIATION,
        EngagementState.AGREEMENT_SIGNING,
        EngagementState.IN_IMPLEMENTATION,
        EngagementState.DELIVERED,
        EngagementState.SIGN_OFF,
        EngagementState.PAYMENT_FINAL,
        EngagementState.CLOSED,
    }
)


class Condition(StrEnum):
    """A failed condition of ``can_view_tier2``; the value is the error code (404s answer ``not_found``)."""

    FEATURE_DISABLED = "tier2_disabled"
    PROPOSAL_UNAVAILABLE = "proposal_unavailable"
    NOT_MEMBER = "not_member"
    ORG_NOT_E2 = "org_not_e2"
    ORG_SUSPENDED = "org_suspended"
    ROLE = "role_not_permitted"
    EMAIL_UNVERIFIED = "email_unverified"
    DOMAIN = "domain_mismatch"
    TOTP = "mfa_enrolment_required"
    STEP_UP = "step_up_required"
    MASTER_TERMS = "master_terms_required"
    NO_GRANT = "grant_required"
    GRANT_REVOKED = "grant_revoked"
    ENGAGEMENT_ENDED = "engagement_ended"
    NDA = "nda_required"


NOT_FOUND_CONDITIONS: Final = frozenset({Condition.PROPOSAL_UNAVAILABLE, Condition.NOT_MEMBER})
# [[COPY-REVIEW]] what a viewer reads when the full proposal stays closed.
MESSAGES: Final = {
    Condition.FEATURE_DISABLED: "Full proposals are not available on this server yet.",
    Condition.ORG_NOT_E2: "Only organisations verified with registration documents (E2) can open full proposals.",
    Condition.ORG_SUSPENDED: "Your organisation's access to full proposals is suspended.",
    Condition.ROLE: "Ask an admin of your organisation for the reviewer, signatory or admin role.",
    Condition.EMAIL_UNVERIFIED: "Confirm your email address to open full proposals.",
    Condition.DOMAIN: "Sign in with your address at your organisation's verified domain to open full proposals.",
    Condition.TOTP: "Turn on two-step sign-in to open full proposals.",
    Condition.STEP_UP: "Confirm with your authenticator code to continue.",
    Condition.MASTER_TERMS: "Your organisation's signatory must accept the current Master Enterprise Terms first.",
    Condition.NO_GRANT: "The owner has not shared the full proposal with your organisation.",
    Condition.GRANT_REVOKED: "The owner stopped sharing the full proposal with your organisation.",
    Condition.ENGAGEMENT_ENDED: "This engagement has ended, so the full proposal is closed to your organisation.",
    Condition.NDA: "Accept the Evaluation NDA for this proposal to open it.",
}


class GrantState(StrEnum):
    LIVE = "live"
    REVOKED = "revoked"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class Target:
    """The proposal's current registered version (Tier 1 only)."""

    proposal_id: UUID
    version_id: UUID
    owner_id: UUID
    version_no: int
    cert_id: str
    registered_at: datetime
    owner_handle: str
    title: str


@dataclass(frozen=True, slots=True)
class Facts:
    """What the predicate reads for one viewer, organisation and proposal (under the viewer's RLS)."""

    enabled: bool
    target: Target | None
    is_owner: bool = False
    roles: frozenset[OrgRole] | None = None  # None: no active membership
    verification: OrgVerification | None = None
    suspended: bool = False
    verified_domain: str | None = None
    email: str = ""
    email_verified: bool = False
    totp_enrolled: bool = False
    mfa_fresh: bool = False
    master_terms: bool = False
    grant: GrantState = GrantState.NONE
    engagement: EngagementState | None = None
    owner_named: bool = False  # the engagement has reached one of REVEALED_STATES
    nda_acceptance_id: UUID | None = None


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def first_failure(facts: Facts, *, check_nda: bool = True) -> Condition | None:
    """The first condition ``facts`` fail, in the module's order; None when the viewer may open Tier 2."""
    if not facts.enabled:
        return Condition.FEATURE_DISABLED
    if facts.target is None:
        return Condition.PROPOSAL_UNAVAILABLE
    if facts.is_owner:
        return None
    rules: tuple[tuple[bool, Condition], ...] = (
        (facts.roles is not None, Condition.NOT_MEMBER),
        (facts.verification == OrgVerification.E2, Condition.ORG_NOT_E2),
        (not facts.suspended, Condition.ORG_SUSPENDED),
        (bool(facts.roles and facts.roles & VIEWER_ROLES), Condition.ROLE),
        (facts.email_verified, Condition.EMAIL_UNVERIFIED),
        (
            facts.verified_domain is not None and email_domain(facts.email) == facts.verified_domain.lower(),
            Condition.DOMAIN,
        ),
        (facts.totp_enrolled, Condition.TOTP),
        (facts.mfa_fresh, Condition.STEP_UP),
        (facts.master_terms, Condition.MASTER_TERMS),
        (facts.grant != GrantState.REVOKED, Condition.GRANT_REVOKED),
        (facts.grant == GrantState.LIVE, Condition.NO_GRANT),
        (facts.engagement not in ENDED_STATES, Condition.ENGAGEMENT_ENDED),
        (not check_nda or facts.nda_acceptance_id is not None, Condition.NDA),
    )
    return next((condition for holds, condition in rules if not holds), None)


@dataclass(frozen=True, slots=True)
class Access:
    """A viewer allowed in: the owner, or a member of ``org_id`` meeting every condition."""

    target: Target
    owner: bool
    org_id: UUID | None = None
    engagement: EngagementState | None = None
    nda_acceptance_id: UUID | None = None
    nda_template_version: str | None = None
    reveals_owner: bool = False  # the engagement has reached REVEALED_STATES: the render names the owner


# --- facts -----------------------------------------------------------------------------------------------------------

_TARGET = text(
    "SELECT p.id, p.owner_id, p.status, p.moderation_state, v.id AS version_id, v.status AS version_status,"
    " v.version_no, v.cert_id, v.registered_at, v.owner_handle, v.title"
    " FROM proposals p JOIN proposal_versions v ON v.id = p.current_version_id WHERE p.id = :proposal"
)
_MEMBERSHIP = text(
    "SELECT CAST(roles AS text[]) FROM memberships WHERE org_id = :org AND user_id = :user AND status = 'active'"
)
_ORG = text(
    "SELECT verification, suspended_at IS NOT NULL AS suspended, verified_domain FROM organizations WHERE id = :org"
)
_MASTER_TERMS = text(
    "SELECT EXISTS (SELECT 1 FROM legal_acceptances WHERE org_id = :org"
    " AND legal_template_id = app_current_legal_template('master_enterprise_terms'))"
)
_GRANTS = text(
    "SELECT status, revoked_at FROM disclosure_grants WHERE proposal_id = :proposal AND org_id = :org AND tier >= 2"
)
_ENGAGEMENT = text(
    "SELECT e.state, EXISTS (SELECT 1 FROM engagement_events ev WHERE ev.engagement_id = e.id"
    " AND ev.to_state = ANY (CAST(:revealed AS engagement_state[]))) AS revealed"
    " FROM engagements e WHERE e.proposal_id = :proposal AND e.org_id = :org"
)
_NDA = text(
    "SELECT a.id, t.version FROM nda_acceptances a JOIN nda_templates t ON t.id = a.nda_template_id"
    " WHERE a.user_id = :user AND a.org_id = :org AND a.proposal_id = :proposal"
    " AND a.nda_template_id = app_current_nda_template('evaluation') ORDER BY a.accepted_at, a.id LIMIT 1"
)
_GRANTED = text("SELECT app_tier2_granted(:proposal, :version, :org)")


def _target(row: Any, *, owner: bool) -> Target | None:
    if row is None or row.version_status != "registered":
        return None
    if not owner and (row.status != "published" or row.moderation_state != "clear"):
        return None
    return Target(
        proposal_id=row.id,
        version_id=row.version_id,
        owner_id=row.owner_id,
        version_no=row.version_no,
        cert_id=row.cert_id,
        registered_at=row.registered_at,
        owner_handle=row.owner_handle,
        title=row.title,
    )


def _grant_state(rows: list[Any]) -> GrantState:
    if any(r.status == GrantStatus.ACTIVE and r.revoked_at is None for r in rows):
        return GrantState.LIVE
    if any(r.status == GrantStatus.REVOKED or r.revoked_at is not None for r in rows):
        return GrantState.REVOKED
    return GrantState.NONE


async def gather(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, *, proposal_id: UUID, org_id: UUID | None
) -> tuple[Facts, str | None]:
    """The facts for ``live``'s user, ``org_id`` (None: the owner's own route) and ``proposal_id``, and the accepted
    NDA's template version. Binds the request to the organisation once the viewer is an active member of it."""
    user = live.user
    enabled = settings.feature_tier2_enabled
    if not enabled:
        return Facts(enabled=False, target=None), None
    row = (await db.execute(_TARGET, {"proposal": proposal_id})).one_or_none()
    is_owner = row is not None and row.owner_id == user.id
    target = _target(row, owner=is_owner)
    if target is None or is_owner:
        return Facts(enabled=True, target=target, is_owner=is_owner), None
    membership = None
    if org_id is not None:
        membership = (await db.execute(_MEMBERSHIP, {"org": org_id, "user": user.id})).scalar_one_or_none()
    if org_id is None or membership is None:
        return Facts(enabled=True, target=target), None
    await bind_tenant(db, user_id=user.id, org_id=org_id)
    org = (await db.execute(_ORG, {"org": org_id})).one()
    keys = {"org": org_id, "proposal": proposal_id}
    grants = list((await db.execute(_GRANTS, keys)).all())
    nda = (await db.execute(_NDA, keys | {"user": user.id})).one_or_none()
    revealed = [state.value for state in REVEALED_STATES]
    engagement = (await db.execute(_ENGAGEMENT, keys | {"revealed": revealed})).one_or_none()
    facts = Facts(
        enabled=True,
        target=target,
        roles=frozenset(OrgRole(r) for r in membership),
        verification=OrgVerification(org.verification),
        suspended=org.suspended,
        verified_domain=org.verified_domain,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        totp_enrolled=user.totp_enabled_at is not None,
        mfa_fresh=sessions.mfa_fresh(live.row, timedelta(hours=settings.step_up_max_age_hours)),
        master_terms=bool((await db.execute(_MASTER_TERMS, {"org": org_id})).scalar_one()),
        grant=_grant_state(grants),
        engagement=None if engagement is None else EngagementState(engagement.state),
        owner_named=engagement is not None and bool(engagement.revealed),
        nda_acceptance_id=None if nda is None else nda.id,
    )
    return facts, None if nda is None else nda.version


async def can_view_tier2(
    db: AsyncSession,
    settings: Settings,
    live: sessions.LiveSession,
    *,
    proposal_id: UUID,
    org_id: UUID | None,
    check_nda: bool = True,
) -> Access | Condition:
    """The access of ``live``'s user to ``proposal_id``'s current Tier 2 through ``org_id``, or the first failed
    condition. Writes nothing (``require`` audits the refusal)."""
    facts, nda_version = await gather(db, settings, live, proposal_id=proposal_id, org_id=org_id)
    failed = first_failure(facts, check_nda=check_nda)
    if failed is not None:
        return failed
    target = facts.target
    assert target is not None  # first_failure checked it
    if facts.is_owner:
        return Access(target=target, owner=True)
    assert org_id is not None  # a member of it (first_failure)
    if check_nda:
        keys = {"proposal": proposal_id, "version": target.version_id, "org": org_id}
        if not (await db.execute(_GRANTED, keys)).scalar_one():
            return Condition.MASTER_TERMS  # the one condition RLS hides from the viewer (module docstring)
    return Access(
        target=target,
        owner=False,
        org_id=org_id,
        engagement=facts.engagement,
        nda_acceptance_id=facts.nda_acceptance_id,
        nda_template_version=nda_version,
        reveals_owner=facts.owner_named,
    )


class Purpose(StrEnum):
    RENDER = "render"
    NDA = "nda"


async def refuse(
    db: AsyncSession,
    condition: Condition,
    *,
    user_id: UUID | None,
    proposal_id: UUID | None,
    org_id: UUID | None,
    purpose: Purpose,
    member: bool,
) -> ApiError:
    """Audit a refusal (ids and the condition only) and commit it; the error to raise. The event goes on the
    organisation's chain when the viewer is its member, else on the viewer's own."""
    if user_id is not None:
        await audit(
            db,
            DENIED,
            actor_user_id=user_id,
            org_id=org_id if member else None,
            subject_type="proposal",
            subject_id=proposal_id,
            payload={
                "condition": condition.value,
                "purpose": purpose.value,
                "org_id": None if org_id is None else str(org_id),
            },
        )
        await db.commit()
    if condition in NOT_FOUND_CONDITIONS:
        return ApiError(404, "not_found", "Not found.")
    return ApiError(403, condition.value, MESSAGES[condition])


async def require(
    db: AsyncSession,
    settings: Settings,
    live: sessions.LiveSession,
    *,
    proposal_id: UUID,
    org_id: UUID | None,
    purpose: Purpose,
) -> Access:
    """``can_view_tier2`` or the refusal (audited, then raised)."""
    outcome = await can_view_tier2(
        db, settings, live, proposal_id=proposal_id, org_id=org_id, check_nda=purpose == Purpose.RENDER
    )
    if isinstance(outcome, Access):
        return outcome
    member = outcome not in (Condition.FEATURE_DISABLED, *NOT_FOUND_CONDITIONS)
    raise await refuse(
        db, outcome, user_id=live.user.id, proposal_id=proposal_id, org_id=org_id, purpose=purpose, member=member
    )


def _path_uuid(request: Request, name: str) -> UUID | None:
    try:
        return UUID(str(request.path_params[name]))
    except (KeyError, ValueError):
        return None


async def tier2_gate(
    request: Request,
    settings: SettingsDep,
    db: Db,
    live: Annotated[sessions.LiveSession | None, Depends(optional_session)],
) -> None:
    """Router dependency of every route tagged ``tier2``, before anything else (the path's other parameters
    included). A session still waiting for its second factor gets 401 ``mfa_required`` first, as from
    ``current_session``: nothing is looked up or audited for it (security review of P3). Then tenancy: a signed-in
    caller who is not an active member of the path's organisation gets 404, as on every organisation route
    (AC-SEC-1). Then the flag (AC-SEC-2): while ``FEATURE_TIER2_ENABLED`` is off, everyone else gets 403
    ``tier2_disabled``, members whatever their NDA state and anonymous callers alike."""
    if live is not None and live.row.mfa_pending:
        raise ApiError(401, "mfa_required", "Enter the code from your authenticator app.")
    org_param = "org_id" in request.path_params
    org_id, proposal_id = _path_uuid(request, "org_id"), _path_uuid(request, "proposal_id")
    purpose = Purpose.NDA if request.url.path.endswith("/nda") else Purpose.RENDER
    user_id = None if live is None else live.user.id
    if user_id is not None and org_param:
        rows = [] if org_id is None else (await db.execute(_MEMBERSHIP, {"org": org_id, "user": user_id})).all()
        if not rows:
            raise await refuse(
                db,
                Condition.NOT_MEMBER,
                user_id=user_id,
                proposal_id=proposal_id,
                org_id=org_id,
                purpose=purpose,
                member=False,
            )
    if settings.feature_tier2_enabled:
        return
    raise await refuse(
        db,
        Condition.FEATURE_DISABLED,
        user_id=user_id,
        proposal_id=proposal_id,
        org_id=org_id,
        purpose=purpose,
        member=user_id is not None and org_param,
    )
