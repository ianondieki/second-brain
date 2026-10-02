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

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import commands, service
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import add_business_days, local_date
from bridge.engagements.policy import get_policy
from bridge.notifications.email import FakeEmailProvider
from bridge.reminders.facts import developer_facts, org_facts
from bridge.reminders.nudge import Nudge, compose_nudge
from bridge.reminders.org_digest import Digest, compose_digest
from tests.integration.engagements.api_world import (
    PROPOSAL_TITLE,
    Tracker,
    World,
    build,
    business_days_later,
    db_today,
    deals_on,
    holidays_of,
    moved_clock,
    open_engagement,
    run_notifications,
    seats,
    simple_terms,
    walk_to,
)

QUESTION = "What would a pilot for 3 depots cost,\nand who maintains the sensors?"
ANSWER = "KES 250,000 for 3 depots; we maintain the sensors for 12 months."
REASON = "Our budget committee meets next month."


async def in_app(owner_engine: AsyncEngine, user: UUID, engagement: UUID) -> list[tuple[str, str, str]]:
    """The user's in-app notices about the engagement: (kind, title, body), oldest first."""
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT kind, title, body FROM in_app_notifications WHERE user_id = :u AND link LIKE :l"
                " ORDER BY created_at, id"
            ),
            {"u": user, "l": f"%/engagements/{engagement}"},
        )
        return [(str(kind), str(title), str(body)) for kind, title, body in rows.all()]


async def email_of(owner_engine: AsyncEngine, user: UUID) -> str:
    async with owner_engine.connect() as conn:
        return str((await conn.execute(text("SELECT email FROM users WHERE id = :u"), {"u": user})).scalar_one())


def eat(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def held_name(detail: dict[str, Any]) -> str:
    return str(detail["developer_name"])


async def reminders_of(app_engine: AsyncEngine, world: World, today: date) -> tuple[Digest, Nudge]:
    """The organisation's progress digest (read as its owner) and the developer's daily reminder, composed from the
    facts both read (REQ-REM-01, REQ-REM-02)."""
    factory = create_session_factory(app_engine)
    async with factory() as db:
        await bind_tenant(db, user_id=world.owner, org_id=world.org)
        digest = compose_digest(await org_facts(db, world.org, today, "daily", deals_enabled=True), frozenset())
    async with factory() as db:
        await bind_tenant(db, user_id=world.developer)
        nudge = compose_nudge(await developer_facts(db, world.developer, today, deals_enabled=True), frozenset())
    return digest, nudge


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
        # The review clock is paused; the question's own deadline is its answer-by date (10 BD, policy.yaml).
        answer_by = sm.end_of_day(add_business_days(await db_today(owner_engine), 10, off))
        assert deadline_of(asked) == answer_by
        assert asked["due"]["business_days_left"] == 10
        assert (asked["stage_label"], asked["stage_group"]) == ("Information requested", None)
        assert asked["whose_turn"] == ["developer"]
        assert asked["awaiting"] == [{"command": "answer_info", "party": "developer"}]
        assert asked["actions"] == ["cancel_request"]  # it waits for the answer, or withdraws its question
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
    assert [n["seq"] for n in answered["notes"]] == [asked_seq, answered_seq]  # the History pairs them exactly
    # UNDER_REVIEW's caps: one question left of two, both holds and all 60 days on hold.
    assert answered["side_limits"] == {"questions_left": 1, "holds_left": 2, "hold_days_left": 60}
    asking = history["events"][asked_seq - 1]
    assert asking["payload"] == {"paused_due_on": str(local_date(due))}  # ids and dates only: no text
    assert datetime.fromisoformat(asking["stage_deadline_at"]) == answer_by
    assert history["chain_verified"] is True
    assert QUESTION not in str(history["events"])
    # N03 both ways: the developer is told of the question, the organisation's reviewer of the answer, each in-app
    # and by one status email (the start of the review is in-app only); the texts stay on the tracker.
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider)
    developer_notices = await in_app(owner_engine, world.developer, engagement)
    assert [(kind, title) for kind, title, _ in developer_notices] == [
        ("engagement.n03", "Under review"),
        ("engagement.n03", "Information requested"),
    ]
    assert "asked you a question" in developer_notices[1][2]
    [(kind, title, body)] = await in_app(owner_engine, world.reviewer, engagement)
    assert (kind, title) == ("engagement.n03", "Under review")
    assert "answered your question" in body
    developer_email, reviewer_email = (
        await email_of(owner_engine, world.developer),
        await email_of(owner_engine, world.reviewer),
    )
    assert sorted(m.to for m in provider.outbox) == sorted([developer_email, reviewer_email])
    for message in provider.outbox:
        assert QUESTION.splitlines()[0] not in message.text
        assert ANSWER not in message.text
        assert f"/engagements/{engagement}" in message.text
    assert await run_notifications(owner_engine, app_engine, engagement, provider) == 0  # nothing left to send


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
        digest, nudge = await reminders_of(app_engine, world, today)
        assert digest.paused == (f"“{PROPOSAL_TITLE}” by {held_name(held)} (On hold): paused until {eat(resume_at)}.",)
        assert (digest.entries, digest.overdue, digest.needs_us) == ((), (), ())  # paused: never overdue
        assert nudge.waiting == (f"“{PROPOSAL_TITLE}” with {world.org_name}: on hold until {eat(resume_at)}.",)
        assert nudge.health == ()
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
    # N20: the organisation's people on the engagement are told of the hold, the developer of the early resume.
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider)
    owner_notices = [n for n in await in_app(owner_engine, world.owner, engagement) if n[0] == "engagement.n20"]
    assert [(title, body.split(" until ")[1]) for _, title, body in owner_notices] == [
        ("On hold", f"{resume_at.day} {resume_at:%b %Y}. Due dates move by the time on hold.")
    ]
    developer_notices = [n for n in await in_app(owner_engine, world.developer, engagement) if n[0] == "engagement.n20"]
    assert [title for _, title, _ in developer_notices] == ["Terms and agreement drafting"]
    assert "resumed" in developer_notices[0][2]
    held_to = sorted(m.to for m in provider.outbox if m.subject == 'On hold: "RLS proposal"')
    acted = (world.owner, world.reviewer, world.signatory)  # the named contact and every member who acted on it
    assert held_to == sorted([await email_of(owner_engine, person) for person in acted])
    resumed_to = [m.to for m in provider.outbox if m.subject == 'Terms and agreement drafting: "RLS proposal"']
    assert resumed_to == [await email_of(owner_engine, world.developer)]


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


async def test_the_status_email_follows_the_preference_and_a_verified_address(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The side states' emails are mutable (REQUIREMENTS.md §5 N03, N20): a developer who turned the kind's email off
    and a member without a verified address get the in-app notice only."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO notification_preferences (user_id, kind, channel, enabled)"
                " VALUES (:u, 'engagement.n03', 'email', false)"
            ),
            {"u": world.developer},
        )
        await conn.execute(text("UPDATE users SET email_verified_at = NULL WHERE id = :u"), {"u": world.reviewer})
    async with seats(app_engine, deals_on(), world) as s:
        await t.ok(s.reviewer, "request-info", {"question": QUESTION})
        await t.ok(s.dev, "answer-info", {"answer": ANSWER})
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider)
    assert provider.outbox == []
    assert [kind for kind, _, _ in await in_app(owner_engine, world.developer, engagement)] == ["engagement.n03"]
    assert [kind for kind, _, _ in await in_app(owner_engine, world.reviewer, engagement)] == ["engagement.n03"]


async def test_the_developer_may_withdraw_while_paused(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Withdrawing stays the developer's before the agreement, a question open or a hold included: the engagement
    ends and the tag is withdrawn (the database accepts leaving a side state for an exit)."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    async with seats(app_engine, deals_on(), world) as s:
        await t.ok(s.reviewer, "request-info", {"question": QUESTION})
        withdrawn = await t.ok(s.dev, "withdraw")
    assert (withdrawn["state"], withdrawn["paused_from"], withdrawn["actions"]) == ("WITHDRAWN", None, [])
    async with owner_engine.connect() as conn:
        status = await conn.execute(text("SELECT status::text FROM tags WHERE id = :id"), {"id": world.tag})
        assert status.scalar_one() == "withdrawn"


async def test_no_contact_details_travel_in_a_note_before_first_contact(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """The contact gate (AC-TRACK-9; THREAT_MODEL I): before CONTACT_MADE (the stage, or the stage a side state
    returns to) a question, an answer or a reason carrying an email, a phone number or a link is refused (422
    ``contains_contact``) and nothing is written; from CONTACT_MADE on, the parties may share them."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s:
        for text_value in ("Write to jane [at] telco (dot) co.ke", "Call 0712 345 678", "See https://telco.example"):
            refused = await t.post(s.reviewer, "request-info", {"question": text_value})
            assert code(refused) == (422, "contains_contact"), text_value
        await t.ok(s.reviewer, "request-info", {"question": QUESTION})
        refused = await t.post(s.dev, "answer-info", {"answer": "Email me: brian@dev.example.com"})
        assert code(refused) == (422, "contains_contact")
        await t.ok(s.dev, "answer-info", {"answer": ANSWER})
        await t.ok(s.reviewer, "start-review")
        held = await t.post(
            s.dev, "pause", {"reason": "WhatsApp +254 712 345 678", "resume_at": str(today + timedelta(days=5))}
        )
        assert code(held) == (422, "contains_contact")
        await t.ok(s.dev, "pause", {"reason": REASON, "resume_at": str(today + timedelta(days=5))})
        assert code(await t.post(s.signatory, "resume", {"reason": "Mail ceo@telco.example"})) == (
            422,
            "contains_contact",
        )
        await t.ok(s.signatory, "resume", {"reason": "Ready."})
        await walk_to(t, s, world, today, "CONTACT_MADE")
        shared = await t.ok(
            s.dev, "pause", {"reason": "Call me on 0712 345 678", "resume_at": str(today + timedelta(days=5))}
        )
    assert shared["state"] == "ON_HOLD"  # after first contact the parties exchange details anyway
    assert [n["kind"] for n in shared["notes"]] == ["info_request", "info_answer", "hold", "resume", "hold"]


async def test_a_stage_takes_two_questions_and_the_organisation_may_withdraw_one(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """policy.yaml info_requests_per_stage (2): a third question in the same stage is 409 info_request_limit. The
    organisation withdraws its open question (cancel-request): back to the stage with the days it waited added to
    the deadline, no note, and the developer told; a withdrawn question still counts."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    off = await holidays_of(owner_engine)
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        reviewing = await t.ok(s.reviewer, "start-review")
        await t.ok(s.reviewer, "request-info", {"question": QUESTION})
        await t.ok(s.dev, "answer-info", {"answer": ANSWER})
        asked = await t.ok(s.signatory, "request-info", {"question": "And the warranty?"})
        assert asked["actions"] == ["cancel_request"]
        assert code(await t.post(s.dev, "cancel-request")) == (403, "not_your_action")
        await business_days_later(owner_engine, advance, 2)
        withdrawn = await t.ok(s.signatory, "cancel-request")
        assert (withdrawn["state"], withdrawn["paused_from"]) == ("UNDER_REVIEW", None)
        assert "request_info" not in withdrawn["actions"]  # two questions asked in this stage
        assert code(await t.post(s.reviewer, "request-info", {"question": "One more?"})) == (409, "info_request_limit")
        history = (await s.dev.get(t.path("/history"))).json()
    assert deadline_of(withdrawn) == sm.end_of_day(add_business_days(local_date(deadline_of(reviewing)), 2, off))
    assert [n["kind"] for n in withdrawn["notes"]] == ["info_request", "info_answer", "info_request"]  # none for it
    assert history["events"][-1]["command"] == "cancel_request"
    provider = FakeEmailProvider()
    await run_notifications(owner_engine, app_engine, engagement, provider)
    told = [body for kind, _, body in await in_app(owner_engine, world.developer, engagement) if "withdrew" in body]
    assert told == [f'{world.org_name} withdrew its question about "{PROPOSAL_TITLE}". The review clock runs again.']


async def test_a_hold_at_stage_3_moves_the_contact_by_date_the_tracker_shows(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """At INTEREST_CONFIRMED the stage's deadline is the contact-by date the organisation named; a hold moves it by
    the business days on hold, and the tracker shows the moved date as the contact-by date (the row keeps the named
    one, which EM2 quoted)."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    off = await holidays_of(owner_engine)
    today = await db_today(owner_engine)
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        approved = await walk_to(t, s, world, today, "INTEREST_CONFIRMED")
        assert approved["contact"]["contact_by"] == str(today)
        await t.ok(s.dev, "pause", {"reason": REASON, "resume_at": str(today + timedelta(days=7))})
        await business_days_later(owner_engine, advance, 2)
        resumed = await t.ok(s.owner, "resume", {"reason": "Ready."})
    moved = add_business_days(today, 2, off)
    assert local_date(deadline_of(resumed)) == moved
    assert resumed["contact"]["contact_by"] == str(moved)
    async with owner_engine.connect() as conn:
        named = await conn.execute(text("SELECT contact_by FROM engagements WHERE id = :e"), {"e": engagement})
        assert named.scalar_one() == today


async def test_pause_and_resume_loops_are_refused_and_never_free(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """THREAT_MODEL D (a party floods the other through free side-state cycles): 200 same-day pause and resume
    cycles stop at the third pause (policy.yaml holds_per_stage, 409 hold_limit), each hold charged at least a day of
    hold_days_total, and the organisation hears of two holds only."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    today = await db_today(owner_engine)
    pause = {"reason": REASON, "resume_at": str(today + timedelta(days=30))}
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "NEGOTIATION")
        refused = None
        for cycle in range(200):
            paused = await t.post(s.dev, "pause", pause)
            if paused.status_code != 200:
                refused = (cycle, code(paused))
                break
            await t.ok(s.owner, "resume", {"reason": "Ready."})
        spent = await t.detail(s.dev)
    assert refused == (2, (409, "hold_limit"))
    assert "pause" not in spent["actions"]
    # NEGOTIATION asks no questions; two same-day holds spent the stage's holds and a day each of the 60.
    assert spent["side_limits"] == {"questions_left": None, "holds_left": 0, "hold_days_left": 58}
    assert [n["kind"] for n in spent["notes"]] == ["hold", "resume", "hold", "resume"]
    await run_notifications(owner_engine, app_engine, engagement, FakeEmailProvider())
    holds = [b for k, _, b in await in_app(owner_engine, world.owner, engagement) if k == "engagement.n20"]
    assert len(holds) == 2


async def test_one_party_runs_at_most_actions_per_hour_side_state_commands(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THREAT_MODEL D: policy.yaml side_states.actions_per_hour caps one party's side-state commands on one engagement
    within any hour (here 3): the fourth is 429 too_many_actions and writes nothing; the other party is counted
    apart, and the organisation's members together."""
    tight = replace(get_policy(), side_actions_per_hour=3, holds_per_stage=10)
    monkeypatch.setattr(commands, "get_policy", lambda: tight)
    monkeypatch.setattr(service, "get_policy", lambda: tight)
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    today = await db_today(owner_engine)
    pause = {"reason": REASON, "resume_at": str(today + timedelta(days=5))}
    async with seats(app_engine, deals_on(), world) as s:
        await walk_to(t, s, world, today, "NEGOTIATION")
        await t.ok(s.dev, "pause", pause)
        await t.ok(s.dev, "resume", {"reason": "Back."})
        await t.ok(s.dev, "pause", pause)
        before = await t.detail(s.dev)
        assert code(await t.post(s.dev, "resume", {"reason": "Back."})) == (429, "too_many_actions")
        assert (await t.detail(s.dev))["lock_version"] == before["lock_version"]  # nothing written
        resumed = await t.ok(s.owner, "resume", {"reason": "Ready."})  # the organisation's own count
        assert code(await t.post(s.dev, "pause", pause)) == (429, "too_many_actions")
        # The organisation's members share one budget (THREAT_MODEL D): the owner spends it, the reviewer is refused.
        await t.ok(s.owner, "pause", pause)
        await t.ok(s.owner, "resume", {"reason": "Ready again."})
        assert code(await t.post(s.reviewer, "pause", pause)) == (429, "too_many_actions")
    assert resumed["state"] == "NEGOTIATION"


async def test_the_question_cap_is_per_stage(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """Two questions in SUBMITTED spend that stage's cap (409 info_request_limit); once the review starts,
    UNDER_REVIEW has its own two."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    t = Tracker(engagement)
    async with seats(app_engine, deals_on(), world) as s:
        for _ in range(2):
            await t.ok(s.reviewer, "request-info", {"question": QUESTION})
            await t.ok(s.dev, "answer-info", {"answer": ANSWER})
        assert code(await t.post(s.reviewer, "request-info", {"question": QUESTION})) == (409, "info_request_limit")
        await t.ok(s.reviewer, "start-review")
        asked = await t.post(s.reviewer, "request-info", {"question": "And under review?"})
    assert asked.status_code == 200, asked.text
    assert asked.json()["paused_from"] == "UNDER_REVIEW"


async def test_the_detail_says_today_on_the_platform_clock(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    """The web app checks a hold's date against the API's ``today`` (the platform clock's Nairobi day), never the
    database's real time: with the test clock moved 30 days, ``today`` is the moved day."""
    world = await build(owner_engine)
    t = Tracker(await open_engagement(app_engine, world))
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        before = await db_today(owner_engine)
        assert (await t.detail(s.dev))["today"] == str(before)
        await advance(30)
        assert (await t.detail(s.owner))["today"] == str(before + timedelta(days=30))
