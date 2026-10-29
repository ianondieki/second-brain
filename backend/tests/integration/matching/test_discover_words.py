"""REQ-TREND-02 (R18), P21 track C: Discover's ``words`` filter, the one a saved search keeps (``problems.service.
words_match``): a problem whose title or statement holds the words, ignoring case and taking ``%`` and ``_`` as typed;
a project through the problems it solves; a Brief by its problem. Blank words filter nothing; over 100 characters 422.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from tests.integration.engagements.api_world import clients
from tests.integration.matching.trend_world import TrendWorld, brief, build, proposal, research_card

SETTINGS = get_settings()


async def discover(app_engine: AsyncEngine, world: TrendWorld, path: str, **params: str) -> dict[str, Any]:
    async with clients(app_engine, SETTINGS, world.author) as (viewer,):
        response = await viewer.get(f"/api/discover/{path}", params={"niche": world.slug("parent"), **params})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def problem_ids(body: dict[str, Any]) -> set[str]:
    return {item["problem"]["id"] for item in body["problems"]}


async def test_words_narrow_trending_problems_and_projects_and_briefs(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    cold = await research_card(owner_engine, world.niche, title="Milk COLD-chain gaps", statement="Coolers fail.")
    stated = await research_card(
        owner_engine, world.sibling, title="Dairy losses", statement="Without a cold-chain milk spoils by noon."
    )
    other = await research_card(owner_engine, world.niche, title="Grain pests", statement="Weevils eat maize.")
    percent = await research_card(owner_engine, world.niche, title="A 100% loss", statement="Floods took it all.")
    cold_project = await proposal(owner_engine, world.niche, cold, age_days=1)
    other_project = await proposal(owner_engine, world.niche, other, age_days=1)
    cold_brief = await brief(owner_engine, world.niche, title="Cold-chain tracking for depots")
    await brief(owner_engine, world.niche, title="Grain stock counts")

    everything = await discover(app_engine, world, "trending")
    assert {str(cold), str(stated), str(other), str(percent)} <= problem_ids(everything)
    narrowed = await discover(app_engine, world, "trending", words="cold-chain")
    # Title or statement, any case; the Problems view lists Briefs as problems too.
    assert problem_ids(narrowed) == {str(cold), str(stated), str(cold_brief)}
    assert [p["proposal"]["id"] for p in narrowed["projects"]] == [str(cold_project)]
    assert str(other_project) in {p["proposal"]["id"] for p in everything["projects"]}
    assert problem_ids(await discover(app_engine, world, "trending", words="100%")) == {str(percent)}
    assert problem_ids(await discover(app_engine, world, "trending", words="10_%")) == set()  # wildcards as typed
    assert problem_ids(await discover(app_engine, world, "trending", words="   ")) == problem_ids(everything)

    briefs = await discover(app_engine, world, "briefs", words="COLD-CHAIN")
    assert [item["problem"]["id"] for item in briefs["items"]] == [str(cold_brief)]
    async with clients(app_engine, SETTINGS, world.author) as (viewer,):
        for path in ("trending", "briefs"):
            assert (await viewer.get(f"/api/discover/{path}", params={"words": "w" * 101})).status_code == 422
