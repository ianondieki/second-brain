"""The saved-search alerts' daily job (P21 track C; REQ-PERS-03, REQ-TREND-02; ``bridge.matching.saved_search_alerts``).

``saved_searches.alert`` runs at 04:05 UTC (Procrastinate's cron is UTC), 07:05 in Nairobi. Its own timestamp is
ignored: the shared clock (``app_clock_now()``) decides which day it is, so the dev/test clock drives it like every
other deadline. One run at a time (a Procrastinate lock); no retry: a person whose alerts failed stays due, and the
next run picks them up (a run is idempotent per Nairobi day). The runtime (database, settings, email provider) is built
from settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.jobs.app import app
from bridge.matching.saved_search_alerts import AlertDeps, run_alerts
from bridge.notifications.email import EmailProvider, provider_from_settings

TASK: Final = "saved_searches.alert"
QUEUE: Final = "notifications"
LOCK: Final = "saved_searches:alert"
CRON: Final = "5 4 * * *"  # 04:05 UTC = 07:05 Africa/Nairobi (UTC+3, no daylight saving)


class AlertRuntime:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        email: EmailProvider | None = None,
    ) -> None:
        self._settings, self._factory, self._email = settings, factory, email

    def deps(self) -> AlertDeps:
        settings = self._settings = self._settings or get_settings()
        if self._factory is None:
            self._factory = create_session_factory(create_engine(settings.database_url.get_secret_value()))
        if self._email is None:
            self._email = provider_from_settings(settings)
        return AlertDeps(self._factory, settings, self._email)


_runtime: AlertRuntime | None = None


def runtime() -> AlertRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AlertRuntime()
    return _runtime


def use_runtime(value: AlertRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="saved-searches-daily-0705-eat")
@app.task(name=TASK, queue=QUEUE, lock=LOCK)
async def alert(timestamp: int) -> None:
    del timestamp  # the shared clock decides, not the job's own time
    await run_alerts(runtime().deps())
