"""REQ-ENG-10 (part), through the API: the side states INFO_REQUESTED and ON_HOLD (before the agreement).

- The organisation asks the developer a question from stage 1 or 2: the review clock pauses (no deadline) until the
  developer answers; meanwhile the organisation can neither approve nor decline. The answer returns the engagement to
  its stage with the deadline moved by the business days it waited. The question and the answer are notes (revision
  0006), each the sibling of its event (``event_seq``), read by both parties.
- Either party puts the engagement on hold with a reason and a resume date (after today, at most 60 days ahead):
  ``due`` reads the resume date; either party resumes early with a reason, and the deadline moves by the business days
  on hold. Not from SUBMITTED. A hold keeps what the stage had: the endorsements of first contact still count after
  it, and the named contact still reads the developer's contact details during it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days, local_date
from tests.integration.engagements.api_world import (
    Tracker,
    build,
    db_today,
    deals_on,
    open_engagement,
    seats,
    simple_terms,
    walk_to,
)

QUESTION = "What would a pilot for 3 depots cost,\nand who maintains the sensors?"
ANSWER = "KES 250,000 for 3 depots; we maintain the sensors for 12 months."
REASON = "Our budget committee meets next month."


async def holidays_of(owner_engine: AsyncEngine) -> frozenset[date]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(text("SELECT observed_on FROM holidays WHERE country = 'KE'"))
        return frozenset(rows.scalars().all())


@asynccontextmanager
async def moved_clock(owner_engine: AsyncEngine) -> AsyncIterator[Callable[[int], Awaitable[None]]]:
    """The shared dev/test clock, moved forward by whole days on demand, and put back as it was at the end."""
    async with owner_engine.connect() as conn:
        enabled, offset = (await conn.execute(text("SELECT enabled, clock_offset FROM test_clock"))).one()
    moved = [offset]

    async def advance(days: int) -> None:
        moved[0] += timedelta(days=days)
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE test_clock SET enabled = true, clock_offset = :o"), {"o": moved[0]})

    try:
        yield advance
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE test_clock SET enabled = :e, clock_offset = :o"), {"e": enabled, "o": offset}
            )


async def business_days_later(owner_engine: AsyncEngine, advance: Callable[[int], Awaitable[None]], n: int) -> date:
    """Move the clock to the ``n``-th Kenyan business day after today (Nairobi); returns that date."""
    today = await db_today(owner_engine)
    later = add_business_days(today, n, await holidays_of(owner_engine))
    await advance((later - today).days)
    assert await db_today(owner_engine) == later
    return later


def deadline_of(detail: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(detail["stage_deadline_at"])


def code(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


async def note_rows(owner_engine: AsyncEngine, engagement: UUID) -> list[tuple[str, int]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT kind, event_seq FROM engagement_notes WHERE engagement_id = :e ORDER BY event_seq"),
            {"e": engagement},
        )
        return [(str(kind), int(seq)) for kind, seq in rows.all()]


def seq_of(history: dict[str, Any], command: str) -> int:
    [seq] = [event["seq"] for event in history["events"] if event["command"] == command]
    return int(seq)


async def test_a_question_pauses_the_review_clock_until_the_developer_answers(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given UNDER_REVIEW (15 BD due), When the organisation asks and the developer answers 3 BD later, Then the
    engagement is UNDER_REVIEW again with its deadline 3 BD later, and the two notes sit beside their events."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    off = await holidays_of(owner_engine)
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        reviewing = await t.ok(s.reviewer, "start-review")
        assert reviewing["due"]["business_days_left"] == 15
        due = deadline_of(reviewing)
        assert code(await t.post(s.reviewer, "request-info", {"question": "  \n "})) == (422, "invalid_note")
        assert code(await t.post(s.dev, "request-info", {"question": QUESTION})) == (403, "not_your_action")
        asked = await t.ok(s.reviewer, "request-info", {"question": QUESTION})
        assert (asked["state"], asked["paused_from"]) == ("INFO_REQUESTED", "UNDER_REVIEW")
        assert (asked["stage_deadline_at"], asked["due"]) == (None, None)  # the clock is paused
        assert (asked["stage_label"], asked["stage_group"]) == ("Information requested", None)
        assert asked["whose_turn"] == ["developer"]
        assert asked["awaiting"] == [{"command": "answer_info", "party": "developer"}]
        assert asked["actions"] == []  # the organisation waits for the answer
        assert [(n["kind"], n["body"], n["resume_at"], n["by"]) for n in asked["notes"]] == [
            ("info_request", QUESTION, None, "org")
        ]
        today = await db_today(owner_engine)
        contact = {"contact_user_id": str(world.owner), "contact_channel": "email", "contact_by": str(today)}
        assert code(await t.post(s.signatory, "approve", contact)) == (409, "illegal_transition")
        assert code(await t.post(s.signatory, "decline", {"reason": "BUDGET"})) == (409, "illegal_transition")
        assert code(await t.post(s.reviewer, "request-info", {"question": QUESTION})) == (409, "illegal_transition")
        assert code(await t.post(s.signatory, "answer-info", {"answer": ANSWER})) == (403, "not_your_action")
        developer_view = await t.detail(s.dev)
        assert developer_view["actions"] == ["withdraw", "answer_info"]
        assert developer_view["notes"] == asked["notes"]  # both parties read the question
        answered_on = await business_days_later(owner_engine, advance, 3)
        answered = await t.ok(s.dev, "answer-info", {"answer": f"  {ANSWER}  "})
        history = (await s.dev.get(t.path("/history"))).json()
    assert (answered["state"], answered["paused_from"]) == ("UNDER_REVIEW", None)
    moved = deadline_of(answered)
    assert moved == sm.end_of_day(add_business_days(local_date(due), 3, off))
    assert answered["due"]["business_days_left"] == 15  # the 3 BD it waited did not count
    assert local_date(moved) > answered_on
    assert [(n["kind"], n["body"], n["by"]) for n in answered["notes"]] == [
        ("info_request", QUESTION, "org"),
        ("info_answer", ANSWER, "developer"),  # trimmed
    ]
    asked_seq, answered_seq = seq_of(history, "request_info"), seq_of(history, "answer_info")
    assert await note_rows(owner_engine, engagement) == [("info_request", asked_seq), ("info_answer", answered_seq)]
    asking = history["events"][asked_seq - 1]
    assert asking["payload"] == {"paused_due_on": str(local_date(due))}  # ids and dates only: no text
    assert asking["stage_deadline_at"] is None
    assert history["chain_verified"] is True
    assert QUESTION not in str(history["events"])


async def test_a_hold_reads_its_resume_date_and_an_early_resume_moves_the_deadline(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given NEGOTIATION, When the developer pauses to a date 10 days out, Then ``due`` is the resume date and the
    organisation can only resume; When the organisation resumes 2 BD later, Then the deadline moved by 2 BD."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    off = await holidays_of(owner_engine)
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        submitted = await t.post(s.dev, "pause", {"reason": REASON, "resume_at": str(today + timedelta(days=10))})
        assert code(submitted) == (409, "illegal_transition")  # not while only submitted
        negotiating = await walk_to(t, s, world, today, "NEGOTIATION")
        due = deadline_of(negotiating)
        for wrong in (today, today + timedelta(days=61)):
            refused = await t.post(s.dev, "pause", {"reason": REASON, "resume_at": str(wrong)})
            assert code(refused) == (422, "invalid_resume_at"), wrong
        assert code(await t.post(s.finance, "pause", {"reason": REASON, "resume_at": str(today)})) == (
            403,
            "role_required",
        )
        resume_at = today + timedelta(days=10)
        held = await t.ok(s.dev, "pause", {"reason": REASON, "resume_at": str(resume_at)})
        assert (held["state"], held["paused_from"], held["stage_label"]) == ("ON_HOLD", "NEGOTIATION", "On hold")
        assert held["due"]["due_on"] == str(resume_at)
        assert deadline_of(held) == sm.end_of_day(resume_at)
        assert (held["whose_turn"], held["awaiting"], held["actions"]) == ([], [], ["withdraw", "resume"])
        assert [(n["kind"], n["body"], n["resume_at"], n["by"]) for n in held["notes"]] == [
            ("hold", REASON, str(resume_at), "developer")
        ]
        organisation_view = await t.detail(s.owner)
        assert organisation_view["actions"] == ["resume"]
        assert organisation_view["notes"] == held["notes"]
        assert code(await t.post(s.owner, "propose-terms", simple_terms(today))) == (409, "illegal_transition")
        assert code(await t.post(s.dev, "pause", {"reason": REASON, "resume_at": str(resume_at)})) == (
            409,
            "illegal_transition",
        )
        await business_days_later(owner_engine, advance, 2)
        resumed = await t.ok(s.owner, "resume", {"reason": "The committee met early."})
        history = (await s.owner.get(t.path("/history"))).json()
    assert (resumed["state"], resumed["paused_from"]) == ("NEGOTIATION", None)
    assert deadline_of(resumed) == sm.end_of_day(add_business_days(local_date(due), 2, off))
    assert [(n["kind"], n["by"]) for n in resumed["notes"]] == [("hold", "developer"), ("resume", "org")]
    pausing = history["events"][seq_of(history, "pause") - 1]
    assert pausing["payload"] == {"paused_due_on": str(local_date(due)), "resume_at": str(resume_at)}
    assert pausing["actor_role"] == "developer"
    assert [kind for kind, _ in await note_rows(owner_engine, engagement)] == ["hold", "resume"]
    assert history["chain_verified"] is True


async def test_a_hold_at_first_contact_keeps_what_the_stage_had(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The organisation's endorsement of first contact still counts after a hold (the database counts a new round on
    the return; the tracker continues the stage), and the named contact keeps the developer's details during it."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        contacted = await walk_to(t, s, world, today, "CONTACT_MADE")
        assert [e["party"] for e in contacted["endorsements"]] == ["org"]
        held = await t.ok(s.dev, "pause", {"reason": REASON, "resume_at": str(today + timedelta(days=5))})
        assert held["endorsements"] == []  # nothing is endorsed while on hold
        assert (await s.owner.get(t.path("/contact"))).status_code == 200  # the named contact, still revealed
        resumed = await t.ok(s.signatory, "resume", {"reason": "Ready to go on."})
        assert resumed["state"] == "CONTACT_MADE"
        assert [e["party"] for e in resumed["endorsements"]] == ["org"]
        assert resumed["whose_turn"] == ["developer"]  # confirm first contact, as before the hold
        confirmed = await t.ok(s.dev, "confirm-contact")
        assert sorted(e["party"] for e in confirmed["endorsements"]) == ["developer", "org"]
        assert [e["stage_round"] for e in confirmed["endorsements"]] == [1, 2]
        sent = await t.ok(s.dev, "send-nda")
    assert sent["state"] == "NDA_PENDING"
