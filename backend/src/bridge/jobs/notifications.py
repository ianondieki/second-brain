"""Notification jobs (REQ-NOT-04; ``bridge.engagements.notify``).

``engagements.notify`` tells the other party about one tracker event (in-app, and EM2 on entering
``INTEREST_CONFIRMED``), queued by the command's transaction on the ``notifications`` queue, one engagement at a time
(lock ``engagement:<id>``). It is idempotent (dedupe keys), so a retry never notifies twice; an email still queued
after transient provider errors raises ``EmailStillQueued`` and the job backs off and resumes it.

The runtime (settings, database sessions, email provider) is built from settings on first use; tests install their
own with ``use_runtime``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.db import create_engine, create_session_factory
from bridge.engagements import notify
from bridge.jobs.app import app
from bridge.jobs.provenance import Backoff
from bridge.notifications.email import EmailProvider, provider_from_settings


class EmailStillQueued(RuntimeError):
    """An email of the job is still queued after transient provider errors: retry later (the ledger resumes it)."""


NOTIFY_RETRY = Backoff(base=30, cap=1800, max_attempts=10, permanent=())


class NotificationRuntime:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        email_provider: EmailProvider | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._email_provider = email_provider

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            self._session_factory = create_session_factory(create_engine(self.settings.database_url.get_secret_value()))
        return self._session_factory

    @property
    def email_provider(self) -> EmailProvider:
        if self._email_provider is None:
            self._email_provider = provider_from_settings(self.settings)
        return self._email_provider


_runtime: NotificationRuntime | None = None


def runtime() -> NotificationRuntime:
    global _runtime
    if _runtime is None:
        _runtime = NotificationRuntime()
    return _runtime


def use_runtime(value: NotificationRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.task(name=notify.TASK, queue=notify.QUEUE, retry=NOTIFY_RETRY)
async def engagement_notify(
    engagement_id: str, event_id: str, developer_id: str, reason_text: str | None = None
) -> None:
    rt = runtime()
    done = await notify.deliver(
        rt.session_factory,
        rt.email_provider,
        rt.settings,
        engagement_id=UUID(engagement_id),
        event_id=UUID(event_id),
        developer_id=UUID(developer_id),
        reason_text=reason_text,
    )
    if not done:
        raise EmailStillQueued(f"engagement {engagement_id}: an email is still queued")
