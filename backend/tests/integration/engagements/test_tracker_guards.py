"""AC-TRACK-1 through the API (REQ-ENG-01), AC-SEC-7, AC-TRACK-10 and the P5 guards.

Every POST route answered for every person of a SUBMITTED engagement agrees with the state machine (403 for an
unauthorised actor, 409 for a transition not in the table); non-parties get 404; a stale ``lock_version`` is 409;
deal steps are 403 while the deals flag is off; signatures need a fresh second factor (the auth step-up); a developer
below D2 cannot sign an agreement; an assignment is never signed internally; a payment is confirmed only at the
recorded amount; one person never acts for both sides; and ``open_engagement_for_tag`` opens one engagement per tag.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.auth import totp
from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import commands
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days, local_date
from bridge.engagements.commands import OpenRefused, open_engagement_for_tag
from bridge.engagements.models import Engagement
from bridge.engagements.policy import get_policy
from bridge.engagements.service import load
from bridge.ids import uuid7
from bridge.models.enums import EngagementActorRole, EngagementEndReason, EngagementParty, EngagementState
from tests.integration.engagements.api_world import (
    FINAL_AMOUNT,
    Tracker,
    build,
    clients,
    db_today,
    deals_on,
    open_engagement,
    seats,
    simple_terms,
    walk_to,
)
from tests.integration.proposals.helpers import rows

R = EngagementActorRole
MILESTONE = uuid7()  # no engagement of these tests has it
ROUTES: dict[sm.Command, str] = {
    sm.Command.ACCEPT_INTEREST: "accept-interest",
    sm.Command.DECLINE_INTEREST: "decline-interest",
    sm.Command.START_REVIEW: "start-review",
    sm.Command.DECLINE: "decline",
    sm.Command.APPROVE: "approve",
    sm.Command.WITHDRAW: "withdraw",
    sm.Command.MARK_CONTACTED: "mark-contacted",
    sm.Command.CONFIRM_CONTACT: "confirm-contact",
    sm.Command.SEND_NDA: "send-nda",
    sm.Command.SIGN_NDA: "sign-nda",
    sm.Command.PROPOSE_TERMS: "propose-terms",
    sm.Command.MARK_FINAL: "mark-final",
    sm.Command.REOPEN_NEGOTIATION: "reopen-negotiation",
    sm.Command.SIGN_AGREEMENT: "sign-agreement",
    sm.Command.DELIVER: "deliver",
    sm.Command.ACCEPT_DELIVERY: "accept-delivery",
    sm.Command.SIGN_CERTIFICATE: "sign-certificate",
    sm.Command.RECORD_PAYMENT: "record-payment",
    sm.Command.CONFIRM_PAYMENT: "confirm-payment",
    # The milestone sub-tracker's routes name a milestone; outside IN_IMPLEMENTATION they are 409 like any command
    # (never 404 for a milestone the engagement cannot have yet).
    sm.Command.START_MILESTONE: f"milestones/{MILESTONE}/start",
    sm.Command.SUBMIT_MILESTONE: f"milestones/{MILESTONE}/submit",
    sm.Command.ACCEPT_MILESTONE: f"milestones/{MILESTONE}/accept",
    sm.Command.REQUEST_CHANGES: f"milestones/{MILESTONE}/request-changes",
}


def body_for(command: sm.Command, world: Any, today: Any) -> dict[str, Any]:
    if command is sm.Command.DECLINE:
        return {"reason": "BUDGET"}
    if command is sm.Command.APPROVE:
        return {"contact_user_id": str(world.owner), "contact_channel": "email", "contact_by": str(today)}
    if command is sm.Command.PROPOSE_TERMS:
        return simple_terms(today)
    if command is sm.Command.RECORD_PAYMENT:
        return {"amount_kes_minor": 100, "method": "mpesa", "paid_on": str(today)}
    if command is sm.Command.CONFIRM_PAYMENT:
        return {"amount_received_kes_minor": 100}
    return {}


async def test_every_actor_and_command_on_a_submitted_engagement_matches_the_table(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AC-TRACK-1: for each person and each command, 403 when the table does not let them act, 409 when the
    engagement is not in a state the command starts from; the only commands that would pass are not sent."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    today = await db_today(owner_engine)
    t = Tracker(engagement)
    people = {
        "developer": (world.developer, sm.Actor(EngagementParty.DEVELOPER, sm.DEVELOPER)),
        "owner": (world.owner, sm.Actor(EngagementParty.ORG, frozenset({R.OWNER, R.ADMIN}))),
        "signatory": (world.signatory, sm.Actor(EngagementParty.ORG, frozenset({R.SIGNATORY}))),
        "reviewer": (world.reviewer, sm.Actor(EngagementParty.ORG, frozenset({R.REVIEWER}))),
        "finance": (world.finance, sm.Actor(EngagementParty.ORG, frozenset({R.FINANCE}))),
        "viewer": (world.viewer, sm.Actor(EngagementParty.ORG, frozenset())),
    }
    ids = [user for user, _ in people.values()]
    assert set(ROUTES) == set(sm.Command)  # every row of the table is sent
    async with clients(app_engine, deals_on(), *ids) as signed_in:
        lock = (await t.detail(signed_in[0]))["lock_version"]
        for client, (name, (_, actor)) in zip(signed_in, people.items(), strict=True):
            for command, route in ROUTES.items():
                try:
                    sm.decide(command, actor, EngagementState.SUBMITTED, sm.Facts(), reason=EngagementEndReason.BUDGET)
                except sm.TrackerError as error:
                    expected = error.status
                else:
                    continue  # it would run: not sent, the engagement stays SUBMITTED
                response = await t.post(client, route, body_for(command, world, today), lock=lock)
                assert response.status_code == expected, (name, route, response.text)
                code = response.json()["detail"]["code"]
                assert code in {"not_your_action", "role_required", "illegal_transition"}, (name, route, code)
        assert (await t.detail(signed_in[0]))["lock_version"] == lock  # nothing changed


async def test_non_parties_get_404(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    async with clients(app_engine, deals_on(), world.outsider, world.staff) as (outsider, staff):
        for client in (outsider, staff):  # staff admin may read engagements under RLS but is not a party
            for path in ("", "/history", "/contact", "/documents/agreement"):
                assert (await client.get(t.path(path))).status_code == 404
            assert (await t.post(client, "start-review", lock=0)).status_code == 404
        unknown = Tracker(uuid7())
        assert (await outsider.get(unknown.path())).status_code == 404
        assert (await outsider.get(f"/api/orgs/{world.org}/engagements")).status_code == 404


async def test_a_stale_lock_version_is_409(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        seen = (await t.detail(s.signatory))["lock_version"]
        assert (await t.post(s.reviewer, "start-review", lock=seen)).status_code == 200
        contact = {"contact_user_id": str(world.owner), "contact_channel": "email", "contact_by": str(today)}
        stale = await t.post(s.signatory, "approve", contact, lock=seen)
        assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "stale")
        assert (await t.detail(s.dev))["state"] == "UNDER_REVIEW"
        assert (await t.post(s.signatory, "approve", contact)).status_code == 200


async def test_deal_steps_are_403_while_the_deals_flag_is_off(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AC-SEC-7 (FEATURE_DEALS_ENABLED=false, the default): entering NDA_PENDING, any signature, any payment."""
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, get_settings(), world) as s:
        await walk_to(t, s, world, today, "CONTACT_MADE")
        await t.ok(s.dev, "confirm-contact")
        refused = await t.post(s.dev, "send-nda")
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "deals_disabled")
        for command, client in (("sign-nda", s.signatory), ("record-payment", s.finance)):
            body = (
                {"amount_kes_minor": 100, "method": "mpesa", "paid_on": str(today)}
                if command == "record-payment"
                else {}
            )
            assert (await t.post(client, command, body)).status_code == 403
        assert (await t.ok(s.dev, "withdraw"))["state"] == "WITHDRAWN"  # leaving is never gated


async def test_signatures_need_a_fresh_second_factor(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """ADR-002 / AC-TRACK-10: no step-up, no signature (403); after the auth step-up with a TOTP code the same
    signature goes through, recorded with step_up_method totp."""
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    settings = deals_on()
    async with seats(app_engine, settings, world) as s:
        await walk_to(t, s, world, today, "NDA_PENDING")
    async with clients(app_engine, settings, world.developer, mfa_verified=False) as (dev,):
        refused = await t.post(dev, "sign-nda")
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "step_up_required")
        code = totp.code_at(world.totp_secret, int(time.time() // totp.PERIOD))
        assert (await dev.post("/api/auth/step-up", json={"code": code})).status_code == 200
        signed = await t.ok(dev, "sign-nda")
        assert [(x["party"], x["step_up_method"]) for x in signed["signatures"]] == [("developer", "totp")]
        assert [(e["party"], e["method"]) for e in signed["endorsements"]] == [("developer", "totp")]


async def test_only_a_d2_developer_signs_an_agreement(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine, d2=False)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "AGREEMENT_SIGNING")
        refused = await t.post(s.dev, "sign-agreement")
        assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "d2_required")
        assert (await t.ok(s.signatory, "sign-agreement"))["state"] == "AGREEMENT_SIGNING"


@pytest.mark.parametrize("ip_terms", ["assignment", "exclusive_licence"])
async def test_an_assignment_or_exclusive_licence_is_not_signed_internally(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, ip_terms: str
) -> None:
    """AC-TRACK-10: 409 with the "sign outside the platform" message; the parties can reopen the terms."""
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "NDA_SIGNED")
        await t.ok(s.dev, "propose-terms", simple_terms(today, ip_terms))
        refused_mark = await t.post(s.dev, "mark-final")
        assert (refused_mark.status_code, refused_mark.json()["detail"]["code"]) == (403, "counterparty_marks_final")
        assert (await t.ok(s.owner, "mark-final"))["state"] == "AGREEMENT_SIGNING"
        for client in (s.signatory, s.dev):
            refused = await t.post(client, "sign-agreement")
            assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "sign_outside_platform")
            assert "outside the platform" in refused.json()["detail"]["message"]
        assert (await t.ok(s.owner, "reopen-negotiation"))["state"] == "NEGOTIATION"
        again = await t.ok(s.dev, "propose-terms", simple_terms(today))
        assert [a["version"] for a in again["agreements"]] == [2, 1]
        await t.ok(s.owner, "mark-final")
        await t.ok(s.signatory, "sign-agreement")
        assert (await t.ok(s.dev, "sign-agreement"))["state"] == "IN_IMPLEMENTATION"


async def test_a_payment_is_confirmed_only_at_the_recorded_amount(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The dispute of AC-TRACK-7 comes after the prototype: a different amount is refused (409) and nothing is
    confirmed; no code path moves money."""
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "PAYMENT_FINAL")
        early = await t.post(s.dev, "confirm-payment", {"amount_received_kes_minor": FINAL_AMOUNT})
        assert (early.status_code, early.json()["detail"]["code"]) == (409, "no_payment_recorded")
        future = {"amount_kes_minor": FINAL_AMOUNT, "method": "mpesa", "paid_on": "2999-01-01"}
        assert (await t.post(s.finance, "record-payment", future)).status_code == 422
        await t.ok(
            s.finance, "record-payment", {"amount_kes_minor": FINAL_AMOUNT, "method": "mpesa", "paid_on": str(today)}
        )
        twice = await t.post(
            s.finance, "record-payment", {"amount_kes_minor": 1, "method": "other", "paid_on": str(today)}
        )
        assert (twice.status_code, twice.json()["detail"]["code"]) == (409, "payment_recorded")
        short = await t.post(s.dev, "confirm-payment", {"amount_received_kes_minor": FINAL_AMOUNT - 100})
        assert (short.status_code, short.json()["detail"]["code"]) == (409, "payment_amount_mismatch")
        detail = await t.detail(s.dev)
        assert detail["state"] == "PAYMENT_FINAL"
        assert detail["payments"][0]["confirmed_at"] is None
        assert (await t.ok(s.dev, "confirm-payment", {"amount_received_kes_minor": FINAL_AMOUNT}))["state"] == "CLOSED"
        after = await t.post(s.dev, "withdraw")
        assert (after.status_code, after.json()["detail"]["code"]) == (409, "illegal_transition")


async def test_one_person_never_acts_for_both_sides(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    async with owner_engine.begin() as conn:  # a membership granted after the engagement exists
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :o, :u, '{reviewer}')"),
            {"id": uuid7(), "o": world.org, "u": world.developer},
        )
    async with clients(app_engine, deals_on(), world.developer) as (dev,):
        response = await dev.get(t.path())
        assert (response.status_code, response.json()["detail"]["code"]) == (403, "both_parties")
        assert (await t.post(dev, "start-review", lock=0)).status_code == 403


async def test_open_engagement_for_tag_opens_one_engagement_per_delivered_tag(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """P4's entry point: the SUBMITTED engagement with its genesis event and the policy deadline; refusals."""
    world = await build(owner_engine)
    engagement_id = await open_engagement(app_engine, world)
    factory = create_session_factory(app_engine)
    async with factory() as db:
        await bind_tenant(db, user_id=world.developer)
        engagement = await db.get(Engagement, engagement_id)
        assert engagement is not None
        assert (engagement.state, engagement.version_id) == (EngagementState.SUBMITTED, world.version)
        loaded = await load(db, engagement, deals_enabled=True, developer_caller=True)
        assert loaded.stage_round == 1
        with pytest.raises(OpenRefused) as twice:
            await open_engagement_for_tag(db, world.tag)
        assert twice.value.code == "engagement_exists"
        with pytest.raises(OpenRefused) as missing:
            await open_engagement_for_tag(db, uuid7())
        assert missing.value.code == "tag_not_found"
    async with factory() as db:
        await bind_tenant(db, user_id=world.outsider)
        with pytest.raises(OpenRefused) as not_theirs:
            await open_engagement_for_tag(db, world.tag)
        assert not_theirs.value.code == "tag_not_found"
    held = await build(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE tags SET status = 'withdrawn' WHERE id = :id"), {"id": held.tag})
    async with factory() as db:
        await bind_tenant(db, user_id=held.developer)
        with pytest.raises(OpenRefused) as withdrawn:
            await open_engagement_for_tag(db, held.tag)
        assert withdrawn.value.code == "tag_not_delivered"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("UPDATE proposals SET moderation_state = 'held' WHERE id = :proposal", "proposal_not_published"),
        ("UPDATE proposals SET status = 'hidden', hidden_at = now() WHERE id = :proposal", "proposal_not_published"),
        ("UPDATE organizations SET suspended_at = now() WHERE id = :org", "org_unavailable"),
        ("UPDATE organizations SET delisted_at = now() WHERE id = :org", "org_unavailable"),
        ("UPDATE organizations SET verification = 'e1' WHERE id = :org", "org_unavailable"),
        (
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (gen_random_uuid(), :org, :developer,"
            " '{reviewer}')",
            "own_organisation",
        ),
    ],
)
async def test_open_engagement_for_tag_refuses_with_a_code(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, change: str, code: str
) -> None:
    """Review P5, MAJOR 2: every refusal is an ``OpenRefused`` with a code (never a raw database error, a 500 through
    P4), and the caller's transaction stays usable."""
    world = await build(owner_engine)
    async with owner_engine.begin() as conn:
        await conn.execute(text(change), {"proposal": world.proposal, "org": world.org, "developer": world.developer})
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=world.developer)
        with pytest.raises(OpenRefused) as refused:
            await open_engagement_for_tag(db, world.tag)
        assert refused.value.code == code
        assert (await db.execute(text("SELECT 1"))).scalar_one() == 1  # still usable


async def test_open_engagement_for_tag_maps_the_databases_refusals(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The database's backstop behind the application's checks: a concurrent duplicate (23505, the unique index) is
    ``engagement_exists``; an insert the policy refuses (42501) is ``refused``."""
    world = await build(owner_engine)
    await open_engagement(app_engine, world)

    async def none(*_: object) -> None:
        return None

    monkeypatch.setattr(commands, "_existing_engagement", none)  # the other request committed after our check
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=world.developer)
        with pytest.raises(OpenRefused) as duplicate:
            await open_engagement_for_tag(db, world.tag)
        assert duplicate.value.code == "engagement_exists"
        assert (await db.execute(text("SELECT 1"))).scalar_one() == 1

    suspended = await build(owner_engine)
    monkeypatch.setattr(commands, "_organisation_refusal", none)  # a check that let an unavailable org through
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE organizations SET suspended_at = now() WHERE id = :o"), {"o": suspended.org})
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=suspended.developer)
        with pytest.raises(OpenRefused) as policy:
            await open_engagement_for_tag(db, suspended.tag)
        assert policy.value.code == "refused"


@pytest.mark.parametrize(
    ("command", "field", "value"),
    [
        ("propose-terms", "deliverable", "Pilot\nM2: forged | KES 0.01"),
        ("propose-terms", "exclusivity", "none\rIP terms: assignment"),
        ("record-payment", "reference", "QK12AB\x1b[2K"),
        ("propose-terms", "deliverable", "Pilot\x7f"),
    ],
)
async def test_control_characters_are_refused_in_a_partys_text(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, command: str, field: str, value: str
) -> None:
    """Security review P5, MINOR 1: C0 controls and DEL (line breaks included) are 422 in the deliverables, the
    exclusivity clause and the payment reference, so none can forge a line of a signed text or a record."""
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        body = simple_terms(today)
        if field == "deliverable":
            body["milestones"][0]["deliverable"] = value
        elif field == "exclusivity":
            body["exclusivity"] = value
        else:
            body = {"amount_kes_minor": 100, "method": "mpesa", "paid_on": str(today), "reference": value}
        client = s.finance if command == "record-payment" else s.owner
        refused = await t.post(client, command, body)
        assert refused.status_code == 422, refused.text


async def test_invalid_inputs_are_422(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Review P5 (MINOR): a contact-by date beyond 5 business days, a contact who is not an active member, and a
    milestone due before today are refused with their codes, and nothing changes."""
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        await t.ok(s.reviewer, "start-review")
        too_late = {
            "contact_user_id": str(world.owner),
            "contact_channel": "email",
            "contact_by": str(today + timedelta(days=30)),
        }
        refused = await t.post(s.signatory, "approve", too_late)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "invalid_contact_by")
        outsider = {"contact_user_id": str(world.outsider), "contact_channel": "email", "contact_by": str(today)}
        refused = await t.post(s.signatory, "approve", outsider)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "invalid_contact")
        assert (await t.detail(s.dev))["state"] == "UNDER_REVIEW"
        await walk_to(t, s, world, today, "NDA_SIGNED")
        past = simple_terms(today)
        past["milestones"][0]["due_date"] = str(today - timedelta(days=1))
        refused = await t.post(s.owner, "propose-terms", past)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "invalid_terms")
        assert (await t.detail(s.dev))["agreements"] == []


async def test_a_new_terms_version_renews_the_stage_deadline(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Review P5 (MINOR): a second version in NEGOTIATION is a same-state event that sets a new deadline (each response
    within 7 business days); a same-state event without renewal (a confirmation) sets none."""
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "NEGOTIATION")
        await t.ok(s.dev, "propose-terms", simple_terms(today))
        history = (await s.dev.get(t.path("/history"))).json()
    proposals = [e for e in history["events"] if e["command"] == "propose_terms"]
    assert [(e["from_state"], e["to_state"]) for e in proposals] == [
        ("NDA_SIGNED", "NEGOTIATION"),
        ("NEGOTIATION", "NEGOTIATION"),
    ]
    assert all(e["stage_deadline_at"] is not None for e in proposals)
    [confirmation] = [e for e in history["events"] if e["command"] == "confirm_contact"]
    assert confirmation["stage_deadline_at"] is None


async def test_milestones_take_the_policys_review_window_and_show_their_review_due_date(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review P5 (MINOR): a milestone without a review window gets policy.yaml's default; a submitted milestone shows
    the business day its review is due (the submission's Nairobi date plus the window)."""
    policy = replace(get_policy(), review_window_bd_default=7)
    monkeypatch.setattr(commands, "get_policy", lambda: policy)
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "NDA_SIGNED")
        terms = simple_terms(today)
        terms["milestones"].append(
            {
                "deliverable": "Second",
                "amount_kes_minor": 100,
                "due_date": str(today + timedelta(days=60)),
                "review_window_bd": 3,
            }
        )
        drafted = await t.ok(s.owner, "propose-terms", terms)
        assert [m["review_window_bd"] for m in drafted["agreements"][0]["milestones"]] == [7, 3]
        await t.ok(s.dev, "mark-final")
        await t.ok(s.signatory, "sign-agreement")
        signed = await t.ok(s.dev, "sign-agreement")
        first, second = (m["id"] for m in signed["agreements"][0]["milestones"])
        await t.ok(s.dev, f"milestones/{first}/start")
        submitted = await t.ok(s.dev, f"milestones/{first}/submit")
        history = (await s.dev.get(t.path("/history"))).json()
    [submit] = [e for e in history["events"] if e["command"] == "submit_milestone"]
    submitted_on = local_date(datetime.fromisoformat(submit["created_at"]))
    holidays = {
        r.observed_on
        for r in await rows(owner_engine, "SELECT observed_on FROM holidays WHERE observed_on >= :d", d=submitted_on)
    }
    by_id = {m["id"]: m for m in submitted["agreements"][0]["milestones"]}
    assert by_id[first]["review_due_on"] == str(add_business_days(submitted_on, 7, holidays))
    assert by_id[second]["review_due_on"] is None
