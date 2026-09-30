"""Stage 0: an organisation's interest, and the developer's manual Tier-2 share (REQ-ENG-04; docs/spec/06 6.9).

``express_interest`` opens an ``ORG_INTEREST`` engagement (origin ``org_agent_match`` from a scout match, or
``org_browse`` from the Browse repo) for the organisation of the path, in the caller's transaction. Refusals, in
order: not a signatory (403 ``role_required``: a reviewer never expresses interest, AC-TRACK-8), no fresh second
factor (403 ``step_up_required``, ADR-002), the organisation not E2 (403 ``org_not_e2``, AC-SCOUT-8) or suspended or
delisted (403 ``org_unavailable``); a scout match that is not the organisation's or not of that proposal (404), a
proposal that is not published and clear, or whose developer is a member of the organisation (the same 404: a
distinct answer would tell an employer that an author is one of its members; the refusal is audited for staff only),
an engagement for the pair already (409 ``engagement_exists``); a contact who is not an active
member (422 ``invalid_contact``) or a contact-by date out of range (422 ``invalid_contact_by``). The database's
policies (revision 0003) are the backstop: a signatory of an E2 organisation inserts ``ORG_INTEREST`` for the current
registered version of a published, clear proposal, and its genesis event names the signatory. The engagement's
deadline is the stage's (policy.yaml, 5 business days). The developer is told (N17, in-app and email) by the
genesis event's notification job; an ``org_interest`` signal and an audit event are written in the same transaction.

``share_tier2`` is the developer's manual grant (docs/spec/06 6.9 stage 0: "Tier 2 by manual grant"): only the
engagement's developer, with a fresh second factor, on an organisation-origin engagement that has not ended, for a
published, clear proposal. It is idempotent: a live grant is returned as it is, an organisation's pending request is
activated, else an active tier-2 grant with source ``org_interest`` is created; ``counts_as_unlock`` is true unless
the developer tagged the organisation (REQ-BIL-03 counts it later; the prototype sets the flags only) and
``billing_month`` is the Nairobi month. A grant opens nothing on its own: ``can_view_tier2`` still requires every
other condition, the Evaluation NDA included. The organisation's people on the engagement are told in-app.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.audit.service import record as audit
from bridge.auth.deps import ensure_step_up
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements import notify
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import local_date
from bridge.engagements.commands import verified_step_up
from bridge.engagements.models import Engagement, EngagementEvent
from bridge.engagements.policy import get_policy
from bridge.engagements.schemas import InterestBody, Tier2ShareOut
from bridge.engagements.service import Party, api_error, app_now, load_holidays, lock_engagement
from bridge.errors import ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.models.enums import (
    AuditActor,
    EngagementOrigin,
    EngagementState,
    GrantSource,
    OrgRole,
    OrgVerification,
)
from bridge.notifications.em2 import one_line
from bridge.notifications.in_app import post_in_app
from bridge.tenancy import signals
from bridge.tenancy.deps import OrgContext
from bridge.tenancy.service import membership_of

S = EngagementState
INTEREST_ORIGINS: Final = frozenset({EngagementOrigin.ORG_AGENT_MATCH, EngagementOrigin.ORG_BROWSE})
TIER2: Final = 2
_ORG = text("SELECT verification, suspended_at, delisted_at FROM organizations WHERE id = :org")
_MATCH = text("SELECT proposal_id FROM agent_matches WHERE id = :id AND org_id = :org")
_PROPOSAL = text(
    "SELECT owner_id, current_version_id FROM proposals WHERE id = :id AND status = 'published'"
    " AND moderation_state = 'clear' AND current_version_id IS NOT NULL"
)
_EXISTING = text("SELECT id FROM engagements WHERE proposal_id = :proposal AND org_id = :org")
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_LIVE = text(
    "SELECT id, status, source, granted_at, counts_as_unlock FROM disclosure_grants WHERE proposal_id = :proposal"
    " AND org_id = :org AND tier = :tier AND status IN ('requested', 'active') AND revoked_at IS NULL"
)
_TAGGED = text(
    "SELECT EXISTS (SELECT 1 FROM tags WHERE proposal_id = :proposal AND org_id = :org AND developer_id = :owner"
    " AND status = 'delivered')"
)
_MONTH = text("SELECT CAST(date_trunc('month', app_clock_now() AT TIME ZONE 'Africa/Nairobi') AS date)")
_INSERT_GRANT = text(
    "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source, counts_as_unlock,"
    " billing_month, granted_by, granted_at) VALUES (:id, :proposal, :org, :owner, :tier, 'active',"
    " CAST(:source AS grant_source), :unlock, :month, :owner, app_clock_now())"
)
_ACTIVATE = text(
    "UPDATE disclosure_grants SET status = 'active', counts_as_unlock = :unlock, billing_month = :month,"
    " granted_by = :owner, granted_at = app_clock_now(), updated_at = now() WHERE id = :id AND owner_id = :owner"
)
# [[COPY-REVIEW]] the organisation's in-app notice when the developer shares the full proposal.
SHARED_TITLE: Final = "Full proposal shared"
SHARED_BODY: Final = 'The developer shared the full proposal "{title}" with your organisation. Open it under NDA.'
SHARED_LINK: Final = "/org/engagements/{engagement}"  # the organisation's tracker (frontend app/(app)/org/engagements)
log = get_logger(__name__)


# ------------------------------------------------------------------------------------------------ express interest


async def _check_organisation(db: AsyncSession, org_id: UUID) -> None:
    found = (await db.execute(_ORG, {"org": org_id})).one()
    if found.verification != OrgVerification.E2:
        raise forbidden(
            "org_not_e2", "Only organisations verified with registration documents (E2) can express interest."
        )
    if found.suspended_at is not None or found.delisted_at is not None:
        raise forbidden("org_unavailable", "Your organisation cannot express interest now (suspended or delisted).")


async def _check_origin(db: AsyncSession, org_id: UUID, body: InterestBody) -> None:
    if body.origin is EngagementOrigin.ORG_AGENT_MATCH:
        if body.match_id is None:
            raise ApiError(422, "match_required", "Name the scout match you are expressing interest from.")
        matched = (await db.execute(_MATCH, {"id": body.match_id, "org": org_id})).scalar_one_or_none()
        if matched is None or matched != body.proposal_id:
            raise not_found("No scout match of your organisation for this proposal.")
    elif body.match_id is not None:
        raise ApiError(422, "unexpected_match", "A scout match goes with the origin org_agent_match only.")


async def express_interest(db: AsyncSession, settings: Settings, org: OrgContext, body: InterestBody) -> UUID:
    """Open the ORG_INTEREST engagement (see the module docstring); the caller commits. Returns its id."""
    if OrgRole.SIGNATORY not in org.roles:
        raise forbidden("role_required", "Only a signatory of your organisation can express interest.")
    ensure_step_up(org.live, settings)
    await _check_organisation(db, org.org_id)
    await _check_origin(db, org.org_id, body)
    proposal = (await db.execute(_PROPOSAL, {"id": body.proposal_id})).one_or_none()
    if proposal is None:
        raise not_found("No published proposal has this id.")
    if await membership_of(db, org.org_id, proposal.owner_id) is not None:
        await _refuse_own_member(db, body.proposal_id)
        raise not_found("No published proposal has this id.")
    if (await db.execute(_EXISTING, {"proposal": body.proposal_id, "org": org.org_id})).scalar_one_or_none():
        raise ApiError(409, "engagement_exists", "Your organisation already has an engagement for this proposal.")
    now = await app_now(db)
    holidays, policy = await load_holidays(db, local_date(now)), get_policy()
    try:
        sm.check_contact_by(body.contact_by, now, holidays, policy)
    except sm.TrackerError as error:
        raise api_error(error) from error
    if await membership_of(db, org.org_id, body.contact_user_id) is None:
        raise ApiError(422, "invalid_contact", "Choose an active member of your organisation as the contact person.")
    engagement = Engagement(
        id=uuid7(),
        proposal_id=body.proposal_id,
        org_id=org.org_id,
        developer_id=proposal.owner_id,
        version_id=proposal.current_version_id,
        origin=body.origin,
        state=S.ORG_INTEREST,
        contact_user_id=body.contact_user_id,
        contact_channel=body.channel,
        contact_by=body.contact_by,
        stage_deadline_at=sm.stage_deadline(S.ORG_INTEREST, now, holidays, policy),
    )
    try:
        async with db.begin_nested():
            db.add(engagement)
            await db.flush()
    except DBAPIError as exc:
        raise _refusal(exc) from exc
    genesis = await db.scalar(
        select(EngagementEvent).where(EngagementEvent.engagement_id == engagement.id, EngagementEvent.seq == 1)
    )
    if genesis is None:  # the database writes it with the row (revision 0003): never missing
        raise RuntimeError("an engagement without its genesis event")
    await notify.enqueue(db, engagement, genesis)
    actor = await signals.actor_hash(db, org.live.user.id)
    await signals.record(
        db, settings, item_id=body.proposal_id, kind=signals.ORG_INTEREST, org_id=org.org_id, actor=actor
    )
    await audit(
        db,
        "engagement.interest_expressed",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="engagement",
        subject_id=engagement.id,
        payload={
            "proposal_id": str(body.proposal_id),
            "origin": body.origin.value,
            "match_id": None if body.match_id is None else str(body.match_id),
        },
    )
    return engagement.id


async def _refuse_own_member(db: AsyncSession, proposal_id: UUID) -> None:
    """Audit the refusal (the condition only) where no organisation member reads it: a system event on the global
    chain (``audit_events`` shows an organisation's events to its owners and admins, and an event to its actor), so
    the audit trail cannot become the oracle the 404 closes. Committed before the 404 is raised."""
    await audit(
        db,
        "engagement.interest_refused",
        actor_user_id=None,
        actor_kind=AuditActor.SYSTEM,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={"condition": "own_organisation"},
    )
    await db.commit()


def _refusal(exc: DBAPIError) -> ApiError:
    """The database's backstop refused the insert (a race the checks above could not see)."""
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "23505":
        return ApiError(409, "engagement_exists", "Your organisation already has an engagement for this proposal.")
    if sqlstate == "42501":
        return forbidden("refused", "The database refused this interest for your role or organisation.")
    if sqlstate == "23514":
        return ApiError(409, "conflict", "This interest is not possible now. Reload and retry.")
    raise exc


# ------------------------------------------------------------------------------------------------ Tier-2 share


async def share_state(db: AsyncSession, engagement: Engagement) -> Tier2ShareOut:
    """The live tier-2 grant of the engagement's proposal to its organisation, as either party reads it."""
    params = {"proposal": engagement.proposal_id, "org": engagement.org_id, "tier": TIER2}
    live = [row for row in (await db.execute(_LIVE, params)).all() if row.status == "active"]
    grant = live[0] if live else None
    return Tier2ShareOut(
        engagement_id=engagement.id,
        shared=grant is not None,
        grant_id=None if grant is None else grant.id,
        source=None if grant is None else GrantSource(grant.source),
        shared_at=None if grant is None else grant.granted_at,
        counts_as_unlock=False if grant is None else bool(grant.counts_as_unlock),
    )


async def share_tier2(db: AsyncSession, settings: Settings, party: Party) -> tuple[Tier2ShareOut, bool]:
    """The developer's manual grant (see the module docstring); the caller commits. Returns the share and whether
    this call created or activated it."""
    if not party.is_developer:
        raise forbidden("not_your_action", "Only the developer can share their full proposal.")
    verified_step_up(party, settings)
    engagement = await lock_engagement(db, party.engagement_id)
    if engagement.origin not in INTEREST_ORIGINS:
        raise ApiError(409, "share_not_applicable", "Tagged proposals are shared by your disclosure policy.")
    if engagement.state in sm.TERMINAL:
        raise ApiError(409, "engagement_ended", "This engagement has ended.")
    proposal = (await db.execute(_PROPOSAL, {"id": engagement.proposal_id})).one_or_none()
    if proposal is None or proposal.owner_id != party.user_id:
        raise ApiError(409, "proposal_unavailable", "The proposal is not published and clear of moderation holds.")
    params: dict[str, Any] = {
        "proposal": engagement.proposal_id,
        "org": engagement.org_id,
        "owner": party.user_id,
        "tier": TIER2,
    }
    await db.execute(_LOCK, {"key": f"tier2.grant:{engagement.proposal_id}:{engagement.org_id}"})
    live = (await db.execute(_LIVE, params)).one_or_none()
    if live is not None and live.status == "active":
        return await share_state(db, engagement), False
    # The unlock flags are the same however the grant comes about (REQ-BIL-03 counts them later).
    tagged = bool((await db.execute(_TAGGED, params)).scalar_one())
    month: date = (await db.execute(_MONTH)).scalar_one()
    flags = {"unlock": not tagged, "month": month}
    if live is not None:  # the organisation asked first: the request keeps its source
        grant_id, action, source = UUID(str(live.id)), "tier2.grant_activated", str(live.source)
        await db.execute(_ACTIVATE, {"id": grant_id, "owner": party.user_id} | flags)
    else:
        grant_id, action, source = uuid7(), "tier2.grant_created", GrantSource.ORG_INTEREST.value
        await db.execute(_INSERT_GRANT, params | {"id": grant_id, "source": source} | flags)
    await audit(
        db,
        action,
        actor_user_id=party.user_id,
        subject_type="proposal",
        subject_id=engagement.proposal_id,
        payload={
            "grant_id": str(grant_id),
            "org_id": str(engagement.org_id),
            "tier": TIER2,
            "source": source,
            "engagement_id": str(engagement.id),
        },
    )
    return await share_state(db, engagement), True


async def tell_organisation(
    factory: async_sessionmaker[AsyncSession], engagement_id: UUID, developer_id: UUID, grant_id: UUID
) -> None:
    """The organisation's people on the engagement are told in-app that the full proposal is shared (once per grant
    and person; each in a session bound to them). Never raises: the share has committed."""
    try:
        async with factory() as db:
            await bind_tenant(db, user_id=developer_id)
            engagement = await db.get(Engagement, engagement_id)
            if engagement is None:
                return
            title = await db.scalar(text("SELECT title FROM proposals WHERE id = :id"), {"id": engagement.proposal_id})
            people = await notify.org_people(db, engagement)
            org_id = engagement.org_id
        body = SHARED_BODY.format(title=one_line(title or "your proposal"))
        for user_id in people:
            async with factory() as db:
                await bind_tenant(db, user_id=user_id, org_id=org_id)
                if await membership_of(db, org_id, user_id) is None:
                    continue
                await post_in_app(
                    db,
                    user_id=user_id,
                    org_id=org_id,
                    kind="engagement.tier2_shared",
                    title=SHARED_TITLE,
                    body=body,
                    link=SHARED_LINK.format(engagement=engagement_id),
                    dedupe_key=f"tier2share:{grant_id}:{user_id}",
                )
                await db.commit()
    except Exception as exc:  # a notice never undoes the share
        log.error("tier2.share_notice_failed", engagement_id=str(engagement_id), error_type=type(exc).__name__)
