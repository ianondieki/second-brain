"""P5 side branches (REQ-ENG-10 DECLINED and WITHDRAWN; REQ-ENG-05 decline reason codes) and stage 0 for M2's scout
(REQ-ENG-04 prototype part: ORG_INTEREST -> INTEREST_CONFIRMED | DECLINED BY_DEVELOPER).

- A decline carries an organisation reason code; ``ALREADY_IN_PROGRESS_INTERNALLY`` needs the internal start date
  and the attestation, recorded immutably in the chain and shown to the developer; ``OTHER`` needs at least 20
  characters, kept out of the chain (a salted digest there) and delivered to the developer's notification.
- The developer withdraws before the agreement is signed: the engagement ends, the tag is withdrawn and closed, and
  the organisation's people on it are told.
- At stage 0 only the developer answers: accepting records their endorsement of ORG_INTEREST and sends EM2.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    Tracker,
    World,
    build,
    clients,
    db_today,
    deals_on,
    open_engagement,
    run_notifications,
    seats,
    walk_to,
)


async def in_app(owner_engine: AsyncEngine, user: UUID, engagement: UUID, portal: str) -> list[dict[str, Any]]:
    """The user's in-app notices that open the engagement in their own portal (``dev`` or ``org``)."""
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT kind, title, body FROM in_app_notifications WHERE user_id = :u AND link = :l"
                " ORDER BY created_at"
            ),
            {"u": user, "l": f"/{portal}/engagements/{engagement}"},
        )
        return [dict(r._mapping) for r in rows]


async def tag_of(owner_engine: AsyncEngine, world: World) -> tuple[str, bool]:
    async with owner_engine.connect() as conn:
        status, closed = (
            await conn.execute(
                text("SELECT status::text, closed_at IS NOT NULL FROM tags WHERE id = :id"), {"id": world.tag}
            )
        ).one()
        return str(status), bool(closed)


async def test_a_decline_already_in_progress_internally_records_the_attestation(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    today = await db_today(owner_engine)
    started = today - timedelta(days=120)
    async with seats(app_engine, deals_on(), world) as s:
        missing = await t.post(s.reviewer, "decline", {"reason": "ALREADY_IN_PROGRESS_INTERNALLY"})
        assert (missing.status_code, missing.json()["detail"]["code"]) == (422, "attestation_required")
        by_dev = await t.post(s.dev, "decline", {"reason": "BUDGET"})
        assert (by_dev.status_code, by_dev.json()["detail"]["code"]) == (403, "not_your_action")
        reserved = await t.post(s.reviewer, "decline", {"reason": "NO_REVIEW"})
        assert (reserved.status_code, reserved.json()["detail"]["code"]) == (422, "invalid_reason")
        body = {"reason": "ALREADY_IN_PROGRESS_INTERNALLY", "internal_start_date": str(started), "attested": True}
        declined = await t.ok(s.reviewer, "decline", body)
        assert (declined["state"], declined["end_reason"]) == ("DECLINED", "ALREADY_IN_PROGRESS_INTERNALLY")
        assert declined["ended_at"] is not None
        assert declined["whose_turn"] == []
        history = (await s.dev.get(t.path("/history"))).json()
        last = history["events"][-1]
        assert last["payload"] == {
            "internal_start_date": str(started),
            "attested": True,
            "attestation_version": "v1",
        }
        after = await t.post(
            s.signatory,
            "approve",
            {"contact_user_id": str(world.owner), "contact_channel": "email", "contact_by": str(today)},
        )
        assert (after.status_code, after.json()["detail"]["code"]) == (409, "illegal_transition")
    assert await tag_of(owner_engine, world) == ("delivered", True)  # closed with the engagement
    await run_notifications(owner_engine, app_engine, engagement, FakeEmailProvider())
    [notice] = await in_app(owner_engine, world.developer, engagement, "dev")
    assert notice["kind"] == "engagement.n03"
    assert "already solved internally" in notice["body"]
    assert f"since {started}" in notice["body"]


async def test_a_decline_for_another_reason_needs_20_characters_kept_out_of_the_chain(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    reason = "We are merging this unit into the group IT team."
    async with seats(app_engine, deals_on(), world) as s:
        await t.ok(s.reviewer, "start-review")
        short = await t.post(s.signatory, "decline", {"reason": "OTHER", "other_text": "Not now."})
        assert (short.status_code, short.json()["detail"]["code"]) == (422, "reason_text_required")
        stray = await t.post(s.signatory, "decline", {"reason": "BUDGET", "other_text": reason})
        assert (stray.status_code, stray.json()["detail"]["code"]) == (422, "unexpected_reason_text")
        declined = await t.ok(s.signatory, "decline", {"reason": "OTHER", "other_text": reason})
        assert (declined["state"], declined["end_reason"]) == ("DECLINED", "OTHER")
        history = (await s.dev.get(t.path("/history"))).json()
        payload = history["events"][-1]["payload"]
        assert set(payload) == {"reason_text_sha256"}
        assert len(payload["reason_text_sha256"]) == 64
        assert reason not in str(history)
    async with owner_engine.connect() as conn:
        details = (
            await conn.execute(
                text(
                    "SELECT d.details->>'reason_text' FROM audit_events e JOIN event_details d ON d.event_id = e.id"
                    " WHERE e.action = 'engagement.declined' AND e.subject_id = :e"
                ),
                {"e": engagement},
            )
        ).scalar_one()
    assert details == reason
    await run_notifications(owner_engine, app_engine, engagement, FakeEmailProvider())
    started, notice = await in_app(owner_engine, world.developer, engagement, "dev")
    assert "started reviewing" in started["body"]
    assert notice["body"].endswith(f"Their reason: {reason}")


async def test_the_developer_withdraws_before_the_agreement_is_signed(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """REQ-ENG-10: WITHDRAWN from any stage before the agreement is signed; the tag is withdrawn and closed (Tier-2
    access stops with the WITHDRAWN engagement: ``app_tier2_granted``, tested in test_rls.py); not after signing."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "NEGOTIATION")
        assert "withdraw" in (await t.detail(s.dev))["actions"]
        withdrawn = await t.ok(s.dev, "withdraw")
        assert (withdrawn["state"], withdrawn["end_reason"]) == ("WITHDRAWN", None)
        refused = await t.post(s.owner, "mark-final")
        assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "illegal_transition")
    assert await tag_of(owner_engine, world) == ("withdrawn", True)
    await run_notifications(owner_engine, app_engine, engagement, FakeEmailProvider())
    for person in (world.reviewer, world.signatory, world.owner):  # the organisation's people on this engagement
        notices = await in_app(owner_engine, person, engagement, "org")
        assert [n["kind"] for n in notices][-1] == "engagement.withdrawn"
    assert await in_app(owner_engine, world.finance, engagement, "org") == []  # never acted on it

    signed = await build(owner_engine)
    t2 = Tracker(await open_engagement(app_engine, signed))
    async with seats(app_engine, deals_on(), signed) as s:
        await walk_to(t2, s, signed, today, "IN_IMPLEMENTATION")
        late = await t2.post(s.dev, "withdraw")
        assert (late.status_code, late.json()["detail"]["code"]) == (409, "illegal_transition")


async def express_interest(
    owner_engine: AsyncEngine, world: World, contact_by: date, origin: str = "org_browse"
) -> UUID:
    """The organisation's signatory expresses interest (M2's scout path), naming its contact: as bridge_app."""
    engagement = uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await conn.execute(
            text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
            {"u": str(world.signatory), "o": str(world.org)},
        )
        await conn.execute(
            text(
                "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state,"
                " contact_user_id, contact_channel, contact_by) VALUES (:id, :p, :o, :d, :v,"
                " CAST(:origin AS engagement_origin), 'ORG_INTEREST', :c, 'video_call', :by)"
            ),
            {
                "id": engagement,
                "p": world.proposal,
                "o": world.org,
                "d": world.developer,
                "v": world.version,
                "origin": origin,
                "c": world.owner,
                "by": contact_by,
            },
        )
    return engagement


async def test_stage_0_the_developer_accepts_an_organisations_interest(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    engagement = await express_interest(owner_engine, world, today + timedelta(days=2))
    t = Tracker(engagement)
    settings = deals_on()
    async with clients(app_engine, settings, world.developer, world.reviewer, world.signatory) as (dev, reviewer, sig):
        first = await t.detail(dev)
        assert (first["state"], first["origin"], first["whose_turn"]) == ("ORG_INTEREST", "org_browse", ["developer"])
        assert first["actions"] == ["accept_interest", "decline_interest"]
        for org_client in (reviewer, sig):
            refused = await t.post(org_client, "accept-interest")
            assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "not_your_action")
        accepted = await t.ok(dev, "accept-interest")
        assert accepted["state"] == "INTEREST_CONFIRMED"
        assert accepted["contact"]["channel"] == "video_call"
        assert accepted["due"]["due_on"] == str(today + timedelta(days=2))
        history = (await dev.get(t.path("/history"))).json()
        assert history == (await sig.get(t.path("/history"))).json()
        accepted_event = history["events"][-1]
        assert accepted_event["command"] == "accept_interest"
        # The named contact is recorded like an approval's (review P5, MINOR); the developer cannot read the roster,
        # so the role is the one recorded when the interest was expressed, else "member".
        assert {k: v for k, v in accepted_event["payload"].items() if k.startswith("contact")} == {
            "contact_user_id": str(world.owner),
            "contact_role": "member",
            "contact_channel": "video_call",
            "contact_by": str(today + timedelta(days=2)),
        }
        [endorsement] = history["endorsements"]
        assert (endorsement["stage"], endorsement["party"], endorsement["role"], endorsement["method"]) == (
            "ORG_INTEREST",
            "developer",
            "developer",
            "totp",
        )
        assert endorsement["name"] is not None
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider, settings)
    assert [m.to for m in provider.outbox] == [world.developer_email]  # EM2 on entering INTEREST_CONFIRMED
    for person in (world.signatory, world.owner):  # the one who expressed interest, and the named contact
        assert [n["kind"] for n in await in_app(owner_engine, person, engagement, "org")] == ["engagement.n17"]


async def test_stage_0_the_developer_declines_an_organisations_interest(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await express_interest(owner_engine, world, await db_today(owner_engine), "org_agent_match")
    t = Tracker(engagement)
    async with clients(app_engine, deals_on(), world.developer) as (dev,):
        declined = await t.ok(dev, "decline-interest")
        assert (declined["state"], declined["end_reason"], declined["origin"]) == (
            "DECLINED",
            "BY_DEVELOPER",
            "org_agent_match",
        )
    assert await tag_of(owner_engine, world) == ("delivered", False)  # an org-origin engagement has no tag of its own
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider)
    assert provider.outbox == []  # no EM2: the engagement never entered INTEREST_CONFIRMED
    [notice] = await in_app(owner_engine, world.signatory, engagement, "org")
    assert notice["kind"] == "engagement.n17"
