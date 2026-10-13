"""REQ-ENG-06 (AC-TRACK-5; P28 track A, AT-A-1 and AT-A-2): a public entity's procurement route (stage 3b).

- AT-A-1: a public entity's approval enters PROCUREMENT_ROUTE (the contact named, no contact-by date yet), so does the
  developer's acceptance of its interest; a private organisation's approval goes straight to INTEREST_CONFIRMED; the
  database refuses 3b for a private organisation and a public entity's direct move into stage 3. The steps include 3b
  only for a public entity.
- AT-A-2: only the organisation's owner or admin chooses the route (a signatory or reviewer 403, a non-member or another
  organisation 404); ``direct`` without a 20-character justification and a contact-by date beyond the policy's limit
  are 422; the choice enters INTEREST_CONFIRMED, both parties read the route, History shows the decision, the named
  contact reads the developer's details, the developer is told (N05 in-app and by email, and EM2).
- The read side: the deadlines list carries the 3b due date and the Board puts 3b with Contact and NDA.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements.calendar import add_business_days
from bridge.engagements.models import EngagementEvent
from bridge.ids import uuid7
from bridge.models.enums import EngagementActorRole, EngagementState
from bridge.notifications.email import FakeEmailProvider
from tests.integration import world as w
from tests.integration.engagements.api_world import (
    Seats,
    Tracker,
    World,
    build,
    clients,
    db_today,
    deals_on,
    holidays_of,
    open_engagement,
    run,
    run_notifications,
    seats,
)

S = EngagementState
SETTINGS = deals_on()
JUSTIFICATION = "Single-source: the only licensed provider of the county's revenue platform."


def route_path(world: World, engagement: UUID) -> str:
    return f"/api/orgs/{world.org}/engagements/{engagement}/procurement-route"


async def under_review(app_engine: AsyncEngine, world: World, s: Seats) -> Tracker:
    t = Tracker(await open_engagement(app_engine, world))
    await t.ok(s.reviewer, "start-review")
    return t


async def approved(app_engine: AsyncEngine, world: World, s: Seats, **contact: Any) -> dict[str, Any]:
    t = await under_review(app_engine, world, s)
    body = {"contact_user_id": str(world.owner), "contact_channel": "phone", **contact}
    detail = await t.ok(s.signatory, "approve", body)
    detail["_tracker"] = t
    return detail


async def five_bd_ahead(owner_engine: AsyncEngine) -> tuple[Any, Any]:
    today = await db_today(owner_engine)
    return today, add_business_days(today, 5, await holidays_of(owner_engine))


def states(detail: dict[str, Any]) -> list[str]:
    return [step["state"] for step in detail["steps"]]


async def test_a_public_entitys_approval_enters_3b_and_a_private_ones_stage_3(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-A-1, AC-TRACK-5 both ways: Given a public entity and a private organisation, When each signatory approves to
    proceed, Then the public entity's engagement waits in PROCUREMENT_ROUTE (contact named, no contact-by date, due in
    10 business days, the owner's turn) with 3b in its steps for both parties, and the private one is in
    INTEREST_CONFIRMED without 3b in its steps."""
    public = await build(owner_engine, public_entity=True)
    async with seats(app_engine, SETTINGS, public) as s:
        today, _ = await five_bd_ahead(owner_engine)
        detail = await approved(app_engine, public, s, contact_by=str(today))  # a date sent is not used
        t = detail["_tracker"]
        assert detail["state"] == "PROCUREMENT_ROUTE"
        assert (detail["stage_label"], detail["stage_group"]) == ("Procurement route determined", "contact_nda")
        assert detail["contact"] is None  # the contact-by date comes with the route
        assert detail["procurement"] is None
        assert detail["due"]["due_on"] == str(add_business_days(today, 10, await holidays_of(owner_engine)))
        assert detail["whose_turn"] == ["org"]
        assert detail["developer_named"] is False  # the handle until stage 3
        owner = await t.detail(s.owner)
        assert owner["actions"] == ["choose_route", "pause"]
        assert "choose_route" not in detail["actions"]  # the signatory's
        developer = await t.detail(s.dev)
        for seen in (developer, owner):
            assert states(seen)[:4] == ["SUBMITTED", "UNDER_REVIEW", "PROCUREMENT_ROUTE", "INTEREST_CONFIRMED"]
        assert developer["actions"] == ["withdraw", "pause"]
        reveal = await s.owner.get(t.path("/contact"))
        assert (reveal.status_code, reveal.json()["detail"]["code"]) == (403, "contact_not_revealed")
        async with owner_engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT contact_user_id, contact_by FROM engagements WHERE id = :e"), {"e": t.engagement}
                )
            ).one()
        assert (row.contact_user_id, row.contact_by) == (public.owner, None)

    private = await build(owner_engine)
    async with seats(app_engine, SETTINGS, private) as s:
        detail = await approved(app_engine, private, s, contact_by=str(today))
        assert detail["state"] == "INTEREST_CONFIRMED"
        assert "PROCUREMENT_ROUTE" not in states(detail)
        assert states(detail)[:3] == ["SUBMITTED", "UNDER_REVIEW", "INTEREST_CONFIRMED"]
        assert detail["contact"]["contact_by"] == str(today)
        t = detail["_tracker"]
        missing = await t.post(
            s.signatory, "approve", {"contact_user_id": str(private.owner), "contact_channel": "phone"}
        )
        assert missing.status_code == 409  # already approved: the table refuses before anything else


async def test_a_private_approval_without_a_contact_by_date_is_refused(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """A private organisation's approval still names its contact-by date (422 invalid_contact_by without it)."""
    private = await build(owner_engine)
    async with seats(app_engine, SETTINGS, private) as s:
        t = await under_review(app_engine, private, s)
        body = {"contact_user_id": str(private.owner), "contact_channel": "phone"}
        refused = await t.post(s.signatory, "approve", body)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "invalid_contact_by")
        assert (await t.detail(s.dev))["state"] == "UNDER_REVIEW"


async def _append(app_engine: AsyncEngine, world: World, engagement: UUID, to_state: S) -> str | None:
    """As the signatory under RLS, append an approval event to ``to_state`` directly: the SQLSTATE of the refusal."""
    factory = create_session_factory(app_engine)
    async with factory() as db:
        await bind_tenant(db, user_id=world.signatory, org_id=world.org)
        db.add(
            EngagementEvent(
                id=uuid7(),
                engagement_id=engagement,
                actor_user_id=world.signatory,
                actor_role=EngagementActorRole.SIGNATORY,
                command="approve",
                from_state=S.UNDER_REVIEW,
                to_state=to_state,
                payload={},
            )
        )
        try:
            await db.flush()
        except DBAPIError as exc:
            return str(getattr(exc.orig, "sqlstate", ""))
        finally:
            await db.rollback()
    return None


async def test_the_database_refuses_3b_for_a_private_organisation_and_stage_3_for_a_public_entity(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-A-1's backstop (revision 0015): a private organisation never enters PROCUREMENT_ROUTE; a public entity never
    enters INTEREST_CONFIRMED from UNDER_REVIEW (check_violation, whatever the application asks)."""
    for public_entity, refused in ((False, S.PROCUREMENT_ROUTE), (True, S.INTEREST_CONFIRMED)):
        world = await build(owner_engine, public_entity=public_entity)
        async with seats(app_engine, SETTINGS, world) as s:
            t = await under_review(app_engine, world, s)
        assert await _append(app_engine, world, t.engagement, refused) == "23514"


async def test_only_an_owner_or_admin_chooses_the_route_with_a_valid_body(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-A-2: a signatory or reviewer is 403 role_required, the developer, an outsider and another organisation's
    owner 404; direct without a 20-character justification, a contact-by date past the policy's 5 business days or
    in the past, contact details in the justification, an unknown route or field are 422; nothing changes."""
    world = await build(owner_engine, public_entity=True)
    other = await build(owner_engine, public_entity=True)
    async with (
        seats(app_engine, SETTINGS, world) as s,
        clients(app_engine, SETTINGS, world.outsider, other.owner) as (outsider, stranger),
    ):
        today, latest = await five_bd_ahead(owner_engine)
        t = (await approved(app_engine, world, s))["_tracker"]
        good = {"route": "rfq_tender", "justification": None, "contact_by": str(today)}
        for client, status, code in (
            (s.signatory, 403, "role_required"),
            (s.reviewer, 403, "role_required"),
            (s.finance, 403, "role_required"),
            (s.dev, 404, "not_found"),
            (outsider, 404, "not_found"),
        ):
            refused = await client.post(route_path(world, t.engagement), json=good)
            assert (refused.status_code, refused.json()["detail"]["code"]) == (status, code), client
        elsewhere = await stranger.post(
            f"/api/orgs/{other.org}/engagements/{t.engagement}/procurement-route", json=good
        )
        assert elsewhere.status_code == 404  # another organisation's engagement under its own path
        for body, code in (
            ({**good, "route": "direct"}, "justification_required"),
            ({**good, "route": "direct", "justification": "Only one supplier."}, "justification_required"),
            ({**good, "contact_by": str(latest + timedelta(days=1))}, "invalid_contact_by"),
            ({**good, "contact_by": str(today - timedelta(days=1))}, "invalid_contact_by"),
            ({**good, "justification": "Write to procurement@county-c.example first."}, "contains_contact"),
            ({**good, "justification": "x" * 1001}, "invalid_justification"),
        ):
            refused = await s.owner.post(route_path(world, t.engagement), json=body)
            assert (refused.status_code, refused.json()["detail"]["code"]) == (422, code), body
        malformed: list[dict[str, Any]] = [{**good, "route": "barter"}, {**good, "extra": 1}, {"route": "direct"}]
        for wrong in malformed:
            assert (await s.owner.post(route_path(world, t.engagement), json=wrong)).status_code == 422
        stale = await s.owner.post(route_path(world, t.engagement), json={**good, "lock_version": 0})
        assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "stale")
        assert (await t.detail(s.owner))["state"] == "PROCUREMENT_ROUTE"


async def test_the_chosen_route_enters_stage_3_for_both_parties(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-A-2: Given 3b, When the owner chooses direct procurement with its justification and a contact-by date,
    Then the engagement is in INTEREST_CONFIRMED with that date as its deadline, both parties read the route, the
    justification, when and by whom; History shows the decision (the route, never the text); the named contact reads
    the developer's details; a second choice is 409; the developer is told the route (N05) and gets EM2 once."""
    world = await build(owner_engine, public_entity=True)
    async with seats(app_engine, SETTINGS, world) as s:
        _, latest = await five_bd_ahead(owner_engine)
        t = (await approved(app_engine, world, s))["_tracker"]
        body = {"route": "direct", "justification": f"  {JUSTIFICATION}\n", "contact_by": str(latest)}
        chosen = await s.owner.post(route_path(world, t.engagement), json=body)
        assert chosen.status_code == 200, chosen.text
        detail = chosen.json()
        assert (detail["state"], detail["my_party"]) == ("INTEREST_CONFIRMED", "org")
        assert detail["contact"]["contact_by"] == str(latest)
        assert detail["due"]["due_on"] == str(latest)
        procurement = detail["procurement"]
        assert (procurement["route"], procurement["justification"]) == ("direct", JUSTIFICATION)
        owner_name = await _name(owner_engine, world.owner)
        assert procurement["decided_by_name"] == owner_name
        developer = await t.detail(s.dev)
        assert developer["procurement"] == procurement  # R46: both parties read it
        assert states(developer)[2] == "PROCUREMENT_ROUTE"
        history = (await s.dev.get(t.path("/history"))).json()
        assert history["chain_verified"] is True
        decision = history["events"][-1]
        assert (decision["command"], decision["from_state"], decision["to_state"]) == (
            "choose_route",
            "PROCUREMENT_ROUTE",
            "INTEREST_CONFIRMED",
        )
        assert decision["payload"]["procurement_route"] == "direct"
        assert decision["payload"]["contact_by"] == str(latest)
        assert JUSTIFICATION not in str(history)  # the chain holds its digest only
        assert len(decision["payload"]["justification_sha256"]) == 64
        reveal = await s.owner.get(t.path("/contact"))
        assert (reveal.status_code, reveal.json()["email"]) == (200, world.developer_email)
        again = await s.owner.post(route_path(world, t.engagement), json=body)
        assert again.status_code == 409
        async with owner_engine.connect() as conn:
            audited = await run(
                conn,
                "SELECT count(*) FROM audit_events WHERE action = 'engagement.procurement_route_chosen'"
                " AND subject_id = :e AND org_id = :o",
                e=t.engagement,
                o=world.org,
            )
        assert audited == 1
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, t.engagement, provider, SETTINGS)
    async with owner_engine.connect() as conn:
        told = (
            await conn.execute(
                text("SELECT kind, title, body FROM in_app_notifications WHERE user_id = :u ORDER BY created_at"),
                {"u": world.developer},
            )
        ).all()
    route_notice = [row for row in told if row.kind == "engagement.n05"]
    assert len(route_notice) == 1
    assert route_notice[0].title == "Procurement route chosen"
    assert "direct procurement" in route_notice[0].body
    assert [row.kind for row in told].count("engagement.n04") == 1  # the approval into 3b
    to_developer = [m for m in provider.outbox if m.to == world.developer_email]
    assert sorted(m.tag or "" for m in to_developer) == ["em2", "engagement.n05"]  # EM2 once, the route (mutable)
    em2 = next(m for m in to_developer if m.tag == "em2")
    assert "Public bodies may need to run a competitive process" in em2.text
    status = next(m for m in to_developer if m.tag == "engagement.n05")
    assert status.subject == 'Procurement route chosen: "RLS proposal"'
    assert "direct procurement" in status.text
    assert JUSTIFICATION not in status.text  # the organisation's words stay on the tracker


async def _name(owner_engine: AsyncEngine, user: UUID) -> str:
    async with owner_engine.connect() as conn:
        return str(await run(conn, "SELECT display_name FROM users WHERE id = :u", u=user))


async def test_a_public_entitys_accepted_interest_waits_for_its_route(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AT-A-1 (stage 0): the developer's acceptance of a public entity's interest enters PROCUREMENT_ROUTE (due in
    10 business days, not on the interest's contact-by date); its steps skip stages 1-2 and include 3b; the owner's
    choice then enters stage 3."""
    world = await build(owner_engine, public_entity=True)
    async with seats(app_engine, SETTINGS, world) as s:
        today, latest = await five_bd_ahead(owner_engine)
        async with owner_engine.begin() as conn:
            niche = await run(conn, "SELECT niche_id FROM proposal_versions WHERE id = :v", v=world.version)
            problem = await run(
                conn, "SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :v", v=world.version
            )
            proposal, _ = await w.add_proposal(conn, world.developer, niche, problem)
        interest = {
            "proposal_id": str(proposal),
            "origin": "org_browse",
            "match_id": None,
            "contact_user_id": str(world.owner),
            "channel": "video_call",
            "contact_by": str(today),
        }
        created = await s.signatory.post(f"/api/orgs/{world.org}/interest", json=interest)
        assert created.status_code == 201, created.text
        t = Tracker(UUID(created.json()["id"]))
        detail = await t.ok(s.dev, "accept-interest")
        assert detail["state"] == "PROCUREMENT_ROUTE"
        assert states(detail)[:3] == ["ORG_INTEREST", "PROCUREMENT_ROUTE", "INTEREST_CONFIRMED"]
        assert detail["due"]["due_on"] == str(add_business_days(today, 10, await holidays_of(owner_engine)))
        chosen = await s.owner.post(
            route_path(world, t.engagement), json={"route": "pilot_mou", "contact_by": str(latest)}
        )
        assert chosen.status_code == 200, chosen.text
        assert (chosen.json()["state"], chosen.json()["procurement"]["justification"]) == ("INTEREST_CONFIRMED", None)
        assert chosen.json()["contact"]["contact_by"] == str(latest)


async def test_the_deadlines_and_the_board_carry_3b(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """P27's read side: the organisation's deadlines list carries the 3b due date as its own turn; the Board puts the
    engagement in Contact and NDA."""
    world = await build(owner_engine, public_entity=True)
    async with seats(app_engine, SETTINGS, world) as s:
        today, _ = await five_bd_ahead(owner_engine)
        t = (await approved(app_engine, world, s))["_tracker"]
        listed = (await s.owner.get(f"/api/orgs/{world.org}/deadlines")).json()["items"]
        [item] = [d for d in listed if d["engagement_id"] == str(t.engagement)]
        assert item["kind"] == "stage"
        assert item["title"].startswith("Procurement route determined: ")
        assert item["due_on"] == str(add_business_days(today, 10, await holidays_of(owner_engine)))
        assert item["mine"] is True
        mine = (await s.dev.get("/api/me/deadlines")).json()["items"]
        assert [d["mine"] for d in mine if d["engagement_id"] == str(t.engagement)] == [False]
        board = (await s.owner.get(f"/api/orgs/{world.org}/pipeline")).json()
        column = next(c for c in board["columns"] if c["group"] == "contact_nda")
        [card] = [c for c in column["items"] if c["id"] == str(t.engagement)]
        assert (card["state"], card["stalled"]) == ("PROCUREMENT_ROUTE", False)


@pytest.mark.parametrize("client_kind", ["developer", "signatory"])
async def test_the_route_is_not_chosen_through_the_tracker_path(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, client_kind: str
) -> None:
    """The route has one way in, the organisation's path: the tracker's command segments have none."""
    world = await build(owner_engine, public_entity=True)
    async with seats(app_engine, SETTINGS, world) as s:
        t = (await approved(app_engine, world, s))["_tracker"]
        client: httpx.AsyncClient = s.dev if client_kind == "developer" else s.signatory
        missing = await t.post(client, "choose-route", {"route": "rfq_tender"})
        assert missing.status_code in (404, 405)
