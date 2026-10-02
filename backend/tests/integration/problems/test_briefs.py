"""REQ-DIR-05 (docs/spec/06 6.2, 6.5, 6.12; AC-PERS-7): Problem Briefs through the API.

A verified (E2) organisation's editor posts a Brief: it waits for review (``pending_review``, in the moderation queue,
nowhere a developer can see it, never ranked); once staff approve it, it is on Discover's Briefs view and its problem
page says "Posted by <organisation>" with the budget band and deadline. A developer who starts a proposal from it gets
it linked, with the organisation for the pitch. The claimed plan's one Brief is enforced (402 with the next plan, also
under parallel posts), only E2 organisations post (403), invited Briefs are not available yet (422), a Brief is public
text (the sanitiser's contact rule and the form checks, 422), and closing one takes it off the feed while the problem
stays. No person's id, name or address is in what developers read.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from tests.integration.engagements.api_world import clients
from tests.integration.matching.scout_world import (
    NAIROBI_CODE,
    ScoutWorld,
    add_org,
    build,
    rows,
    run,
    subscribe,
)
from tests.integration.proposals.helpers import (
    Developers,
    ProposalWorld,
    Staff,
    cases_about,
    create,
    decide,
    draft_body,
    publish,
)

SETTINGS = get_settings()
TELCO = "Telco A (fixture)"


async def today(owner_engine: AsyncEngine) -> date:
    [row] = await rows(owner_engine, "SELECT (app_clock_now() AT TIME ZONE 'Africa/Nairobi')::date")
    day: date = row[0]
    return day


async def telco_world(owner_engine: AsyncEngine) -> ScoutWorld:
    """``build``'s organisations and niches; the E2 organisation is renamed Telco A (fixture), on the claimed plan."""
    world = await build(owner_engine)
    async with owner_engine.begin() as conn:
        await run(conn, "UPDATE organizations SET legal_name = :name WHERE id = :id", name=TELCO, id=world.org.id)
    return world


async def form(owner_engine: AsyncEngine, niche: UUID, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "title": "Rural towers lose power at night",
        "statement": "Our rural base stations drop off the network when the diesel runs out after dark.",
        "affected_group": "Subscribers in rural counties",
        "niche_id": str(niche),
        "county_code": NAIROBI_CODE,
        "budget_band": "500k_2m",
        "deadline": (await today(owner_engine) + timedelta(days=30)).isoformat(),
    }
    return body | overrides


def path(org: UUID, suffix: str = "") -> str:
    return f"/api/orgs/{org}/briefs{suffix}"


async def post(client: httpx.AsyncClient, org: UUID, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(path(org), json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def briefs_count(owner_engine: AsyncEngine, org: UUID) -> int:
    [row] = await rows(owner_engine, "SELECT count(*) FROM problem_briefs WHERE org_id = :org", org=org)
    return int(row[0])


async def feed(client: httpx.AsyncClient, world: ScoutWorld) -> dict[str, dict[str, Any]]:
    """Discover's Briefs view in the world's niche (``build`` names it ``p10-niche-<tag>``), by problem id."""
    response = await client.get("/api/discover/briefs", params={"niche": f"p10-niche-{world.tag}"})
    assert response.status_code == 200, response.text
    return {item["problem"]["id"]: item for item in response.json()["items"]}


async def recommended_ids(developer: httpx.AsyncClient) -> set[str]:
    response = await developer.get("/api/me/recommendations")
    assert response.status_code == 200, response.text
    return {item["problem"]["id"] for item in response.json()["items"]}


async def approve(moderators: Staff, problem_id: str) -> None:
    staff = await moderators()
    [case] = await cases_about(staff, problem_id)
    assert "new_org_brief" in case["reasons"]
    assert (await decide(staff, case, "approve")).status_code == 200


async def test_a_brief_waits_for_review_then_reaches_developers_with_its_organisation(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    developers: Developers,
    moderators: Staff,
    proposal_world: ProposalWorld,
) -> None:
    """Given Telco A (E2, claimed plan), When its reviewer posts a Brief, Then it is pending review, in the moderation
    queue, not on Discover, not readable by a developer and never ranked (AC-PERS-7); When staff approve it, Then it is
    on the Briefs view and its page says "Posted by Telco A (fixture)" with the band and deadline; a developer's
    proposal links it; closing takes it off the feed and keeps the problem."""
    world = await telco_world(owner_engine)
    body = await form(owner_engine, world.niche)
    developer = await developers()
    liked = {"liked": [str(world.niche), str(world.sibling), str(world.elsewhere)]}
    assert (await developer.put("/api/me/niches", json=liked)).status_code == 200
    async with clients(app_engine, SETTINGS, world.org.reviewer, world.org.viewer) as (reviewer, viewer):
        created = await post(reviewer, world.org.id, body)
        brief_id = created["id"]
        assert (created["problem_status"], created["moderation_state"], created["state"]) == (
            "pending_review",
            "clear",
            "in_review",
        )
        assert created["budget_band"] == {"code": "500k_2m", "label": "KES 500,000 to 2 million"}
        assert created["deadline"] == body["deadline"]
        assert created["proposal_count"] == 0
        listed = (await viewer.get(path(world.org.id))).json()  # any member reads the organisation's Briefs
        assert [item["id"] for item in listed["items"]] == [brief_id]
        assert listed["plan"] == {"plan": "org_claimed", "problem_briefs": 1, "used": 1}
        assert {band["code"] for band in listed["budget_bands"]} >= {"under_500k", "500k_2m"}

        assert brief_id not in await feed(developer, world)
        assert (await developer.get(f"/api/problems/{brief_id}")).status_code == 404
        assert brief_id not in await recommended_ids(developer)  # AC-PERS-7: a Brief under review never ranks

        await approve(moderators, brief_id)

        item = (await feed(developer, world))[brief_id]
        org_ref = {"id": str(world.org.id), "slug": f"p10-{world.org.id.hex}", "name": TELCO}
        assert item["problem"]["label"] == f"Posted by {TELCO}"
        assert item["problem"]["org"] == org_ref
        assert item["brief"] == {
            "org": org_ref,
            "budget_band": {"code": "500k_2m", "label": "KES 500,000 to 2 million"},
            "deadline": body["deadline"],
        }
        assert item["proposal_count"] == 0
        page = await developer.get(f"/api/problems/{brief_id}")
        assert page.status_code == 200, page.text
        detail = page.json()
        assert (detail["source"], detail["label"], detail["org"]) == ("org_brief", f"Posted by {TELCO}", org_ref)
        assert detail["brief"] == item["brief"]
        assert detail["affected_group"] == body["affected_group"]
        assert brief_id in await recommended_ids(developer)
        for text in (page.text, (await developer.get("/api/discover/briefs")).text):
            for person in (world.org.reviewer, world.org.owner, world.org.viewer):
                assert str(person) not in text  # no member of the organisation, only the organisation
            assert world.org.domain not in text

        draft = draft_body(proposal_world, link=False, niche_id=str(world.niche))
        draft["problem_ids"] = [brief_id]
        proposal = await create(developer, draft)
        assert (await publish(developer, proposal["id"])).status_code == 200
        teaser = (await developer.get(f"/api/proposals/{proposal['id']}")).json()
        [linked] = [p for p in teaser["problems"] if p["id"] == brief_id]
        assert (linked["org"], linked["label"]) == (org_ref, f"Posted by {TELCO}")
        assert (await feed(developer, world))[brief_id]["proposal_count"] == 1
        mine = (await reviewer.get(path(world.org.id, f"/{brief_id}"))).json()
        assert (mine["state"], mine["proposal_count"]) == ("published", 1)

        closed = await reviewer.post(path(world.org.id, f"/{brief_id}/close"))
        assert closed.status_code == 200, closed.text
        assert (closed.json()["status"], closed.json()["state"]) == ("closed", "closed")
        assert brief_id not in await feed(developer, world)
        assert (await reviewer.get(f"/api/problems/{brief_id}")).status_code == 200  # the problem stays
        [row] = await rows(owner_engine, "SELECT status FROM problems WHERE id = :id", id=UUID(brief_id))
        assert row.status == "published"
        again = await reviewer.post(path(world.org.id, f"/{brief_id}/close"))
        assert (again.status_code, again.json()["state"]) == (200, "closed")
        assert (await reviewer.get(path(world.org.id))).json()["plan"]["used"] == 0  # a closed Brief frees its slot
        await post(reviewer, world.org.id, await form(owner_engine, world.niche, title="Second brief"))
    events = await rows(
        owner_engine,
        "SELECT action FROM audit_events WHERE org_id = :org AND action LIKE 'brief.%' ORDER BY seq",
        org=world.org.id,
    )
    assert [e.action for e in events] == ["brief.created", "brief.closed", "brief.created"]


async def test_the_claimed_plan_posts_one_brief_and_a_rejected_one_frees_it(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, moderators: Staff
) -> None:
    """A second Brief on the claimed plan is 402 with the next plan named, and creates nothing; a Brief staff reject
    no longer counts; Growth has no limit."""
    world = await telco_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        first = await post(signatory, world.org.id, await form(owner_engine, world.niche))
        second = await signatory.post(path(world.org.id), json=await form(owner_engine, world.niche))
        assert second.status_code == 402, second.text
        detail = second.json()["detail"]
        assert (detail["code"], detail["limit_key"], detail["limit"], detail["used"]) == (
            "plan_limit",
            "problem_briefs",
            1,
            1,
        )
        assert detail["upgrade"] == {"plan": "org_starter", "url": "/billing/upgrade?plan=org_starter"}
        assert await briefs_count(owner_engine, world.org.id) == 1

        staff = await moderators()
        [case] = await cases_about(staff, first["id"])
        assert (await decide(staff, case, "reject")).status_code == 200
        rejected = (await signatory.get(path(world.org.id, f"/{first['id']}"))).json()
        assert (rejected["problem_status"], rejected["state"]) == ("rejected", "rejected")
        await post(signatory, world.org.id, await form(owner_engine, world.niche))

        await subscribe(owner_engine, world.org.id, "org_growth")
        for _ in range(2):
            await post(signatory, world.org.id, await form(owner_engine, world.niche))
        assert (await signatory.get(path(world.org.id))).json()["plan"] == {
            "plan": "org_growth",
            "problem_briefs": None,
            "used": 3,
        }


async def test_parallel_posts_never_pass_the_plan_limit(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Three Briefs at once on the claimed plan: one is created, two answer 402."""
    world = await telco_world(owner_engine)
    body = await form(owner_engine, world.niche)
    async with clients(app_engine, SETTINGS, world.org.reviewer, world.org.signatory, world.org.owner) as people:
        made = await asyncio.gather(*(client.post(path(world.org.id), json=body) for client in people))
    assert sorted(r.status_code for r in made) == [201, 402, 402]
    assert await briefs_count(owner_engine, world.org.id) == 1


async def test_only_verified_organisations_post_briefs(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """E1 (domain verified) and pending organisations get 403 verification_required and nothing is created."""
    world = await telco_world(owner_engine)
    async with owner_engine.begin() as conn:
        e1 = await add_org(conn, "claimed", "e1")
        pending = await add_org(conn, "pending", "pending")
    async with clients(app_engine, SETTINGS, e1.owner, pending.reviewer) as (owner, reviewer):
        for client, org in ((owner, e1), (reviewer, pending)):
            response = await client.post(path(org.id), json=await form(owner_engine, world.niche))
            assert response.status_code == 403, response.text
            assert response.json()["detail"]["code"] == "verification_required"
            assert await briefs_count(owner_engine, org.id) == 0
