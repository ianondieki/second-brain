"""The API's database engine (REQ-FND-01): its connections end a transaction left idle for 5 minutes
(``idle_in_transaction_session_timeout``), so a request that stalls while holding locks frees them; the worker's
engines keep the server default."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import URL

from bridge.db import API_IDLE_IN_TRANSACTION_MS, create_engine


async def test_the_apis_connections_end_a_transaction_left_idle(database_url: URL) -> None:
    engine = create_engine(
        database_url.render_as_string(hide_password=False), idle_in_transaction_timeout_ms=API_IDLE_IN_TRANSACTION_MS
    )
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SHOW idle_in_transaction_session_timeout"))).scalar_one() == "5min"
    finally:
        await engine.dispose()
