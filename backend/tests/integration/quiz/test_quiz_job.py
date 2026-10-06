"""REQ-DEV-01 (D-59; P22 card A tests A1 and A2, the job's half): the nightly pass ``run_nightly`` on the shared clock.

- It drafts today and the next Nairobi day when they have no set: one call each (scripted, through the real
  ``LLMService``), stored as draft sets of origin ``model`` with the call's trace id; a second run the same night
  makes no call and stores nothing (idempotent per day); a day with a draft or approved set gets no call at all.
- The kill switch refuses without a call and stores nothing; a prompt of the last 60 days discards the draft (twice:
  the retry) and the day gets nothing.
- A set staff rejected is drafted again by the next run (the next night, the rejected day being today by then).
- Wired as the worker wires it (``NightlyRuntime`` with the routed client of an unbound session, the fake provider of
  APP_ENV=test), no provider is reached: the demo fallback is never a set.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, time, timedelta
from typing import Any

from bridge.config import get_settings
from bridge.db import create_session_factory
from bridge.ids import uuid7
from bridge.jobs.quiz import NightlyRuntime
from bridge.llm.fakes import FAKE_GLOBAL_DAILY_CAP_USD, FakeLLMClient
from bridge.llm.ledger import CallStatus
from bridge.quiz import fakes
from bridge.quiz.checks import prompt_hash
from bridge.quiz.generate import QuizAnswer
from bridge.quiz.nightly import NightlyDeps, run_nightly
from bridge.quiz.policy import get_quiz_policy
from bridge.quiz.run import Refused
from bridge.quiz.sources import get_sources
from bridge.quiz.store import DAY_TAKEN, NotStored, Stored, store_draft
from tests.integration.quiz.api_world import (
    QuizDb,
    accepted_set,
    approved_set,
    at,
    cast,
    decide,
    draft_set,
    owner_rows,
)

NIGHT = time(2, 30)  # the job's hour in Nairobi


def answer(day: date) -> QuizAnswer:
    """The fakes' valid answer for ``day``, its prompts made unique to this call (the module's tests share a
    database, and the no-repeat rule reads 60 days of prompts)."""
    found = fakes.answer(fakes.day_sample(day))
    token = uuid7().hex[-12:]
    for index, question in enumerate(found.questions):
        found = fakes.edit_question(found, index, prompt=f"{question.prompt} Set {token} question {index + 1}.")
    return found


def client(*replies: Any, **settings: Any) -> FakeLLMClient:
    roomy = {"llm_global_daily_cap_usd": FAKE_GLOBAL_DAILY_CAP_USD, "llm_prototype_total_cap_usd": 1000} | settings
    return FakeLLMClient(replies, settings=get_settings().model_copy(update=roomy))


def deps(quiz: QuizDb, llm: FakeLLMClient) -> NightlyDeps:
    return NightlyDeps(
        factory=create_session_factory(quiz.app),
        llm=lambda db: llm,
        sources=get_sources(),
        policy=get_quiz_policy(),
    )


async def sets_of(quiz: QuizDb, *days: date) -> list[Any]:
    return await owner_rows(
        quiz,
        "SELECT id, quiz_date, status, origin, llm_trace_id FROM quiz_sets WHERE quiz_date = ANY(:d)"
        " ORDER BY quiz_date, created_at",
        d=list(days),
    )


async def test_the_job_drafts_today_and_tomorrow_once_a_night(quiz: QuizDb) -> None:
    today = quiz.monday()
    tomorrow = today + timedelta(days=1)
    await at(quiz, today, NIGHT)
    llm = client(answer(today), answer(tomorrow))
    first = await run_nightly(deps(quiz, llm))
    assert [type(outcome) for outcome in first] == [Stored, Stored]
    assert [entry.trace_id for entry in llm.ledger.entries] == [f"quiz:{today}:1", f"quiz:{tomorrow}:1"]
    assert [(e.status, e.user_id, e.org_id) for e in llm.ledger.entries] == [(CallStatus.OK, None, None)] * 2
    stored = await sets_of(quiz, today, tomorrow)
    assert [(r.quiz_date, r.status, r.origin, r.llm_trace_id) for r in stored] == [
        (today, "draft", "model", f"quiz:{today}:1"),
        (tomorrow, "draft", "model", f"quiz:{tomorrow}:1"),
    ]
    questions = await owner_rows(
        quiz, "SELECT count(*) AS n FROM quiz_questions WHERE set_id = ANY(:s)", s=[r.id for r in stored]
    )
    assert questions[0].n == 10
    second = await run_nightly(deps(quiz, llm))  # the same night again: nothing to do, no call
    assert second == (NotStored(today, DAY_TAKEN), NotStored(tomorrow, DAY_TAKEN))
    assert len(llm.requests) == 2
    assert len(await sets_of(quiz, today, tomorrow)) == 2


async def test_a_day_with_a_set_gets_no_call(quiz: QuizDb) -> None:
    today = quiz.monday()
    tomorrow = today + timedelta(days=1)
    await at(quiz, today, NIGHT)
    p = await cast(quiz)
    await approved_set(quiz, today, p.admin)
    await draft_set(quiz, tomorrow, role="job")
    llm = client()  # no scripted answer: a call would fail the test
    assert await run_nightly(deps(quiz, llm)) == (NotStored(today, DAY_TAKEN), NotStored(tomorrow, DAY_TAKEN))
    assert llm.requests == []
    assert llm.ledger.entries == []


async def test_the_kill_switch_refuses_without_a_call(quiz: QuizDb) -> None:
    today = quiz.monday()
    await at(quiz, today, NIGHT)
    llm = client(answer(today), answer(today + timedelta(days=1)), llm_kill_switch=True)
    outcomes = await run_nightly(deps(quiz, llm))
    assert [(o.reason, o.attempts) for o in outcomes if isinstance(o, Refused)] == [("llm_kill_switch", 1)] * 2
    assert llm.requests == []
    assert [e.status for e in llm.ledger.entries] == [CallStatus.BLOCKED_KILL_SWITCH] * 2
    assert await sets_of(quiz, today, today + timedelta(days=1)) == []


async def test_a_prompt_of_the_last_60_days_is_discarded(quiz: QuizDb) -> None:
    today = quiz.monday()
    tomorrow = today + timedelta(days=1)
    await at(quiz, today, NIGHT)
    p = await cast(quiz)
    await approved_set(quiz, today, p.admin)
    drafted = answer(tomorrow)
    held = list(accepted_set())  # a set 59 days before, holding one of the draft's prompts
    held[2] = replace(held[2], prompt_hash=prompt_hash(drafted.questions[1].prompt))
    async with create_session_factory(quiz.owner)() as db:
        old = await store_draft(
            db, tomorrow - timedelta(days=59), held, origin="seeded", trace_id=None, no_repeat_days=60
        )
    assert isinstance(old, Stored)
    llm = client(drafted, drafted)
    outcomes = await run_nightly(deps(quiz, llm))
    assert outcomes[0] == NotStored(today, DAY_TAKEN)
    refused = outcomes[1]
    assert isinstance(refused, Refused)
    assert (refused.reason, refused.attempts) == ("repeated_prompt", 2)
    assert len(llm.requests) == 2
    assert await sets_of(quiz, tomorrow) == []


async def test_a_rejected_set_is_drafted_again_by_the_next_run(quiz: QuizDb) -> None:
    monday = quiz.monday()
    tuesday, wednesday = monday + timedelta(days=1), monday + timedelta(days=2)
    await at(quiz, monday, NIGHT)
    p = await cast(quiz)
    await approved_set(quiz, monday, p.admin)
    llm = client(answer(tuesday))
    [_, stored] = await run_nightly(deps(quiz, llm))
    assert isinstance(stored, Stored)
    await at(quiz, monday, time(15, 0))
    await decide(quiz, stored.set_id, p.admin, "rejected")  # staff reject Tuesday's set on Monday afternoon
    await at(quiz, tuesday, NIGHT)  # the next night: the rejected day is today
    llm.queue(answer(tuesday), answer(wednesday))
    again = await run_nightly(deps(quiz, llm))
    assert [type(outcome) for outcome in again] == [Stored, Stored]
    assert [(r.quiz_date, r.status) for r in await sets_of(quiz, tuesday, wednesday)] == [
        (tuesday, "rejected"),
        (tuesday, "draft"),
        (wednesday, "draft"),
    ]


async def test_wired_as_the_worker_no_provider_is_reached(quiz: QuizDb) -> None:
    today = quiz.monday()
    await at(quiz, today, NIGHT)
    runtime = NightlyRuntime(get_settings(), factory=create_session_factory(quiz.app))
    try:
        outcomes = await run_nightly(runtime.deps())
    finally:
        await runtime.aclose()
    assert [(o.reason, o.attempts) for o in outcomes if isinstance(o, Refused)] == [("demo_fallback", 1)] * 2
    assert await sets_of(quiz, today, today + timedelta(days=1)) == []
