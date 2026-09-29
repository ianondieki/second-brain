"""The scouts' job names and the ``on_new`` trigger (REQ-SCOUT-02; docs/spec/06 6.8).

The API never imports the task modules (``bridge.jobs.scouts``): a publication queues ``scouts.on_new`` through the
transactional outbox (``bridge.jobs.outbox.defer``), so the job exists if and only if the publication commits. The
defer runs in a savepoint and its failure is logged, never raised: a publication never fails because its scouts could
not be queued (the periodic scans still find the proposal).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.jobs.outbox import defer
from bridge.logging import get_logger

QUEUE: Final = "scouts"
SCAN_TASK: Final = "scouts.scan"
ON_NEW_TASK: Final = "scouts.on_new"
LOCK: Final = "scouts:scan"  # one scan at a time, periodic or on_new


async def defer_on_new(db: AsyncSession, proposal_id: UUID) -> bool:
    """Queue ``scouts.on_new`` for a proposal that just became visible (published and clear), in the caller's
    transaction. False, with the caller's transaction intact, when it could not be queued."""
    try:
        async with db.begin_nested():
            await defer(db, ON_NEW_TASK, {"proposal_id": str(proposal_id)}, queue=QUEUE, lock=LOCK)
    except SQLAlchemyError as exc:
        get_logger(__name__).error("scouts.on_new_not_queued", proposal_id=str(proposal_id), error=type(exc).__name__)
        return False
    return True
