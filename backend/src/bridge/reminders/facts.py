"""The reminders' facts, read from the tracker's rows as the recipient (REQ-REM-01, REQ-REM-02; AC-REM-3).

Both reminders build ``EngagementFact``s with the same query (``engagement_facts``), on a session bound to the
recipient (``bridge.db.bind_tenant``): the developer reads their own engagements, an organisation member (bound to the
organisation) the organisation's. RLS decides what each may read; a name or title the recipient may not read comes
back empty and is worded generically. Times are the shared clock's (``app_clock_now()``, so the dev/test clock moves
reminders with deadlines) and become Nairobi dates here.

What is read per engagement: its state, stage entry and deadline; the milestones of its **signed** agreement; the
parties that signed the current stage's document since the stage began (mutual NDA, the final agreement, the
acceptance certificate); the developer's confirmation of first contact; a recorded final payment; who proposed the
latest terms; the tracker's ``submit_milestone`` and ``request_changes`` events (submission dates and rework loops);
and the developer's latest action (an event, a non-automatic endorsement or a signature).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.admin.models import Holiday
from bridge.auth.models import User
from bridge.engagements.calendar import local_date
from bridge.engagements.models import (
    Agreement,
    Engagement,
    EngagementEndorsement,
    EngagementEvent,
    Milestone,
    PaymentRecord,
    Signature,
)
from bridge.models.enums import (
    TERMINAL_STATES,
    AgreementStatus,
    EndorsementMethod,
    EngagementActorRole,
    EngagementOrigin,
    EngagementParty,
    EngagementState,
    ProposalStatus,
    SignatureDocumentKind,
)
from bridge.proposals.models import Proposal, ProposalVersion
from bridge.reminders.health import EngagementFact, MilestoneFact, whose_turn
from bridge.reminders.nudge import DeveloperFacts
from bridge.reminders.org_digest import Cadence, OrgFacts
from bridge.tenancy.models import Organization

S = EngagementState
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
MAX_DRAFTS: Final = 5
REWORK: Final = "request_changes"  # the tracker's commands (P5 state machine)
SUBMIT: Final = "submit_milestone"
_STAGE_DOCUMENT: Final = {
    S.NDA_PENDING: SignatureDocumentKind.MUTUAL_NDA,
    S.AGREEMENT_SIGNING: SignatureDocumentKind.AGREEMENT,
    S.SIGN_OFF: SignatureDocumentKind.ACCEPTANCE_CERTIFICATE,
}
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


async def engagement_facts(db: AsyncSession, condition: ColumnElement[bool]) -> tuple[EngagementFact, ...]:
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
    ids = [row[0].id for row in rows]
    engagements = {row[0].id: row[0] for row in rows}
    milestones = await _milestones(db, ids)
    signed = await _signed(db, engagements)
    confirmed = await _contact_confirmed(db, engagements)
    paid = set(
        (
            await db.scalars(
                select(PaymentRecord.engagement_id).where(
                    PaymentRecord.engagement_id.in_(ids), PaymentRecord.milestone_id.is_(None)
                )
            )
        ).all()
    )
    terms_by = await _terms_by(db, engagements)
    last_update = await _last_developer_update(db, engagements)
    facts = []
    for engagement, org_name, title, developer_name in rows:
        own = milestones.get(engagement.id, ())
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
                awaiting=whose_turn(
                    engagement.state,
                    signed=signed.get(engagement.id, frozenset()),
                    contact_confirmed=engagement.id in confirmed,
                    milestones=tuple(m.state for m in own),
                    payment_recorded=engagement.id in paid,
                    terms_by=terms_by.get(engagement.id),
                ),
                milestones=own,
                last_developer_update_on=_day(last_update.get(engagement.id)),
                tagged=engagement.origin is EngagementOrigin.TAGGED,
            )
        )
    return tuple(facts)


async def _milestones(db: AsyncSession, ids: Sequence[UUID]) -> dict[UUID, tuple[MilestoneFact, ...]]:
    """The signed agreement's milestones, with submission dates and rework loops from the tracker's events."""
    rows = (
        (
            await db.execute(
                select(Milestone)
                .join(Agreement, Agreement.id == Milestone.agreement_id)
                .where(Milestone.engagement_id.in_(ids), Agreement.status == AgreementStatus.SIGNED)
                .order_by(Milestone.engagement_id, Milestone.seq)
            )
        )
        .scalars()
        .all()
    )
    milestone_id = EngagementEvent.payload["milestone_id"].astext
    events = await db.execute(
        select(EngagementEvent.command, milestone_id, func.count(), func.max(EngagementEvent.created_at))
        .where(EngagementEvent.engagement_id.in_(ids), EngagementEvent.command.in_((REWORK, SUBMIT)))
        .group_by(EngagementEvent.command, milestone_id)
    )
    loops: dict[str, int] = {}
    submitted: dict[str, datetime] = {}
    for command, key, count, latest in events.all():
        if command == REWORK:
            loops[str(key)] = int(count)
        else:
            submitted[str(key)] = latest
    found: dict[UUID, list[MilestoneFact]] = defaultdict(list)
    for m in rows:
        found[m.engagement_id].append(
            MilestoneFact(
                seq=m.seq,
                deliverable=m.deliverable,
                due_on=m.due_date,
                state=m.state,
                rework_loops=loops.get(str(m.id), 0),
                submitted_on=_day(submitted.get(str(m.id))),
                review_window_bd=m.review_window_bd,
            )
        )
    return {key: tuple(value) for key, value in found.items()}


async def _signed(db: AsyncSession, engagements: dict[UUID, Engagement]) -> dict[UUID, frozenset[EngagementParty]]:
    """The parties that signed the current stage's document since the stage began."""
    signing = {i: e for i, e in engagements.items() if e.state in _STAGE_DOCUMENT}
    if not signing:
        return {}
    rows = await db.execute(
        select(Signature.engagement_id, Signature.document_kind, Signature.party, Signature.signed_at).where(
            Signature.engagement_id.in_(list(signing))
        )
    )
    found: dict[UUID, set[EngagementParty]] = defaultdict(set)
    for engagement_id, kind, party, signed_at in rows.all():
        e = signing[engagement_id]
        if kind is _STAGE_DOCUMENT[e.state] and signed_at >= e.stage_entered_at:
            found[engagement_id].add(party)
    return {key: frozenset(value) for key, value in found.items()}


async def _contact_confirmed(db: AsyncSession, engagements: dict[UUID, Engagement]) -> set[UUID]:
    contact = {i: e for i, e in engagements.items() if e.state is S.CONTACT_MADE}
    if not contact:
        return set()
    rows = await db.execute(
        select(EngagementEndorsement.engagement_id, EngagementEndorsement.endorsed_at).where(
            EngagementEndorsement.engagement_id.in_(list(contact)),
            EngagementEndorsement.stage == S.CONTACT_MADE,
            EngagementEndorsement.party == DEV,
        )
    )
    return {i for i, at in rows.all() if at >= contact[i].stage_entered_at}


async def _terms_by(db: AsyncSession, engagements: dict[UUID, Engagement]) -> dict[UUID, EngagementParty]:
    """Who created the latest agreement version of an engagement in negotiation."""
    negotiating = {i: e for i, e in engagements.items() if e.state is S.NEGOTIATION}
    if not negotiating:
        return {}
    rows = await db.execute(
        select(Agreement.engagement_id, Agreement.created_by)
        .where(Agreement.engagement_id.in_(list(negotiating)))
        .order_by(Agreement.engagement_id, Agreement.version.desc())
        .distinct(Agreement.engagement_id)
    )
    return {i: DEV if by == negotiating[i].developer_id else ORG for i, by in rows.all()}


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


async def developer_facts(db: AsyncSession, user_id: UUID, today: date) -> DeveloperFacts:
    """Read as the developer (``db`` bound to ``user_id``, no organisation)."""
    engagements = await engagement_facts(db, Engagement.developer_id == user_id)
    drafts = await db.execute(
        select(func.coalesce(Proposal.title, ProposalVersion.title))
        .outerjoin(ProposalVersion, ProposalVersion.id == Proposal.draft_version_id)
        .where(Proposal.owner_id == user_id, Proposal.status == ProposalStatus.DRAFT)
        .order_by(Proposal.updated_at.desc(), Proposal.id)
        .limit(MAX_DRAFTS)
    )
    return DeveloperFacts(user_id, today, engagements, tuple(drafts.scalars().all()))


async def org_facts(db: AsyncSession, org_id: UUID, today: date, cadence: Cadence) -> OrgFacts:
    """Read as a member of the organisation (``db`` bound to the member and ``org_id``)."""
    name = await db.scalar(select(Organization.legal_name).where(Organization.id == org_id))
    engagements = await engagement_facts(db, Engagement.org_id == org_id)
    return OrgFacts(org_id, name or "", today, cadence, engagements)
