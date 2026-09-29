"""The reminders' periodic jobs (REQ-REM-01, REQ-REM-02; docs/spec/06 6.11; ``REQUIREMENTS.md`` §5 N23).

``reminders.dispatch`` (the developers' EM7) and ``reminders.org_digest`` (the organisations' progress digest) run
every 15 minutes. Procrastinate's cron is UTC and passes its own ``timestamp``; the reminders ignore it and read the
shared clock (``app_clock_now()``), so the dev/test clock drives them like every tracker deadline. Before 07:30 EAT
(developers) or 08:30 EAT (organisations) a run looks at nothing; after, each recipient is sent at most once per
period and channel (``bridge.reminders.dispatch``), so the frequent runs cost little and catch up after a restart.

One run of each task at a time (a Procrastinate lock). No retry: the next run, 15 minutes later, picks up whatever this
one could not do (a recipient's failure is logged and skipped; a queued email is resumed). The runtime (database,
email provider, LLM runtime) is built from settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from typing import Final

from bridge.jobs.app import app
from bridge.reminders.dispatch import ReminderRuntime, run_developer_nudges, run_org_digests

DISPATCH_TASK: Final = "reminders.dispatch"
ORG_DIGEST_TASK: Final = "reminders.org_digest"
QUEUE: Final = "reminders"
CRON: Final = "*/15 * * * *"

_runtime: ReminderRuntime | None = None


def runtime() -> ReminderRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ReminderRuntime()
    return _runtime


def use_runtime(value: ReminderRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="every-15-minutes")
@app.task(name=DISPATCH_TASK, queue=QUEUE, lock="reminders:dispatch")
async def dispatch(timestamp: int) -> None:
    del timestamp  # the shared clock decides, not the job's own time
    await run_developer_nudges(runtime().deps())


@app.periodic(cron=CRON, periodic_id="every-15-minutes")
@app.task(name=ORG_DIGEST_TASK, queue=QUEUE, lock="reminders:org_digest")
async def org_digest(timestamp: int) -> None:
    del timestamp
    await run_org_digests(runtime().deps())
