"""P5 main path through the API with two parties (REQ-ENG-01..REQ-ENG-03, REQ-ENG-05, REQ-ENG-07..REQ-ENG-09;
AC-TRACK-3 parity, AC-TRACK-10 signatures, X3-1 path to CLOSED).

SUBMITTED -> UNDER_REVIEW -> INTEREST_CONFIRMED -> CONTACT_MADE -> NDA_PENDING -> NDA_SIGNED -> NEGOTIATION ->
AGREEMENT_SIGNING -> IN_IMPLEMENTATION (two milestones, one sent back for changes) -> DELIVERED -> SIGN_OFF ->
PAYMENT_FINAL -> CLOSED, each step by the party and role the state machine names, each dual-endorsement stage
endorsed by both, every signature behind a fresh step-up; both parties then read the identical History.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import (
    Tracker,
    build,
    clients,
    db_today,
    deals_on,
    open_engagement,
    run_notifications,
)

MILESTONE_1 = 15_000_000  # KES 150,000.00
MILESTONE_2 = 10_000_000  # KES 100,000.00


def terms(today: date) -> dict[str, Any]:
    return {
        "ip_terms": "non_exclusive_licence",
        "deemed_acceptance_days": 10,
        "milestones": [
            {
                "deliverable": "Pilot in one county",
                "amount_kes_minor": MILESTONE_1,
                "due_date": str(today + timedelta(days=60)),
            },
            {
                "deliverable": "Roll-out and handover",
                "amount_kes_minor": MILESTONE_2,
                "due_date": str(today + timedelta(days=120)),
                "review_window_bd": 10,
            },
        ],
    }


async def test_the_main_path_runs_submitted_to_closed_with_both_parties(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    settings = deals_on()
    today = await db_today(owner_engine)
    t = Tracker(engagement)
    async with clients(
        app_engine, settings, world.developer, world.owner, world.signatory, world.reviewer, world.finance
    ) as (dev, owner, signatory, reviewer, finance):
        first = await t.detail(dev)
        assert (first["state"], first["origin"], first["whose_turn"]) == ("SUBMITTED", "tagged", ["org"])
        assert first["actions"] == ["withdraw"]
        assert first["stage_deadline_at"] is not None
        assert first["due"]["business_days_left"] == 10
        assert (await t.detail(reviewer))["actions"] == ["start_review", "decline"]

        assert (await t.ok(reviewer, "start-review"))["state"] == "UNDER_REVIEW"
        approve = {"contact_user_id": str(world.owner), "contact_channel": "email", "contact_by": str(today)}
        approved = await t.ok(signatory, "approve", approve)
        assert approved["state"] == "INTEREST_CONFIRMED"
        assert approved["contact"]["user_id"] == str(world.owner)
        assert approved["contact"]["role"] == "owner"
        assert approved["due"]["due_on"] == str(today)

        contacted = await t.ok(owner, "mark-contacted")
        assert contacted["state"] == "CONTACT_MADE"
        assert [(e["party"], e["method"]) for e in contacted["endorsements"]] == [("org", "totp")]
        assert contacted["whose_turn"] == ["developer"]
        confirmed = await t.ok(dev, "confirm-contact")
        assert confirmed["state"] == "CONTACT_MADE"
        assert {e["party"] for e in confirmed["endorsements"]} == {"developer", "org"}
        assert confirmed["whose_turn"] == ["developer", "org"]

        sent = await t.ok(dev, "send-nda")
        assert sent["state"] == "NDA_PENDING"
        assert [d["kind"] for d in sent["documents"]] == ["mutual_nda"]
        assert (await t.ok(dev, "sign-nda"))["whose_turn"] == ["org"]
        assert (await t.ok(signatory, "sign-nda"))["state"] == "NDA_SIGNED"

        drafted = await t.ok(owner, "propose-terms", terms(today))
        assert drafted["state"] == "NEGOTIATION"
        assert drafted["agreements"][0]["status"] == "draft"
        assert drafted["whose_turn"] == ["developer"]  # the party who did not upload the latest version
        final = await t.ok(dev, "mark-final")
        assert final["state"] == "AGREEMENT_SIGNING"
        agreement = final["agreements"][0]
        assert (agreement["status"], agreement["ip_terms"], agreement["deemed_acceptance_days"]) == (
            "final",
            "non_exclusive_licence",
            10,
        )
        assert [m["amount_kes_minor"] for m in agreement["milestones"]] == [MILESTONE_1, MILESTONE_2]
        # AC-TRACK-10: the terms show identically to both parties.
        assert (await t.detail(owner))["agreements"] == final["agreements"]
        assert (await t.ok(signatory, "sign-agreement"))["state"] == "AGREEMENT_SIGNING"
        signed = await t.ok(dev, "sign-agreement")
        assert signed["state"] == "IN_IMPLEMENTATION"
        assert signed["agreements"][0]["status"] == "signed"

        m1, m2 = (UUID(m["id"]) for m in signed["agreements"][0]["milestones"])
        for step, client in (("start", dev), ("submit", dev), ("accept", reviewer)):
            await t.ok(client, f"milestones/{m1}/{step}")
        for step, client in (
            ("start", dev),
            ("submit", dev),
            ("request-changes", reviewer),
            ("start", dev),
            ("submit", dev),
            ("accept", reviewer),
        ):
            detail = await t.ok(client, f"milestones/{m2}/{step}")
        assert [m["state"] for m in detail["agreements"][0]["milestones"]] == ["ACCEPTED", "ACCEPTED"]
        assert detail["actions"] == []  # the reviewer: delivering is the developer's
        assert (await t.detail(dev))["actions"] == ["deliver"]

        assert (await t.ok(dev, "deliver"))["state"] == "DELIVERED"
        sign_off = await t.ok(reviewer, "accept-delivery")
        assert sign_off["state"] == "SIGN_OFF"
        assert [d["kind"] for d in sign_off["documents"]] == ["acceptance_certificate"]
        early = await t.post(dev, "sign-certificate")
        assert (early.status_code, early.json()["detail"]["code"]) == (409, "awaiting_enterprise_signature")
        await t.ok(signatory, "sign-certificate")
        assert (await t.ok(dev, "sign-certificate"))["state"] == "PAYMENT_FINAL"

        amount = MILESTONE_1 + MILESTONE_2
        payment = {"amount_kes_minor": amount, "method": "mpesa", "reference": "QK12AB34CD", "paid_on": str(today)}
        recorded = await t.ok(finance, "record-payment", payment)
        assert recorded["whose_turn"] == ["developer"]
        closed = await t.ok(dev, "confirm-payment", {"amount_received_kes_minor": amount})
        assert closed["state"] == "CLOSED"
        assert closed["ended_at"] is not None
        assert closed["payments"][0]["confirmed_amount_kes_minor"] == amount
        assert {(s["document_kind"], s["party"], s["step_up_method"]) for s in closed["signatures"]} == {
            (kind, party, "totp")
            for kind in ("mutual_nda", "agreement", "acceptance_certificate")
            for party in ("developer", "org")
        }

        # AC-TRACK-3: both parties read the identical History, and the chain verifies.
        histories = [(await c.get(t.path("/history"))).json() for c in (dev, owner, signatory, finance)]
        assert all(h == histories[0] for h in histories)
        history = histories[0]
        assert history["chain_verified"] is True
        states = [e["to_state"] for e in history["events"]]
        assert states[0] == "SUBMITTED"
        assert states[-1] == "CLOSED"
        assert [e["seq"] for e in history["events"]] == list(range(1, len(states) + 1))
        endorsed = {(e["stage"], e["party"]) for e in history["endorsements"] if e["milestone_id"] is None}
        for stage in ("CONTACT_MADE", "NDA_PENDING", "AGREEMENT_SIGNING", "SIGN_OFF", "PAYMENT_FINAL"):
            assert {(stage, "developer"), (stage, "org")} <= endorsed, stage
        per_milestone = {(e["milestone_id"], e["party"]) for e in history["endorsements"] if e["milestone_id"]}
        assert per_milestone == {(str(m), p) for m in (m1, m2) for p in ("developer", "org")}
        # Every endorsement is named by an event of the chain.
        named = {e["payload"].get("endorsement_id") for e in history["events"]}
        assert {e["id"] for e in history["endorsements"]} <= named

        for kind in ("mutual_nda", "agreement", "acceptance_certificate"):
            doc = (await dev.get(t.path(f"/documents/{kind}"))).json()
            assert doc["intact"] is True, kind
            assert doc["text"].startswith("bridge-document/1\n")

        mine = (await dev.get("/api/me/engagements")).json()["items"]
        assert [(i["id"], i["state"]) for i in mine] == [(str(engagement), "CLOSED")]
        theirs = (await owner.get(f"/api/orgs/{world.org}/engagements")).json()["items"]
        assert [(i["id"], i["whose_turn"]) for i in theirs] == [(str(engagement), [])]

    async with owner_engine.connect() as conn:
        closed_at = (await conn.execute(text("SELECT closed_at FROM tags WHERE id = :id"), {"id": world.tag})).scalar()
        signed_events = (
            await conn.execute(
                text("SELECT count(*) FROM audit_events WHERE action = 'doc.signed' AND subject_id = :e"),
                {"e": engagement},
            )
        ).scalar_one()
    assert closed_at is not None  # the tag closes with the engagement
    assert signed_events == 6

    provider = FakeEmailProvider()
    assert await run_notifications(owner_engine, app_engine, engagement, provider, settings) > 10
    assert [m.to for m in provider.outbox] == [world.developer_email]  # EM2, once
