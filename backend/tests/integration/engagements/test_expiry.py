"""AC-PROP-3, REQ-ENG-10 (part), REQ-ENG-05 (expiry): the tracker's clock job on the shared dev/test clock.

- An engagement left in ORG_INTEREST, SUBMITTED, UNDER_REVIEW or INTEREST_CONFIRMED expires once the end of the
  ``expire_bd``-th business day after it entered the stage has passed (5, 20, 30 and 10 BD; stage 3 whatever contact-by
  date was named): the system's EXPIRED event with the stage's reason, the tag closed, no second event on a later run.
- A request for information pauses that count: asked at +15 BD, a submitted engagement has not expired at +25 BD, and
  once answered it expires the business days it waited later.
- A hold resumes on its resume date by the system, back to the stage it left with the deadline moved by the hold.

The job runs over this test's developer only (``user_ids``): other tests' engagements live in the same database.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import create_session_factory
from bridge.engagements import expiry
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days, business_days_between, local_date
from bridge.engagements.expiry import Outcome, Report, run_expiry
from bridge.models.enums import EngagementState
from tests.integration import world as w
from tests.integration.engagements.api_world import (
    Seats,
    Tracker,
    World,
    build,
    business_days_later,
    db_today,
    deals_on,
    holidays_of,
    moved_clock,
    open_engagement,
    run,
    seats,
    walk_to,
)

S = EngagementState


async def tick(app_engine: AsyncEngine, world: World, now: datetime | None = None) -> Report:
    """One run of the job over the world's developer (on the shared clock unless ``now`` is given)."""
    return await run_expiry(create_session_factory(app_engine), now=now, user_ids=[world.developer])


async def interest(owner_engine: AsyncEngine, world: World, s: Seats) -> UUID:
    """Stage 0: the signatory's interest in another of the developer's proposals, from the Browse repo."""
    async with owner_engine.begin() as conn:
        niche = await run(conn, "SELECT niche_id FROM proposal_versions WHERE id = :v", v=world.version)
        problem = await run(
            conn, "SELECT problem_id FROM proposal_problems WHERE proposal_version_id = :v", v=world.version
        )
        proposal, _ = await w.add_proposal(conn, world.developer, niche, problem)
    today = await db_today(owner_engine)
    body = {
        "proposal_id": str(proposal),
        "origin": "org_browse",
        "match_id": None,
        "contact_user_id": str(world.owner),
        "channel": "video_call",
        "contact_by": str(today + timedelta(days=1)),
    }
    created = await s.signatory.post(f"/api/orgs/{world.org}/interest", json=body)
    assert created.status_code == 201, created.text
    return UUID(created.json()["id"])


async def reach(owner_engine: AsyncEngine, app_engine: AsyncEngine, world: World, s: Seats, state: S) -> Tracker:
    if state is S.ORG_INTEREST:
        return Tracker(await interest(owner_engine, world, s))
    t = Tracker(await open_engagement(app_engine, world))
    if state is not S.SUBMITTED:
        await walk_to(t, s, world, await db_today(owner_engine), state.value)
    return t


async def tag_closed(owner_engine: AsyncEngine, world: World) -> tuple[str, bool]:
    async with owner_engine.connect() as conn:
        status, closed = (
            await conn.execute(
                text("SELECT status::text, closed_at IS NOT NULL FROM tags WHERE id = :id"), {"id": world.tag}
            )
        ).one()
        return str(status), bool(closed)


def system_events(history: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in history["events"] if e["actor_role"] == "system"]


@pytest.mark.parametrize(
    ("state", "reason", "expire_bd"),
    [
        (S.SUBMITTED, "NO_REVIEW", 20),
        (S.UNDER_REVIEW, "NO_DECISION", 30),
        (S.INTEREST_CONFIRMED, "CONTACT_NOT_MADE", 10),
        (S.ORG_INTEREST, "NO_DEV_RESPONSE", 5),
    ],
)
async def test_an_engagement_nobody_moves_expires_once(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, state: S, reason: str, expire_bd: int
) -> None:
    """AC-PROP-3: Given the stage and the clock past its expire_bd, When the job runs, Then EXPIRED with the reason,
    the tag closed, and a second run writes nothing."""
    world = await build(owner_engine)
    off = await holidays_of(owner_engine)
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        t = await reach(owner_engine, app_engine, world, s, state)
        before = await t.detail(s.dev)
        assert before["state"] == state.value
        entered_on = local_date(datetime.fromisoformat(before["stage_entered_at"]))
        last = add_business_days(entered_on, expire_bd, off)
        assert (await tick(app_engine, world, now=sm.end_of_day(last))).outcomes == ()  # not before its day ends
        await advance((last - await db_today(owner_engine)).days + 1)
        report = await tick(app_engine, world)
        assert report.of(t.engagement) == Outcome(t.engagement, "expire", S.EXPIRED)
        assert (await tick(app_engine, world)).outcomes == ()  # idempotent: nothing is due any more
        ended = await t.detail(s.dev)
        history = (await s.owner.get(t.path("/history"))).json()
    assert (ended["state"], ended["end_reason"], ended["stage_label"]) == ("EXPIRED", reason, "Expired")
    assert ended["ended_at"] is not None
    assert (ended["due"], ended["actions"], ended["whose_turn"]) == (None, [], [])
    [expired] = system_events(history)
    assert (expired["command"], expired["from_state"], expired["to_state"]) == ("expire", state.value, "EXPIRED")
    assert (expired["actor_user_id"], expired["end_reason"], expired["payload"]) == (None, reason, {})
    assert history["chain_verified"] is True
    if state is not S.ORG_INTEREST:  # a tagged engagement's tag closes with it (an organisation's interest has none)
        assert (await tag_closed(owner_engine, world))[1] is True


async def test_a_question_at_15_business_days_stops_the_expiry_at_25(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """AC-PROP-3 "Request info pauses the clock": asked at +15 BD, a submitted engagement is still waiting at +25 BD;
    answered then, it expires 20 BD after it was submitted plus the business days it waited."""
    world = await build(owner_engine)
    off = await holidays_of(owner_engine)
    entered_on = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        t = Tracker(await open_engagement(app_engine, world))
        submitted = await t.detail(s.dev)
        await business_days_later(owner_engine, advance, 15)
        await t.ok(s.reviewer, "request-info", {"question": "Which depots does the pilot cover?"})
        await advance((add_business_days(entered_on, 25, off) - await db_today(owner_engine)).days + 1)
        assert (await tick(app_engine, world)).outcomes == ()
        assert (await t.detail(s.dev))["state"] == "INFO_REQUESTED"
        answered = await t.ok(s.dev, "answer-info", {"answer": "Nairobi, Mombasa and Kisumu."})
        assert answered["state"] == "SUBMITTED"
        waited = business_days_between(
            local_date(datetime.fromisoformat(submitted["stage_deadline_at"])),
            local_date(datetime.fromisoformat(answered["stage_deadline_at"])),
            off,
        )
        assert waited >= 10
        last = add_business_days(entered_on, 20 + waited, off)
        assert (await tick(app_engine, world, now=sm.end_of_day(last))).outcomes == ()
        await advance((last - await db_today(owner_engine)).days + 1)
        report = await tick(app_engine, world)
        ended = await t.detail(s.dev)
    assert report.of(t.engagement) == Outcome(t.engagement, "expire", S.EXPIRED)
    assert (ended["state"], ended["end_reason"]) == ("EXPIRED", "NO_REVIEW")


async def test_a_hold_resumes_by_itself_on_its_date(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Given NEGOTIATION on hold until a date 10 days out, When the clock reaches it and the job runs, Then it is
    NEGOTIATION again with the deadline moved by the business days on hold; the system writes no note."""
    world = await build(owner_engine)
    off = await holidays_of(owner_engine)
    today = await db_today(owner_engine)
    resume_at = today + timedelta(days=10)
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        t = Tracker(await open_engagement(app_engine, world))
        negotiating = await walk_to(t, s, world, today, "NEGOTIATION")
        due = local_date(datetime.fromisoformat(negotiating["stage_deadline_at"]))
        await t.ok(s.dev, "pause", {"reason": "Waiting for the board.", "resume_at": str(resume_at)})
        day_before = sm.end_of_day(resume_at - timedelta(days=1))
        assert (await tick(app_engine, world, now=day_before)).outcomes == ()
        await advance(10)
        report = await tick(app_engine, world)
        assert (await tick(app_engine, world)).outcomes == ()
        resumed = await t.detail(s.owner)
        history = (await s.dev.get(t.path("/history"))).json()
    assert report.of(t.engagement) == Outcome(t.engagement, "resume", S.NEGOTIATION)
    assert (resumed["state"], resumed["paused_from"]) == ("NEGOTIATION", None)
    held = business_days_between(today, resume_at, off)
    assert datetime.fromisoformat(resumed["stage_deadline_at"]) == sm.end_of_day(add_business_days(due, held, off))
    [resume] = system_events(history)
    assert (resume["command"], resume["from_state"], resume["to_state"]) == ("resume", "ON_HOLD", "NEGOTIATION")
    assert [n["kind"] for n in resumed["notes"]] == ["hold"]
    assert history["chain_verified"] is True


async def test_a_failing_engagement_is_reported_and_retried_by_the_next_run(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One engagement's failure never stops the run: it is logged and reported, nothing of it is written, and the
    next run acts on it."""
    world = await build(owner_engine)
    off = await holidays_of(owner_engine)
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        t = await reach(owner_engine, app_engine, world, s, S.SUBMITTED)
        last = add_business_days(await db_today(owner_engine), 20, off)
        await advance((last - await db_today(owner_engine)).days + 1)

        async def broken(*args: object, **kwargs: object) -> Outcome:
            raise RuntimeError("the database went away")

        with monkeypatch.context() as patched:
            patched.setattr(expiry, "act_on", broken)
            failed = await tick(app_engine, world)
        assert failed.of(t.engagement) == Outcome(t.engagement, None, None, error=True)
        assert (await t.detail(s.dev))["state"] == "SUBMITTED"
        retried = await tick(app_engine, world)
    assert retried.of(t.engagement) == Outcome(t.engagement, "expire", S.EXPIRED)
