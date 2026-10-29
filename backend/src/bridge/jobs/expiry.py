"""The tracker's clock job (REQ-ENG-10 part, AC-PROP-3; ``bridge.engagements.expiry``).

``engagements.expire`` runs every 15 minutes: engagements left past their stage's ``expire_bd`` become ``EXPIRED``
and holds whose resume date has come resume, on the shared clock (Procrastinate's own timestamp is ignored, so the
dev/test clock moves it). One run at a time (lock ``engagements:expire``); no retry: whatever a run could not do, the
next one picks up (each engagement is decided again under its row lock, so a run never acts twice). The session factory
is built from settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.engagements.expiry import run_expiry
from bridge.jobs.app import app

TASK: Final = "engagements.expire"
QUEUE: Final = "engagements"
LOCK: Final = "engagements:expire"
CRON: Final = "*/15 * * * *"


class ExpiryRuntime:
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


_runtime: ExpiryRuntime | None = None


def runtime() -> ExpiryRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ExpiryRuntime()
    return _runtime


def use_runtime(value: ExpiryRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="engagements-expire-every-15-minutes")
@app.task(name=TASK, queue=QUEUE, lock=LOCK)
async def expire(timestamp: int) -> None:
    del timestamp  # the shared clock decides, not the job's own time
    await run_expiry(runtime().session_factory)
