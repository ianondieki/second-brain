"""docs/spec/06 6.1 (REQ-ENG-04, REQ-ENG-02; P10 security review MAJOR 1): the developer is a pseudonymous handle to the
organisation until the engagement reaches INTEREST_CONFIRMED. Before that, every organisation view (the Express
interest answer, a viewer's detail, the organisation's list and the History, a stage-0 decline included) carries the
registered version's handle and no developer user id; afterwards the display name and id. The developer's own view
is always named. The same holds for a pitched engagement at SUBMITTED and UNDER_REVIEW (M1)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.engagements.api_world import (
    Tracker,
    clients,
    db_today,
    deals_on,
    open_engagement,
)
from tests.integration.engagements.api_world import build as tracker_world
from tests.integration.engagements.test_stage0 import interest
from tests.integration.matching.scout_world import build, publish, rows

SETTINGS = deals_on()


async def handle_and_name(owner_engine: AsyncEngine, developer: UUID) -> tuple[str, str]:
    [row] = await rows(
        owner_engine,
        "SELECT p.handle, u.display_name FROM developer_profiles p JOIN users u ON u.id = p.user_id"
        " WHERE p.user_id = :u",
        u=developer,
    )
    return str(row.handle), str(row.display_name)


def assert_pseudonymous(view: dict[str, Any], handle: str) -> None:
    assert (view["developer_id"], view["developer_name"], view["developer_named"]) == (None, handle, False)


def assert_named(view: dict[str, Any], developer: UUID, name: str) -> None:
    assert (view["developer_id"], view["developer_name"], view["developer_named"]) == (str(developer), name, True)


async def org_views(client: httpx.AsyncClient, org: UUID, engagement: UUID) -> list[dict[str, Any]]:
    detail = (await client.get(f"/api/engagements/{engagement}")).json()
    listed = (await client.get(f"/api/orgs/{org}/engagements")).json()["items"]
    return [detail, next(item for item in listed if item["id"] == str(engagement))]


async def test_stage_0_shows_the_handle_until_the_developer_accepts(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    proposal = (await publish(owner_engine, world, "one"))[0]
    handle, name = await handle_and_name(owner_engine, world.developer)
    today = await db_today(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.signatory, world.org.viewer, world.developer) as (
        signatory,
        viewer,
        dev,
    ):
        created = await signatory.post(
            f"/api/orgs/{world.org.id}/interest", json=interest(world, proposal, None, today)
        )
        assert created.status_code == 201
        assert_pseudonymous(created.json(), handle)  # the 201 body of Express interest
        engagement = UUID(created.json()["id"])
        for view in await org_views(viewer, world.org.id, engagement):
            assert_pseudonymous(view, handle)
        assert name not in created.text
        assert str(world.developer) not in created.text
        mine = (await dev.get(f"/api/engagements/{engagement}")).json()
        assert_named(mine, world.developer, name)  # the developer's own view is unchanged
        accepted = await Tracker(engagement).ok(dev, "accept-interest")
        assert accepted["state"] == "INTEREST_CONFIRMED"
        for view in await org_views(viewer, world.org.id, engagement):
            assert_named(view, world.developer, name)
        history = (await viewer.get(f"/api/engagements/{engagement}/history")).json()
        assert history == (await dev.get(f"/api/engagements/{engagement}/history")).json()  # named: one History


async def test_a_stage_0_decline_does_not_name_the_developer_in_history(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    proposal = (await publish(owner_engine, world, "one"))[0]
    handle, name = await handle_and_name(owner_engine, world.developer)
    today = await db_today(owner_engine)
    async with clients(app_engine, SETTINGS, world.org.signatory, world.developer) as (signatory, dev):
        created = await signatory.post(
            f"/api/orgs/{world.org.id}/interest", json=interest(world, proposal, None, today)
        )
        engagement = UUID(created.json()["id"])
        await Tracker(engagement).ok(dev, "decline-interest")
        seen = await signatory.get(f"/api/engagements/{engagement}/history")
        own = (await dev.get(f"/api/engagements/{engagement}/history")).json()
    events = seen.json()["events"]
    [decline] = [e for e in events if e["command"] == "decline_interest"]
    assert (decline["actor_user_id"], decline["actor_name"], decline["actor_role"]) == (None, handle, "developer")
    assert name not in seen.text
    assert str(world.developer) not in seen.text
    [own_decline] = [e for e in own["events"] if e["command"] == "decline_interest"]
    assert (own_decline["actor_user_id"], own_decline["actor_name"]) == (str(world.developer), name)
    assert seen.json()["chain_verified"] is True


async def test_a_pitched_engagement_shows_the_handle_until_approval(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await tracker_world(owner_engine)
    handle, name = await handle_and_name(owner_engine, world.developer)
    engagement = await open_engagement(app_engine, world)
    today = await db_today(owner_engine)
    t = Tracker(engagement)
    async with clients(app_engine, SETTINGS, world.viewer, world.reviewer, world.signatory) as (
        viewer,
        reviewer,
        signatory,
    ):
        for view in await org_views(viewer, world.org, engagement):  # SUBMITTED
            assert_pseudonymous(view, handle)
        history = await viewer.get(t.path("/history"))
        [genesis] = history.json()["events"]
        assert (genesis["actor_user_id"], genesis["actor_name"]) == (None, handle)  # the developer's genesis
        assert name not in history.text
        await t.ok(reviewer, "start-review")
        for view in await org_views(viewer, world.org, engagement):  # UNDER_REVIEW
            assert_pseudonymous(view, handle)
        contact = {"contact_user_id": str(world.owner), "contact_channel": "phone", "contact_by": str(today)}
        await t.ok(signatory, "approve", contact)
        for view in await org_views(viewer, world.org, engagement):  # INTEREST_CONFIRMED
            assert_named(view, world.developer, name)
