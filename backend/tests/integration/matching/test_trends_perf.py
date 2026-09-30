"""AC-TREND-3 (REQ-TREND-01): 50k signal events; trends are computed on read (no recompute job in the prototype), so
"the job runs twice" is two Discover requests and two recommendation requests over the same facts. Both give the same
answer (idempotent) and each finishes far inside the 5 minutes (the CI bound here is 60 seconds).

The events go into a database of their own (50k rows would slow every other test's Discover reads). Setup: 50
proposals and their problems in three niches, a research card each, then 50k ``scout_match`` and ``org_interest``
signals from 40 actors of 12 organisations over 170 days."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from tests.integration.api import make_client, sign_in_as
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.matching.trend_world import build, developer_problem, proposal, research_card

EVENTS = 50_000
SPIKE = 500
ITEMS = 50
BOUND_SECONDS = 60.0


@pytest.fixture(scope="module")
def perf_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_trends_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def engines(perf_url: URL) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    owner, app = role_engine(perf_url, "bridge_owner"), role_engine(perf_url, "bridge_app")
    yield owner, app
    await owner.dispose()
    await app.dispose()


def without_clock(body: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k != "generated_at"}


async def test_fifty_thousand_events_twice_give_the_same_answer_in_time(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    owner, app = engines
    setup = time.perf_counter()
    world = await build(owner)
    items = []
    for n in range(ITEMS):
        niche = (world.niche, world.sibling, world.elsewhere)[n % 3]
        problem = await developer_problem(owner, world.author, niche, age_days=200)
        items.append(await proposal(owner, niche, problem, age_days=190))
        await research_card(owner, niche, age_days=n % 30, source_days=(n % 60,))
    async with owner.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO signal_events (id, item_id, kind, actor_hash, org_hash, ts)"
                " SELECT gen_random_uuid(), (CAST(:items AS uuid[]))[1 + i % :n],"
                " CASE WHEN i % 3 = 0 THEN 'org_interest' ELSE 'scout_match' END,"
                " sha256(convert_to('actor-' || (i % 40), 'UTF8')), sha256(convert_to('org-' || (i % 12), 'UTF8')),"
                " app_clock_now() - make_interval(hours => i % (170 * 24))"
                " FROM generate_series(1, :events) AS i"
            ),
            {"items": items, "n": ITEMS, "events": EVENTS - SPIKE},
        )
        await conn.execute(  # a burst of interest in five proposals over the last two days
            text(
                "INSERT INTO signal_events (id, item_id, kind, actor_hash, org_hash, ts)"
                " SELECT gen_random_uuid(), (CAST(:items AS uuid[]))[1 + i % 5], 'scout_match',"
                " sha256(convert_to('actor-' || (i % 40), 'UTF8')), sha256(convert_to('org-' || (i % 12), 'UTF8')),"
                " app_clock_now() - make_interval(mins => i % (48 * 60)) FROM generate_series(1, :events) AS i"
            ),
            {"items": items, "events": SPIKE},
        )
        assert (await conn.execute(text("SELECT count(*) FROM signal_events"))).scalar_one() >= EVENTS
        # What autovacuum does to a table that grew by 50k rows. Without statistics the planner reads the bulk-loaded
        # table as empty and the definer takes minutes (measured: 150 s); with them, 0.2 s (REQ-TREND-01 card).
        await conn.execute(text("ANALYZE signal_events"))

        await conn.execute(
            text("INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)"),
            {"u": world.author, "h": f"perf-{world.tag}"},
        )
    print(f"AC-TREND-3 setup: {time.perf_counter() - setup:.1f}s")  # noqa: T201
    settings = get_settings()
    timings: dict[str, list[float]] = {}
    answers: dict[str, list[dict[str, Any]]] = {}
    async with make_client(app, settings) as client:
        await sign_in_as(client, app, world.author, mfa_verified=True)
        liked = {"liked": [str(world.niche), str(world.sibling), str(world.elsewhere)]}
        assert (await client.put("/api/me/niches", json=liked)).status_code == 200
        for path in ("/api/discover/trending", "/api/discover/opportunity-gap", "/api/me/recommendations"):
            for _ in range(2):
                started = time.perf_counter()
                response = await client.get(path)
                timings.setdefault(path, []).append(time.perf_counter() - started)
                assert response.status_code == 200, response.text
                answers.setdefault(path, []).append(without_clock(response.json()))
    for path, (first, second) in answers.items():
        assert first == second, path  # idempotent: the same facts give the same answer
    trending = answers["/api/discover/trending"][0]
    assert trending["problems"]
    assert any(p["trend"]["trending"] for p in trending["problems"])
    assert answers["/api/me/recommendations"][0]["items"]
    slowest = max(t for ts in timings.values() for t in ts)
    assert slowest < BOUND_SECONDS, timings
    print(f"AC-TREND-3: {EVENTS} events, slowest request {slowest:.2f}s: {timings}")  # noqa: T201
