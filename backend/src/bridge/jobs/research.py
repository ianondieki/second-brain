"""The research job (REQ-RES-01; docs/spec/06 6.5; PLAN §8 P11): ``research.run``, one per research run.

Queued by ``POST /api/admin/research/runs`` in the run's own transaction (``bridge.problems.research.tasks``) with the
run id and the staff admin who started it. The job binds that admin (``research_runs`` is staff admin only, and
``app_create_research_candidate`` takes only the caller's own running run), runs the pipeline
(``bridge.problems.research.pipeline.execute_run``: saved excerpts, one ``research_synthesis`` call, the checks in
code, candidates) and commits. Nothing is searched or fetched, so the run's ``searches`` and ``fetches`` stay 0, under
the ``research_runs`` CHECK caps (25 and 40, AC-RES-3). Idempotent: a run that is no longer running is left alone.
One job per run at a time (lock ``research:<run id>``); no retry (a failed run records its stop reason, and the admin
starts another). The runtime is built from settings on first use; tests install their own with ``use_runtime``.
"""

from __future__ import annotations

from uuid import UUID

from bridge.db import bind_tenant
from bridge.jobs.app import app
from bridge.logging import get_logger
from bridge.problems.research.pipeline import RunOutcome, execute_run
from bridge.problems.research.runtime import ResearchRuntime
from bridge.problems.research.tasks import QUEUE, RUN_TASK

_runtime: ResearchRuntime | None = None
log = get_logger(__name__)


def runtime() -> ResearchRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ResearchRuntime()
    return _runtime


def use_runtime(value: ResearchRuntime | None) -> None:
    """Install a runtime (tests), or None to rebuild from settings on next use."""
    global _runtime
    _runtime = value


async def run_research(run_id: UUID, user_id: UUID, rt: ResearchRuntime | None = None) -> RunOutcome | None:
    deps = (rt or runtime()).deps()
    async with deps.factory() as db:
        await bind_tenant(db, user_id=user_id)
        outcome = await execute_run(
            db, run_id, client=deps.llm(db), settings=deps.settings, catalogue=deps.catalogue, policy=deps.policy
        )
        await db.commit()
    if outcome is None:
        log.info("research.run_skipped", run_id=str(run_id))
    return outcome


@app.task(name=RUN_TASK, queue=QUEUE)
async def run(run_id: str, user_id: str) -> None:
    await run_research(UUID(run_id), UUID(user_id))
