"""REQ-NOT-04: the tracker's notification task is registered under the name the commands queue, on its own queue;
it runs ``notify.deliver`` with the runtime's parts and retries while an email is still queued."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from bridge.config import get_settings
from bridge.engagements import notify
from bridge.jobs import notifications
from bridge.jobs.app import IMPORT_PATHS, app
from bridge.notifications.email import FakeEmailProvider

IDS = {
    "engagement_id": "01900000-0000-7000-8000-00000000000d",
    "event_id": "01900000-0000-7000-8000-00000000000e",
    "developer_id": "01900000-0000-7000-8000-00000000000f",
}


def test_the_task_is_registered_on_the_notifications_queue() -> None:
    assert "bridge.jobs.notifications" in IMPORT_PATHS
    task = app.tasks[notify.TASK]
    assert task.queue == notify.QUEUE == "notifications"


async def test_the_task_delivers_and_retries_while_an_email_is_queued(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    outcome = {"done": True}

    async def deliver(factory: object, provider: object, settings: object, **kwargs: Any) -> bool:
        calls.append({"provider": provider, **kwargs})
        return outcome["done"]

    monkeypatch.setattr(notify, "deliver", deliver)
    provider = FakeEmailProvider()
    notifications.use_runtime(
        notifications.NotificationRuntime(get_settings(), session_factory=object(), email_provider=provider)  # type: ignore[arg-type]
    )
    try:
        await notifications.engagement_notify(**IDS, reason_text="Because.")
        assert calls == [
            {
                "provider": provider,
                "engagement_id": UUID(IDS["engagement_id"]),
                "event_id": UUID(IDS["event_id"]),
                "developer_id": UUID(IDS["developer_id"]),
                "reason_text": "Because.",
            }
        ]
        outcome["done"] = False
        with pytest.raises(notifications.EmailStillQueued):
            await notifications.engagement_notify(**IDS)
    finally:
        notifications.use_runtime(None)


def test_the_runtime_builds_its_parts_from_settings() -> None:
    runtime = notifications.NotificationRuntime(get_settings())
    assert isinstance(runtime.email_provider, FakeEmailProvider)  # EMAIL_PROVIDER=fake in tests
    assert runtime.email_provider is runtime.email_provider
    assert runtime.session_factory is runtime.session_factory
    assert runtime.settings is get_settings()
    notifications.use_runtime(None)
    assert notifications.runtime() is notifications.runtime()
    notifications.use_runtime(None)
    assert notifications.NotificationRuntime().settings is get_settings()
    assert notifications.NOTIFY_RETRY.permanent == ()
