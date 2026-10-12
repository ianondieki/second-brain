"""The organisation's board: its engagements by stage group, their age, what has stalled, and a funnel (REQ-ENG-14;
docs/platform/tasks/P27.md track B; docs/spec/06 6.9 "5-group stepper"; REQUIREMENTS "pipeline analytics", REQ-R2-04,
brought forward read-only).

- Columns: the five stage groups of the stepper (``state_machine.STAGE_GROUPS``: Review, Contact and NDA, Agreement,
  Implementation, Close; a public entity's procurement route with Contact and NDA, where the spec places it). An
  engagement in a side state (INFO_REQUESTED, ON_HOLD) sits under the stage it left (``paused_from``), as the stepper
  shows it; an ended one (DECLINED, WITHDRAWN, EXPIRED, TERMINATED) sits in none; CLOSED sits in Close while it
  closed inside the funnel's window (``WINDOW_DAYS``; the column's count is that bounded count), and in none after.
- Each card: the engagement's summary (as the organisation's list shows it: the developer's handle until named), when
  it entered the stage of its column from the main path (``stage_start``: a question or a hold does not restart it),
  its latest tracker event (``engagement_events``: messages are not tracker events), the calendar days since the stage
  began (Nairobi dates) and ``stalled``: active, not on hold, no tracker event for ``pipeline.stalled_after_bd``
  Kenyan business days or more (policy.yaml; ``calendar.business_days_between`` over the holidays table). ``team`` is
  the organisation's triage facts (REQ-ENG-15), filled where that track is built.
- ``median_days_in_stage``: the median age of the column's open engagements (CLOSED ones left out: they no longer age
  in a stage); None with none.
- Funnel: over the last ``WINDOW_DAYS`` days, the engagements whose first entry into each group (an event whose
  ``to_state`` maps to it, ever) fell inside the window; ``closed`` those that reached CLOSED and ``ended`` those that
  ended DECLINED, WITHDRAWN, EXPIRED or TERMINATED inside it (a terminal state is entered once: the engagement's
  ``ended_at``, which the database stamps from that event). The database computes each first entry
  (``min(created_at)`` per engagement and group) and returns only those inside the window.

Everything is read under the member's Row-Level Security (``app.org_id`` bound), with one query per kind of row
however many engagements there are; what is read is bounded by the board (its open engagements and those CLOSED inside
the window: their state changes) and by the window (the funnel's rows), never by the organisation's whole history.
Plain code decides every value.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final, get_args
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.engagements import history
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import NAIROBI, business_days_between, local_date
from bridge.engagements.models import Engagement, EngagementEvent
from bridge.engagements.pipeline_policy import get_pipeline_policy
from bridge.engagements.schemas import (
    EngagementSummary,
    FunnelEntered,
    FunnelOut,
    PipelineColumn,
    PipelineItem,
    PipelineOut,
    StageGroup,
    TeamFacts,
)
from bridge.engagements.service import all_holidays
from bridge.engagements.team import team_facts
from bridge.models.enums import EngagementState

S = EngagementState
WINDOW_DAYS: Final = 90
GROUPS: Final[tuple[StageGroup, ...]] = get_args(StageGroup)


def as_group(name: str) -> StageGroup:
    """``name`` as one of the five groups (the stepper's names; anything else is a bug: ValueError at import)."""
    for group in GROUPS:
        if group == name:
            return group
    raise ValueError(f"not a stage group: {name}")


_GROUP_OF: Final[Mapping[EngagementState, StageGroup]] = {
    **{state: as_group(name) for state, name in sm.STAGE_GROUPS.items()},
    S.PROCUREMENT_ROUTE: "contact_nda",  # stage 3b, between approval and first contact (docs/spec/06 6.9)
}
ENDED: Final = frozenset({S.DECLINED, S.WITHDRAWN, S.EXPIRED, S.TERMINATED})
# The group an event's ``to_state`` enters, in SQL (NULL for a side or terminal state outside the five groups).
_EVENT_GROUP: Final = case(
    *(
        (EngagementEvent.to_state.in_([state for state, of in _GROUP_OF.items() if of == group]), group)
        for group in GROUPS
    )
)


@dataclass(frozen=True, slots=True)
class Change:
    """A state change of the chain: from, to, when (in chain order)."""

    from_state: EngagementState | None
    to_state: EngagementState
    at: datetime


# ------------------------------------------------------------------------------------------------- pure rules


def board_group(state: EngagementState, paused_from: EngagementState | None) -> StageGroup | None:
    """The column of an engagement in ``state`` (a side state's: the stage it left); None for an ended one."""
    stage = paused_from if state in sm.RETURNING else state
    return None if stage is None else _GROUP_OF.get(stage)


def stage_start(changes: Sequence[Change], stage: EngagementState, fallback: datetime) -> datetime:
    """When ``stage`` was last entered from the main path (a return from a side state continues it); ``fallback``
    when the chain read has no such entry."""
    entries = [c.at for c in changes if c.to_state is stage and c.from_state not in sm.RETURNING]
    return entries[-1] if entries else fallback


def days_since(start: datetime, now: datetime) -> int:
    """Calendar days from the Nairobi date of ``start`` to that of ``now`` (never negative)."""
    return max(0, (local_date(now) - local_date(start)).days)


def stalled(
    state: EngagementState, last_event_at: datetime, now: datetime, holidays: frozenset[date], after_bd: int
) -> bool:
    """No movement: active, not on hold, and ``after_bd`` or more Kenyan business days since the last event."""
    if state in sm.TERMINAL or state is S.ON_HOLD:
        return False
    return business_days_between(local_date(last_event_at), local_date(now), holidays) >= after_bd


def median(days: Sequence[int]) -> float | None:
    return float(statistics.median(days)) if days else None


def window_start(now: datetime, window_days: int) -> datetime:
    """The window's first instant: midnight in Nairobi ``window_days`` days before ``now``'s Nairobi day, so whole
    days count and the Close column and the funnel do not shift through the day."""
    return datetime.combine(local_date(now) - timedelta(days=window_days), time.min, tzinfo=NAIROBI)


def funnel(
    firsts: Iterable[tuple[StageGroup, datetime]],
    endings: Iterable[tuple[EngagementState, datetime]],
    now: datetime,
    window_days: int,
) -> FunnelOut:
    """The funnel of the window ending at ``now``: ``firsts`` holds each engagement's first entry into a group (one
    per engagement and group), ``endings`` each ended engagement's terminal state and when it was entered (one per
    engagement). What falls inside the window counts."""
    start = window_start(now, window_days)
    entered: dict[StageGroup, int] = dict.fromkeys(GROUPS, 0)
    for group, at in firsts:
        entered[group] += int(start <= at <= now)
    inside = [state for state, at in endings if start <= at <= now]
    closed = sum(state is S.CLOSED for state in inside)
    ended = sum(state in ENDED for state in inside)
    return FunnelOut(window_days=window_days, entered=FunnelEntered(**entered), closed=closed, ended=ended)


# ------------------------------------------------------------------------------------------------- the read


async def _changes(db: AsyncSession, engagement_ids: Sequence[UUID]) -> dict[UUID, list[Change]]:
    """The state changes of the board's engagements, in chain order (each card's ``stage_start``)."""
    if not engagement_ids:
        return {}
    rows = await db.execute(
        select(
            EngagementEvent.engagement_id,
            EngagementEvent.from_state,
            EngagementEvent.to_state,
            EngagementEvent.created_at,
        )
        .where(
            EngagementEvent.engagement_id.in_(list(engagement_ids)),
            EngagementEvent.from_state.is_distinct_from(EngagementEvent.to_state),
        )
        .order_by(EngagementEvent.engagement_id, EngagementEvent.seq)
    )
    found: dict[UUID, list[Change]] = defaultdict(list)
    for engagement_id, from_state, to_state, created_at in rows.tuples():
        found[engagement_id].append(Change(from_state, to_state, created_at))
    return found


async def _first_entries(
    db: AsyncSession, org_id: UUID, start: datetime, now: datetime
) -> list[tuple[StageGroup, datetime]]:
    """Each of the organisation's engagements' first entry into each group, ever (``min(created_at)`` per engagement
    and group, ended engagements too), returned only when it falls inside ``[start, now]``."""
    events = (
        select(EngagementEvent.engagement_id, _EVENT_GROUP.label("grp"), EngagementEvent.created_at)
        .join(Engagement, Engagement.id == EngagementEvent.engagement_id)
        .where(Engagement.org_id == org_id, EngagementEvent.from_state.is_distinct_from(EngagementEvent.to_state))
        .subquery()
    )
    first = func.min(events.c.created_at)
    rows = await db.execute(
        select(events.c.grp, first)
        .where(events.c.grp.is_not(None))
        .group_by(events.c.engagement_id, events.c.grp)
        .having(first.between(start, now))
    )
    return [(as_group(group), at) for group, at in rows.tuples()]


async def _endings(
    db: AsyncSession, org_id: UUID, start: datetime, now: datetime
) -> list[tuple[EngagementState, datetime]]:
    """The organisation's engagements that entered a terminal state inside ``[start, now]``: the state and when."""
    rows = await db.execute(
        select(Engagement.state, Engagement.ended_at).where(
            Engagement.org_id == org_id, Engagement.ended_at.between(start, now)
        )
    )
    return [(state, at) for state, at in rows.tuples() if at is not None]


async def _last_events(db: AsyncSession, engagement_ids: Sequence[UUID]) -> dict[UUID, datetime]:
    if not engagement_ids:
        return {}
    rows = await db.execute(
        select(EngagementEvent.engagement_id, func.max(EngagementEvent.created_at))
        .where(EngagementEvent.engagement_id.in_(list(engagement_ids)))
        .group_by(EngagementEvent.engagement_id)
    )
    return dict(rows.tuples().all())


def _item(
    summary: EngagementSummary,
    changes: Sequence[Change],
    last_event_at: datetime,
    now: datetime,
    holidays: frozenset[date],
    after_bd: int,
    team: TeamFacts | None,
) -> PipelineItem:
    stage = summary.paused_from if summary.state in sm.RETURNING and summary.paused_from else summary.state
    started = stage_start(changes, stage, summary.stage_entered_at)
    return PipelineItem.model_validate(
        {
            **summary.model_dump(),
            "stage_entered_at": started,
            "last_event_at": last_event_at,
            "days_in_stage": days_since(started, now),
            "stalled": stalled(summary.state, last_event_at, now, holidays, after_bd),
            "team": team,
        }
    )


async def pipeline(
    db: AsyncSession, org_id: UUID, *, now: datetime, deals_enabled: bool, reader_id: UUID
) -> PipelineOut:
    """The organisation's board at ``now`` (see the module docstring); ``reader_id`` counts each card's unread
    messages for the member reading it."""
    after_bd = get_pipeline_policy().stalled_after_bd
    start = window_start(now, WINDOW_DAYS)
    found = await db.execute(
        select(Engagement)
        .where(
            Engagement.org_id == org_id,
            Engagement.state.not_in(list(ENDED)),
            or_(Engagement.state != S.CLOSED, Engagement.ended_at.between(start, now)),  # Close: the window's
        )
        .order_by(Engagement.stage_entered_at, Engagement.id)
    )
    engagements = list(found.scalars())
    summaries = await history.summaries(
        db, engagements, deals_enabled=deals_enabled, developer_caller=False, reader_id=reader_id
    )
    changes = await _changes(db, [e.id for e in engagements])
    last = await _last_events(db, [e.id for e in engagements])
    # The organisation's triage per card (REQ-ENG-15, D-68): constant statements; nothing for an engagement whose
    # developer is the reading member.
    team = await team_facts(db, org_id, [e.id for e in engagements], reader_id)
    holidays = await all_holidays(db)
    columns: dict[StageGroup, list[PipelineItem]] = {group: [] for group in GROUPS}
    for summary in summaries:
        group = board_group(summary.state, summary.paused_from)
        if group is None:  # pragma: no cover - a side state that left no main-path stage (never written)
            continue
        latest = last.get(summary.id, summary.stage_entered_at)
        columns[group].append(
            _item(summary, changes.get(summary.id, []), latest, now, holidays, after_bd, team.get(summary.id))
        )
    out = []
    for group, items in columns.items():
        items.sort(key=lambda item: (item.stage_entered_at, item.id))
        ages = [item.days_in_stage for item in items if item.state is not S.CLOSED]
        out.append(PipelineColumn(group=group, count=len(items), median_days_in_stage=median(ages), items=items))
    flow = funnel(
        await _first_entries(db, org_id, start, now), await _endings(db, org_id, start, now), now, WINDOW_DAYS
    )
    return PipelineOut(columns=out, funnel=flow, stalled_after_bd=after_bd, now=now)
