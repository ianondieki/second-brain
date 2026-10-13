"""REQ-NOT-05 (P28 track B): the nudge job runs every 15 minutes, one run at a time, on the shared clock, registered as
the expiry job is; its notification task delivers a recorded nudge and retries while an email is still queued."""

from __future__ import annotations

from typing import Any

import pytest

from bridge.engagements import nudges
from bridge.jobs import notifications
from bridge.jobs import nudges as jobs
from bridge.jobs.app import IMPORT_PATHS, app

ENGAGEMENT = "01900000-0000-7000-8000-00000000000b"
DEVELOPER = "01900000-0000-7000-8000-00000000000c"


def test_the_task_runs_every_fifteen_minutes_one_run_at_a_time() -> None:
    assert "bridge.jobs.nudges" in IMPORT_PATHS
    app.perform_import_paths()  # type: ignore[no-untyped-call]
    task = app.tasks[jobs.TASK]
    assert (task.name, task.queue, task.lock) == ("engagements.nudge", "engagements", "engagements:nudge")
    crons = {t.task.name: t.cron for t in app.periodic_registry.periodic_tasks.values()}
    assert crons[jobs.TASK] == "*/15 * * * *"
    notify_task = app.tasks[nudges.TASK]
    assert (notify_task.name, notify_task.queue) == ("engagements.nudge_notify", "notifications")


async def test_the_task_runs_a_pass_on_the_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    async def run(factory: object, **kwargs: Any) -> None:
        calls.append((factory, kwargs))

    factory = object()
    monkeypatch.setattr(jobs, "run_nudges", run)
    jobs.use_runtime(jobs.NudgeRuntime(session_factory=factory))  # type: ignore[arg-type]
    try:
        await jobs.nudge(timestamp=0)
    finally:
        jobs.use_runtime(None)
    assert calls == [(factory, {})]  # the job's own timestamp is ignored: the shared clock decides
    assert isinstance(jobs.runtime(), jobs.NudgeRuntime)
    jobs.use_runtime(None)


@pytest.mark.parametrize("done", [True, False])
async def test_the_notification_task_delivers_and_retries_a_queued_email(
    monkeypatch: pytest.MonkeyPatch, done: bool
) -> None:
    seen: list[dict[str, Any]] = []

    async def deliver(factory: object, provider: object, settings: object, **kwargs: Any) -> bool:
        seen.append(kwargs)
        return done

    monkeypatch.setattr(nudges, "deliver", deliver)
    notifications.use_runtime(
        notifications.NotificationRuntime(settings=object(), session_factory=object(), email_provider=object())  # type: ignore[arg-type]
    )
    args: dict[str, Any] = {
        "engagement_id": ENGAGEMENT,
        "developer_id": DEVELOPER,
        "kind": "contact_overdue",
        "key": "e4:2026-10-09",
        "org_recipients": [DEVELOPER],
        "developer": True,
        "on": "2026-10-09",
    }
    try:
        if done:
            await notifications.engagement_nudge_notify(**args)
        else:
            with pytest.raises(notifications.EmailStillQueued):
                await notifications.engagement_nudge_notify(**args)
    finally:
        notifications.use_runtime(None)
    assert seen[0]["kind"] == "contact_overdue"
    assert str(seen[0]["engagement_id"]) == ENGAGEMENT
    assert (seen[0]["days"], seen[0]["on"], seen[0]["seq"]) == (None, "2026-10-09", None)
