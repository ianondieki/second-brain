"""REQ-UX-03 (P24-B): ``GET /api/public/activity`` and ``GET /api/public/explore`` as routes, without a database.

Both answer a signed-out visitor, say ``Cache-Control: public, max-age=60``, read once a minute per worker (the second
call within the minute costs no load), count every read against the client address like the other public reads
(429 ``rate_limited`` past the limit, never cached), stamp the feed with the platform clock, tell the reads whether
this is a demo deployment, and return exactly the shapes the OpenAPI document gives.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest

from bridge.config import Settings, get_settings
from bridge.db import get_session
from bridge.main import create_app, stamp
from bridge.provenance import verify
from bridge.public import feed, router
from bridge.public.schemas import (
    ActivityFeed,
    ActivityItem,
    Explore,
    ExploreCounty,
    ExploreNiche,
    ExploreTeaser,
    ExploreTotals,
)
from tests.unit.public.openapi_shape import conforms

AT = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
TEASER = ExploreTeaser(id=UUID(int=9), title="Agents run out of float", niche="Microfinance & SACCOs", posted_at=AT)
EXPLORE = Explore(
    totals=ExploreTotals(problems=1, counties=1, niches=1),
    counties=[ExploreCounty(code="KE-30", name="Nairobi City", count=1, newest=[TEASER])],
    niches=[ExploreNiche(id=UUID(int=8), name="Microfinance & SACCOs", count=1, newest=[TEASER])],
    seeded=True,
)


class FakeDb:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class Scene:
    """Fake loads and throttle: what each was called with."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, allowed: bool = True) -> None:
        self.loads: list[tuple[str, dict[str, Any]]] = []
        self.throttled: list[dict[str, Any]] = []
        self.allowed = allowed

        async def allow(_db: Any, _settings: Settings, **kwargs: Any) -> bool:
            self.throttled.append(kwargs)
            return self.allowed

        async def activity(factory: Any, *, generated_at: datetime, demo: bool) -> ActivityFeed:
            self.loads.append(("activity", {"factory": factory, "generated_at": generated_at, "demo": demo}))
            item = ActivityItem(
                id="abc", kind="problem_posted", at=AT, county=None, niche=None, title="T", stage=None, seeded=demo
            )
            return feed.activity_feed([item], generated_at)

        async def explore(factory: Any, *, demo: bool) -> Explore:
            self.loads.append(("explore", {"factory": factory, "demo": demo}))
            return EXPLORE

        monkeypatch.setattr(verify, "allow", allow)
        monkeypatch.setattr(feed, "activity", activity)
        monkeypatch.setattr(feed, "explore", explore)


@asynccontextmanager
async def client(settings: Settings | None = None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings or get_settings())
    app.state.session_factory = "the session factory"
    db = FakeDb()
    app.dependency_overrides[get_session] = lambda: db
    transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        http.app = app  # type: ignore[attr-defined]
        yield http


PATHS = ("/api/public/activity", "/api/public/explore")


@pytest.mark.parametrize("path", PATHS)
async def test_a_signed_out_visitor_reads_it_with_a_public_60_second_cache(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    scene = Scene(monkeypatch)
    async with client() as http:
        response = await http.get(path)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert [factory for _, call in scene.loads for factory in [call["factory"]]] == ["the session factory"]


@pytest.mark.parametrize("path", PATHS)
async def test_two_reads_within_the_minute_cost_one_load(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    scene = Scene(monkeypatch)
    async with client() as http:
        first, second = await http.get(path), await http.get(path)
    assert first.json() == second.json()
    assert len(scene.loads) == 1
    assert len(scene.throttled) == 2  # the cache never skips the rate limit


async def test_the_cache_expires_after_a_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    scene = Scene(monkeypatch)
    ticks = [0.0, 59.0, 61.0]  # after the first load; the second read; the third (then it stays there)

    def now() -> float:
        return ticks.pop(0) if len(ticks) > 1 else ticks[0]

    monkeypatch.setattr(router, "monotonic", now)
    async with client() as http:
        for _ in range(3):
            assert (await http.get("/api/public/activity")).status_code == 200
    assert len(scene.loads) == 2


@pytest.mark.parametrize(("path", "purpose"), list(zip(PATHS, ("public-activity", "public-explore"), strict=True)))
async def test_every_read_counts_against_the_client_address(
    monkeypatch: pytest.MonkeyPatch, path: str, purpose: str
) -> None:
    scene = Scene(monkeypatch)
    async with client() as http:
        await http.get(path)
    assert scene.throttled == [{"purpose": purpose, "ip": "203.0.113.7", "per_minute": router.READS_PER_MINUTE}]


@pytest.mark.parametrize("path", PATHS)
async def test_past_the_limit_the_address_gets_429_and_nothing_is_read_or_cached(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    scene = Scene(monkeypatch, allowed=False)
    async with client() as http:
        response = await http.get(path)
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "rate_limited"
    assert response.headers["cache-control"] == "no-store"
    assert scene.loads == []


async def test_the_feed_is_stamped_with_the_platform_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    scene = Scene(monkeypatch)
    async with client() as http:
        response = await http.get("/api/public/activity")
    [(_, call)] = scene.loads
    assert response.headers["x-app-now"] == stamp(call["generated_at"])
    assert datetime.fromisoformat(response.json()["generated_at"]) == call["generated_at"]


@pytest.mark.parametrize(("env", "demo"), [("test", True), ("dev", True), ("staging", False)])
async def test_the_reads_are_told_whether_this_is_a_demo_deployment(
    monkeypatch: pytest.MonkeyPatch, env: str, demo: bool
) -> None:
    scene = Scene(monkeypatch)
    async with client(get_settings().model_copy(update={"app_env": env})) as http:
        for path in PATHS:
            assert (await http.get(path)).status_code == 200
    assert [call["demo"] for _, call in scene.loads] == [demo, demo]


@pytest.mark.parametrize("path", PATHS)
async def test_the_bodies_have_the_shapes_the_openapi_document_gives(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    Scene(monkeypatch)
    async with client() as http:
        body = (await http.get(path)).json()
        document = http.app.openapi()  # type: ignore[attr-defined]
    schema = document["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    conforms(body, schema, document["components"]["schemas"])


def test_the_documented_shapes_are_the_cards() -> None:
    schemas = create_app(get_settings()).openapi()["components"]["schemas"]
    assert set(schemas["ActivityFeed"]["properties"]) == {"generated_at", "items", "seeded"}
    assert set(schemas["ActivityItem"]["properties"]) == {
        "id",
        "kind",
        "at",
        "county",
        "niche",
        "title",
        "stage",
        "seeded",
    }
    assert schemas["ActivityItem"]["properties"]["kind"]["enum"] == [
        "problem_posted",
        "version_registered",
        "stage_reached",
        "brief_opened",
    ]
    assert set(schemas["Explore"]["properties"]) == {"totals", "counties", "niches", "seeded"}
    assert set(schemas["ExploreTotals"]["properties"]) == {"problems", "counties", "niches"}
    assert set(schemas["ExploreCounty"]["properties"]) == {"code", "name", "count", "newest"}
    assert set(schemas["ExploreNiche"]["properties"]) == {"id", "name", "count", "newest"}
    assert set(schemas["ExploreTeaser"]["properties"]) == {"id", "title", "niche", "posted_at"}
