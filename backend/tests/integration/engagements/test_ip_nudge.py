"""REQ-DEV-04 (P27 track E; docs/spec/06 6.1: "before first Tier-2 release: non-blocking nudge about KIPI
utility-model/patent filing and KECOBO voluntary registration"): the developer's tracker carries ``ip_nudge`` true only
while their next step is ``send_nda``, no organisation has viewed the proposal's Tier 2 and they have not dismissed
it; the organisation's tracker has no such field."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration.engagements.api_world import (
    Seats,
    Tracker,
    World,
    build,
    db_today,
    deals_on,
    open_engagement,
    seats,
    walk_to,
)

SETTINGS = deals_on()


async def at_send_nda(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, s: Seats, world: World, t: Tracker | None = None
) -> Tracker:
    """The engagement (``t``, else the world's, opened) at first contact, the developer's next step being to send the
    mutual NDA."""
    t = t or Tracker(await open_engagement(app_engine, world))
    await walk_to(t, s, world, await db_today(owner_engine), "CONTACT_MADE")
    if "confirm_contact" in (await t.detail(s.dev))["actions"]:
        await t.ok(s.dev, "confirm-contact")
    return t


async def nudged(t: Tracker, client: httpx.AsyncClient) -> Any:
    detail = await t.detail(client)
    assert detail["my_party"] == "developer"
    return detail["ip_nudge"]


async def view(owner_engine: AsyncEngine, world: World) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id,"
                " render_kind, fingerprint_seed) VALUES (:id, :p, :v, :d, :viewer, :o, 'html', '\\x00')"
            ),
            {
                "id": uuid7(),
                "p": world.proposal,
                "v": world.version,
                "d": world.developer,
                "viewer": world.reviewer,
                "o": world.org,
            },
        )


async def test_the_nudge_shows_with_the_send_nda_step_until_a_tier2_view(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    async with seats(app_engine, SETTINGS, world) as s:
        submitted = Tracker(await open_engagement(app_engine, world))
        assert await nudged(submitted, s.dev) is False  # not the send_nda step
        t = await at_send_nda(owner_engine, app_engine, s, world, submitted)
        detail = await t.detail(s.dev)
        assert "send_nda" in detail["actions"]
        assert detail["ip_nudge"] is True
        org_detail = await t.detail(s.owner)
        assert "ip_nudge" not in org_detail
        await view(owner_engine, world)
        assert await nudged(t, s.dev) is False  # the full proposal has been seen: too late to nudge


async def test_the_nudge_goes_once_dismissed(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    async with seats(app_engine, SETTINGS, world) as s:
        t = await at_send_nda(owner_engine, app_engine, s, world)
        assert await nudged(t, s.dev) is True
        assert (await s.dev.post("/api/me/profile/ip-nudge/dismiss")).status_code == 204
        assert await nudged(t, s.dev) is False
        sent = await t.ok(s.dev, "send-nda")
        assert sent["ip_nudge"] is False


async def test_the_nudge_needs_the_deal_steps(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """With the deal steps off (AC-SEC-7's default) the developer has no send_nda step, so no nudge."""
    world = await build(owner_engine)
    async with seats(app_engine, SETTINGS, world) as s:
        t = await at_send_nda(owner_engine, app_engine, s, world)
        engagement: UUID = t.engagement
    off = SETTINGS.model_copy(update={"feature_deals_enabled": False})
    async with seats(app_engine, off, world) as s:
        detail = await Tracker(engagement).detail(s.dev)
        assert "send_nda" not in detail["actions"]
        assert detail["ip_nudge"] is False
