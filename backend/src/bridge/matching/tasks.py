"""The scouts' job names and the ``on_new`` trigger (REQ-SCOUT-02; docs/spec/06 6.8).

The API never imports the task modules (``bridge.jobs.scouts``): a publication queues ``scouts.on_new`` through the
transactional outbox (``bridge.jobs.outbox.defer``), so the job exists if and only if the publication commits. The
caller's pending changes are flushed first, so the savepoint holds only the defer: the defer's failure is logged, never
raised (a publication never fails because its scouts could not be queued), and the caller's own failure still reaches
the caller.

A publication whose ``scouts.on_new`` was not queued is still found by the daily and weekly scouts' periodic scans,
but not by the ``on_new`` scouts: the periodic scans never sweep them, so such a scout misses that proposal (the
error log ``scouts.on_new_not_queued`` is the signal; a sweep is recorded as a gap on the REQ-SCOUT-02 card).
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
    await db.flush()  # the caller's own changes: outside the savepoint, so their failure is never swallowed here
    try:
        async with db.begin_nested():
            await defer(db, ON_NEW_TASK, {"proposal_id": str(proposal_id)}, queue=QUEUE, lock=LOCK)
    except SQLAlchemyError as exc:
        get_logger(__name__).error("scouts.on_new_not_queued", proposal_id=str(proposal_id), error=type(exc).__name__)
        return False
    return True
