"""REQ-DEV-01 (D-59; P22 card A): ``store_draft`` writes a checked draft as the day's draft set.

As the nightly job (bridge_app, no user bound) it writes the set and its five questions (the curated title, URL and
topic, the 32-byte prompt hashes) in one transaction without reading a quiz row back; a day with a draft or approved
set refuses (``day_taken``), a rejected day takes a new draft; a prompt hash of the last 60 days discards the draft
(``repeated_prompt``) and one older than that does not; a concurrent writer of the same day loses on the index. The
owner (the seed) may write a seeded set of a past day; malformed calls raise."""

from __future__ import annotations

from datetime import timedelta

import pytest

from bridge.db import create_session_factory
from bridge.quiz import store
from bridge.quiz.store import DAY_TAKEN, NotStored, Stored, store_draft
from tests.integration.quiz.api_world import (
    NO_REPEAT_DAYS,
    QuizDb,
    accepted_set,
    at,
    cast,
    decide,
    draft_set,
    owner_rows,
)
from tests.integration.quiz.schema_world import KEY

COLUMNS = (
    "SELECT position, prompt, options, answer, why, source_id, source_title, source_url, topic, prompt_hash, status"
    " FROM quiz_questions WHERE set_id = :s ORDER BY position"
)


async def _store(quiz: QuizDb, day: object, questions: object, **kwargs: object) -> Stored | NotStored:
    options = {"origin": "model", "trace_id": "quiz:test:1", "no_repeat_days": NO_REPEAT_DAYS} | kwargs
    async with create_session_factory(quiz.app)() as db:
        return await store_draft(db, day, questions, **options)  # type: ignore[arg-type]


async def test_the_job_stores_a_draft_set_without_reading_it_back(quiz: QuizDb) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    questions = accepted_set(KEY)
    stored = await _store(quiz, monday + timedelta(days=1), questions, trace_id="quiz:2026-01-01:2")
    assert isinstance(stored, Stored)
    [row] = await owner_rows(
        quiz, "SELECT quiz_date, status, origin, llm_trace_id, decided_at FROM quiz_sets WHERE id = :s", s=stored.set_id
    )
    assert tuple(row) == (monday + timedelta(days=1), "draft", "model", "quiz:2026-01-01:2", None)
    written = await owner_rows(quiz, COLUMNS, s=stored.set_id)
    assert [tuple(r) for r in written] == [
        (
            q.position,
            q.prompt,
            list(q.options),
            q.answer,
            q.why,
            q.source_id,
            q.source_title,
            q.source_url,
            q.topic,
            bytes.fromhex(q.prompt_hash),
            "live",
        )
        for q in questions
    ]
    again = await _store(quiz, monday + timedelta(days=1), accepted_set(KEY))
    assert again == NotStored(monday + timedelta(days=1), DAY_TAKEN)
    assert len(await owner_rows(quiz, "SELECT id FROM quiz_sets WHERE quiz_date = :d", d=row.quiz_date)) == 1


async def test_a_rejected_day_takes_a_new_draft_and_an_approved_one_does_not(quiz: QuizDb) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    p = await cast(quiz)
    first = await draft_set(quiz, monday, role="job")
    await decide(quiz, first, p.admin, "rejected")
    second = await _store(quiz, monday, accepted_set(KEY))
    assert isinstance(second, Stored)
    await decide(quiz, second.set_id, p.admin)
    assert await _store(quiz, monday, accepted_set(KEY)) == NotStored(monday, DAY_TAKEN)


async def test_a_prompt_of_the_last_60_days_discards_the_draft(quiz: QuizDb) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    used = accepted_set(KEY)
    async with create_session_factory(quiz.owner)() as db:  # the seed's role: a past day
        old = await store_draft(
            db,
            monday - timedelta(days=NO_REPEAT_DAYS),
            used,
            origin="seeded",
            trace_id=None,
            no_repeat_days=NO_REPEAT_DAYS,
        )
    assert isinstance(old, Stored)
    repeat = (*accepted_set(KEY)[:3], used[3], accepted_set(KEY)[4])
    assert await _store(quiz, monday, repeat) == NotStored(monday, "repeated_prompt", 4)
    assert await owner_rows(quiz, "SELECT id FROM quiz_sets WHERE quiz_date = :d", d=monday) == []
    later = await _store(quiz, monday + timedelta(days=1), repeat)  # the old set is 61 days before: out of the window
    assert isinstance(later, Stored)


async def test_a_concurrent_writer_of_the_same_day_loses_on_the_index(
    quiz: QuizDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monday = quiz.monday()
    await at(quiz, monday)
    await draft_set(quiz, monday, role="job")

    async def not_yet(*_: object) -> None:  # the other run committed after this one looked
        return None

    monkeypatch.setattr(store, "_refusal", not_yet)
    assert await _store(quiz, monday, accepted_set(KEY)) == NotStored(monday, DAY_TAKEN)
    assert len(await owner_rows(quiz, "SELECT id FROM quiz_sets WHERE quiz_date = :d", d=monday)) == 1


async def test_malformed_drafts_are_refused_before_any_write(quiz: QuizDb) -> None:
    monday = quiz.monday()
    with pytest.raises(ValueError, match="positions 1 to 5"):
        await _store(quiz, monday, accepted_set(KEY)[:4])
    with pytest.raises(ValueError, match="trace id"):
        await _store(quiz, monday, accepted_set(KEY), trace_id=None)
    with pytest.raises(ValueError, match="trace id"):
        await _store(quiz, monday, accepted_set(KEY), origin="seeded")
