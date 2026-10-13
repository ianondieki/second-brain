"""The tracker's nudge job (REQ-NOT-05, REQ-NOT-03, REQ-ENG-05; ``bridge.engagements.nudges``).

``engagements.nudge`` runs every 15 minutes: the escalations to an organisation's admins (first contact late, the
procurement route waiting, a milestone review late), EM6 Contact overdue to both sides, EM5 NDA reminders and the
milestone review reminders, each recorded once in ``engagement_nudges`` before its notification is queued
(``engagements.nudge_notify``, ``bridge.jobs.notifications``), on the shared clock (Procrastinate's own timestamp is
ignored, so the dev/test clock moves it). One run at a time (lock ``engagements:nudge``); no retry: whatever a run could
not do, the next one picks up (the ledger makes each nudge fire once). The session factory is built from settings on
first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.engagements.nudges import run_nudges
from bridge.jobs.app import app

TASK: Final = "engagements.nudge"
QUEUE: Final = "engagements"
LOCK: Final = "engagements:nudge"
CRON: Final = "*/15 * * * *"


class NudgeRuntime:
    def __init__(
        self, settings: Settings | None = None, *, session_factory: async_sessionmaker[AsyncSession] | None = None
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            settings = self._settings or get_settings()
            self._session_factory = create_session_factory(create_engine(settings.database_url.get_secret_value()))
        return self._session_factory


_runtime: NudgeRuntime | None = None


def runtime() -> NudgeRuntime:
    global _runtime
    if _runtime is None:
        _runtime = NudgeRuntime()
    return _runtime


def use_runtime(value: NudgeRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="engagements-nudge-every-15-minutes")
@app.task(name=TASK, queue=QUEUE, lock=LOCK)
async def nudge(timestamp: int) -> None:
    del timestamp  # the shared clock decides, not the job's own time
    await run_nudges(runtime().session_factory)
