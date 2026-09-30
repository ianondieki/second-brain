"""The research job's names and its queueing (REQ-RES-01). The API never imports the task module
(``bridge.jobs.research``): starting a run queues ``research.run`` through the transactional outbox
(``bridge.jobs.outbox.defer``), so the job exists if and only if the run's row commits."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bridge.jobs.outbox import defer

QUEUE: Final = "research"
RUN_TASK: Final = "research.run"


def lock_of(run_id: UUID) -> str:
    return f"research:{run_id}"


async def defer_run(db: AsyncSession, *, run_id: UUID, user_id: UUID) -> int:
    """Queue one run in the caller's transaction. ``user_id`` is the staff admin who started it: the job binds it, so
    the run is read and written under that admin's Row-Level Security (``research_runs`` is staff admin only)."""
    return await defer(
        db, RUN_TASK, {"run_id": str(run_id), "user_id": str(user_id)}, queue=QUEUE, lock=lock_of(run_id)
    )
