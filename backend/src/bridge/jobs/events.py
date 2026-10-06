"""This week's reminder job (REQ-DEV-02; D-61; P22 card B; ``REQUIREMENTS.md`` §5 N26, N27; ``bridge.events.reminders``).

``events.remind`` runs every 15 minutes on the reminders queue. Procrastinate's cron is UTC and passes its own
``timestamp``; the job ignores it and reads the shared clock (``app_clock_now()``), so the dev and test clock drives
it like every other reminder. One run at a time (lock ``events:remind``). No retry: the next run, 15 minutes later,
picks up whatever this one could not do, and every message is keyed once per developer and event. The runtime
(database, email provider) is built from settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from typing import Final

from bridge.events.reminders import EventReminderRuntime, run_event_reminders
from bridge.jobs.app import app

TASK: Final = "events.remind"
QUEUE: Final = "reminders"
LOCK: Final = "events:remind"
CRON: Final = "*/15 * * * *"

_runtime: EventReminderRuntime | None = None


def runtime() -> EventReminderRuntime:
    global _runtime
    if _runtime is None:
        _runtime = EventReminderRuntime()
    return _runtime


def use_runtime(value: EventReminderRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="events-remind-every-15-minutes")
@app.task(name=TASK, queue=QUEUE, lock=LOCK)
async def remind(timestamp: int) -> None:
    del timestamp  # the shared clock decides, not the job's own time
    await run_event_reminders(runtime().deps())
