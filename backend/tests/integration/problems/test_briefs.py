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
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge import pagination
from bridge.config import get_settings
from bridge.problems import briefs
from bridge.problems.brief_policy import BriefsPolicy
from tests.integration.engagements.api_world import clients
from tests.integration.matching.scout_world import (
    MOMBASA_CODE,
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


async def pass_deadline(owner_engine: AsyncEngine, brief_id: str) -> None:
    """Move a Brief's deadline 31 days back (into the past: ``form`` sets it 30 days ahead)."""
    async with owner_engine.begin() as conn:
        await run(conn, "UPDATE problem_briefs SET deadline = deadline - 31 WHERE problem_id = :id", id=UUID(brief_id))


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
        assert (created["status"], created["problem_status"], created["moderation_state"], created["state"]) == (
            "draft",
            "pending_review",
            "clear",
            "in_review",
        )
        [row] = await rows(owner_engine, "SELECT status FROM problem_briefs WHERE problem_id = :id", id=UUID(brief_id))
        assert row.status == "draft"  # nothing of it is readable beyond the organisation and staff
        early = await reviewer.post(path(world.org.id, f"/{brief_id}/close"))
        assert (early.status_code, early.json()["detail"]["code"]) == (409, "brief_not_published")
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
        approved = (await reviewer.get(path(world.org.id, f"/{brief_id}"))).json()
        assert (approved["status"], approved["state"]) == ("published", "published")  # approval published both

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
        kept = await developer.get(f"/api/problems/{brief_id}")
        assert (kept.status_code, kept.json()["brief"]["org"]) == (200, org_ref)  # readable once closed (0006)
        teaser = (await developer.get(f"/api/proposals/{proposal['id']}")).json()
        assert brief_id in [p["id"] for p in teaser["problems"]]  # the proposal's link stays
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


async def test_editors_post_and_other_members_read(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Owner, admin, signatory and reviewer post; finance and viewer get 403; a non-member and another organisation's
    member get 404 for the list, a Brief, a change and a close."""
    world = await telco_world(owner_engine)
    await subscribe(owner_engine, world.org.id, "org_growth")
    async with clients(
        app_engine, SETTINGS, world.org.finance, world.org.owner, world.other.owner, world.developer
    ) as (finance, owner, outsider, stranger):
        body = await form(owner_engine, world.niche)
        refused = await finance.post(path(world.org.id), json=body)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "forbidden")
        assert (await finance.get(path(world.org.id))).status_code == 200
        brief = await post(owner, world.org.id, body)
        assert (await finance.get(path(world.org.id, f"/{brief['id']}"))).status_code == 200
        assert (await finance.post(path(world.org.id, f"/{brief['id']}/close"))).status_code == 403
        for client in (outsider, stranger):
            assert (await client.get(path(world.org.id))).status_code == 404
            assert (await client.get(path(world.org.id, f"/{brief['id']}"))).status_code == 404
        # Another organisation's own path does not reach this Brief.
        foreign = path(world.other.id, f"/{brief['id']}")
        assert (await outsider.get(foreign)).status_code == 404
        assert (await outsider.patch(foreign, json={"budget_band": None})).status_code == 404
        assert (await outsider.post(f"{foreign}/close")).status_code == 404


async def test_invited_briefs_are_not_available_yet(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await telco_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        response = await reviewer.post(
            path(world.org.id), json=await form(owner_engine, world.niche, visibility="invited")
        )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "visibility_not_available"
    assert await briefs_count(owner_engine, world.org.id) == 0


async def test_a_brief_is_public_text_and_its_form_is_checked(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """A phone number or an email address (the sanitiser's contact rule), a long title or statement, an unknown band,
    niche or county and a past deadline are 422 ``invalid_brief`` with one error per field; nothing is created."""
    world = await telco_world(owner_engine)
    yesterday = (await today(owner_engine) - timedelta(days=1)).isoformat()
    cases: list[tuple[dict[str, Any], dict[str, str]]] = [
        ({"statement": "Call our desk on 0712 345 678 to discuss."}, {"statement": "contains_phone"}),
        ({"title": "Write to briefs@telco.example.com"}, {"title": "contains_email"}),
        ({"title": "T" * 91}, {"title": "too_long"}),
        ({"statement": "S" * 1201}, {"statement": "too_long"}),
        ({"statement": "word " * 121}, {"statement": "too_long"}),
        ({"title": "<b></b>"}, {"title": "blank"}),
        ({"budget_band": "a_lot"}, {"budget_band": "unknown_budget_band"}),
        ({"deadline": yesterday}, {"deadline": "deadline_past"}),
        ({"niche_id": str(UUID(int=7))}, {"niche_id": "unknown_niche"}),
        ({"county_code": "KE-99"}, {"county_code": "unknown_county"}),
        (
            {"budget_band": "a_lot", "deadline": yesterday},
            {"budget_band": "unknown_budget_band", "deadline": "deadline_past"},
        ),
    ]
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        for overrides, expected in cases:
            response = await reviewer.post(path(world.org.id), json=await form(owner_engine, world.niche, **overrides))
            assert response.status_code == 422, (overrides, response.text)
            detail = response.json()["detail"]
            assert detail["code"] == "invalid_brief"
            assert {e["field"]: e["code"] for e in detail["errors"]} == expected
            assert all(e["message"] for e in detail["errors"])
            assert "0712" not in response.text  # the refused text is never quoted back
            assert "telco.example.com" not in response.text
        assert await briefs_count(owner_engine, world.org.id) == 0
        ok = await post(reviewer, world.org.id, await form(owner_engine, world.niche, deadline=None, budget_band=None))
        assert (ok["deadline"], ok["budget_band"], ok["visibility"]) == (None, None, "public")


async def test_an_org_negative_brief_is_held_for_the_moderator(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, moderators: Staff
) -> None:
    """The same pre-screen as a developer's problem: naming a directory organisation negatively holds the Brief."""
    world = await telco_world(owner_engine)
    statement = f"{world.other.name} is a fraud and its agents cheat farmers."
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        held = await post(reviewer, world.org.id, await form(owner_engine, world.niche, statement=statement))
    assert (held["moderation_state"], held["state"]) == ("held", "in_review")
    staff = await moderators()
    [case] = await cases_about(staff, held["id"])
    assert {"new_org_brief", "names_real_org_negative"} <= set(case["reasons"])
    assert case["brief_org"] == {"id": str(world.org.id), "slug": f"p10-{world.org.id.hex}", "name": TELCO}
    assert (await staff.get(f"/api/admin/moderation/cases/{case['id']}")).json()["brief_org"]["name"] == TELCO
    assert {f["name"] for f in case["fields"]} == {"title", "statement", "affected_group"}


async def test_the_band_and_deadline_change_until_the_brief_closes(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, moderators: Staff
) -> None:
    world = await telco_world(owner_engine)
    day = await today(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        brief = await post(reviewer, world.org.id, await form(owner_engine, world.niche))
        one = path(world.org.id, f"/{brief['id']}")
        later = (day + timedelta(days=60)).isoformat()
        moved = await reviewer.patch(one, json={"budget_band": "over_10m", "deadline": later})
        assert moved.status_code == 200, moved.text
        assert moved.json()["budget_band"]["code"] == "over_10m"
        assert moved.json()["deadline"] == later
        cleared = (await reviewer.patch(one, json={"deadline": None})).json()
        assert (cleared["deadline"], cleared["budget_band"]["code"]) == (None, "over_10m")
        past = await reviewer.patch(one, json={"deadline": (day - timedelta(days=1)).isoformat()})
        assert (past.status_code, past.json()["detail"]["code"]) == (422, "invalid_brief")
        unknown = await reviewer.patch(one, json={"budget_band": "a_lot"})
        assert unknown.json()["detail"]["errors"][0]["code"] == "unknown_budget_band"
        extra = await reviewer.patch(one, json={"title": "A new title"})
        assert extra.status_code == 422  # the moderated text does not change here
        await approve(moderators, brief["id"])
        published = await reviewer.patch(one, json={"budget_band": "2m_10m"})  # still open once published
        assert published.json()["budget_band"]["code"] == "2m_10m"
        assert (await reviewer.post(f"{one}/close")).status_code == 200
        late = await reviewer.patch(one, json={"budget_band": "under_500k"})
        assert (late.status_code, late.json()["detail"]["code"]) == (409, "brief_closed")
        missing = await reviewer.patch(path(world.org.id, f"/{UUID(int=9)}"), json={"budget_band": None})
        assert missing.status_code == 404


async def test_the_lists_page_filter_and_a_passed_deadline_leaves_the_view(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers, moderators: Staff
) -> None:
    """The organisation's list and Discover's Briefs view page with ``limit`` and ``cursor`` (newest first); the view
    filters by county; a Brief whose deadline has passed leaves the view and keeps its page."""
    world = await telco_world(owner_engine)
    await subscribe(owner_engine, world.org.id, "org_growth")
    developer = await developers()
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        posted = [
            (await post(reviewer, world.org.id, await form(owner_engine, world.niche, title=f"Brief {n}")))["id"]
            for n in range(3)
        ]
        first = (await reviewer.get(path(world.org.id), params={"limit": 2})).json()
        assert [item["id"] for item in first["items"]] == posted[:0:-1]
        rest = (await reviewer.get(path(world.org.id), params={"limit": 2, "cursor": first["next_cursor"]})).json()
        assert ([item["id"] for item in rest["items"]], rest["next_cursor"]) == ([posted[0]], None)
        momentless = pagination.encode(None, UUID(posted[0]))
        refused = await reviewer.get(path(world.org.id), params={"cursor": momentless})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (400, "invalid_cursor")
    for brief_id in posted:
        await approve(moderators, brief_id)

    niche = f"p10-niche-{world.tag}"
    page = (await developer.get("/api/discover/briefs", params={"niche": niche, "limit": 2})).json()
    assert [item["problem"]["id"] for item in page["items"]] == posted[:0:-1]
    after = {"niche": niche, "limit": 2, "cursor": page["next_cursor"]}
    tail = (await developer.get("/api/discover/briefs", params=after)).json()
    assert ([item["problem"]["id"] for item in tail["items"]], tail["next_cursor"]) == ([posted[0]], None)
    nairobi = await developer.get("/api/discover/briefs", params={"niche": niche, "county": NAIROBI_CODE})
    assert len(nairobi.json()["items"]) == 3
    mombasa = await developer.get("/api/discover/briefs", params={"niche": niche, "county": MOMBASA_CODE})
    assert mombasa.json()["items"] == []

    await pass_deadline(owner_engine, posted[0])
    assert posted[0] not in await feed(developer, world)
    kept = await developer.get(f"/api/problems/{posted[0]}")
    assert kept.status_code == 200
    assert kept.json()["brief"]["deadline"] < (await today(owner_engine)).isoformat()


async def test_an_organisation_no_longer_e2_cannot_change_its_published_brief(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, moderators: Staff
) -> None:
    """The policies' E2 guard on a published Brief refuses the change (42501 on the Brief's write): 403
    verification_required, nothing changed; closing it is still the organisation's."""
    world = await telco_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        brief = await post(reviewer, world.org.id, await form(owner_engine, world.niche))
        await approve(moderators, brief["id"])
        async with owner_engine.begin() as conn:
            await run(conn, "UPDATE organizations SET verification = 'e1' WHERE id = :id", id=world.org.id)
        one = path(world.org.id, f"/{brief['id']}")
        refused = await reviewer.patch(one, json={"budget_band": "over_10m"})
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "verification_required")
        assert (await reviewer.get(one)).json()["budget_band"]["code"] == "500k_2m"
        assert (await reviewer.post(f"{one}/close")).json()["state"] == "closed"


async def test_a_brief_past_its_deadline_leaves_trending_and_the_ranker(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, developers: Developers, moderators: Staff
) -> None:
    """Approved, a Brief is new this week on Trending and ranked; once its deadline has passed (Africa/Nairobi, the
    platform clock) it is neither, and its page stays."""
    world = await telco_world(owner_engine)
    developer = await developers()
    liked = {"liked": [str(world.niche), str(world.sibling), str(world.elsewhere)]}
    assert (await developer.put("/api/me/niches", json=liked)).status_code == 200
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        brief_id = (await post(reviewer, world.org.id, await form(owner_engine, world.niche)))["id"]
    await approve(moderators, brief_id)

    async def trending() -> set[str]:
        response = await developer.get("/api/discover/trending", params={"niche": f"p10-niche-{world.tag}"})
        assert response.status_code == 200, response.text
        return {item["problem"]["id"] for item in response.json()["problems"]}

    assert brief_id in await trending()
    assert brief_id in await recommended_ids(developer)
    await pass_deadline(owner_engine, brief_id)
    assert brief_id not in await trending()
    assert brief_id not in await recommended_ids(developer)
    assert (await developer.get(f"/api/problems/{brief_id}")).status_code == 200


async def test_a_brief_past_its_deadline_frees_its_plan_slot(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Open, for the plan, is not closed and the deadline unset or not passed: on the claimed plan (one Brief) a
    Brief whose deadline has passed no longer counts, so another may be posted."""
    world = await telco_world(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        first = await post(reviewer, world.org.id, await form(owner_engine, world.niche))
        assert (await reviewer.post(path(world.org.id), json=await form(owner_engine, world.niche))).status_code == 402
        await pass_deadline(owner_engine, first["id"])
        assert (await reviewer.get(path(world.org.id))).json()["plan"]["used"] == 0
        await post(reviewer, world.org.id, await form(owner_engine, world.niche, deadline=None))
        assert (await reviewer.get(path(world.org.id))).json()["plan"]["used"] == 1  # no deadline: open until closed


async def test_a_suspended_or_delisted_organisation_posts_no_brief(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """E2 is not enough: a suspended or a delisted organisation gets 403 org_unavailable and nothing is created."""
    world = await telco_world(owner_engine)
    for column in ("suspended_at", "delisted_at"):
        async with owner_engine.begin() as conn:
            org = await add_org(conn, column.split("_")[0])
            await run(conn, f"UPDATE organizations SET {column} = now() WHERE id = :id", id=org.id)
        async with clients(app_engine, SETTINGS, org.reviewer) as (reviewer,):
            response = await reviewer.post(path(org.id), json=await form(owner_engine, world.niche))
        assert (response.status_code, response.json()["detail"]["code"]) == (403, "org_unavailable"), column
        assert await briefs_count(owner_engine, org.id) == 0


async def test_a_delisted_organisations_brief_leaves_the_feeds_and_its_page(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    developers: Developers,
    moderators: Staff,
    proposal_world: ProposalWorld,
) -> None:
    """A published Brief's problem needs a listed organisation: once it is delisted, the Brief leaves the Briefs view,
    Trending, the ranker, the problem list and the proposals' links, and its page is 404 (to its members too); the
    organisation's own list still shows it."""
    world = await telco_world(owner_engine)
    developer = await developers()
    liked = {"liked": [str(world.niche), str(world.sibling), str(world.elsewhere)]}
    assert (await developer.put("/api/me/niches", json=liked)).status_code == 200
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        brief_id = (await post(reviewer, world.org.id, await form(owner_engine, world.niche)))["id"]
        await approve(moderators, brief_id)
        draft = draft_body(proposal_world, link=False, niche_id=str(world.niche))
        draft["problem_ids"] = [brief_id]
        proposal = await create(developer, draft)
        assert (await publish(developer, proposal["id"])).status_code == 200
        niche = {"niche": f"p10-niche-{world.tag}"}

        async def seen() -> dict[str, bool]:
            trending = (await developer.get("/api/discover/trending", params=niche)).json()["problems"]
            listed = (await developer.get("/api/problems", params=niche)).json()["items"]
            teaser = (await developer.get(f"/api/proposals/{proposal['id']}")).json()["problems"]
            return {
                "view": brief_id in await feed(developer, world),
                "trending": brief_id in {p["problem"]["id"] for p in trending},
                "ranked": brief_id in await recommended_ids(developer),
                "list": brief_id in {p["id"] for p in listed},
                "link": brief_id in {p["id"] for p in teaser},
                "page": (await developer.get(f"/api/problems/{brief_id}")).status_code == 200,
                "members_page": (await reviewer.get(f"/api/problems/{brief_id}")).status_code == 200,
            }

        before = await seen()
        assert all(before.values()), before
        async with owner_engine.begin() as conn:
            await run(conn, "UPDATE organizations SET delisted_at = now() WHERE id = :id", id=world.org.id)
        after = await seen()
        assert not any(after.values()), after
        assert (await reviewer.get(path(world.org.id, f"/{brief_id}"))).json()["state"] == "published"


async def test_an_organisation_posts_a_limited_number_of_briefs_a_day(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """policy.yaml's briefs.daily_posts (2 here) caps posts per Nairobi day whatever the plan: the next is 429
    briefs_daily_limit and creates nothing; a closed or rejected Brief still counted as a post."""
    monkeypatch.setattr(briefs, "get_briefs_policy", lambda: BriefsPolicy(daily_posts=2))
    world = await telco_world(owner_engine)
    await subscribe(owner_engine, world.org.id, "org_growth")
    async with clients(app_engine, SETTINGS, world.org.reviewer) as (reviewer,):
        for _ in range(2):
            await post(reviewer, world.org.id, await form(owner_engine, world.niche))
        refused = await reviewer.post(path(world.org.id), json=await form(owner_engine, world.niche))
    assert (refused.status_code, refused.json()["detail"]["code"]) == (429, "briefs_daily_limit")
    assert await briefs_count(owner_engine, world.org.id) == 2
