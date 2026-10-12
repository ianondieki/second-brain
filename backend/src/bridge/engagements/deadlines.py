"""Every deadline a person carries (REQ-ENG-13; docs/platform/tasks/P27.md track A; docs/spec/06 6.9 "due countdown",
6.11; D-61, D-70).

A viewer is a developer (their own engagements) or a member of one organisation (its engagements). Their deadlines,
read under their Row-Level Security:

- ``stage``: the stage deadline (``stage_deadline_at``) of each engagement that is neither ended nor on hold (a hold's
  resume date is not a deadline; a dispute freezes due dates).
- ``answer``: the answer-by date of the organisation's open question (``INFO_REQUESTED``: its ``stage_deadline_at``).
- ``milestone``: each milestone of a signed agreement not yet accepted, on an engagement in ``IN_IMPLEMENTATION``:
  its due date while the developer works on it, its review date (the review window after the latest submission)
  while the organisation reviews it.
- ``brief``: the open Briefs with a deadline (published, closing today or later): the organisation's own; for a
  developer, the Briefs of the problems their proposals link to where they have a live engagement or an open pitch.
- ``event``: published events: the organisation's own; for a developer, those they asked to be reminded of.

``mine`` is whose turn it is (the state machine's ``whose_turn``; a milestone the developer's until submitted, then the
organisation's); a Brief or an event is the viewer's own entry. A deadline of a day falls at the end of its Nairobi
day; an event at its start. The default window is every overdue item plus the next ``DEFAULT_DAYS`` days; an explicit
window (at most ``MAX_SPAN_DAYS`` days) keeps what falls due inside it. The items carry titles, dates and names only
(D-70): a stage's label, a proposal's or Brief's or event's title, the other party's name; never a note, a message, a
Brief's statement or a proposal's text. Plain code decides every value here; nothing is worded by a model.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import web_paths
from bridge.admin.models import Holiday
from bridge.engagements import history
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days, local_date
from bridge.engagements.models import Agreement, Engagement, EngagementEvent, Milestone
from bridge.engagements.schemas import DeadlineKind, DeadlineOut
from bridge.errors import ApiError, not_found
from bridge.events.calendar import Entry, public_host
from bridge.events.models import Event, EventReminder
from bridge.models.enums import (
    AgreementStatus,
    BriefStatus,
    EngagementParty,
    EngagementState,
    MilestoneState,
)
from bridge.problems.models import Problem, ProblemBrief
from bridge.proposals.models import ProposalProblem, ProposalVersion, Tag
from bridge.tenancy.models import Organization

DEFAULT_DAYS: Final = 90  # the default window: overdue items plus this many days ahead
MAX_SPAN_DAYS: Final = 366  # an explicit window's longest span
ENTRY_MINUTES: Final = 15  # a deadline's calendar entry
DUE_SUFFIX: Final = " — due"  # [[COPY-REVIEW]] a deadline's calendar summary: "<title> — due"
MILESTONE_TITLE: Final = "Milestone {seq}: {title}"  # [[COPY-REVIEW]]
MILESTONE_REVIEW_TITLE: Final = "Milestone {seq} review: {title}"  # [[COPY-REVIEW]]
INVALID_RANGE: Final = f"Choose a start on or before the end, at most {MAX_SPAN_DAYS} days apart."  # [[COPY-REVIEW]]
NO_DEADLINE: Final = "No deadline of yours has this id."
_ENGAGEMENT_KINDS: Final = frozenset({DeadlineKind.STAGE, DeadlineKind.ANSWER, DeadlineKind.MILESTONE})
# No stage deadline here: ended, on hold (a hold's resume date is not a deadline), disputed (due dates frozen).
_NO_STAGE_DEADLINE: Final = sm.TERMINAL | {EngagementState.ON_HOLD, EngagementState.DISPUTED}
_DEVELOPER_WORKS: Final = frozenset(
    {MilestoneState.PLANNED, MilestoneState.IN_PROGRESS, MilestoneState.CHANGES_REQUESTED}
)


@dataclass(frozen=True, slots=True)
class Viewer:
    """Whose deadlines: a developer's own (``org_id`` None) or an organisation member's (its engagements)."""

    user_id: UUID
    org_id: UUID | None = None

    @property
    def party(self) -> EngagementParty:
        return EngagementParty.DEVELOPER if self.org_id is None else EngagementParty.ORG


@dataclass(frozen=True, slots=True)
class Window:
    """``start`` None: every overdue item and everything from today; else what falls due from ``start``."""

    start: date | None
    end: date


@dataclass(frozen=True, slots=True)
class Item:
    """A deadline as read, before the clock: what it is, where it links, when it falls due (``ends_at``: an event's
    end, for its calendar entry)."""

    kind: DeadlineKind
    item_id: UUID
    title: str
    context: str
    href: str
    due_at: datetime
    mine: bool
    engagement_id: UUID | None
    ends_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Deadline:
    item: Item
    out: DeadlineOut


# ------------------------------------------------------------------------------------------------- pure rules


def window(today: date, start: date | None, end: date | None) -> Window:
    """The window asked for (see the module docstring); 422 ``invalid_range`` for a reversed or overlong one."""
    first = start if start is not None else today
    last = end if end is not None else first + timedelta(days=DEFAULT_DAYS)
    if (start is not None and last < start) or (last - first).days > MAX_SPAN_DAYS:
        raise ApiError(422, "invalid_range", INVALID_RANGE)
    return Window(start, last)


def build(item: Item, *, now: datetime, holidays: frozenset[date]) -> Deadline:
    """The deadline as the API shows it at ``now``: its Nairobi date, the Kenyan business days left from today and
    whether it is overdue (never for an event)."""
    due = sm.due(item.due_at, now, holidays)
    out = DeadlineOut(
        key=f"{item.kind.value}:{item.item_id}",
        kind=item.kind,
        title=item.title,
        context=item.context,
        href=item.href,
        due_at=item.due_at.astimezone(UTC),
        due_on=due.due_on,
        business_days_left=due.business_days_left,
        overdue=due.overdue and item.kind is not DeadlineKind.EVENT,
        mine=item.mine,
        engagement_id=item.engagement_id,
    )
    return Deadline(item, out)


def in_window(deadline: Deadline, frame: Window, today: date) -> bool:
    due_on = deadline.out.due_on
    if frame.start is None:
        return deadline.out.overdue or today <= due_on <= frame.end
    return frame.start <= due_on <= frame.end


def ordered(found: Iterable[Deadline]) -> list[Deadline]:
    return sorted(found, key=lambda d: (d.out.due_at, d.out.key))


def calendar_entry(deadline: Deadline, *, base_url: str, stamp: datetime) -> Entry:
    """One deadline as a calendar entry: ``ENTRY_MINUTES`` at its instant, "<title> — due", transparent; an event
    spans its own start and end under its title (the UID its own file uses, so a calendar keeps one entry). The
    description is the context (the other party's name); the URL the item's page."""
    item, out = deadline.item, deadline.out
    is_event = item.kind is DeadlineKind.EVENT
    ends_at = item.ends_at if is_event and item.ends_at is not None else out.due_at + timedelta(minutes=ENTRY_MINUTES)
    return Entry(
        uid=f"{item.kind.value}-{item.item_id}@{public_host(base_url)}",
        stamp=stamp,
        starts_at=out.due_at,
        ends_at=ends_at,
        summary=out.title if is_event else f"{out.title}{DUE_SUFFIX}",
        description=out.context,
        url=f"{base_url.rstrip('/')}{out.href}",
        transparent=not is_event,
    )


# ----------------------------------------------------------------------------------------------- the reads


async def list_deadlines(
    db: AsyncSession,
    viewer: Viewer,
    *,
    frame: Window,
    now: datetime,
    deals_enabled: bool,
    platform_name: str,
) -> list[Deadline]:
    """The viewer's deadlines inside ``frame``, sorted by ``due_at``."""
    today = local_date(now)
    holidays = await all_holidays(db)
    items = await _items(
        db, viewer, today=today, holidays=holidays, deals_enabled=deals_enabled, platform_name=platform_name
    )
    built = (build(item, now=now, holidays=holidays) for item in items)
    return ordered(d for d in built if in_window(d, frame, today))


async def one_deadline(
    db: AsyncSession,
    viewer: Viewer,
    kind: DeadlineKind,
    item_id: UUID,
    *,
    now: datetime,
    deals_enabled: bool,
    platform_name: str,
) -> Deadline:
    """One of the viewer's deadlines, whatever its date; 404 when it is not theirs (or not a deadline now)."""
    holidays = await all_holidays(db)
    items = await _items(
        db,
        viewer,
        today=local_date(now),
        holidays=holidays,
        deals_enabled=deals_enabled,
        platform_name=platform_name,
        only=(kind, item_id),
    )
    found = [item for item in items if item.kind is kind and item.item_id == item_id]
    if not found:
        raise not_found(NO_DEADLINE)
    return build(found[0], now=now, holidays=holidays)


async def _items(
    db: AsyncSession,
    viewer: Viewer,
    *,
    today: date,
    holidays: frozenset[date],
    deals_enabled: bool,
    platform_name: str,
    only: tuple[DeadlineKind, UUID] | None = None,
) -> list[Item]:
    kind = only[0] if only else None
    items: list[Item] = []
    if kind is None or kind in _ENGAGEMENT_KINDS:
        items += await _engagement_items(db, viewer, holidays=holidays, deals_enabled=deals_enabled, only=only)
    if kind is None or kind is DeadlineKind.BRIEF:
        items += await _brief_items(db, viewer, today=today, only=only[1] if only else None)
    if kind is None or kind is DeadlineKind.EVENT:
        items += await _event_items(db, viewer, platform_name=platform_name, only=only[1] if only else None)
    return items


async def all_holidays(db: AsyncSession) -> frozenset[date]:
    """Every observed Kenyan holiday (a short table: tens of rows a year), so a count over any window is right."""
    rows = await db.execute(select(Holiday.observed_on).where(Holiday.country == "KE"))
    return frozenset(rows.scalars().all())


async def _engagement_items(
    db: AsyncSession,
    viewer: Viewer,
    *,
    holidays: frozenset[date],
    deals_enabled: bool,
    only: tuple[DeadlineKind, UUID] | None,
) -> list[Item]:
    query = select(Engagement).where(Engagement.ended_at.is_(None), Engagement.state.not_in(list(_NO_STAGE_DEADLINE)))
    if viewer.org_id is None:
        query = query.where(Engagement.developer_id == viewer.user_id)
    else:
        query = query.where(Engagement.org_id == viewer.org_id)
    if only is not None:
        kind, item_id = only
        if kind is DeadlineKind.MILESTONE:
            query = query.where(
                Engagement.id == select(Milestone.engagement_id).where(Milestone.id == item_id).scalar_subquery()
            )
        else:
            query = query.where(Engagement.id == item_id)
    engagements = list((await db.execute(query.order_by(Engagement.id))).scalars())
    developer = viewer.org_id is None
    shown = await history.summaries(db, engagements, deals_enabled=deals_enabled, developer_caller=developer)
    items: list[Item] = []
    working: dict[UUID, tuple[str, str, str]] = {}  # IN_IMPLEMENTATION: (title, context, href) by engagement
    for engagement, summary in zip(engagements, shown, strict=True):
        context = summary.org_name if developer else summary.developer_name
        href = web_paths.engagement_path(viewer.party, engagement.id)
        if engagement.state is EngagementState.IN_IMPLEMENTATION:
            working[engagement.id] = (summary.proposal_title, context, href)
        if engagement.stage_deadline_at is None:
            continue
        answer = engagement.state is EngagementState.INFO_REQUESTED
        items.append(
            Item(
                kind=DeadlineKind.ANSWER if answer else DeadlineKind.STAGE,
                item_id=engagement.id,
                title=f"{summary.stage_label}: {summary.proposal_title}",
                context=context,
                href=href,
                due_at=engagement.stage_deadline_at,
                mine=viewer.party in summary.whose_turn,
                engagement_id=engagement.id,
            )
        )
    return items + await _milestone_items(db, viewer, working, holidays)


async def _milestone_items(
    db: AsyncSession, viewer: Viewer, working: dict[UUID, tuple[str, str, str]], holidays: frozenset[date]
) -> list[Item]:
    """The signed agreements' milestones not yet accepted, of the engagements in ``working``."""
    if not working:
        return []
    rows = await db.execute(
        select(Milestone)
        .join(
            Agreement, and_(Agreement.id == Milestone.agreement_id, Agreement.engagement_id == Milestone.engagement_id)
        )
        .where(
            Milestone.engagement_id.in_(list(working)),
            Agreement.status == AgreementStatus.SIGNED,
            Milestone.state != MilestoneState.ACCEPTED,
        )
        .order_by(Milestone.engagement_id, Milestone.seq)
    )
    milestones = list(rows.scalars())
    waiting = [m for m in milestones if m.state is MilestoneState.SUBMITTED_FOR_REVIEW]
    reviews = await _review_dates(db, waiting, holidays)
    items = []
    for m in milestones:
        title, context, href = working[m.engagement_id]
        if m.state in _DEVELOPER_WORKS:
            due_on, party, words = m.due_date, EngagementParty.DEVELOPER, MILESTONE_TITLE
        elif m.id in reviews:
            due_on, party, words = reviews[m.id], EngagementParty.ORG, MILESTONE_REVIEW_TITLE
        else:  # pragma: no cover - submitted, but the chain holds no submission (never for the app's writes)
            continue
        items.append(
            Item(
                kind=DeadlineKind.MILESTONE,
                item_id=m.id,
                title=words.format(seq=m.seq, title=title),
                context=context,
                href=href,
                due_at=sm.end_of_day(due_on),
                mine=viewer.party is party,
                engagement_id=m.engagement_id,
            )
        )
    return items


async def _review_dates(db: AsyncSession, waiting: Sequence[Milestone], holidays: frozenset[date]) -> dict[UUID, date]:
    """REQ-ENG-09's review date of each milestone under review (as the tracker's ``review_due_on``): its review
    window in business days after the Nairobi date of its latest submission, for every engagement at once."""
    if not waiting:
        return {}
    by_id = {str(m.id): m for m in waiting}
    milestone_id = EngagementEvent.payload["milestone_id"].astext
    rows = await db.execute(
        select(milestone_id, func.max(EngagementEvent.created_at))
        .where(
            EngagementEvent.engagement_id.in_(list({m.engagement_id for m in waiting})),
            EngagementEvent.command == sm.Command.SUBMIT_MILESTONE.value,
            milestone_id.in_(list(by_id)),
        )
        .group_by(milestone_id)
    )
    return {
        by_id[key].id: add_business_days(local_date(at), by_id[key].review_window_bd, holidays)
        for key, at in rows.tuples()
    }


async def _brief_items(db: AsyncSession, viewer: Viewer, *, today: date, only: UUID | None) -> list[Item]:
    query = (
        select(
            ProblemBrief.problem_id, ProblemBrief.org_id, ProblemBrief.deadline, Problem.title, Organization.legal_name
        )
        .join(Problem, Problem.id == ProblemBrief.problem_id)
        .join(Organization, Organization.id == ProblemBrief.org_id)
        .where(
            ProblemBrief.status == BriefStatus.PUBLISHED,
            ProblemBrief.deadline.is_not(None),
            ProblemBrief.deadline >= today,
        )
    )
    if viewer.org_id is not None:
        query = query.where(ProblemBrief.org_id == viewer.org_id)
    else:
        engaged = select(Engagement.proposal_id).where(
            Engagement.developer_id == viewer.user_id, Engagement.ended_at.is_(None)
        )
        pitched = select(Tag.proposal_id).where(Tag.developer_id == viewer.user_id, Tag.closed_at.is_(None))
        linked = (
            select(ProposalProblem.problem_id)
            .join(ProposalVersion, ProposalVersion.id == ProposalProblem.proposal_version_id)
            .where(or_(ProposalVersion.proposal_id.in_(engaged), ProposalVersion.proposal_id.in_(pitched)))
        )
        query = query.where(ProblemBrief.problem_id.in_(linked))
    if only is not None:
        query = query.where(ProblemBrief.problem_id == only)
    items = []
    for problem_id, org_id, deadline, title, org_name in (await db.execute(query)).tuples():
        if deadline is None:  # pragma: no cover - the query keeps Briefs with a deadline
            continue
        href = (
            web_paths.problem_path(problem_id)
            if viewer.org_id is None
            else web_paths.org_problem_path(org_id, problem_id)
        )
        items.append(
            Item(
                kind=DeadlineKind.BRIEF,
                item_id=problem_id,
                title=title,
                context=org_name,
                href=href,
                due_at=sm.end_of_day(deadline),
                mine=True,
                engagement_id=None,
            )
        )
    return items


async def _event_items(db: AsyncSession, viewer: Viewer, *, platform_name: str, only: UUID | None) -> list[Item]:
    query = (
        select(Event.id, Event.org_id, Event.title, Event.starts_at, Event.ends_at, Organization.legal_name)
        .outerjoin(Organization, Organization.id == Event.org_id)
        .where(Event.status == "published")
    )
    if viewer.org_id is not None:
        query = query.where(Event.org_id == viewer.org_id)
    else:
        query = query.join(
            EventReminder, and_(EventReminder.event_id == Event.id, EventReminder.user_id == viewer.user_id)
        )
    if only is not None:
        query = query.where(Event.id == only)
    items = []
    for event_id, org_id, title, starts_at, ends_at, org_name in (await db.execute(query)).tuples():
        href = (
            web_paths.dev_event_path(event_id)
            if viewer.org_id is None
            else web_paths.org_event_path(viewer.org_id, event_id)
        )
        items.append(
            Item(
                kind=DeadlineKind.EVENT,
                item_id=event_id,
                title=title,
                context=org_name if org_id is not None and org_name else platform_name,
                href=href,
                due_at=starts_at,
                mine=True,
                engagement_id=None,
                ends_at=ends_at,
            )
        )
    return items
