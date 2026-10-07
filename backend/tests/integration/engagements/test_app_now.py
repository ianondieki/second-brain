"""REQ-TRACK-03 (P23-3): the deadline countdown's clock, through the API.

Given the platform clock (``app_clock_now()``), When any /api answer is read, Then ``X-App-Now`` carries it in ISO
8601 UTC with a ``Z``, and moving the dev/test clock moves it (errors included), so ``make demo-clock`` and the e2e
clock scenarios move a countdown with every other deadline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.main import APP_NOW_HEADER
from tests.integration.api import make_client
from tests.integration.engagements.api_world import moved_clock

ONE_MS = timedelta(milliseconds=1)  # the header is to the millisecond


async def platform_now(owner_engine: AsyncEngine) -> datetime:
    async with owner_engine.connect() as conn:
        now: datetime = (await conn.execute(text("SELECT app_clock_now()"))).scalar_one()
        return now


def stamped(response: httpx.Response) -> datetime:
    value = response.headers[APP_NOW_HEADER]
    assert value.endswith("Z"), value
    moment = datetime.fromisoformat(value)
    assert moment.utcoffset() == timedelta(0)
    return moment


async def assert_platform_clock(client: httpx.AsyncClient, owner_engine: AsyncEngine, path: str, status: int) -> None:
    before = await platform_now(owner_engine)
    response = await client.get(path)
    after = await platform_now(owner_engine)
    assert response.status_code == status, response.text
    assert before - ONE_MS <= stamped(response) <= after


def lead(response: httpx.Response) -> timedelta:
    """How far the stamped clock runs ahead of the wall clock (the test clock's offset)."""
    return stamped(response) - datetime.now(UTC)


async def test_the_header_is_the_platform_clock_and_follows_the_test_clock(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    slack = timedelta(minutes=1)
    async with make_client(app_engine) as client:
        await assert_platform_clock(client, owner_engine, "/api/auth/csrf", 200)
        offset = lead(await client.get("/api/auth/csrf"))
        async with moved_clock(owner_engine) as advance:
            await advance(3)
            await assert_platform_clock(client, owner_engine, "/api/auth/csrf", 200)
            await assert_platform_clock(client, owner_engine, "/api/no-such-thing", 404)
            moved = lead(await client.get("/api/auth/csrf")) - offset
            assert abs(moved - timedelta(days=3)) < slack
        assert abs(lead(await client.get("/api/auth/csrf")) - offset) < slack  # put back with the clock
