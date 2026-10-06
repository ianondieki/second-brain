"""The weekly technology trends job (REQ-DEV-02; D-60; P22 card B, default (5)): ``trends.draft``.

Procrastinate runs it on Mondays at 02:15 UTC (05:15 in Nairobi); a staff admin's manual run (``POST
/api/admin/research/trend-runs``) queues the same task with their id. Its own timestamp is ignored: the shared clock
(``app_clock_now()``) decides the week. One run at a time (lock ``trends:draft``); no retry (a week without cards is
drafted by the next run, or staff start one). The pass (``run_weekly``):

1. ``job_state``: when a candidate or published card was created in the last 6 days, nothing else happens (no model
   call); the excerpts that candidate and published cards cite are left out of the call.
2. One ``draft_trends`` call for the week's Monday on a session with no user bound (a platform call: the global daily
   cap, the prototype total and the kill switch apply; ``bridge.problems.trends.run``: the checks in code, one retry on
   a refused answer; the kill switch, a spent cap or the demo fallback refuse the week without storing anything).
3. ``store_candidates``: each kept card through ``app_create_trend_candidate``, committed together.

The cards are read as the session's user: the manual run binds the staff admin who started it (who reads every card,
and may create candidates). Revision 0010 gives a session with no user bound no reader of the cards, so the weekly run
cannot see whether it would repeat a card: it fails closed (``trends.draft_skipped``, reason ``no_reader``) until a
job-only reader exists (the open question of this task's report). Every outcome is one log line; nobody is notified:
staff admins find the candidates on the research page. The runtime (database sessions, the LLM runtime) is built from
settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import bind_tenant, create_engine, create_session_factory
from bridge.engagements.calendar import NAIROBI
from bridge.jobs.app import app
from bridge.llm.client import LLMClient
from bridge.llm.deps import build_runtime, routed_client
from bridge.llm.routing import LLMRuntime
from bridge.logging import get_logger
from bridge.problems.trends.run import Refused, TrendsDeps, draft_trends
from bridge.problems.trends.store import LOCK, QUEUE, RUN_TASK, job_state, store_candidates

TASK: Final = RUN_TASK
CRON: Final = "15 2 * * 1"  # Monday 02:15 UTC = 05:15 Africa/Nairobi
LOOK_BACK: Final = timedelta(days=6)
RECENT_CARD: Final = "recent_card"
NO_READER: Final = "no_reader"
_NOW: Final = text("SELECT app_clock_now()")
log = get_logger(__name__)


@dataclass(frozen=True)
class WeeklyDeps:
    """The job's sessions, its LLM client of a session, and the drafting dependencies around a client."""

    factory: async_sessionmaker[AsyncSession]
    llm: Callable[[AsyncSession], LLMClient]
    trends: Callable[[LLMClient], TrendsDeps] = field(default=TrendsDeps.default)


@dataclass(frozen=True, slots=True)
class Skipped:
    week_start: date
    reason: str  # RECENT_CARD or NO_READER


@dataclass(frozen=True, slots=True)
class Stored:
    week_start: date
    card_ids: tuple[UUID, ...]


WeeklyOutcome = Stored | Skipped | Refused


def monday_of(now: datetime) -> date:
    today = now.astimezone(NAIROBI).date()
    return today - timedelta(days=today.weekday())


async def run_weekly(deps: WeeklyDeps, *, user_id: UUID | None = None) -> WeeklyOutcome:
    """One pass of ``trends.draft`` (see the module docstring); ``user_id``: the staff admin of a manual run."""
    async with deps.factory() as db:
        if user_id is not None:
            await bind_tenant(db, user_id=user_id)
        now: datetime = (await db.execute(_NOW)).scalar_one()
        week_start = monday_of(now)
        state = await job_state(db, now - LOOK_BACK)
    if state is None or state.recent:
        reason = NO_READER if state is None else RECENT_CARD
        log.info("trends.draft_skipped", day=week_start.isoformat(), reason=reason)
        return Skipped(week_start, reason)
    async with deps.factory() as platform:  # the call is the platform's (no user, no organisation: the global caps)
        outcome = await draft_trends(deps.trends(deps.llm(platform)), week_start, exclude_refs=state.cited)
        await platform.commit()  # the client's own writes (the ledger)
    if isinstance(outcome, Refused):
        return outcome  # draft_trends logged it
    async with deps.factory() as db:  # the cards, in one transaction, as whoever read the state
        if user_id is not None:
            await bind_tenant(db, user_id=user_id)
        card_ids = await store_candidates(db, outcome)
        await db.commit()
    log.info("trends.stored", day=week_start.isoformat(), count=len(card_ids))
    return Stored(week_start, tuple(card_ids))


class TrendsRuntime:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        llm: LLMRuntime | None = None,
        client: Callable[[AsyncSession], LLMClient] | None = None,
    ) -> None:
        self._settings, self._factory, self._llm, self._client = settings, factory, llm, client

    def deps(self) -> WeeklyDeps:
        settings = self._settings = self._settings or get_settings()
        if self._factory is None:
            self._factory = create_session_factory(create_engine(settings.database_url.get_secret_value()))
        factory, client = self._factory, self._client
        if client is None:
            if self._llm is None:
                self._llm = build_runtime(settings)
            llm = self._llm

            def client(db: AsyncSession) -> LLMClient:
                return routed_client(db, factory=factory, settings=settings, runtime=llm)

        return WeeklyDeps(factory=factory, llm=client)

    async def aclose(self) -> None:
        if self._llm is not None:
            await self._llm.aclose()


_runtime: TrendsRuntime | None = None


def runtime() -> TrendsRuntime:
    global _runtime
    if _runtime is None:
        _runtime = TrendsRuntime()
    return _runtime


def use_runtime(value: TrendsRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="trends-draft-weekly-monday-0515-eat")
@app.task(name=TASK, queue=QUEUE, lock=LOCK)
async def draft(timestamp: int, user_id: str | None = None) -> None:
    del timestamp  # the shared clock decides, not the job's own time
    await run_weekly(runtime().deps(), user_id=None if user_id is None else UUID(user_id))
