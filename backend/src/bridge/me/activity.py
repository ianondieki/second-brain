"""The activity calendar (REQ-UX-05; D-67; P25-B): ``GET /api/me/activity?weeks=``, the caller's own actions per day.

**The range.** ``weeks`` x 7 days ending today, a day being Africa/Nairobi's (UTC+3, no daylight saving) and today
the platform clock's (``app_clock_now()``, so the dev/test clock moves it). A row counts on the Nairobi day of its
time: 20:59 UTC is still that day, 21:00 UTC is the next.

**What counts, by side** (``bridge.me.caller``; staff use the developer portal, so they get the developer's kinds):

- developer: ``proposal_published`` (their proposal's first publication: ``published_at``; that registers version 1,
  counted here only), ``version_registered`` (a later version of it registered: ``version_no`` above 1,
  ``registered_at``), ``engagement_step`` (a tracker
  event they acted: ``actor_user_id``), ``message_sent`` (an engagement message they sent), ``quiz_answered`` (their
  attempt at a day's quiz: ``finished_at``) and ``team_message`` (a message they sent in a team-up thread);
- organisation member: ``proposal_opened`` (a full proposal they opened: their own ``document_views`` rows),
  ``engagement_step``, ``message_sent`` and ``brief_posted`` (a Brief they posted: ``created_by``).

Only rows whose actor is the caller, read in the request's session under the caller's Row-Level Security (every one
of these tables shows a person their own rows); counts only, never a record. Every kind of the side is listed, with
0 when it has none, in a fixed order.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy import (
    ColumnElement,
    Date,
    Select,
    SQLColumnExpression,
    Text,
    cast,
    func,
    label,
    literal_column,
    select,
    text,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.engagements.models import EngagementEvent, EngagementMessage
from bridge.me.caller import Caller, Side
from bridge.me.schemas import NAIROBI_ZONE, ActivityCalendar, ActivityDay, ActivityKind, ActivityKindCount
from bridge.models.enums import ProblemSource
from bridge.problems.models import Problem
from bridge.proposals.models import DocumentView, Proposal, ProposalVersion
from bridge.quiz.models import QuizAttempt
from bridge.teams.models import TeamMessage

NAIROBI: Final = ZoneInfo(NAIROBI_ZONE)
DEFAULT_WEEKS: Final = 26
MAX_WEEKS: Final = 52
DEVELOPER_KINDS: Final[tuple[ActivityKind, ...]] = (
    "version_registered",
    "proposal_published",
    "engagement_step",
    "message_sent",
    "quiz_answered",
    "team_message",
)
ORG_KINDS: Final[tuple[ActivityKind, ...]] = ("proposal_opened", "engagement_step", "message_sent", "brief_posted")
KINDS: Final[dict[Side, tuple[ActivityKind, ...]]] = {
    "developer": DEVELOPER_KINDS,
    "org": ORG_KINDS,
    "staff": DEVELOPER_KINDS,
}
FIRST_VERSION: Final = 1
_NOW: Final = text("SELECT app_clock_now()")
_ZONE: Final = literal_column(f"'{NAIROBI_ZONE}'", Text)  # a constant, not a parameter: GROUP BY repeats the expression


def nairobi_day(moment: datetime) -> date:
    return moment.astimezone(NAIROBI).date()


def window(today: date, weeks: int) -> tuple[date, date]:
    """The first and last day of ``weeks`` weeks ending ``today``."""
    return today - timedelta(days=7 * weeks - 1), today


def bounds(first: date, last: date) -> tuple[datetime, datetime]:
    """The instants the range covers: from the start of ``first`` to the start of the day after ``last`` (Nairobi)."""
    return datetime.combine(first, time(), NAIROBI), datetime.combine(last + timedelta(days=1), time(), NAIROBI)


def _when(kind: ActivityKind, moment: SQLColumnExpression[Any], *where: ColumnElement[bool]) -> Select[Any]:
    return select(literal_column(f"'{kind}'", Text).label("kind"), label("at", moment)).where(*where)


def kind_statement(kind: ActivityKind, caller: Caller) -> Select[Any]:
    """One kind's actions by the caller, as (kind, at): the moment each happened."""
    user = caller.user_id
    if kind == "version_registered":
        return _when(
            kind,
            ProposalVersion.registered_at,
            ProposalVersion.proposal_id.in_(select(Proposal.id).where(Proposal.owner_id == user)),
            ProposalVersion.registered_at.is_not(None),
            ProposalVersion.version_no > FIRST_VERSION,  # the first is the publication: one action, one count
        )
    if kind == "proposal_published":
        return _when(kind, Proposal.published_at, Proposal.owner_id == user, Proposal.published_at.is_not(None))
    if kind == "engagement_step":
        return _when(kind, EngagementEvent.created_at, EngagementEvent.actor_user_id == user)
    if kind == "message_sent":
        return _when(kind, EngagementMessage.created_at, EngagementMessage.sender_user_id == user)
    if kind == "quiz_answered":
        return _when(kind, QuizAttempt.finished_at, QuizAttempt.user_id == user)
    if kind == "team_message":
        return _when(kind, TeamMessage.created_at, TeamMessage.sender_user_id == user)
    if kind == "proposal_opened":
        return _when(kind, DocumentView.started_at, DocumentView.viewer_user_id == user)
    if kind == "brief_posted":
        return _when(kind, Problem.created_at, Problem.created_by == user, Problem.source == ProblemSource.ORG_BRIEF)
    raise ValueError(f"no activity kind {kind!r}")


def counts_statement(caller: Caller, start: datetime, end: datetime) -> Select[Any]:
    """Per kind and Nairobi day, how many of the caller's actions fall in [``start``, ``end``)."""
    actions = union_all(*(kind_statement(kind, caller) for kind in KINDS[caller.side])).subquery("actions")
    day = cast(func.timezone(_ZONE, actions.c.at), Date).label("day")
    return (
        select(actions.c.kind, day, func.count().label("n"))
        .where(actions.c.at >= start, actions.c.at < end)
        .group_by(actions.c.kind, day)
    )


def calendar(side: Side, first: date, last: date, rows: Iterable[tuple[str, date, int]]) -> ActivityCalendar:
    """Every day from ``first`` to ``last`` with its count, each kind of ``side`` with its own, and the total; a row
    of another kind or outside the range is left out."""
    kinds = KINDS[side]
    per_day: Counter[date] = Counter()
    per_kind: Counter[str] = Counter()
    for kind, day, n in rows:
        if kind in kinds and first <= day <= last:
            per_day[day] += n
            per_kind[kind] += n
    span = (last - first).days + 1
    days = [first + timedelta(days=offset) for offset in range(span)]
    return ActivityCalendar(
        from_=first,
        to=last,
        timezone=NAIROBI_ZONE,
        days=[ActivityDay(date=day, count=per_day[day]) for day in days],
        kinds=[ActivityKindCount(kind=kind, count=per_kind[kind]) for kind in kinds],
        total=sum(per_kind.values()),
    )


def rows_of(result: Iterable[Any]) -> list[tuple[str, date, int]]:
    return [(str(row.kind), row.day, int(row.n)) for row in result]


async def read(db: AsyncSession, caller: Caller, weeks: int) -> ActivityCalendar:
    """The caller's calendar over ``weeks`` weeks ending today on the platform clock, in the caller's transaction."""
    now: datetime = (await db.execute(_NOW)).scalar_one()
    first, last = window(nairobi_day(now), weeks)
    start, end = bounds(first, last)
    result = await db.execute(counts_statement(caller, start, end))
    return calendar(caller.side, first, last, rows_of(result))
