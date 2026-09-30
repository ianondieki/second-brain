"""REQ-TREND-01, REQ-TREND-02 (docs/spec/06 6.6): ``GET /api/discover/trending``.

A problem whose linked proposal three organisations' scouts matched weekly, then all at once this week, trends against
its niche's baseline: its badge explains itself (niche, place, "3 companies scouting"), it carries its sources and
Why chips, and the project three organisations asked about is listed beside it with that problem (AC-TREND-2) and a
badge with no organisation count or name. A niche without history shows "New this week" and no badge. The niche and
county filters narrow the lists. Anti-gaming through the API: the problem's own author's proposals never boost it,
and one organisation's many seats (fewer than 3 organisations) count for nothing.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from tests.integration.engagements.api_world import clients
from tests.integration.matching.trend_world import (
    TrendWorld,
    build,
    developer_problem,
    proposal,
    research_card,
    signals,
)

SETTINGS = get_settings()
WEEKLY = [float(d) for d in range(14, 90, 7)]
SPIKE = [0.1, 1.0, 2.0]


async def trending(app_engine: AsyncEngine, world: TrendWorld, **params: str) -> dict[str, Any]:
    async with clients(app_engine, SETTINGS, world.author) as (viewer,):
        response = await viewer.get("/api/discover/trending", params=params or {"niche": world.slug("parent")})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def rising(owner_engine: AsyncEngine, world: TrendWorld) -> tuple[Any, Any]:
    """A developer's problem in the world's niche with a proposal that scouts and interested organisations picked up
    weekly, then all at once this week: (problem, proposal)."""
    problem = await developer_problem(owner_engine, world.author, world.niche, age_days=120)
    project = await proposal(owner_engine, world.niche, problem, age_days=100, county="KE-30")
    await signals(owner_engine, project, "scout_match", days_ago=WEEKLY + SPIKE, actors=3, label=f"{world.tag}-s")
    await signals(owner_engine, project, "org_interest", days_ago=WEEKLY[::2] + SPIKE, actors=3, label=f"{world.tag}-i")
    return problem, project


async def test_a_rising_problem_trends_with_its_badge_sources_and_project_beside_it(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    problem, project = await rising(owner_engine, world)
    quiet = await developer_problem(owner_engine, world.author, world.niche, age_days=120)
    card = await research_card(owner_engine, world.sibling, source_days=(3, 10), age_days=3)
    body = await trending(app_engine, world)

    [item] = [p for p in body["problems"] if p["problem"]["id"] == str(problem)]
    assert item["trend"]["trending"] is True
    assert item["trend"]["z"] >= 1.0
    assert item["trend"]["badge"] == f"Trending in {world.label('niche')} · Kenya: 3 companies scouting"
    assert "3 companies scouting" in item["why"]
    assert item["proposal_count"] == 1
    assert item["project_ids"] == [str(project)]
    assert item["problem"]["label"] == "Developer-reported"
    assert str(quiet) not in {p["problem"]["id"] for p in body["problems"]}  # neither trending nor new

    [shown] = [p for p in body["projects"] if p["proposal"]["id"] == str(project)]
    assert shown["problem"]["id"] == str(problem)  # AC-TREND-2: the card renders its linked problem
    assert shown["trend"]["trending"] is True
    assert shown["trend"]["badge"] == f"Trending in {world.label('niche')}"
    assert not re.search(r"\d", shown["trend"]["badge"].replace(world.tag, ""))  # no organisation count
    assert "score" not in shown["trend"]
    assert "Verified organisations expressed interest" in shown["why"]
    assert all(p["problem"]["id"] for p in body["projects"])  # every project card has its problem

    [research] = [p for p in body["problems"] if p["problem"]["id"] == str(card)]
    assert (research["trend"]["trending"], research["trend"]["new_this_week"]) == (False, True)  # no baseline yet
    assert research["trend"]["badge"] is None
    assert [s["publisher"] for s in research["sources"]] == ["Agency 0", "Agency 1"]  # newest first
    assert research["sources"][0]["quote"] == "A quoted line"


async def test_cold_start_shows_new_this_week_without_a_badge(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    fresh = await research_card(owner_engine, world.elsewhere, age_days=2)
    old = await research_card(owner_engine, world.elsewhere, age_days=40)
    body = await trending(app_engine, world, niche=world.slug("elsewhere"))
    assert [p["problem"]["id"] for p in body["problems"]] == [str(fresh)]
    [item] = body["problems"]
    assert item["trend"] == {"trending": False, "new_this_week": True, "z": None, "score": 0.0, "badge": None}
    assert "New this week" in item["why"]
    assert str(old) not in str(body)


async def test_the_niche_and_county_filters(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    child = await research_card(owner_engine, world.niche, county="KE-30")
    sibling = await research_card(owner_engine, world.sibling, county="KE-22")
    elsewhere = await research_card(owner_engine, world.elsewhere, county="KE-30")

    def ids(body: dict[str, Any]) -> set[str]:
        return {p["problem"]["id"] for p in body["problems"]}

    parent = await trending(app_engine, world, niche=world.slug("parent"))
    assert {str(child), str(sibling)} <= ids(parent)
    assert str(elsewhere) not in ids(parent)
    assert ids(await trending(app_engine, world, niche=world.slug("niche"))) == {str(child)}
    narrowed = await trending(app_engine, world, niche=world.slug("parent"), county="KE-22")
    assert ids(narrowed) == {str(sibling)}
    assert (await trending(app_engine, world, niche=f"p12-unknown-{world.tag}"))["problems"] == []
    async with clients(app_engine, SETTINGS, world.author) as (viewer,):
        assert (await viewer.get("/api/discover/trending", params={"county": "nairobi"})).status_code == 422
        assert (await viewer.get("/api/discover/trending", params={"niche": "Not A Slug"})).status_code == 422


async def test_the_authors_own_proposals_never_boost_their_problem(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    own = await developer_problem(owner_engine, world.author, world.niche, age_days=3)
    others = await developer_problem(owner_engine, world.author, world.sibling, age_days=3)
    for _ in range(3):
        await proposal(owner_engine, world.niche, own, owner=world.author, age_days=1)
        await proposal(owner_engine, world.sibling, others, age_days=1)
    body = await trending(app_engine, world)
    scores = {p["problem"]["id"]: p["trend"]["score"] for p in body["problems"]}
    assert scores[str(own)] == 0.0  # self-boost: nothing counts
    assert scores[str(others)] > 5.0  # three other developers: 3 x weight 2, one day old


async def test_one_organisations_seats_count_for_nothing(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Five reviewers of two organisations (the definer's 3-actor floor passes, but not 3 organisations)."""
    world = await build(owner_engine)
    problem = await developer_problem(owner_engine, world.author, world.niche, age_days=3)
    project = await proposal(owner_engine, world.niche, problem, age_days=2)
    await signals(owner_engine, project, "scout_match", days_ago=[0.5, 1.5], actors=5, orgs=2)
    await signals(owner_engine, project, "org_interest", days_ago=[0.5], actors=5, orgs=2)
    body = await trending(app_engine, world)
    [item] = [p for p in body["problems"] if p["problem"]["id"] == str(problem)]
    assert item["trend"]["score"] == pytest.approx(2.0 * 0.5 ** (2 / 14), abs=1e-3)  # the proposal only (2 days old)
    assert "companies scouting" not in " ".join(item["why"])
    [shown] = [p for p in body["projects"] if p["proposal"]["id"] == str(project)]
    assert "Verified organisations expressed interest" not in shown["why"]
