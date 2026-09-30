"""REQ-ENG-04 (AC-TRACK-8/a; AC-SCOUT-8): Express interest opens ORG_INTEREST through the API. Only a signatory of an
E2 organisation with a fresh second factor (a reviewer gets 403); the developer is told (N17 in-app and email),
accepts with step-up (EM2 exactly once, their endorsement of stage 0) or declines; the same from a Browse teaser
gives origin org_browse. Every refusal is checked, and the org_interest signal is written."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.matching.scan import clock_now, run_periodic
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    Tracker,
    clients,
    db_today,
    deals_on,
    run_notifications,
)
from tests.integration.matching.scout_world import (
    ScoutWorld,
    Teaser,
    add_person,
    add_scout,
    build,
    deps,
    matches,
    publish,
    rows,
)

SETTINGS = deals_on()


async def matched(owner_engine: AsyncEngine, app_engine: AsyncEngine, world: ScoutWorld) -> tuple[UUID, UUID]:
    """A real scout match of the world's organisation: (proposal, match)."""
    proposal = (await publish(owner_engine, world, "one"))[0]
    scout = await add_scout(owner_engine, world.org, [world.niche])
    scan_deps, _ = deps(app_engine)
    await run_periodic(scan_deps, now=await clock_now(scan_deps.factory), force=True)
    [match] = await matches(owner_engine, scout)
    return proposal, match.id


def interest(world: ScoutWorld, proposal: UUID, match: UUID | None, today: Any, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "proposal_id": str(proposal),
        "origin": "org_agent_match" if match else "org_browse",
        "match_id": str(match) if match else None,
        "contact_user_id": str(world.org.owner),
        "channel": "video_call",
        "contact_by": str(today + timedelta(days=1)),
    }
    return body | overrides


async def stale_step_up(owner_engine: AsyncEngine, user: UUID) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE sessions SET mfa_verified_at = now() - interval '13 hours' WHERE user_id = :u"), {"u": user}
        )


async def test_a_signatory_expresses_interest_from_a_scout_match_and_the_developer_accepts(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    proposal, match = await matched(owner_engine, app_engine, world)
    today = await db_today(owner_engine)
    url = f"/api/orgs/{world.org.id}/interest"
    body = interest(world, proposal, match, today)
    async with clients(app_engine, SETTINGS, world.org.reviewer, world.org.owner, world.org.signatory) as (
        reviewer,
        owner,
        signatory,
    ):
        for refused in (reviewer, owner):  # AC-TRACK-8: a reviewer (or any role but signatory) gets 403
            response = await refused.post(url, json=body)
            assert (response.status_code, response.json()["detail"]["code"]) == (403, "role_required")
        created = await signatory.post(url, json=body)
        assert created.status_code == 201, created.text
        detail = created.json()
        assert (detail["state"], detail["origin"], detail["whose_turn"]) == (
            "ORG_INTEREST",
            "org_agent_match",
            ["developer"],
        )
        assert detail["my_party"] == "org"
        again = await signatory.post(url, json=body)
        assert (again.status_code, again.json()["detail"]["code"]) == (409, "engagement_exists")
        match_page = (await signatory.get(f"/api/orgs/{world.org.id}/matches/{match}")).json()
        assert match_page["engagement_id"] == detail["id"]
        assert match_page["interest"] == {"allowed": False, "reason": "engagement_exists"}
    engagement = UUID(detail["id"])
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider, SETTINGS)
    [n17] = provider.outbox  # N17 by email to the developer
    assert n17.to == world.developer_email
    assert n17.subject == f'{world.org.name} is interested in "Mobile money savings for SACCO members"'
    assert "through its scout" in n17.text
    assert f"/engagements/{engagement}" in n17.text
    notices = await rows(
        owner_engine, "SELECT kind, body FROM in_app_notifications WHERE user_id = :u", u=world.developer
    )
    assert [n.kind for n in notices] == ["engagement.n17"]
    assert notices[0].body == f'{world.org.name} is interested in "Mobile money savings for SACCO members".' + (
        " Accept or decline on your tracker."
    )
    t = Tracker(engagement)
    async with clients(app_engine, SETTINGS, world.developer, world.org.signatory) as (dev, signatory):
        accepted = await t.ok(dev, "accept-interest")
        assert accepted["state"] == "INTEREST_CONFIRMED"
        history = (await dev.get(t.path("/history"))).json()
        assert [e["command"] for e in history["events"]] == ["create", "accept_interest"]
        assert history["events"][0]["actor_role"] == "signatory"
        [endorsement] = history["endorsements"]
        assert (endorsement["stage"], endorsement["party"], endorsement["method"]) == (
            "ORG_INTEREST",
            "developer",
            "totp",
        )
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider, SETTINGS)
    await run_notifications(owner_engine, app_engine, engagement, provider, SETTINGS)
    [em2] = provider.outbox  # EM2 exactly once
    assert em2.subject.startswith("Good news:")
    assert "Your full proposal has not been shared yet." in em2.text
    signal = await rows(
        owner_engine,
        "SELECT actor_hash, org_hash FROM signal_events WHERE item_id = :p AND kind = 'org_interest'",
        p=proposal,
    )
    assert len(signal) == 1
    assert signal[0].actor_hash is not None
    assert signal[0].org_hash is not None
    [audit] = await rows(
        owner_engine,
        "SELECT payload FROM audit_events WHERE action = 'engagement.interest_expressed' AND subject_id = :e",
        e=engagement,
    )
    assert audit.payload == {"proposal_id": str(proposal), "origin": "org_agent_match", "match_id": str(match)}


async def test_the_same_flow_from_a_browse_teaser(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    proposal = (await publish(owner_engine, world, "browsed"))[0]
    today = await db_today(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.signatory, world.developer) as (signatory, dev):
        created = await signatory.post(
            f"/api/orgs/{world.org.id}/interest", json=interest(world, proposal, None, today)
        )
        assert created.status_code == 201, created.text
        assert created.json()["origin"] == "org_browse"
        declined = await Tracker(UUID(created.json()["id"])).ok(dev, "decline-interest")
        assert (declined["state"], declined["end_reason"]) == ("DECLINED", "BY_DEVELOPER")
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, UUID(created.json()["id"]), provider, SETTINGS)
    assert "while browsing proposals" in provider.outbox[0].text
    assert len(provider.outbox) == 1  # N17 only: no EM2 on a decline


async def test_refusals(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    proposal, match = await matched(owner_engine, app_engine, world)
    held = (await publish(owner_engine, world, "held", moderation_state="held"))[0]
    today = await db_today(owner_engine)
    url = f"/api/orgs/{world.org.id}/interest"
    other_scout = await add_scout(owner_engine, world.other, [world.niche])
    scan_deps, _ = deps(app_engine)
    await run_periodic(scan_deps, now=await clock_now(scan_deps.factory), force=True)
    [other_match] = await matches(owner_engine, other_scout)
    second = (await publish(owner_engine, world, "second", Teaser(title="Another")))[0]
    cases: list[tuple[dict[str, Any], int, str]] = [
        (interest(world, proposal, None, today, origin="org_agent_match", match_id=None), 422, "match_required"),
        (interest(world, proposal, match, today, origin="org_browse"), 422, "unexpected_match"),
        (interest(world, proposal, other_match.id, today), 404, "not_found"),  # another organisation's match
        (interest(world, second, match, today), 404, "not_found"),  # a match of another proposal
        (interest(world, held, None, today), 404, "not_found"),
        (interest(world, uuid4(), None, today), 404, "not_found"),
        (interest(world, proposal, None, today, contact_user_id=str(world.other.owner)), 422, "invalid_contact"),
        (interest(world, proposal, None, today, contact_by=str(today - timedelta(days=1))), 422, "invalid_contact_by"),
        (interest(world, proposal, None, today, contact_by=str(today + timedelta(days=30))), 422, "invalid_contact_by"),
    ]
    async with clients(app_engine, SETTINGS, world.org.signatory, world.other.signatory) as (signatory, stranger):
        for body, status, code in cases:
            response = await signatory.post(url, json=body)
            assert (response.status_code, response.json()["detail"]["code"]) == (status, code), body
        assert (await stranger.post(url, json=interest(world, proposal, None, today))).status_code == 404
        await stale_step_up(owner_engine, world.org.signatory)
        stale = await signatory.post(url, json=interest(world, proposal, None, today))
        assert (stale.status_code, stale.json()["detail"]["code"]) == (403, "step_up_required")
    assert await rows(owner_engine, "SELECT id FROM engagements WHERE org_id = :o", o=world.org.id) == []


async def test_an_e1_organisation_gets_403_until_e2(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """AC-SCOUT-8: an E1 organisation's Express interest returns 403 until it is E2."""
    world = await build(owner_engine, verification="e1")
    proposal = (await publish(owner_engine, world, "one"))[0]
    today = await db_today(owner_engine)
    url = f"/api/orgs/{world.org.id}/interest"
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        refused = await signatory.post(url, json=interest(world, proposal, None, today))
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "org_not_e2")
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE organizations SET verification = 'e2' WHERE id = :o"), {"o": world.org.id})
        assert (await signatory.post(url, json=interest(world, proposal, None, today))).status_code == 201


async def test_the_developer_may_not_be_a_member(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """P10 security review MINOR (a): the refusal is the 404 of an unavailable proposal (no oracle telling an employer
    that an author is one of its members), audited where no organisation member reads it."""
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    async with owner_engine.begin() as conn:
        insider = await add_person(conn, "insider", world.org.domain)
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :o, :u, '{viewer}')"),
            {"id": uuid4(), "o": world.org.id, "u": insider},
        )
    own = replace(world, developer=insider, proposals={})
    proposal = (await publish(owner_engine, own, "own"))[0]
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        refused = await signatory.post(
            f"/api/orgs/{world.org.id}/interest", json=interest(world, proposal, None, today)
        )
        unavailable_id = str(uuid4())
        unavailable = await signatory.post(
            f"/api/orgs/{world.org.id}/interest", json=interest(world, UUID(unavailable_id), None, today)
        )
    assert (refused.status_code, refused.json()) == (unavailable.status_code, unavailable.json())
    assert refused.status_code == 404
    events = await rows(
        owner_engine,
        "SELECT chain_id, actor_user_id, org_id, actor_kind::text AS kind, payload FROM audit_events"
        " WHERE action = 'engagement.interest_refused' AND subject_id IN (:p, :q) ORDER BY seq",
        p=proposal,
        q=UUID(unavailable_id),
    )
    who = {"org_id": str(world.org.id), "user_id": str(world.org.signatory)}  # round-2 MINOR 4: staff see both
    assert [(e.chain_id, e.actor_user_id, e.org_id, e.kind, e.payload) for e in events] == [
        ("global", None, None, "system", {"condition": "own_organisation"} | who),
        ("global", None, None, "system", {"condition": "proposal_unavailable"} | who),
    ]
    for member in (world.org.signatory, world.org.owner):  # neither the actor nor the organisation's admins see it
        async with create_session_factory(app_engine)() as db:
            await bind_tenant(db, user_id=member, org_id=world.org.id)
            seen = await db.scalar(
                text("SELECT count(*) FROM audit_events WHERE action = 'engagement.interest_refused'")
            )
        assert seen == 0


async def test_both_404s_of_a_proposal_run_the_same_statements(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Round-2 review MINOR 1: the own-member 404 was about 3 ms slower than an unavailable proposal's (a membership
    read, an audit INSERT and a COMMIT only on that branch). Now one read gives the proposal with the membership and
    both refusals write the same audit event and commit, so the database does the same work for both answers."""
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    async with owner_engine.begin() as conn:
        insider = await add_person(conn, "insider", world.org.domain)
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :o, :u, '{viewer}')"),
            {"id": uuid4(), "o": world.org.id, "u": insider},
        )
    own = (await publish(owner_engine, replace(world, developer=insider, proposals={}), "own"))[0]
    held = (await publish(owner_engine, world, "held", moderation_state="held"))[0]
    statements: list[str] = []

    def capture(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    url = f"/api/orgs/{world.org.id}/interest"
    by_case: dict[str, list[str]] = {}
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        await signatory.post(url, json=interest(world, uuid4(), None, today))  # warm: the same caches for each case
        event.listen(app_engine.sync_engine, "before_cursor_execute", capture)
        try:
            for case, proposal in (("own", own), ("held", held), ("missing", uuid4())):
                statements.clear()
                response = await signatory.post(url, json=interest(world, proposal, None, today))
                assert response.status_code == 404, case
                by_case[case] = list(statements)
        finally:
            event.remove(app_engine.sync_engine, "before_cursor_execute", capture)
    assert by_case["own"] == by_case["held"] == by_case["missing"]
    assert any(s.startswith("INSERT INTO audit_events") for s in by_case["own"])  # each refusal is audited


async def test_a_suspended_organisation_cannot_express_interest(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    proposal = (await publish(owner_engine, world, "one"))[0]
    today = await db_today(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE organizations SET suspended_at = now() WHERE id = :o"), {"o": world.org.id})
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        refused = await signatory.post(
            f"/api/orgs/{world.org.id}/interest", json=interest(world, proposal, None, today)
        )
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "org_unavailable")


async def test_n17_by_email_follows_the_developers_preference(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """N17 is mutable: with the n17 email preference off, or an unverified address, it is in-app only."""
    for change in (
        "INSERT INTO notification_preferences (user_id, kind, channel, enabled) VALUES (:u, 'n17', 'email', false)",
        "UPDATE users SET email_verified_at = NULL WHERE id = :u",
    ):
        world = await build(owner_engine)
        proposal = (await publish(owner_engine, world, "one"))[0]
        today = await db_today(owner_engine)
        async with owner_engine.begin() as conn:
            await conn.execute(text(change), {"u": world.developer})
        async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
            created = await signatory.post(
                f"/api/orgs/{world.org.id}/interest", json=interest(world, proposal, None, today)
            )
            assert created.status_code == 201
        provider = FakeEmailProvider()
        await run_notifications(owner_engine, app_engine, UUID(created.json()["id"]), provider, SETTINGS)
        assert provider.outbox == []
        notices = await rows(
            owner_engine, "SELECT kind FROM in_app_notifications WHERE user_id = :u", u=world.developer
        )
        assert [n.kind for n in notices] == ["engagement.n17"]
