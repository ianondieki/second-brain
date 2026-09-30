"""AC-TREND-2 (REQ-TREND-02): ``GET /api/discover/opportunity-gap`` lists only problems in the top trend decile that
have fewer than 3 proposals. Twenty problems of one niche each have an old proposal; one then trends with three
organisations scouting, another with two new proposals (3 in all): both are the top decile (2 of 20) with z above
the floor, and only the first, with fewer than 3 proposals, is an opportunity gap. A niche with no trend (twenty
equally quiet problems) has a top decile but no gap: the z floor."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from tests.integration.engagements.api_world import clients
from tests.integration.matching.trend_world import board_as, build, developer_problem, proposal, signals

SETTINGS = get_settings()


async def test_only_top_decile_problems_with_fewer_than_three_proposals(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    problems, projects = [], []
    for _ in range(20):
        problem = await developer_problem(owner_engine, world.author, world.niche, age_days=150)
        problems.append(problem)
        projects.append(await proposal(owner_engine, world.niche, problem, age_days=60))
    top, crowded = problems[0], problems[1]
    await signals(owner_engine, projects[0], "scout_match", days_ago=[0.1, 1.0, 2.0], actors=3)
    for _ in range(2):  # with its old one, exactly 3: not "fewer than 3"
        await proposal(owner_engine, world.niche, crowded, age_days=0.1)

    async with clients(app_engine, SETTINGS, world.author) as (viewer,):
        gap = await viewer.get("/api/discover/opportunity-gap", params={"niche": world.slug("parent")})
        elsewhere = await viewer.get("/api/discover/opportunity-gap", params={"niche": world.slug("elsewhere")})
    assert gap.status_code == 200, gap.text
    items = gap.json()["items"]
    assert [i["problem"]["id"] for i in items] == [str(top)]
    assert all(i["proposal_count"] < 3 for i in items)
    assert items[0]["proposal_count"] == 1
    assert items[0]["trend"]["trending"] is True
    assert elsewhere.json()["items"] == []
    board = await board_as(app_engine, world.author)  # what kept the crowded problem out: its count alone
    z = board.problems[crowded].z
    assert z is not None
    assert z >= 1.0
    assert board.signals[crowded].proposals == 3


async def test_a_quiet_niche_has_no_opportunity_gap(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    for _ in range(20):
        problem = await developer_problem(owner_engine, world.author, world.niche, age_days=150)
        await proposal(owner_engine, world.niche, problem, age_days=60)
    async with clients(app_engine, SETTINGS, world.author) as (viewer,):
        gap = await viewer.get("/api/discover/opportunity-gap", params={"niche": world.slug("niche")})
    assert gap.json()["items"] == []  # ceil(20 x 0.1) = 2 problems rank top, but none is a trend
