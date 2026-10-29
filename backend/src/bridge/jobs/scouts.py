"""The scouts' jobs (REQ-SCOUT-02, REQ-SCOUT-03; docs/spec/06 6.8; REQUIREMENTS.md §5 N02).

``scouts.scan`` runs every 15 minutes: from ``schedule.scan_after`` (07:00 EAT) each daily and weekly scout that
``app_scouts_due`` names runs once per Nairobi day or ISO week (the shared clock decides, so the dev/test clock moves
it; Procrastinate's own timestamp is ignored). ``scouts.on_new`` runs the on_new scouts for one publication, queued by
the publication's transaction (``bridge.matching.tasks.defer_on_new``). One scan at a time (lock ``scouts:scan``); no
retry: a failed run is marked and the next pass retries it. The runtime is built from settings on first use; tests
install their own with ``use_runtime``.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from bridge.jobs.app import app
from bridge.matching.runtime import ScoutRuntime
from bridge.matching.scan import run_on_new, run_periodic
from bridge.matching.tasks import LOCK, ON_NEW_TASK, QUEUE, SCAN_TASK

CRON: Final = "*/15 * * * *"

_runtime: ScoutRuntime | None = None


def runtime() -> ScoutRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ScoutRuntime()
    return _runtime


def use_runtime(value: ScoutRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


@app.periodic(cron=CRON, periodic_id="scouts-every-15-minutes")
@app.task(name=SCAN_TASK, queue=QUEUE, lock=LOCK)
async def scan(timestamp: int) -> None:
    del timestamp  # the shared clock decides, not the job's own time
    await run_periodic(runtime().deps())


@app.task(name=ON_NEW_TASK, queue=QUEUE, lock=LOCK)
async def on_new(proposal_id: str) -> None:
    await run_on_new(runtime().deps(), UUID(proposal_id))
