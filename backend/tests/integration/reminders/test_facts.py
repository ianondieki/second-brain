"""REQ-REM-01, REQ-REM-02 against PostgreSQL: the facts both reminders read from the tracker's rows, as each recipient.

Whose turn it is per stage (signatures of the stage's document since it began, the developer's confirmation of
first contact, who proposed the latest terms, a recorded final payment), the signed agreement's milestones with their
rework loops and submission dates from the tracker's events, the developer's latest action, their drafts, and the
same facts for the developer and the organisation's member.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days
from bridge.ids import uuid7
from bridge.models.enums import EngagementParty, MilestoneState
from bridge.reminders.facts import developer_facts, engagement_facts, org_facts
from bridge.reminders.health import EngagementFact
from tests.integration import world as base_world
from tests.integration.engagements import tracker
from tests.integration.engagements.tracker import as_app
from tests.integration.reminders.world import World, build

DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
TODAY = date(2027, 3, 30)


async def as_developer(w: World) -> EngagementFact:
    await w.conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
    async with w.factory() as db:
        await bind_tenant(db, user_id=w.p.developer)
        facts = await developer_facts(db, w.p.developer, TODAY, deals_enabled=True)
    (fact,) = facts.engagements
    return fact


async def as_member(w: World, member: UUID) -> EngagementFact:
    await w.conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
    async with w.factory() as db:
        await bind_tenant(db, user_id=member, org_id=w.p.org)
        facts = await org_facts(db, w.p.org, TODAY, "weekly", deals_enabled=True)
    assert facts.org_name == "Tracker Ltd"
    (fact,) = facts.engagements
    return fact


@pytest.mark.parametrize(
    ("until", "awaiting"),
    [
        ("SUBMITTED", {ORG}),
        ("CONTACT_MADE", {DEV}),
        ("NDA_PENDING", {DEV, ORG}),
        ("NEGOTIATION", {ORG}),  # the developer proposed the terms (walk)
        ("AGREEMENT_SIGNING", {DEV, ORG}),
        ("IN_IMPLEMENTATION", {DEV}),
        ("SIGN_OFF", {ORG}),
        ("PAYMENT_FINAL", {ORG}),
    ],
)
async def test_whose_turn_is_read_from_the_stage_evidence(
    owner_engine: AsyncEngine, until: str, awaiting: set[EngagementParty]
) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn, until=until)
        fact = await as_developer(w)
        assert (fact.state.value, fact.awaiting) == (until, frozenset(awaiting))
        assert fact == await as_member(w, w.p.signatory)  # the same facts for both recipients
        # The developer is their pseudonymous handle until INTEREST_CONFIRMED (docs/spec/06 6.1), then named.
        named = until != "SUBMITTED"
        assert (fact.title, fact.org_name, fact.tagged) == ("RLS proposal", "Tracker Ltd", True)
        assert (fact.developer_name == "Developer") is named
        assert fact.developer_name.startswith("dev-") is not named


async def test_the_parties_evidence_moves_the_turn(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn, until="CONTACT_MADE")
        p = w.p
        await tracker.act(conn, p.developer)
        await tracker.run(
            conn,
            tracker.ENDORSE,
            id=uuid7(),
            e=w.engagement,
            stage="CONTACT_MADE",
            milestone=None,
            party="developer",
            user=p.developer,
            role="developer",
            method="click",
        )
        assert (await as_developer(w)).awaiting == frozenset({DEV, ORG})  # confirmed: either sends the NDA
        await tracker.act(conn, p.developer)
        nda = uuid7()  # the NDA sent, named in the event as P5's send_nda names it
        sent = {"document_ref": str(nda), "document_sha256": tracker.PDF_SHA256.hex()}
        await tracker.append(
            conn, w.engagement, p.developer, "developer", "send_nda", "CONTACT_MADE", "NDA_PENDING", payload=sent
        )
        assert (await as_developer(w)).awaiting == frozenset({DEV, ORG})
        await tracker.run(
            conn,
            tracker.SIGN,
            **tracker.sign_params(w.engagement, "mutual_nda", nda, tracker.PDF_SHA256, p.developer, "developer"),
        )
        assert (await as_developer(w)).awaiting == frozenset({ORG})


async def test_a_reopened_negotiation_awaits_new_terms_from_either_party(owner_engine: AsyncEngine) -> None:
    """Whose turn is the state machine's (docs/spec/06 6.9: the only definition): after a reopen the latest version
    is final, not a draft, so either party proposes the next one (``state_machine.pending``)."""
    async with as_app(owner_engine) as conn:
        w = await build(conn, until="AGREEMENT_SIGNING")  # version 1, drafted by the developer, is final
        await tracker.act(conn, w.p.signatory, w.p.org)
        await tracker.append(
            conn, w.engagement, w.p.signatory, "signatory", "reopen_negotiation", "AGREEMENT_SIGNING", "NEGOTIATION"
        )
        fact = await as_developer(w)
        assert (fact.state.value, fact.awaiting) == ("NEGOTIATION", frozenset({DEV, ORG}))


async def test_a_recorded_final_payment_is_the_developers_turn(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn, until="PAYMENT_FINAL")
        await tracker.act(conn, w.p.finance, w.p.org)
        await tracker.run(conn, tracker.RECORD_PAYMENT, **tracker.payment_params(w.engagement, w.p.finance, 100))
        assert (await as_developer(w)).awaiting == frozenset({DEV})


async def test_milestones_carry_rework_loops_and_submission_dates_from_the_events(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn)
        p = w.p
        milestone = await tracker.run(conn, "SELECT id FROM milestones WHERE engagement_id = :e", e=w.engagement)
        await tracker.act(conn, p.reviewer, p.org)
        for _ in range(2):
            await tracker.append(
                conn,
                w.engagement,
                p.reviewer,
                "reviewer",
                sm.Command.REQUEST_CHANGES.value,
                "IN_IMPLEMENTATION",
                "IN_IMPLEMENTATION",
                payload={"milestone_id": str(milestone)},
            )
        await tracker.act(conn, p.developer)
        await tracker.append(
            conn,
            w.engagement,
            p.developer,
            "developer",
            sm.Command.SUBMIT_MILESTONE.value,
            "IN_IMPLEMENTATION",
            "IN_IMPLEMENTATION",
            payload={"milestone_id": str(milestone)},
        )
        for step in ("IN_PROGRESS", "SUBMITTED_FOR_REVIEW"):
            await tracker.run(
                conn, "UPDATE milestones SET state = CAST(:s AS milestone_state) WHERE id = :id", s=step, id=milestone
            )
        fact = await as_developer(w)
        (m,) = fact.milestones
        today = await tracker.run(conn, "SELECT (app_clock_now() AT TIME ZONE 'Africa/Nairobi')::date")
        assert (m.seq, m.deliverable, m.due_on, m.state) == (
            1,
            "Pilot for one county",
            date(2027, 3, 31),
            MilestoneState.SUBMITTED_FOR_REVIEW,
        )
        holidays = frozenset(row[0] for row in await w.owner_rows("SELECT observed_on FROM holidays"))
        assert (m.rework_loops, m.review_due_on) == (2, add_business_days(today, 5, holidays))  # P5's review date
        assert fact.awaiting == frozenset({ORG})
        assert fact.last_developer_update_on == today


async def test_the_developers_drafts_are_listed_newest_first(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        w = await build(conn, until="SUBMITTED")
        niche = await tracker.run(conn, "SELECT niche_id FROM proposals WHERE id = :p", p=w.p.proposal)
        problem = await tracker.run(
            conn, "SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :v", v=w.p.version
        )
        await tracker.as_owner(conn)
        await base_world.add_proposal(conn, w.p.developer, niche, problem, registered=False)
        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        async with w.factory() as db:
            await bind_tenant(db, user_id=w.p.developer)
            facts = await developer_facts(db, w.p.developer, TODAY, deals_enabled=True)
            outsider = await engagement_facts(db, sa.true(), deals_enabled=True)
        assert facts.drafts == ("RLS proposal",)
        assert [e.id for e in outsider] == [w.engagement]  # RLS: only the developer's own engagement is read
