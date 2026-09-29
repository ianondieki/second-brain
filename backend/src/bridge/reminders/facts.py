"""The reminders' facts, read from the tracker's rows as the recipient (REQ-REM-01, REQ-REM-02; AC-REM-3).

Both reminders build ``EngagementFact``s with the same query (``engagement_facts``), on a session bound to the
recipient (``bridge.db.bind_tenant``): the developer reads their own engagements, an organisation member (bound to the
organisation) the organisation's. RLS decides what each may read; a name or title the recipient may not read comes
back empty and is worded generically. Times are the shared clock's (``app_clock_now()``, so the dev/test clock moves
reminders with deadlines) and become Nairobi dates here.

What is read per engagement: its state, stage entry and deadline; the tracker's own facts and the signed agreement's
milestones through P5's service (``bridge.engagements.service.load``), and whose turn it is from the state machine
(``bridge.engagements.state_machine.pending``: docs/spec/06 6.9, the only definition); each milestone's review due date
(``bridge.engagements.history.review_due_dates``) and its rework loops (the tracker's ``request_changes`` events);
and the developer's latest action (an event, a non-automatic endorsement or a signature).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.admin.models import Holiday
from bridge.auth.models import User
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import local_date
from bridge.engagements.history import review_due_dates
from bridge.engagements.models import Engagement, EngagementEndorsement, EngagementEvent, Milestone, Signature
from bridge.engagements.service import load as load_tracker
from bridge.models.enums import (
    TERMINAL_STATES,
    EndorsementMethod,
    EngagementActorRole,
    EngagementOrigin,
    EngagementParty,
    ProposalStatus,
)
from bridge.proposals.models import Proposal, ProposalVersion
from bridge.reminders.health import EngagementFact, MilestoneFact
from bridge.reminders.nudge import DeveloperFacts
from bridge.reminders.org_digest import Cadence, OrgFacts
from bridge.tenancy.models import Organization

DEV = EngagementParty.DEVELOPER
MAX_DRAFTS: Final = 5
_CLOCK = text("SELECT app_clock_now()")


async def clock_now(db: AsyncSession) -> datetime:
    """The shared clock (the database's, plus the test clock's offset where the owner enabled it)."""
    now: datetime = (await db.execute(_CLOCK)).scalar_one()
    return now


async def load_holidays(db: AsyncSession, country: str = "KE") -> frozenset[date]:
    rows = await db.scalars(select(Holiday.observed_on).where(Holiday.country == country))
    return frozenset(rows.all())


def _day(value: datetime | None) -> date | None:
    return local_date(value) if value is not None else None


async def engagement_facts(
    db: AsyncSession, condition: ColumnElement[bool], *, deals_enabled: bool
) -> tuple[EngagementFact, ...]:
    """The active engagements matching ``condition`` that the bound recipient may read, oldest first."""
    rows = (
        await db.execute(
            select(Engagement, Organization.legal_name, ProposalVersion.title, User.display_name)
            .outerjoin(Organization, Organization.id == Engagement.org_id)
            .outerjoin(ProposalVersion, ProposalVersion.id == Engagement.version_id)
            .outerjoin(User, User.id == Engagement.developer_id)
            .where(condition, Engagement.state.not_in(TERMINAL_STATES))
            .order_by(Engagement.created_at, Engagement.id)
        )
    ).all()
    if not rows:
        return ()
    engagements = {row[0].id: row[0] for row in rows}
    loops = await _rework_loops(db, list(engagements))
    last_update = await _last_developer_update(db, engagements)
    facts = []
    for engagement, org_name, title, developer_name in rows:
        tracker = await load_tracker(db, engagement, deals_enabled=deals_enabled)
        review_due = await review_due_dates(db, engagement.id, tracker.milestones)
        facts.append(
            EngagementFact(
                id=engagement.id,
                org_id=engagement.org_id,
                state=engagement.state,
                title=title or "",
                org_name=org_name or "",
                developer_name=developer_name or "",
                created_on=local_date(engagement.created_at),
                entered_on=local_date(engagement.stage_entered_at),
                stage_deadline_on=_day(engagement.stage_deadline_at),
                awaiting=frozenset(p.party for p in sm.pending(engagement.state, tracker.facts)),
                milestones=tuple(_milestone(m, loops, review_due) for m in tracker.milestones),
                last_developer_update_on=_day(last_update.get(engagement.id)),
                tagged=engagement.origin is EngagementOrigin.TAGGED,
            )
        )
    return tuple(facts)


def _milestone(m: Milestone, loops: dict[str, int], review_due: dict[UUID, date]) -> MilestoneFact:
    return MilestoneFact(
        seq=m.seq,
        deliverable=m.deliverable,
        due_on=m.due_date,
        state=m.state,
        rework_loops=loops.get(str(m.id), 0),
        review_due_on=review_due.get(m.id),
    )


async def _rework_loops(db: AsyncSession, ids: list[UUID]) -> dict[str, int]:
    """How many times each milestone was sent back for changes (the tracker's ``request_changes`` events)."""
    milestone_id = EngagementEvent.payload["milestone_id"].astext
    rows = await db.execute(
        select(milestone_id, func.count())
        .where(EngagementEvent.engagement_id.in_(ids), EngagementEvent.command == sm.Command.REQUEST_CHANGES.value)
        .group_by(milestone_id)
    )
    return {str(key): int(count) for key, count in rows.tuples()}


async def _last_developer_update(db: AsyncSession, engagements: dict[UUID, Engagement]) -> dict[UUID, datetime]:
    ids = list(engagements)
    queries = (
        select(EngagementEvent.engagement_id, func.max(EngagementEvent.created_at))
        .where(EngagementEvent.engagement_id.in_(ids), EngagementEvent.actor_role == EngagementActorRole.DEVELOPER)
        .group_by(EngagementEvent.engagement_id),
        select(EngagementEndorsement.engagement_id, func.max(EngagementEndorsement.endorsed_at))
        .where(
            EngagementEndorsement.engagement_id.in_(ids),
            EngagementEndorsement.party == DEV,
            EngagementEndorsement.method != EndorsementMethod.AUTO,
        )
        .group_by(EngagementEndorsement.engagement_id),
        select(Signature.engagement_id, func.max(Signature.signed_at))
        .where(Signature.engagement_id.in_(ids), Signature.party == DEV)
        .group_by(Signature.engagement_id),
    )
    latest: dict[UUID, datetime] = {}
    for query in queries:
        for engagement_id, at in (await db.execute(query)).all():
            if at is not None and (engagement_id not in latest or at > latest[engagement_id]):
                latest[engagement_id] = at
    return latest


async def developer_facts(db: AsyncSession, user_id: UUID, today: date, *, deals_enabled: bool) -> DeveloperFacts:
    """Read as the developer (``db`` bound to ``user_id``, no organisation)."""
    engagements = await engagement_facts(db, Engagement.developer_id == user_id, deals_enabled=deals_enabled)
    drafts = await db.execute(
        select(func.coalesce(Proposal.title, ProposalVersion.title))
        .outerjoin(ProposalVersion, ProposalVersion.id == Proposal.draft_version_id)
        .where(Proposal.owner_id == user_id, Proposal.status == ProposalStatus.DRAFT)
        .order_by(Proposal.updated_at.desc(), Proposal.id)
        .limit(MAX_DRAFTS)
    )
    return DeveloperFacts(user_id, today, engagements, tuple(drafts.scalars().all()))


async def org_facts(db: AsyncSession, org_id: UUID, today: date, cadence: Cadence, *, deals_enabled: bool) -> OrgFacts:
    """Read as a member of the organisation (``db`` bound to the member and ``org_id``)."""
    name = await db.scalar(select(Organization.legal_name).where(Organization.id == org_id))
    engagements = await engagement_facts(db, Engagement.org_id == org_id, deals_enabled=deals_enabled)
    return OrgFacts(org_id, name or "", today, cadence, engagements)
