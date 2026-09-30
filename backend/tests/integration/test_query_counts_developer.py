"""P16-E1 item 5 (REQ-FND-01, docs/spec/08 p95 budgets): the developer's main lists and details send as many
statements with many rows as with few (``tests/integration/query_counts.py``): My ideas, one idea (its linked
problems and attachments), Discover (Trending and the Opportunity Gap), Recommended for you and Companies."""

from __future__ import annotations

from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.matching import trend_world as tw
from tests.integration.proposals.helpers import Developers, ProposalWorld, create, draft_body, user_of
from tests.integration.query_counts import LARGE, SMALL, counted


async def test_my_ideas(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    client = await developers()

    async def add(count: int) -> None:
        async with owner_engine.begin() as conn:
            for n in range(count):
                niche, problem = proposal_world.niche_id, proposal_world.problem_id
                await w.add_proposal(conn, user_of(client), niche, problem, registered=n % 2 == 0)

    await add(SMALL)
    small, body = await counted(client, app_engine, "/api/me/proposals")
    assert len(body["items"]) == SMALL
    await add(LARGE - SMALL)
    large, body = await counted(client, app_engine, "/api/me/proposals")
    assert len(body["items"]) == LARGE
    assert large == small


async def _upload(client: httpx.AsyncClient, proposal_id: str, n: int) -> None:
    response = await client.post(
        f"/api/me/proposals/{proposal_id}/attachments",
        content=b"%PDF-1.4 query count " + str(n).encode(),
        headers={"Content-Type": "application/pdf", "X-File-Name": quote(f"plan-{n}.pdf")},
    )
    assert response.status_code == 201, response.text


async def test_one_idea_with_its_problems_and_attachments(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """One linked problem and one attachment, then five problems (the most) and ten attachments (the most)."""
    client = await developers()
    created = await create(client, draft_body(proposal_world))
    url = f"/api/me/proposals/{created['id']}"
    await _upload(client, created["id"], 0)
    small, body = await counted(client, app_engine, url)
    assert (len(body["draft"]["problems"]), len(body["draft"]["confidential"]["attachments"])) == (1, 1)
    async with owner_engine.begin() as conn:
        author = await w.add_user(conn, f"qc-{uuid4().hex[:8]}@example.test", "Author")
        extra = [await w.add_problem(conn, author, proposal_world.niche_id) for _ in range(4)]
    linked = [str(proposal_world.problem_id), *map(str, extra)]
    patched = await client.patch(url, json=draft_body(proposal_world) | {"problem_ids": linked})
    assert patched.status_code == 200, patched.text
    for n in range(1, 10):
        await _upload(client, created["id"], n)
    large, body = await counted(client, app_engine, url)
    assert (len(body["draft"]["problems"]), len(body["draft"]["confidential"]["attachments"])) == (5, 10)
    assert large == small


async def _fresh_problems(owner_engine: AsyncEngine, world: tw.TrendWorld, count: int) -> None:
    """Problems of this week with a project of this week each: listed on Discover as new."""
    for n in range(count):
        niche = world.niche if n % 2 else world.sibling
        problem = await tw.developer_problem(owner_engine, world.author, niche, age_days=1)
        await tw.proposal(owner_engine, niche, problem, age_days=0.5, county="KE-30")
        await tw.research_card(owner_engine, niche, age_days=2, source_days=(3.0,))


async def test_discover_trending_and_the_opportunity_gap(
    developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await tw.build(owner_engine)
    client = await developers()
    params = {"niche": world.slug("parent")}
    await _fresh_problems(owner_engine, world, SMALL)
    small, body = await counted(client, app_engine, "/api/discover/trending", params)
    small_gap, _ = await counted(client, app_engine, "/api/discover/opportunity-gap", params)
    assert (len(body["problems"]), len(body["projects"])) == (2 * SMALL, SMALL)
    await _fresh_problems(owner_engine, world, LARGE - SMALL)
    large, body = await counted(client, app_engine, "/api/discover/trending", params)
    large_gap, _ = await counted(client, app_engine, "/api/discover/opportunity-gap", params)
    assert (len(body["problems"]), len(body["projects"])) == (LARGE, LARGE)  # 20 a list at most
    assert (large, large_gap) == (small, small_gap)


async def test_recommended_for_you(developers: Developers, owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await tw.build(owner_engine)
    client = await developers()
    liked = {"liked": [str(world.niche), str(world.sibling), str(world.elsewhere)]}
    assert (await client.put("/api/me/niches", json=liked)).status_code == 200

    async def add(count: int) -> None:
        for n in range(count):
            niche = (world.niche, world.sibling, world.elsewhere)[n % 3]
            await tw.research_card(owner_engine, niche, county="KE-30", age_days=n + 1, source_days=(n + 2.0,))
            await tw.brief(owner_engine, niche, age_days=n + 1)

    await add(SMALL)
    small, body = await counted(client, app_engine, "/api/me/recommendations")
    assert body["items"]
    await add(LARGE - SMALL)
    large, body = await counted(client, app_engine, "/api/me/recommendations")
    assert len(body["items"]) == 10  # the top 10 of every recommendable card (all of them ranked, 40 of them ours)
    assert large == small


async def _listed_orgs(owner_engine: AsyncEngine, niche: UUID, tag: str, count: int, start: int) -> None:
    async with owner_engine.begin() as conn:
        for n in range(start, start + count):
            org_id = uuid7()
            await conn.execute(
                text(
                    "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, county_code)"
                    " VALUES (:id, 'company', :name, :slug, 'admin', CAST(:level AS org_verification), 'KE-30')"
                ),
                {
                    "id": org_id,
                    "name": f"Query Count {n} {tag}",
                    "slug": f"qc-{n}-{tag}",
                    "level": ("unclaimed", "e2")[n % 2],
                },
            )
            await conn.execute(
                text("INSERT INTO org_niches (org_id, niche_id) VALUES (:org, :niche)"), {"org": org_id, "niche": niche}
            )


async def test_companies(
    developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    tag = uuid4().hex[:8]
    niche = uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO niches (id, parent_id, slug, name_en) VALUES (:id, :parent, :slug, :name)"),
            {"id": niche, "parent": proposal_world.parent_id, "slug": f"qc-{tag}", "name": f"Query count {tag}"},
        )
    client = await developers()
    params = {"niche": f"qc-{tag}", "limit": "50"}
    await _listed_orgs(owner_engine, niche, tag, SMALL, 0)
    small, body = await counted(client, app_engine, "/api/directory/orgs", params)
    assert sum(len(g["orgs"]) for g in body["groups"]) == SMALL
    await _listed_orgs(owner_engine, niche, tag, LARGE - SMALL, SMALL)
    large, body = await counted(client, app_engine, "/api/directory/orgs", params)
    assert sum(len(g["orgs"]) for g in body["groups"]) == LARGE
    assert large == small
