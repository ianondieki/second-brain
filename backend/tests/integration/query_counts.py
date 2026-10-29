"""Query counting for the N+1 tests (P16-E1 item 5, REQ-FND-01 p95 budgets): the statements the app sends on
``app_engine`` while one request runs, through SQLAlchemy's ``before_cursor_execute`` event. A list or detail endpoint
must send as many with 20 rows as with 2 (one batched query per kind of row, never one per row)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

SMALL, LARGE = 2, 20  # rows of the listed kind before and after the scene grows


@contextmanager
def statements(engine: AsyncEngine) -> Iterator[list[str]]:
    """Every statement sent on ``engine`` inside the block, in order."""
    seen: list[str] = []

    def capture(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)


async def counted(
    client: httpx.AsyncClient, engine: AsyncEngine, url: str, params: dict[str, Any] | None = None
) -> tuple[int, Any]:
    """(statements, JSON body) of one GET of ``url``, after a first GET so per-app caches are warm."""
    warm = await client.get(url, params=params)
    assert warm.status_code == 200, warm.text
    with statements(engine) as seen:
        response = await client.get(url, params=params)
    assert response.status_code == 200, response.text
    return len(seen), response.json()


def show(seen: list[str]) -> str:
    """The statements, one per line, to read in a failure message."""
    return "\n".join(" ".join(s.split())[:160] for s in seen)
