"""Revision 0009 (REQ-DEV-01; P22 track A, D-59): the quiz's schema rules, each test in one rolled-back transaction.

- The nightly job (bridge_app with no user bound) drafts a set and its five questions for today or a later Nairobi
  day, reads no quiz row itself (it asks ``app_quiz_day_taken`` and ``app_quiz_recent_prompt_hashes``, which refuse a
  signed-in session) and can neither decide a set nor pull a question.
- A set is decided once, draft to approved (with its five questions) or rejected, by a staff admin only; a rejected
  day may be drafted again; questions join only a draft and change only by a pull or restore.
- Readers: staff admin reads every set and question, a developer the approved ones, an organisation-only account
  none; nobody reads ``answer`` or ``why`` (column grant) but through ``app_quiz_answers``, after an attempt or as staff
  admin.
- Attempts: the developer's own, on today's approved set (the shared clock in Nairobi), once per set; five answers,
  each NULL or 0 to 3; the score is the database's; append-only.
- Flags (``app_flag_question``): once per developer and question, at most 10 a Nairobi day; the third developer's
  flag pulls the question and rescores every attempt of the set; staff restore and pull again, rescoring each time.
- A developer reads only their own attempts, flags and quiz profile; the board (``app_quiz_board``) is this ISO week's,
  opted-in, non-demo developers only, ties by time, the first 20 rows and the caller's own.

The shared clock is moved, in each test's transaction only, to a Nairobi day whose neighbourhood holds no set of the
session's other tests (``free_day``).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration.engagements import tracker as t
from tests.integration.quiz.schema_world import (
    ATTEMPT,
    DECIDE,
    DENIED,
    FLAG,
    JOB_QUESTION,
    JOB_SET,
    KEY,
    RLS,
    SET_STATUS,
    approved,
    attempt,
    developer,
    draft,
    flag,
    free_day,
    owner_attempt,
    owner_set,
    people,
    qualify,
    question,
    scores,
)

BOARD = "SELECT rank, handle, points, time_ms, is_caller FROM app_quiz_board()"
STATS = "SELECT attempts, average_score, per_question_correct FROM app_quiz_set_stats(:s)"


async def test_the_job_drafts_reads_only_through_its_functions_and_decides_nothing(owner_engine: AsyncEngine) -> None:
    """Given the nightly job (bridge_app with no user bound), When it drafts today's set, Then it inserts the set and
    its five questions, reads no quiz row itself, learns that the day is taken and the prompts' hashes only through its
    two functions, and can neither decide nor pull; a second draft of the day, a past day and a decided status are
    refused; a signed-in session can neither use the job's functions nor insert a set or a question."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        await t.act(conn, None)
        assert await t.run(conn, "SELECT app_quiz_day_taken(:d)", d=today) is False
        set_id, questions = await draft(conn, today)
        for table in ("quiz_sets", "quiz_questions"):
            assert await t.run(conn, f"SELECT count(*) FROM {table}") == 0  # the job reads no quiz row
        assert await t.run(conn, "SELECT app_quiz_day_taken(:d)", d=today) is True
        assert await t.run(conn, "SELECT app_quiz_day_taken(:d)", d=today + timedelta(days=1)) is False
        hashes = await conn.execute(sa.text("SELECT * FROM app_quiz_recent_prompt_hashes(:d)"), {"d": today})
        assert list(hashes.keys()) == ["prompt_hash"]
        assert {bytes(row.prompt_hash) for row in hashes} == {question(set_id, n)["hash"] for n in range(1, 6)}
        later = "SELECT count(*) FROM app_quiz_recent_prompt_hashes(:d)"
        assert await t.run(conn, later, d=today + timedelta(days=1)) == 0
        for call in ("SELECT app_quiz_day_taken(:d)", "SELECT * FROM app_quiz_recent_prompt_hashes(:d)"):
            await t.expect(conn, call, "name the", d=None)
        await t.expect(conn, JOB_SET, "uq_quiz_sets_quiz_date", id=uuid7(), day=today, trace="again")
        await t.expect(conn, JOB_SET, RLS, id=uuid7(), day=today - timedelta(days=1), trace="past")
        for column, value in (("status", "'approved'"), ("decided_at", "now()"), ("created_at", "now()")):
            named = (
                f"INSERT INTO quiz_sets (id, quiz_date, origin, llm_trace_id, {column})"
                f" VALUES (uuid7(), :d, 'model', 'x', {value})"
            )
            await t.expect(conn, named, DENIED, d=today + timedelta(days=2))
        untraced = "INSERT INTO quiz_sets (id, quiz_date, origin) VALUES (uuid7(), :d, 'model')"
        await t.expect(conn, untraced, "trace_of_model", d=today + timedelta(days=2))
        await t.expect(conn, JOB_QUESTION, "uq_quiz_questions_set_id_position", **question(set_id, 1))
        await t.expect(conn, DECIDE, "staff admin only", set=set_id, decision="approved")
        await t.expect(conn, "UPDATE quiz_sets SET status = 'approved' WHERE id = :s", DENIED, s=set_id)
        await t.expect(conn, SET_STATUS, "staff admin only", question=questions[0], status="pulled", reason="Wrong")
        await t.expect(conn, "UPDATE quiz_questions SET status = 'pulled' WHERE id = :q", DENIED, q=questions[0])
        await t.expect(conn, "SELECT answer FROM quiz_questions", DENIED)
        for user in (p.developer, p.admin):
            await t.act(conn, user)
            await t.expect(conn, "SELECT app_quiz_day_taken(:d)", "the quiz job only", d=today)
            await t.expect(conn, "SELECT * FROM app_quiz_recent_prompt_hashes(:d)", "the quiz job only", d=today)
            await t.expect(conn, JOB_SET, RLS, id=uuid7(), day=today + timedelta(days=3), trace="signed-in")
            await t.expect(conn, JOB_QUESTION, RLS, **question(set_id, 1))


async def test_a_set_is_decided_once_by_a_staff_admin_and_its_questions_are_fixed(owner_engine: AsyncEngine) -> None:
    """A draft is approved only by a staff admin and only with its five questions, or rejected; then nothing of it
    changes, for the owner too; a rejected day is free for a new draft; who decided it, when and its generating call
    are staff admin's to read (``app_quiz_set_detail``), never a developer's; a question joins only a draft and
    changes only by its pull or restore."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        short, _ = await draft(conn, today, count=4)
        for user in (p.developer, p.moderator, p.org_only, None):
            await t.act(conn, user)
            await t.expect(conn, DECIDE, "staff admin only", set=short, decision="approved")
        await t.act(conn, p.admin)
        await t.expect(conn, DECIDE, "approved or rejected", set=short, decision="draft")
        await t.expect(conn, DECIDE, "no quiz set with that id", set=uuid7(), decision="approved")
        await t.expect(conn, DECIDE, "only with its five questions", set=short, decision="approved")
        await t.run(conn, DECIDE, set=short, decision="rejected")
        await t.expect(conn, DECIDE, r"already decided \(rejected\)", set=short, decision="approved")
        await t.act(conn, None)
        assert await t.run(conn, "SELECT app_quiz_day_taken(:d)", d=today) is False  # drafted again
        set_id, questions = await draft(conn, today)
        await t.expect(conn, JOB_QUESTION, "only to a draft set", **question(short, 5))
        await t.act(conn, p.admin)
        await t.run(conn, DECIDE, set=set_id, decision="approved")
        await t.expect(conn, DECIDE, "already decided", set=set_id, decision="rejected")
        await t.as_owner(conn)
        decided = await t.run(
            conn,
            "SELECT decided_by = :admin AND (decided_at AT TIME ZONE 'Africa/Nairobi')::date = :today"
            " AND status = 'approved' FROM quiz_sets WHERE id = :s",
            admin=p.admin,
            today=today,
            s=set_id,
        )
        assert decided is True  # by the admin, on the shared clock
        detail = "SELECT decided_by, llm_trace_id FROM app_quiz_set_detail(:s)"
        await t.act(conn, p.admin)
        assert tuple((await conn.execute(sa.text(detail), {"s": set_id})).one()) == (p.admin, f"quiz-{set_id.hex}")
        await t.expect(conn, detail, "no quiz set with that id", s=uuid7())
        for column in ("decided_by", "decided_at", "llm_trace_id", "*"):  # staff too: the function only
            await t.expect(conn, f"SELECT {column} FROM quiz_sets WHERE id = :s", DENIED, s=set_id)
        await t.act(conn, p.developer)
        assert await t.run(conn, "SELECT count(*) FROM quiz_sets WHERE id = :s", s=set_id) == 1
        for column in ("decided_by", "decided_at", "llm_trace_id"):
            await t.expect(conn, f"SELECT {column} FROM quiz_sets WHERE id = :s", DENIED, s=set_id)
        visible = "SELECT id, quiz_date, status, origin, created_at FROM quiz_sets WHERE id = :s"
        assert (await conn.execute(sa.text(visible), {"s": set_id})).one().status == "approved"
        for user in (p.developer, p.moderator, None):
            await t.act(conn, user)
            await t.expect(conn, detail, "staff admin only", s=set_id)
        await t.as_owner(conn)
        for assignment in ("status = 'draft'", "status = 'rejected'", "quiz_date = quiz_date + 1", "origin = 'seeded'"):
            await t.expect(conn, f"UPDATE quiz_sets SET {assignment} WHERE id = :s", "quiz_sets: a ", s=set_id)
        await t.expect(conn, JOB_QUESTION, "only to a draft set", **question(set_id, 5))
        for assignment in ("prompt = 'Changed?'", "answer = 0", "why = 'Other.'", "position = 5"):
            await t.expect(
                conn, f"UPDATE quiz_questions SET {assignment} WHERE id = :q", "pull or restore", q=questions[0]
            )
        await t.expect(
            conn, "UPDATE quiz_questions SET status = 'pulled' WHERE id = :q", "pull_complete", q=questions[0]
        )


async def test_a_question_holds_four_distinct_options_one_answer_and_a_sourced_why(owner_engine: AsyncEngine) -> None:
    """The job's question is checked: position 1 to 5, a prompt of at most 300 characters, four distinct options of at
    most 120, an answer 0 to 3, a why of at most 600, an https source, no control character, a 32-byte hash."""
    async with t.as_app(owner_engine) as conn:
        await people(conn)
        today = await free_day(conn)
        set_id, _ = await draft(conn, today, count=0)
        cases: tuple[tuple[dict[str, Any], str], ...] = (
            ({"position": 6}, "position_range"),
            ({"prompt": "x" * 301}, "prompt_valid"),
            ({"prompt": "  "}, "prompt_valid"),
            ({"prompt": "Line\nbreak?"}, "prompt_valid"),
            ({"options": ["A", "B", "C"]}, "options_valid"),
            ({"options": ["A", "B", "C", "D", "E"]}, "options_valid"),
            ({"options": ["A", "B", "C", "A"]}, "options_valid"),
            ({"options": ["A", "B", "C", None]}, "options_valid"),
            ({"options": ["A", "B", "C", " "]}, "options_valid"),
            ({"options": ["A", "B", "C", "d" * 121]}, "options_valid"),
            ({"answer": 4}, "answer_range"),
            ({"answer": -1}, "answer_range"),
            ({"why": "w" * 601}, "why_valid"),
            ({"source_id": "has space"}, "source_id_valid"),
            ({"source_url": "http://docs.python.org/3/"}, "source_url_valid"),
            ({"source_url": "https://docs.python.org/a b"}, "source_url_valid"),
            ({"source_title": "t" * 161}, "source_title_valid"),
            ({"topic": ""}, "topic_valid"),
            ({"hash": b"short"}, "prompt_hash_length"),
        )
        for overrides, constraint in cases:
            await t.expect(conn, JOB_QUESTION, constraint, **(question(set_id, 1) | overrides))
        edge = {"prompt": "p" * 300, "options": ["a" * 120, "B", "C", "D"], "why": "w" * 600, "answer": 3}
        await t.run(conn, JOB_QUESTION, **question(set_id, 1, **edge))


async def test_developers_read_approved_sets_without_answers_until_they_played(owner_engine: AsyncEngine) -> None:
    """A developer reads today's approved set and its questions but no draft and no approved set of a later day; never
    the answer or the why directly; ``app_quiz_answers`` returns them only after their own attempt; staff admin reads
    every set and every answer; an organisation-only account and a moderator read nothing."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        set_id, questions = await approved(conn, today, p.admin)
        tomorrow, _ = await draft(conn, today + timedelta(days=1))
        ahead, _ = await approved(conn, today + timedelta(days=2), p.admin)  # approved early: not shown before its day
        answers = "SELECT question_id, answer, why FROM app_quiz_answers(:s)"
        sets = "SELECT count(*) FROM quiz_sets WHERE id IN (:a, :b, :c)"
        their_questions = "SELECT count(*) FROM quiz_questions WHERE set_id IN (:a, :b, :c)"
        await t.act(conn, p.developer)
        assert await t.run(conn, sets, a=set_id, b=tomorrow, c=ahead) == 1
        assert await t.run(conn, their_questions, a=set_id, b=tomorrow, c=ahead) == 5
        visible = "SELECT prompt, options, source_url, status, prompt_hash FROM quiz_questions WHERE set_id = :s"
        assert len((await conn.execute(sa.text(visible), {"s": set_id})).all()) == 5
        for column in ("answer", "why", "*"):
            await t.expect(conn, f"SELECT {column} FROM quiz_questions WHERE set_id = :s", DENIED, s=set_id)
        assert (await conn.execute(sa.text(answers), {"s": set_id})).all() == []
        await attempt(conn, set_id, p.developer, [1, 2, None, 0, 0])
        mine = (await conn.execute(sa.text(answers), {"s": set_id})).all()
        assert [(row.question_id, row.answer) for row in mine] == list(zip(questions, KEY, strict=True))
        assert {row.why for row in mine} == {"Because the documentation says so."}
        await t.act(conn, p.other)
        assert (await conn.execute(sa.text(answers), {"s": set_id})).all() == []  # another developer's attempt
        for user in (p.org_only, p.moderator):
            await t.act(conn, user)
            for table in ("quiz_sets", "quiz_questions", "quiz_attempts", "quiz_flags", "quiz_profiles"):
                assert await t.run(conn, f"SELECT count(*) FROM {table}") == 0, table
            assert (await conn.execute(sa.text(answers), {"s": set_id})).all() == []
        await t.act(conn, p.admin)
        assert await t.run(conn, sets, a=set_id, b=tomorrow, c=ahead) == 3
        assert await t.run(conn, their_questions, a=set_id, b=tomorrow, c=ahead) == 15
        assert len((await conn.execute(sa.text(answers), {"s": tomorrow})).all()) == 5  # a draft's, for the queue
        await t.expect(conn, "SELECT answer FROM quiz_questions", DENIED)  # staff too: the function only


async def test_staff_and_suspended_accounts_neither_play_nor_flag_nor_rank(owner_engine: AsyncEngine) -> None:
    """Staff are no developers, even with a developer profile (they approve the sets), and nor is a suspended
    developer: neither reads a set, plays, flags or opens the board, and neither shows on a developer's board, though
    each has an opted-in attempt this week (written before the suspension or by the owner)."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        set_id, questions = await approved(conn, today, p.admin)
        await t.as_owner(conn)
        staff = await developer(conn, "staffdev")
        await t.run(conn, "UPDATE users SET staff_role = 'moderator', totp_enabled_at = now() WHERE id = :u", u=staff)
        suspended = await developer(conn, "suspended")
        opted = "INSERT INTO quiz_profiles (user_id, leaderboard_opt_in) VALUES (:u, true)"
        for user in (p.developer, suspended):
            assert await attempt(conn, set_id, user, list(KEY)) == 5
            await t.run(conn, opted, u=user)
        await t.act(conn, staff)
        await t.expect(conn, ATTEMPT, RLS, id=uuid7(), set=set_id, user=staff, answers=list(KEY), ms=1)
        await owner_attempt(conn, set_id, staff, list(KEY))
        await t.run(conn, opted, u=staff)
        await t.run(conn, "UPDATE users SET status = 'suspended' WHERE id = :u", u=suspended)
        for user in (staff, suspended):
            await t.act(conn, user)
            assert await t.run(conn, "SELECT app_is_developer()") is False
            assert await t.run(conn, "SELECT count(*) FROM quiz_sets WHERE id = :s", s=set_id) == 0
            await t.expect(
                conn, FLAG, "no question of an approved set", question=questions[0], reason="other", note=None
            )
            await t.expect(conn, BOARD, "developers only")
        await t.act(conn, suspended)
        await t.expect(conn, ATTEMPT, RLS, id=uuid7(), set=set_id, user=suspended, answers=list(KEY), ms=1)
        await t.act(conn, p.developer)
        assert await t.run(conn, "SELECT app_is_developer()") is True
        board = [tuple(row) for row in await conn.execute(sa.text(BOARD))]
        assert board == [(1, f"dev-{p.developer.hex}", 5, 60000, True)]  # neither staff nor the suspended account


async def test_one_attempt_per_developer_on_todays_approved_set_scored_by_the_database(
    owner_engine: AsyncEngine,
) -> None:
    """A developer's attempt is their own, on today's approved set only (not a draft, a rejected set or another day's
    set), once; its five answers are each NULL or 0 to 3; the database scores it whatever is sent and times it; the
    app never updates or deletes it, and the owner changes only its score, and only to the computed one."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        set_id, _ = await approved(conn, today, p.admin)
        tomorrow, _ = await draft(conn, today + timedelta(days=1))
        yesterday, _ = await owner_set(conn, today - timedelta(days=1))
        rejected, _ = await draft(conn, today + timedelta(days=2))
        await t.act(conn, p.admin)
        await t.run(conn, DECIDE, set=rejected, decision="rejected")
        await t.act(conn, p.developer)
        for other_set, refusal in (
            (tomorrow, "only on an approved set"),
            (rejected, "only on an approved set"),
            (uuid7(), "only on an approved set"),
            (yesterday, RLS),
        ):
            await t.expect(conn, ATTEMPT, refusal, id=uuid7(), set=other_set, user=p.developer, answers=[1] * 5, ms=1)
        for answers in ([1, 2, 3, 0], [1, 2, 3, 0, 1, 2], [4, 2, 3, 0, 1], [-1, 2, 3, 0, 1], [[1, 2], [3, 0]]):
            await t.expect(
                conn, ATTEMPT, "answers_valid", id=uuid7(), set=set_id, user=p.developer, answers=answers, ms=1
            )
        shifted = (
            "INSERT INTO quiz_attempts (id, set_id, user_id, answers, time_ms)"
            " VALUES (uuid7(), :s, :u, CAST('[0:4]={1,2,3,0,1}' AS smallint[]), 1)"
        )
        await t.expect(conn, shifted, "answers_valid", s=set_id, u=p.developer)
        await t.expect(conn, ATTEMPT, "time_ms_range", id=uuid7(), set=set_id, user=p.developer, answers=[1] * 5, ms=-1)
        await t.expect(conn, ATTEMPT, RLS, id=uuid7(), set=set_id, user=p.other, answers=[1] * 5, ms=1)
        for column, value in (("score", "5"), ("finished_at", "now()"), ("created_at", "now()")):
            named = (
                f"INSERT INTO quiz_attempts (id, set_id, user_id, answers, time_ms, {column})"
                f" VALUES (uuid7(), :s, :u, '{{1,2,3,0,1}}', 1, {value})"
            )
            await t.expect(conn, named, DENIED, s=set_id, u=p.developer)
        assert await attempt(conn, set_id, p.developer, [1, 2, None, 0, 3], ms=42000) == 3
        await t.expect(
            conn,
            ATTEMPT,
            "uq_quiz_attempts_set_id_user_id",
            id=uuid7(),
            set=set_id,
            user=p.developer,
            answers=[1] * 5,
            ms=1,
        )
        mine = (
            await conn.execute(
                sa.text(
                    "SELECT id, user_id, score, time_ms, (finished_at AT TIME ZONE 'Africa/Nairobi')::date AS day"
                    " FROM quiz_attempts WHERE set_id = :s"
                ),
                {"s": set_id},
            )
        ).one()
        assert (mine.user_id, mine.score, mine.time_ms, mine.day) == (p.developer, 3, 42000, today)  # the clock's
        assert await attempt(conn, set_id, p.other, [None] * 5) == 0  # all skipped
        await t.act(conn, p.org_only)
        await t.expect(conn, ATTEMPT, RLS, id=uuid7(), set=set_id, user=p.org_only, answers=[1] * 5, ms=1)
        await t.act(conn, p.developer)
        for statement in (
            "UPDATE quiz_attempts SET score = 5",
            "UPDATE quiz_attempts SET answers = '{1,2,3,0,1}'",
            "DELETE FROM quiz_attempts",
            "TRUNCATE quiz_attempts",
        ):
            await t.expect(conn, statement, DENIED)
        await t.as_owner(conn)
        for assignment in ("score = 5", "answers = '{1,2,3,0,1}'", "time_ms = 1", "user_id = :other"):
            await t.expect(
                conn,
                f"UPDATE quiz_attempts SET {assignment} WHERE id = :id",
                "only by its rescore",
                id=mine.id,
                other=p.other,
            )
        assert await t.rowcount(conn, "UPDATE quiz_attempts SET score = 3 WHERE id = :id", id=mine.id) == 1


async def test_three_developers_flags_pull_a_question_and_every_attempt_is_rescored(owner_engine: AsyncEngine) -> None:
    """A developer flags a live question of an approved set once, with a reason code and an optional note; the third
    developer's flag pulls it (``three_flags``) and rescores the set: a right answer on it counts no more; a pulled
    question takes no flag. Staff admin restores it (rescoring again) and pulls another with a reason; a restored
    question is not pulled again by a fourth flag; flags never change."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        set_id, questions = await approved(conn, today, p.admin)
        _, later = await draft(conn, today + timedelta(days=1))
        await qualify(conn, today, [p.developer, p.other, p.third, p.fourth])
        assert await attempt(conn, set_id, p.developer, list(KEY)) == 5
        assert await attempt(conn, set_id, p.other, [0, 2, 3, 0, 1]) == 4  # wrong on question 1
        assert await attempt(conn, set_id, p.third, [None] * 5) == 0
        await t.act(conn, p.developer)
        for reason, note, refusal in (
            ("spam", None, "a reason of"),
            ("unclear", " ", "a reason of"),
            ("unclear", "n" * 301, "a reason of"),
            (None, None, "a reason of"),
        ):
            await t.expect(conn, FLAG, refusal, question=questions[0], reason=reason, note=note)
        for unknown in (uuid7(), later[0]):  # no such question; a draft's
            await t.expect(conn, FLAG, "no question of an approved set", question=unknown, reason="other", note=None)
        await t.act(conn, p.fourth)  # a developer who has not played the set
        savepoint = await conn.begin_nested()
        with pytest.raises(DBAPIError, match="play the set first") as refused:
            await conn.execute(sa.text(FLAG), {"question": questions[0], "reason": "other", "note": None})
        await savepoint.rollback()
        assert isinstance(refused.value.orig, psycopg.Error)
        assert refused.value.orig.sqlstate == "42501"  # insufficient_privilege: the API's 403 play_first
        await t.act(conn, p.developer)
        first = (
            await conn.execute(
                sa.text(FLAG), {"question": questions[0], "reason": "wrong_answer", "note": "The answer is Alpha."}
            )
        ).one()
        assert first.pulled is False
        await t.expect(conn, FLAG, "already flagged by the caller", question=questions[0], reason="other", note=None)
        for user in (p.org_only, p.admin, None):  # they read no question: for them it does not exist
            await t.act(conn, user)
            unseen = {"question": questions[0], "reason": "other", "note": None}
            await t.expect(conn, FLAG, "no question of an approved set", **unseen)
        assert await flag(conn, p.other, questions[0], "outdated") is False
        assert await scores(conn, set_id) == {p.developer: 5, p.other: 4, p.third: 0}
        assert await flag(conn, p.third, questions[0], "unclear") is True
        assert await scores(conn, set_id) == {p.developer: 4, p.other: 4, p.third: 0}
        pulled = "SELECT status, pulled_reason, pulled_at IS NOT NULL AS dated FROM quiz_questions WHERE id = :q"
        assert tuple((await conn.execute(sa.text(pulled), {"q": questions[0]})).one()) == (
            "pulled",
            "three_flags",
            True,
        )
        await t.act(conn, p.fourth)
        await t.expect(conn, FLAG, "play the set first", question=questions[0], reason="other", note=None)
        assert await attempt(conn, set_id, p.fourth, [None] * 5) == 0
        await t.expect(conn, FLAG, "the question was pulled", question=questions[0], reason="other", note=None)
        assert await t.run(conn, "SELECT count(*) FROM quiz_flags") == 0  # their own: none
        await t.act(conn, p.developer)
        assert await t.run(conn, "SELECT count(*) FROM quiz_flags") == 1
        await t.expect(conn, "UPDATE quiz_flags SET reason = 'other'", DENIED)
        await t.expect(conn, "DELETE FROM quiz_flags", DENIED)
        await t.expect(
            conn,
            "INSERT INTO quiz_flags (id, question_id, user_id, reason) VALUES (uuid7(), :q, :u, 'other')",
            DENIED,
            q=questions[1],
            u=p.developer,
        )
        await t.as_owner(conn)
        await t.expect(conn, "UPDATE quiz_flags SET reason = 'other'", "append-only")
        for user in (p.developer, p.moderator, None):
            await t.act(conn, user)
            await t.expect(conn, SET_STATUS, "staff admin only", question=questions[0], status="live", reason=None)
        await t.act(conn, p.admin)
        assert await t.run(conn, "SELECT count(*) FROM quiz_flags WHERE question_id = :q", q=questions[0]) == 3
        for status, reason in (("live", "Because"), ("pulled", None), ("pulled", " "), ("gone", None)):
            await t.expect(
                conn, SET_STATUS, "pulled with a reason", question=questions[0], status=status, reason=reason
            )
        await t.expect(conn, SET_STATUS, "no quiz question", question=uuid7(), status="live", reason=None)
        assert await t.run(conn, SET_STATUS, question=questions[0], status="live", reason=None) == 1
        await t.expect(conn, SET_STATUS, "already live", question=questions[0], status="live", reason=None)
        assert await scores(conn, set_id) == {p.developer: 5, p.other: 4, p.third: 0, p.fourth: 0}
        await t.act(conn, p.admin)
        assert await t.run(conn, SET_STATUS, question=questions[1], status="pulled", reason="Two answers fit.") == 2
        assert await scores(conn, set_id) == {p.developer: 4, p.other: 3, p.third: 0, p.fourth: 0}
        assert await flag(conn, p.fourth, questions[0]) is False  # a fourth flag: staff restored it, it stays live
        await t.as_owner(conn)
        assert await t.run(conn, "SELECT status FROM quiz_questions WHERE id = :q", q=questions[0]) == "live"
        for user in (p.admin, None):  # staff admin or a repair job: nothing left to change
            await t.act(conn, user)
            assert await t.run(conn, "SELECT app_rescore_quiz_set(:s)", s=set_id) == 0
        await t.act(conn, p.developer)
        await t.expect(conn, "SELECT app_rescore_quiz_set(:s)", "staff admin, or a job", s=set_id)
        await t.act(conn, p.admin)
        await t.expect(conn, "SELECT app_rescore_quiz_set(:s)", "no quiz set", s=uuid7())


async def test_a_staff_restore_is_never_overturned_by_flags(owner_engine: AsyncEngine) -> None:
    """A question staff pulled and restored with two flags is not pulled by a third or a fourth; a question the flags
    pulled and staff restored is not pulled again when a flagger's account is deleted (their flags go with it) and a
    new flag brings the count back to three. A restore is never undone, for the owner too."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        set_id, questions = await approved(conn, today, p.admin)
        await qualify(conn, today, [p.developer, p.other, p.third, p.fourth])
        for user in (p.developer, p.other, p.third, p.fourth):
            await attempt(conn, set_id, user, list(KEY))
        status = "SELECT status, restored_at IS NOT NULL AS restored FROM quiz_questions WHERE id = :q"
        assert await flag(conn, p.developer, questions[0]) is False
        assert await flag(conn, p.other, questions[0]) is False
        await t.act(conn, p.admin)
        await t.run(conn, SET_STATUS, question=questions[0], status="pulled", reason="Checking the key.")
        await t.run(conn, SET_STATUS, question=questions[0], status="live", reason=None)
        assert await flag(conn, p.third, questions[0]) is False
        assert await flag(conn, p.fourth, questions[0]) is False
        assert tuple((await conn.execute(sa.text(status), {"q": questions[0]})).one()) == ("live", True)
        for user in (p.developer, p.other):
            assert await flag(conn, user, questions[1]) is False
        assert await flag(conn, p.third, questions[1]) is True
        await t.act(conn, p.admin)
        await t.run(conn, SET_STATUS, question=questions[1], status="live", reason=None)
        await t.as_owner(conn)
        await t.run(conn, "DELETE FROM users WHERE id = :u", u=p.third)  # their attempt and flags go with them
        assert await t.run(conn, "SELECT count(*) FROM quiz_flags WHERE question_id = :q", q=questions[1]) == 2
        assert await flag(conn, p.fourth, questions[1]) is False  # three flags again: staff restored it
        assert tuple((await conn.execute(sa.text(status), {"q": questions[1]})).one()) == ("live", True)
        await t.as_owner(conn)
        await t.expect(
            conn, "UPDATE quiz_questions SET restored_at = NULL WHERE id = :q", "never undone", q=questions[1]
        )


async def test_only_flags_of_verified_accounts_with_a_history_pull_a_question(owner_engine: AsyncEngine) -> None:
    """Flags count towards the automatic pull only from accounts with a verified email and three finished attempts on
    sets of earlier days: three fresh accounts, an unverified one with a history and a verified one with two earlier
    attempts (and today's) pull nothing, though every flag is kept for staff; the third counted flag pulls it."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        set_id, questions = await approved(conn, today, p.admin)
        await t.as_owner(conn)
        fresh = [await developer(conn, f"fresh{n}") for n in range(3)]
        unverified, short = await developer(conn, "unverified"), await developer(conn, "short")
        await qualify(conn, today, [p.developer, p.other, unverified])
        await t.run(conn, "UPDATE users SET email_verified_at = NULL WHERE id = :u", u=unverified)
        for back in (1, 2):
            past, _ = await owner_set(conn, today - timedelta(days=back))
            await owner_attempt(conn, past, short)
        await t.run(conn, "UPDATE users SET email_verified_at = now() WHERE id = :u", u=short)
        flaggers = [*fresh, unverified, short, p.developer, p.other]
        for user in flaggers:
            await attempt(conn, set_id, user, list(KEY))
        for user in flaggers[:5]:
            assert await flag(conn, user, questions[0]) is False
        assert await flag(conn, p.developer, questions[0]) is False  # one counted flag
        assert await flag(conn, p.other, questions[0]) is False  # two
        await t.act(conn, p.admin)
        assert await t.run(conn, "SELECT count(*) FROM quiz_flags WHERE question_id = :q", q=questions[0]) == 7
        assert await t.run(conn, "SELECT status FROM quiz_questions WHERE id = :q", q=questions[0]) == "live"
        await t.as_owner(conn)
        await qualify(conn, today + timedelta(days=-3), [p.third])  # days 7 to 9 before today
        await attempt(conn, set_id, p.third, list(KEY))
        assert await flag(conn, p.third, questions[0]) is True  # the third counted flag


async def test_at_most_ten_flags_a_nairobi_day_per_developer(owner_engine: AsyncEngine) -> None:
    """Ten flags in a Nairobi day, then the eleventh is refused (a fixed limit); the next day, flags are taken again;
    another developer has their own ten. Each flags questions of sets they played."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        set_id, questions = await approved(conn, today, p.admin)
        sets = [set_id]
        for back in (1, 2):
            past, ids = await owner_set(conn, today - timedelta(days=back))
            sets.append(past)
            questions += ids
        for played in sets:
            await owner_attempt(conn, played, p.developer)
        await owner_attempt(conn, sets[2], p.other)
        for question_id in questions[:10]:
            assert await flag(conn, p.developer, question_id) is False
        await t.expect(conn, FLAG, "at most 10 flags a day", question=questions[10], reason="other", note=None)
        assert await flag(conn, p.other, questions[10]) is False
        offset = "UPDATE test_clock SET clock_offset = clock_offset + interval '1 day'"
        await t.as_owner(conn)
        await t.run(conn, offset)
        assert await flag(conn, p.developer, questions[10]) is False


async def test_a_developer_reads_and_writes_only_their_own_attempts_flags_and_profile(
    owner_engine: AsyncEngine,
) -> None:
    """Developers read only their own attempts, flags and quiz profile; staff admin reads flags (the queue), a set's
    attempts only in aggregate (``app_quiz_set_stats``) and never a profile; a profile is inserted and updated by its
    developer only, its streak checked, its key and time never written; an organisation-only account cannot create
    one."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        set_id, questions = await approved(conn, today, p.admin)
        profile = (
            "INSERT INTO quiz_profiles (user_id, leaderboard_opt_in, current_streak, best_streak, last_played_on)"
            " VALUES (:u, :opt, :streak, :best, :day)"
        )
        for user in (p.developer, p.other):
            await attempt(conn, set_id, user, list(KEY))
            await flag(conn, user, questions[0])
            await t.run(conn, profile, u=user, opt=True, streak=1, best=1, day=today)
        for user, other in ((p.developer, p.other), (p.other, p.developer)):
            await t.act(conn, user)
            for table in ("quiz_attempts", "quiz_flags", "quiz_profiles"):
                assert await t.run(conn, f"SELECT count(*) FROM {table}") == 1, table
                assert await t.run(conn, f"SELECT count(*) FROM {table} WHERE user_id = :o", o=other) == 0, table
            assert (
                await t.rowcount(conn, "UPDATE quiz_profiles SET current_streak = 0 WHERE user_id = :o", o=other) == 0
            )
        await t.act(conn, p.developer)
        await t.expect(conn, profile, RLS, u=p.third, opt=False, streak=0, best=0, day=None)
        await t.expect(conn, profile, "uq|pk_quiz_profiles", u=p.developer, opt=False, streak=0, best=0, day=None)
        await t.expect(conn, "UPDATE quiz_profiles SET best_streak = 0, current_streak = 1", "streaks_valid")
        assert (
            await t.rowcount(
                conn,
                "UPDATE quiz_profiles SET current_streak = 2, best_streak = 2, last_played_on = :d, leaderboard_opt_in"
                " = false",
                d=today,
            )
            == 1
        )
        for assignment in ("user_id = :o", "created_at = now()"):
            await t.expect(conn, f"UPDATE quiz_profiles SET {assignment}", DENIED, o=p.third)
        await t.expect(conn, "DELETE FROM quiz_profiles", DENIED)
        await t.act(conn, p.org_only)
        await t.expect(conn, profile, RLS, u=p.org_only, opt=False, streak=0, best=0, day=None)
        await t.act(conn, p.admin)
        assert await t.run(conn, "SELECT count(*) FROM quiz_attempts") == 0  # no attempt row but one's own
        assert await t.run(conn, "SELECT count(*) FROM quiz_flags WHERE question_id = :q", q=questions[0]) == 2
        assert tuple((await conn.execute(sa.text(STATS), {"s": set_id})).one()) == (2, None, None)  # below 3: a count
        await attempt(conn, set_id, p.third, [1, 0, 3, None, 1])
        await t.act(conn, p.admin)
        stats = (await conn.execute(sa.text(STATS), {"s": set_id})).one()
        assert tuple(stats) == (3, Decimal("4.33"), [3, 2, 3, 2, 3])
        empty, _ = await draft(conn, today + timedelta(days=1))
        await t.act(conn, p.admin)
        assert tuple((await conn.execute(sa.text(STATS), {"s": empty})).one()) == (0, None, None)
        await t.expect(conn, STATS, "no quiz set with that id", s=uuid7())
        for caller in (p.developer, p.moderator, p.org_only, None):
            await t.act(conn, caller)
            await t.expect(conn, STATS, "staff admin only", s=set_id)
        await t.act(conn, p.admin)
        assert (
            await t.run(conn, "SELECT count(*) FROM quiz_profiles WHERE user_id IN (:a, :b)", a=p.developer, b=p.other)
            == 0
        )


async def test_the_board_is_this_weeks_opted_in_developers_by_points_then_time(owner_engine: AsyncEngine) -> None:
    """The board sums this ISO week's attempts on approved sets (last week's do not count) of active developers who
    opted in and are of the caller's kind: a real caller never sees a demo account, a demo caller sees only demo
    accounts (the local demo's people); more points first, then less time, equal both sharing a rank; the first 20
    rows by rank and handle, plus the caller's own row: the rank they would have among their kind when not opted in,
    none when they did not play. Developers only."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        today = await free_day(conn)
        this_week, _ = await approved(conn, today, p.admin)
        monday = today - timedelta(days=today.weekday())
        last_week, _ = await owner_set(conn, monday - timedelta(days=1))
        players: dict[str, UUID] = {}
        for label in ("ann", "ben", "cat", "dee", "eve", "fay", "gus", "hal", "ivy"):
            players[label] = await developer(conn, label)
        extras = [await developer(conn, f"x{n:02d}") for n in range(22)]
        opted = "INSERT INTO quiz_profiles (user_id, leaderboard_opt_in) VALUES (:u, :opt)"

        async def plays(user: UUID, answers: list[int | None], ms: int, opt: bool, *, set_id: UUID = this_week) -> None:
            await t.as_owner(conn)
            await t.run(
                conn,
                "INSERT INTO quiz_attempts (id, set_id, user_id, answers, time_ms) VALUES (uuid7(), :s,"
                " :u, CAST(:a AS smallint[]), :ms) ON CONFLICT DO NOTHING",
                s=set_id,
                u=user,
                a=answers,
                ms=ms,
            )
            await t.run(conn, opted + " ON CONFLICT (user_id) DO NOTHING", u=user, opt=opt)

        four = [1, 2, 3, 0, None]
        await plays(players["ann"], four, 50000, True)
        await plays(players["ben"], four, 40000, True)
        await plays(players["fay"], four, 40000, True)  # ties ben
        await plays(players["cat"], list(KEY), 10000, True)  # cat, gus, hal and ivy: demo accounts
        await plays(players["gus"], [1, 2, 3, None, None], 20000, True)
        await plays(players["hal"], four, 30000, False)  # not opted in
        demo = [players[label] for label in ("cat", "gus", "hal", "ivy")]  # ivy did not play
        await t.run(conn, "UPDATE users SET demo_account = true WHERE id = ANY(:u)", u=demo)
        await plays(players["dee"], list(KEY), 90000, False)  # not opted in
        await plays(players["ann"], list(KEY), 1000, True, set_id=last_week)  # last week: not counted
        for n, user in enumerate(extras):
            await plays(user, [1, None, None, None, None], 1000 + n, True)
        handle = {user: f"{label}-{user.hex}" for label, user in players.items()}
        handle |= {user: f"x{n:02d}-{user.hex}" for n, user in enumerate(extras)}

        async def board(user: UUID) -> list[tuple[Any, ...]]:
            await t.act(conn, user)
            return [tuple(row) for row in await conn.execute(sa.text(BOARD))]

        tied = sorted([handle[players["ben"]], handle[players["fay"]]])
        leaders = [(1, tied[0], 4, 40000), (1, tied[1], 4, 40000), (3, handle[players["ann"]], 4, 50000)]
        leaders += [(4 + n, handle[user], 1, 1000 + n) for n, user in enumerate(extras[:17])]
        seen = await board(players["ann"])
        assert [row[:4] for row in seen] == leaders  # 20 rows: the demo accounts and dee (not opted in) left out
        assert [row[1] for row in seen if row[4]] == [handle[players["ann"]]]
        last = await board(extras[21])
        assert last[:20] == [(*row, False) for row in leaders]
        assert last[20] == (25, handle[extras[21]], 1, 1021, True)
        dee = await board(players["dee"])
        assert (1, handle[players["dee"]], 5, 90000, True) in dee
        assert len(dee) == 21
        assert (await board(players["eve"]))[-1] == (None, handle[players["eve"]], 0, 0, True)  # did not play
        cat, gus = (1, handle[players["cat"]], 5, 10000), (2, handle[players["gus"]], 3, 20000)
        assert await board(players["cat"]) == [(*cat, True), (*gus, False)]  # demo accounts only
        hal = (2, handle[players["hal"]], 4, 30000, True)  # the rank hal would have among the demo accounts
        assert await board(players["hal"]) == [(*cat, False), (*gus, False), hal]
        assert await board(players["ivy"]) == [(*cat, False), (*gus, False), (None, handle[players["ivy"]], 0, 0, True)]
        for caller in (p.org_only, p.admin, None):
            await t.act(conn, caller)
            await t.expect(conn, BOARD, "developers only")
