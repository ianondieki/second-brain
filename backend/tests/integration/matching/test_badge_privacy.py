"""AC-REPO-6/b (REQ-REPO-03, REQ-TREND-02) and the Tier-2 rule of Discover and "Recommended for you".

A trending proposal tagged to three organisations (and signalled by them): its Trending badges and every Discover and
recommendation response contain none of those organisations' names or ids. A proposal published through the API
with Tier-2 markers: its teaser is on Discover (the positive control) and no Tier-2 marker is in any response.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from tests.integration.engagements.api_world import clients
from tests.integration.matching.scout_world import add_org, run
from tests.integration.matching.trend_world import build, developer_problem, proposal, research_card, signals
from tests.integration.proposals.helpers import TIER2_MARKERS, Developers, ProposalWorld, published

SETTINGS = get_settings()
PATHS = ("/api/discover/trending", "/api/discover/opportunity-gap")


async def test_trending_badges_never_name_the_tagged_organisations(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers
) -> None:
    world = await build(owner_engine)
    problem = await developer_problem(owner_engine, world.author, world.niche, age_days=120)
    project = await proposal(owner_engine, world.niche, problem, age_days=100)
    await research_card(owner_engine, world.niche, age_days=2)
    async with owner_engine.begin() as conn:
        orgs = [await add_org(conn, label) for label in ("safaricom", "airtel", "telkom")]
        for org in orgs:
            await run(
                conn,
                "INSERT INTO tags (id, proposal_id, org_id, developer_id, status)"
                " VALUES (:id, :p, :org, (SELECT owner_id FROM proposals WHERE id = :p), 'delivered')",
                id=uuid7(),
                p=project,
                org=org.id,
            )
    weekly = [float(d) for d in range(14, 90, 7)]
    await signals(owner_engine, project, "scout_match", days_ago=[*weekly, 0.1, 1.0], actors=3)
    await signals(owner_engine, project, "org_interest", days_ago=[*weekly[::2], 0.1, 1.0], actors=3)
    developer = await developers()
    liked = {"liked": [str(world.niche), str(world.sibling), str(world.parent)]}
    assert (await developer.put("/api/me/niches", json=liked)).status_code == 200
    bodies = [(await developer.get(path, params={"niche": world.slug("parent")})).text for path in PATHS]
    bodies.append((await developer.get("/api/me/recommendations")).text)
    trending = (await developer.get(PATHS[0], params={"niche": world.slug("parent")})).json()
    [shown] = [p for p in trending["projects"] if p["proposal"]["id"] == str(project)]
    assert shown["trend"]["badge"]  # the badge is rendered
    [item] = [p for p in trending["problems"] if p["problem"]["id"] == str(problem)]
    assert item["trend"]["badge"]
    for org in orgs:
        for text in bodies:
            assert org.name not in text
            assert org.name.split(" ")[0] not in text.lower()
            assert str(org.id) not in text
            assert org.domain not in text


async def test_no_tier2_text_reaches_discover_or_recommendations(
    developers: Developers, proposal_world: ProposalWorld
) -> None:
    owner = await developers()
    body = await published(owner, proposal_world, title="Cooler alerts for Tier-1 readers")
    reader = await developers()
    texts = [(await reader.get(path, params={"niche": proposal_world.parent_slug})).text for path in PATHS]
    texts.append((await reader.get("/api/me/recommendations")).text)
    texts.append((await owner.get("/api/me/recommendations")).text)
    assert body["proposal_id"] in texts[0]  # the positive control: the new teaser is on Discover
    assert "Cooler alerts for Tier-1 readers" in texts[0]
    for text in texts:
        for marker in TIER2_MARKERS:
            assert marker.lower() not in text.lower()
