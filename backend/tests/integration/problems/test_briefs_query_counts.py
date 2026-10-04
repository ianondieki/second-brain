"""P16-E1 item 5 for REQ-DIR-05 (docs/spec/08 p95 budgets): Discover's Briefs view and the organisation's Briefs list
send as many statements with many Briefs as with few (``tests/integration/query_counts.py``), as Trending and the
Opportunity Gap do."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from tests.integration.engagements.api_world import clients
from tests.integration.matching.scout_world import ScoutWorld, build, run
from tests.integration.proposals.helpers import Developers
from tests.integration.query_counts import LARGE, SMALL, counted

SETTINGS = get_settings()


async def published_briefs(owner_engine: AsyncEngine, world: ScoutWorld, count: int) -> None:
    """``count`` approved, public Briefs of the world's E2 organisation in its niche, each with a band and deadline."""
    async with owner_engine.begin() as conn:
        for n in range(count):
            problem = uuid7()
            await run(
                conn,
                "INSERT INTO problems (id, source, niche_id, county_code, title, statement, status, created_by,"
                " org_id, published_at) VALUES (:id, 'org_brief', :niche, 'KE-30', :title, 'A statement.',"
                " 'published', :by, :org, now() - make_interval(mins => :n))",
                id=problem,
                niche=world.niche,
                title=f"Brief {n}",
                by=world.org.reviewer,
                org=world.org.id,
                n=n,
            )
            await run(
                conn,
                "INSERT INTO problem_briefs (problem_id, org_id, visibility, budget_band, deadline, status)"
                " VALUES (:p, :org, 'public', '500k_2m', CURRENT_DATE + 30, 'published')",
                p=problem,
                org=world.org.id,
            )


async def test_discover_briefs(owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers) -> None:
    world = await build(owner_engine)
    client = await developers()
    params = {"niche": f"p10-niche-{world.tag}"}
    await published_briefs(owner_engine, world, SMALL)
    small, body = await counted(client, app_engine, "/api/discover/briefs", params)
    assert len(body["items"]) == SMALL
    await published_briefs(owner_engine, world, LARGE - SMALL)
    large, body = await counted(client, app_engine, "/api/discover/briefs", params)
    assert len(body["items"]) == LARGE
    assert large == small


async def test_the_organisations_briefs(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    url = f"/api/orgs/{world.org.id}/briefs"
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        await published_briefs(owner_engine, world, SMALL)
        small, body = await counted(reviewer, app_engine, url)
        assert len(body["items"]) == SMALL
        await published_briefs(owner_engine, world, LARGE - SMALL)
        large, body = await counted(reviewer, app_engine, url)
        assert len(body["items"]) == LARGE
        assert body["plan"]["used"] == LARGE
    assert large == small
