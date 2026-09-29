"""Defer a Procrastinate job inside the caller's database transaction (a transactional outbox).

``defer`` inserts the job with Procrastinate's own ``procrastinate_defer_jobs_v1`` function on the caller's
SQLAlchemy session, so the job exists if and only if the caller's transaction commits: a publish that rolls back
leaves no registration job, and a pipeline step that commits always leaves its next step queued. It needs no open
Procrastinate connector (the API never opens one). ``bridge_app`` holds EXECUTE on the function (revision 0001).

Do not pass a ``queueing_lock``: a duplicate would abort the caller's whole transaction. Use ``lock`` to run the jobs
of one subject one at a time, and make the task idempotent instead.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_DEFER = text(
    "SELECT (procrastinate_defer_jobs_v1(ARRAY[ROW(CAST(:queue AS varchar), CAST(:task AS varchar),"
    " CAST(:priority AS integer), CAST(:lock AS text), CAST(NULL AS text), CAST(:args AS jsonb),"
    " CAST(:scheduled_at AS timestamptz))::procrastinate_job_to_defer_v1]))[1]"
)


async def defer(
    session: AsyncSession,
    task_name: str,
    args: Mapping[str, Any],
    *,
    queue: str = "default",
    lock: str | None = None,
    priority: int = 0,
    scheduled_at: datetime | None = None,
) -> int:
    """Queue ``task_name(**args)`` in the session's current transaction and return the job id."""
    params = {
        "queue": queue,
        "task": task_name,
        "priority": priority,
        "lock": lock,
        "args": json.dumps(dict(args), sort_keys=True),
        "scheduled_at": scheduled_at,
    }
    job_id: int = (await session.execute(_DEFER, params)).scalar_one()
    return job_id
