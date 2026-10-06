"""Today's five's nightly job (REQ-DEV-01; D-59; P22 card A; ``bridge.quiz.nightly``).

``quiz.draft`` runs at 23:30 UTC (Procrastinate's cron is UTC), 02:30 in Nairobi. Its own timestamp is ignored: the
shared clock (``app_nairobi_today()``) decides which days it drafts, so the dev/test clock drives it like every other
deadline. One run at a time (a Procrastinate lock); no retry (a day without a draft is drafted by the next run, or
staff see an empty queue). The runtime (database sessions with no user bound, the LLM runtime, the curated list and
the policy) is built from settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.jobs.app import app
from bridge.llm.client import LLMClient
from bridge.llm.deps import build_runtime, routed_client
from bridge.llm.routing import LLMRuntime
from bridge.quiz.nightly import NightlyDeps, run_nightly
from bridge.quiz.policy import QuizPolicy, get_quiz_policy
from bridge.quiz.sources import SourceList, get_sources

TASK: Final = "quiz.draft"
QUEUE: Final = "quiz"
LOCK: Final = "quiz:draft"
CRON: Final = "30 23 * * *"  # 23:30 UTC = 02:30 Africa/Nairobi (UTC+3, no daylight saving)


class NightlyRuntime:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        llm: LLMRuntime | None = None,
        client: Callable[[AsyncSession], LLMClient] | None = None,
        sources: SourceList | None = None,
        policy: QuizPolicy | None = None,
    ) -> None:
        self._settings, self._factory, self._llm, self._client = settings, factory, llm, client
        self._sources, self._policy = sources, policy

    def deps(self) -> NightlyDeps:
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

        return NightlyDeps(
            factory=factory,
            llm=client,
            sources=self._sources or get_sources(),
            policy=self._policy or get_quiz_policy(),
        )

    async def aclose(self) -> None:
        if self._llm is not None:
            await self._llm.aclose()


_runtime: NightlyRuntime | None = None


def runtime() -> NightlyRuntime:
    global _runtime
    if _runtime is None:
        _runtime = NightlyRuntime()
    return _runtime


def use_runtime(value: NightlyRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="quiz-draft-daily-0230-eat")
@app.task(name=TASK, queue=QUEUE, lock=LOCK)
async def draft(timestamp: int) -> None:
    del timestamp  # the shared clock decides, not the job's own time
    await run_nightly(runtime().deps())
