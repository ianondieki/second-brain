"""REQ-ENG-04, REQ-REPO-01 (docs/spec/06 6.9 stage 0 "Tier 2 by manual grant"): the developer shares the full proposal
with an organisation that expressed interest. Developer only, with a fresh second factor, on an organisation-origin
engagement that has not ended; idempotent; source org_interest, counts_as_unlock for an untagged proposal, the Nairobi
billing month; the organisation is told in-app, EM2's Tier-2 sentence follows it, and the database's half of
can_view_tier2 opens for a reviewer who meets every other condition."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements.interest import tell_organisation
from bridge.ids import uuid7
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    Tracker,
    clients,
    db_today,
    deals_on,
    open_engagement,
    run_notifications,
)
from tests.integration.engagements.api_world import build as tracker_world
from tests.integration.engagements.test_stage0 import interest, stale_step_up
from tests.integration.matching.scout_world import ScoutWorld, build, publish, rows
from tests.integration.proposals.tier2_scene import accept_nda, accept_terms, new_template

SETTINGS = deals_on()
FRONTEND_APP = Path(__file__).resolve().parents[4] / "frontend" / "app" / "(app)"


async def interested(owner_engine: AsyncEngine, app_engine: AsyncEngine, world: ScoutWorld) -> tuple[UUID, UUID]:
    """The organisation's signatory expressed interest from Browse: (proposal, engagement)."""
    proposal = (await publish(owner_engine, world, "one"))[0]
    today = await db_today(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        created = await signatory.post(
            f"/api/orgs/{world.org.id}/interest", json=interest(world, proposal, None, today)
        )
        assert created.status_code == 201, created.text
    return proposal, UUID(created.json()["id"])


async def grants(owner_engine: AsyncEngine, proposal: UUID) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT id, status::text AS status, source::text AS source, counts_as_unlock, billing_month, granted_by"
        " FROM disclosure_grants WHERE proposal_id = :p",
        p=proposal,
    )


async def tier2_open_for(app_engine: AsyncEngine, user: UUID, org: UUID, proposal: UUID, version: UUID) -> bool:
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=user, org_id=org)
        found = await db.execute(text("SELECT app_tier2_granted(:p, :v, :o)"), {"p": proposal, "v": version, "o": org})
        return bool(found.scalar_one())


async def test_the_developer_shares_tier2_with_an_interested_organisation(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    proposal, engagement = await interested(owner_engine, app_engine, world)
    version = world.proposals["one"][1]
    async with owner_engine.begin() as conn:  # every other condition of can_view_tier2 for the reviewer
        terms = await new_template(conn, "master_enterprise_terms")
        await accept_terms(conn, world.org.id, world.org.signatory, terms)
        nda = await new_template(conn, "evaluation_nda")
        await accept_nda(conn, world.org.reviewer, world.org.id, proposal, nda)
    assert not await tier2_open_for(app_engine, world.org.reviewer, world.org.id, proposal, version)
    url = f"/api/engagements/{engagement}/share-tier2"
    async with clients(app_engine, SETTINGS, world.developer, world.org.signatory) as (dev, signatory):
        before = (await signatory.get(url)).json()
        assert (before["shared"], before["grant_id"]) == (False, None)
        shared = await dev.post(url)
        assert shared.status_code == 200, shared.text
        body = shared.json()
        assert (body["shared"], body["source"], body["counts_as_unlock"]) == (True, "org_interest", True)
        again = await dev.post(url)  # idempotent
        assert again.json()["grant_id"] == body["grant_id"]
        assert (await signatory.get(url)).json() == again.json()
    [grant] = await grants(owner_engine, proposal)
    assert (grant.status, grant.source, grant.counts_as_unlock, grant.granted_by) == (
        "active",
        "org_interest",
        True,
        world.developer,
    )
    assert grant.billing_month is not None
    assert grant.billing_month.day == 1
    assert await tier2_open_for(app_engine, world.org.reviewer, world.org.id, proposal, version)
    events = await rows(
        owner_engine,
        "SELECT action, payload FROM audit_events WHERE action LIKE 'tier2.grant%' AND subject_id = :p",
        p=proposal,
    )
    assert [(e.action, e.payload["source"], e.payload["engagement_id"]) for e in events] == [
        ("tier2.grant_created", "org_interest", str(engagement))
    ]
    notices = await rows(
        owner_engine,
        "SELECT user_id, kind FROM in_app_notifications WHERE kind = 'engagement.tier2_shared' AND org_id = :o",
        o=world.org.id,
    )
    assert sorted(n.user_id for n in notices) == sorted([world.org.signatory, world.org.owner])  # actor + contact
    # EM2 then says the proposal is shared (AC-MAIL-1's tier2_status follows the grants).
    async with clients(app_engine, SETTINGS, world.developer) as (dev,):
        await Tracker(engagement).ok(dev, "accept-interest")
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider, SETTINGS)
    em2 = [m for m in provider.outbox if m.subject.startswith("Good news:")]
    assert len(em2) == 1
    assert "shared with" in em2[0].text


async def test_only_the_developer_with_step_up_shares(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    proposal, engagement = await interested(owner_engine, app_engine, world)
    url = f"/api/engagements/{engagement}/share-tier2"
    async with owner_engine.begin() as conn:
        outsider = uuid7()
        await conn.execute(
            text("INSERT INTO users (id, email, display_name, email_verified_at) VALUES (:id, :e, 'Out', now())"),
            {"id": outsider, "e": f"out-{uuid4().hex[:8]}@example.test"},
        )
    async with clients(app_engine, SETTINGS, world.org.signatory, world.org.owner, outsider, world.developer) as (
        signatory,
        owner,
        stranger,
        dev,
    ):
        for member in (signatory, owner):
            refused = await member.post(url)
            assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "not_your_action")
        assert (await stranger.post(url)).status_code == 404
        assert (await stranger.get(url)).status_code == 404
        await stale_step_up(owner_engine, world.developer)
        stale = await dev.post(url)
        assert (stale.status_code, stale.json()["detail"]["code"]) == (403, "step_up_required")
    assert await grants(owner_engine, proposal) == []


async def test_nothing_is_shared_on_a_tagged_or_ended_engagement(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    proposal, engagement = await interested(owner_engine, app_engine, world)
    async with clients(app_engine, SETTINGS, world.developer) as (dev,):
        await Tracker(engagement).ok(dev, "decline-interest")
        ended = await dev.post(f"/api/engagements/{engagement}/share-tier2")
        assert (ended.status_code, ended.json()["detail"]["code"]) == (409, "engagement_ended")
    assert await grants(owner_engine, proposal) == []
    tagged_world = await tracker_world(owner_engine)
    tagged = await open_engagement(app_engine, tagged_world)
    async with clients(app_engine, SETTINGS, tagged_world.developer) as (dev,):
        refused = await dev.post(f"/api/engagements/{tagged}/share-tier2")
        assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "share_not_applicable")


async def test_an_organisations_request_is_activated_and_keeps_its_source(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    proposal, engagement = await interested(owner_engine, app_engine, world)
    requested = uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source, requested_by)"
                " VALUES (:id, :p, :o, :d, 2, 'requested', 'manual', :r)"
            ),
            {"id": requested, "p": proposal, "o": world.org.id, "d": world.developer, "r": world.org.reviewer},
        )
    async with clients(app_engine, SETTINGS, world.developer) as (dev,):
        shared = (await dev.post(f"/api/engagements/{engagement}/share-tier2")).json()
    assert (shared["grant_id"], shared["source"]) == (str(requested), "manual")
    [grant] = await grants(owner_engine, proposal)
    assert (grant.status, grant.granted_by) == ("active", world.developer)
    assert grant.counts_as_unlock is True  # the same flags as a new grant (P10 security review MINOR b)
    assert grant.billing_month is not None
    assert grant.billing_month.day == 1


async def test_a_share_is_granted_at_the_shared_clocks_time(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Round-2 review MINOR 5 (F17): ``granted_at`` is ``app_clock_now()`` on a new grant and on an activated request
    (P10 review MINOR k), so a moved dev/test clock moves it. The clock runs three days ahead for this test only and
    is then put back exactly as it was (the owner may; the app only moves it forward)."""
    new_world, asked_world = await build(owner_engine), await build(owner_engine)
    new_proposal, new_engagement = await interested(owner_engine, app_engine, new_world)
    asked_proposal, asked_engagement = await interested(owner_engine, app_engine, asked_world)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source, requested_by)"
                " VALUES (:id, :p, :o, :d, 2, 'requested', 'manual', :r)"
            ),
            {
                "id": uuid7(),
                "p": asked_proposal,
                "o": asked_world.org.id,
                "d": asked_world.developer,
                "r": asked_world.org.reviewer,
            },
        )
        enabled, offset = (await conn.execute(text("SELECT enabled, clock_offset FROM test_clock"))).one()
        await conn.execute(
            text("UPDATE test_clock SET enabled = true, clock_offset = :o"), {"o": offset + timedelta(days=3)}
        )
    try:
        async with clients(app_engine, SETTINGS, new_world.developer, asked_world.developer) as (new_dev, asked_dev):
            assert (await new_dev.post(f"/api/engagements/{new_engagement}/share-tier2")).status_code == 200
            assert (await asked_dev.post(f"/api/engagements/{asked_engagement}/share-tier2")).status_code == 200
        ahead = await rows(
            owner_engine,
            "SELECT proposal_id, status::text AS status, granted_at - app_clock_now() AS behind,"
            " granted_at - now() > interval '71 hours' AS ahead FROM disclosure_grants"
            " WHERE proposal_id IN (:n, :a) ORDER BY proposal_id = :a",
            n=new_proposal,
            a=asked_proposal,
        )
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE test_clock SET enabled = :e, clock_offset = :o"), {"e": enabled, "o": offset}
            )
    assert [(g.proposal_id, g.status, g.ahead) for g in ahead] == [
        (new_proposal, "active", True),  # inserted
        (asked_proposal, "active", True),  # activated
    ]
    assert all(timedelta(minutes=-5) < g.behind <= timedelta(0) for g in ahead)


async def test_a_proposal_no_longer_clear_is_not_shared(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    proposal, engagement = await interested(owner_engine, app_engine, world)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE proposals SET moderation_state = 'held' WHERE id = :p"), {"p": proposal})
    async with clients(app_engine, SETTINGS, world.developer) as (dev,):
        refused = await dev.post(f"/api/engagements/{engagement}/share-tier2")
        assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "proposal_unavailable")
    assert await grants(owner_engine, proposal) == []


async def test_the_share_notice_skips_former_members_and_never_raises(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    _, engagement = await interested(owner_engine, app_engine, world)
    async with owner_engine.begin() as conn:  # the named contact left the organisation
        await conn.execute(
            text("UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u"),
            {"o": world.org.id, "u": world.org.owner},
        )
    factory = create_session_factory(app_engine)
    grant = uuid7()
    await tell_organisation(factory, engagement, world.developer, grant)
    told = await rows(
        owner_engine,
        "SELECT user_id FROM in_app_notifications WHERE kind = 'engagement.tier2_shared' AND link = :l",
        l=f"/org/engagements/{engagement}",
    )
    assert [t.user_id for t in told] == [world.org.signatory]
    await tell_organisation(factory, uuid4(), world.developer, grant)  # no such engagement: nothing, no error

    def broken() -> Any:
        raise RuntimeError("no database")

    await tell_organisation(broken, engagement, world.developer, grant)  # type: ignore[arg-type]


async def test_the_share_notice_opens_the_organisations_tracker(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """P10-F open item 2: the in-app notice of a share linked to /engagements/{id}, which is no page of the web app;
    each of the organisation's people told gets the organisation's tracker, /org/engagements/{id}."""
    world = await build(owner_engine)
    _, engagement = await interested(owner_engine, app_engine, world)
    async with clients(app_engine, SETTINGS, world.developer) as (dev,):
        assert (await dev.post(f"/api/engagements/{engagement}/share-tier2")).status_code == 200
    notices = await rows(
        owner_engine,
        "SELECT user_id, link FROM in_app_notifications WHERE kind = 'engagement.tier2_shared' AND org_id = :o",
        o=world.org.id,
    )
    assert sorted((n.user_id, n.link) for n in notices) == sorted(
        (person, f"/org/engagements/{engagement}") for person in (world.org.signatory, world.org.owner)
    )
    assert (FRONTEND_APP / "org" / "engagements" / "[id]" / "page.tsx").is_file()  # the route the link opens
