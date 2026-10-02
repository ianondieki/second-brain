"""REQ-SCOUT-02, REQ-SCOUT-03: the matches API. Members read their organisation's matches (the teaser through the
current version, the niche label, score, why and the demo fallback flag); nothing changes on GET; another
organisation's matches are never visible (404); feedback is recorded as the caller by members who act on proposals."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.matching.scan import clock_now, run_periodic
from tests.integration.engagements.api_world import clients, db_today
from tests.integration.matching.scout_world import (
    ScoutWorld,
    add_scout,
    build,
    deps,
    matches,
    publish,
    rows,
)

SETTINGS = get_settings()


async def scanned(owner_engine: AsyncEngine, app_engine: AsyncEngine, world: ScoutWorld) -> tuple[UUID, UUID]:
    """A scout of the world's organisation that matched one proposal: (scout, match)."""
    await publish(owner_engine, world, "one")
    scout = await add_scout(owner_engine, world.org, [world.niche])
    scan_deps, _ = deps(app_engine)
    await run_periodic(scan_deps, now=await clock_now(scan_deps.factory), force=True)
    [match] = await matches(owner_engine, scout)
    return scout, match.id


async def snapshot(owner_engine: AsyncEngine, match: UUID) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT score, rationale, digest_sent_at, feedback, feedback_by, feedback_at,"
        " (SELECT count(*) FROM engagements) AS engagements, (SELECT count(*) FROM audit_events) AS events"
        " FROM agent_matches WHERE id = :m",
        m=match,
    )


async def test_members_read_matches_and_nothing_changes_on_get(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    scout, match = await scanned(owner_engine, app_engine, world)
    before = await snapshot(owner_engine, match)
    async with clients(app_engine, SETTINGS, world.org.viewer, world.org.signatory, world.org.reviewer) as (
        viewer,
        signatory,
        reviewer,
    ):
        listed = await viewer.get(f"/api/orgs/{world.org.id}/matches")
        assert listed.status_code == 200
        [item] = [i for i in listed.json()["items"] if i["scout_id"] == str(scout)]
        assert item["id"] == str(match)
        assert item["proposal_id"] == str(world.proposal("one"))
        assert (item["available"], item["score"], item["why_source"], item["demo_fallback"]) == (
            True,
            90,
            "code",
            False,
        )
        assert item["niche"]["label"] == f"Finance {world.tag} › Microfinance {world.tag}"
        assert item["teaser"]["title"] == "Mobile money savings for SACCO members"
        assert item["owner_handle"] == f"dev-{world.developer.hex}"
        assert item["why"].startswith("Matched on niche")
        only = await viewer.get(f"/api/orgs/{world.org.id}/matches", params={"scout_id": str(scout)})
        assert [i["id"] for i in only.json()["items"]] == [str(match)]
        detail = await signatory.get(f"/api/orgs/{world.org.id}/matches/{match}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["rule_breakdown"]["deterministic"] == 90
        assert (body["engagement_id"], body["interest"]) == (None, {"allowed": True, "reason": None})
        assert body["today"] == str(await db_today(owner_engine))  # the platform clock's day (Express interest)
        by_reviewer = (await reviewer.get(f"/api/orgs/{world.org.id}/matches/{match}")).json()
        assert by_reviewer["interest"] == {"allowed": False, "reason": "role_required"}
        for _ in range(2):
            await viewer.get(f"/api/orgs/{world.org.id}/matches/{match}")
    assert await snapshot(owner_engine, match) == before  # reads change nothing (no audit, no engagement)


async def test_another_organisations_matches_are_never_visible(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    _, match = await scanned(owner_engine, app_engine, world)
    other = world.other
    async with clients(app_engine, SETTINGS, other.owner, other.reviewer) as (owner, reviewer):
        own = await owner.get(f"/api/orgs/{other.id}/matches")
        assert all(i["id"] != str(match) for i in own.json()["items"])
        assert (await owner.get(f"/api/orgs/{world.org.id}/matches")).status_code == 404  # not a member
        assert (await owner.get(f"/api/orgs/{other.id}/matches/{match}")).status_code == 404  # not theirs
        feedback = await reviewer.post(f"/api/orgs/{other.id}/matches/{match}/feedback", json={"feedback": "relevant"})
        assert feedback.status_code == 404
    [row] = await matches(
        owner_engine,
        (await rows(owner_engine, "SELECT scout_id FROM agent_matches WHERE id = :m", m=match))[0].scout_id,
    )
    assert row.id == match


async def test_feedback_is_recorded_as_the_caller(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    _, match = await scanned(owner_engine, app_engine, world)
    org = world.org
    url = f"/api/orgs/{org.id}/matches/{match}/feedback"
    async with clients(app_engine, SETTINGS, org.reviewer, org.finance, org.viewer, org.signatory) as (
        reviewer,
        finance,
        viewer,
        signatory,
    ):
        for refused in (finance, viewer):
            response = await refused.post(url, json={"feedback": "relevant"})
            assert (response.status_code, response.json()["detail"]["code"]) == (403, "role_required")
        assert (await reviewer.post(url, json={"feedback": "not_relevant", "reason": "made_up"})).status_code == 422
        given = await reviewer.post(url, json={"feedback": "not_relevant", "reason": "wrong_county"})
        assert given.status_code == 200
        assert (given.json()["feedback"], given.json()["feedback_reason"]) == ("not_relevant", "wrong_county")
        taken = await signatory.post(url, json={"feedback": "relevant"})  # the feedback stays its author's
        assert (taken.status_code, taken.json()["detail"]["code"]) == (409, "feedback_given")
        changed = await reviewer.post(url, json={"feedback": "relevant"})
        assert (changed.json()["feedback"], changed.json()["feedback_reason"]) == ("relevant", None)
    [row] = await rows(owner_engine, "SELECT feedback_by, feedback_at FROM agent_matches WHERE id = :m", m=match)
    assert row.feedback_by == org.reviewer
    assert row.feedback_at is not None


async def test_a_match_whose_proposal_is_held_shows_no_teaser(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    _, match = await scanned(owner_engine, app_engine, world)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE proposals SET moderation_state = 'held' WHERE id = :p"), {"p": world.proposal("one")}
        )
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        body = (await signatory.get(f"/api/orgs/{world.org.id}/matches/{match}")).json()
    assert (body["available"], body["teaser"], body["owner_handle"]) == (False, None, None)
    assert (body["why"], body["why_source"], body["rule_breakdown"]) == (None, "code", {})  # nothing of the teaser
    assert body["niche"]["label"].endswith(f"Microfinance {world.tag}")
    assert body["interest"] == {"allowed": False, "reason": "proposal_unavailable"}


async def test_a_match_whose_author_joined_the_organisation_is_unavailable(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Round-2 review MINOR 2: a match found before its author joined the organisation showed the teaser and allowed
    Express interest, which then answered 404. While the author is an active member the match is unavailable (no
    teaser, why or rules; ``proposal_unavailable``) in the list and on its page, like the interest route's 404; a
    removed membership makes it available again."""
    world = await build(owner_engine)
    _, match = await scanned(owner_engine, app_engine, world)
    membership = uuid4()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :o, :u, '{viewer}')"),
            {"id": membership, "o": world.org.id, "u": world.developer},
        )
    today = await db_today(owner_engine)
    body = {
        "proposal_id": str(world.proposal("one")),
        "origin": "org_agent_match",
        "match_id": str(match),
        "contact_user_id": str(world.org.owner),
        "channel": "video_call",
        "contact_by": str(today + timedelta(days=1)),
    }
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        detail = (await signatory.get(f"/api/orgs/{world.org.id}/matches/{match}")).json()
        listed = (await signatory.get(f"/api/orgs/{world.org.id}/matches")).json()["items"]
        interest = await signatory.post(f"/api/orgs/{world.org.id}/interest", json=body)
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE memberships SET status = 'removed' WHERE id = :id"), {"id": membership})
        again = (await signatory.get(f"/api/orgs/{world.org.id}/matches/{match}")).json()
    assert (detail["available"], detail["teaser"], detail["owner_handle"]) == (False, None, None)
    assert (detail["why"], detail["why_source"], detail["rule_breakdown"]) == (None, "code", {})
    assert detail["interest"] == {"allowed": False, "reason": "proposal_unavailable"}
    [item] = [i for i in listed if i["id"] == str(match)]
    assert (item["available"], item["teaser"], item["why"]) == (False, None, None)
    assert interest.status_code == 404  # what the page now says
    assert (again["available"], again["interest"]) == (True, {"allowed": True, "reason": None})
    assert again["teaser"]["title"] == "Mobile money savings for SACCO members"


async def test_an_e1_organisation_cannot_express_interest_yet(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AC-SCOUT-8: an E1 organisation's matches say why Express interest is disabled."""
    world = await build(owner_engine, verification="e1")
    _, match = await scanned(owner_engine, app_engine, world)
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        body = (await signatory.get(f"/api/orgs/{world.org.id}/matches/{match}")).json()
    assert body["interest"] == {"allowed": False, "reason": "org_not_e2"}


async def test_a_suspended_or_delisted_organisation_cannot_express_interest(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    _, match = await scanned(owner_engine, app_engine, world)
    for change in (
        "UPDATE organizations SET suspended_at = now() WHERE id = :o",
        "UPDATE organizations SET suspended_at = NULL, delisted_at = now() WHERE id = :o",
    ):
        async with owner_engine.begin() as conn:
            await conn.execute(text(change), {"o": world.org.id})
        async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
            body = (await signatory.get(f"/api/orgs/{world.org.id}/matches/{match}")).json()
        assert body["interest"] == {"allowed": False, "reason": "org_unavailable"}, change
