"""Fixtures of the quiz schema tests (revision 0009, REQ-DEV-01): the people, the shared clock moved to a free Nairobi
day, a set drafted by the job (bridge_app with no user bound) and approved by staff admin, a seeded set the owner writes
for any day, an attempt and a flag as a developer. Every helper runs inside one transaction of the owner engine
(``tracker.as_app``) and switches the role as it acts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t

RLS = "row-level security"
DENIED = "permission denied"
KEY = (1, 2, 3, 0, 1)  # the answer of the question at each position 1 to 5
JOB_SET = "INSERT INTO quiz_sets (id, quiz_date, origin, llm_trace_id) VALUES (:id, :day, 'model', :trace)"
JOB_QUESTION = (
    "INSERT INTO quiz_questions (id, set_id, position, prompt, options, answer, why, source_id, source_title,"
    " source_url, topic, prompt_hash) VALUES (:id, :set, :position, :prompt, :options, :answer, :why, :source_id,"
    " :source_title, :source_url, :topic, :hash)"
)
ATTEMPT = (
    "INSERT INTO quiz_attempts (id, set_id, user_id, answers, time_ms)"
    " VALUES (:id, :set, :user, CAST(:answers AS smallint[]), :ms) RETURNING score"
)
DECIDE = "SELECT app_decide_quiz_set(:set, :decision)"
SET_STATUS = "SELECT app_set_quiz_question_status(:question, :status, :reason)"
FLAG = "SELECT flag_id, pulled FROM app_flag_question(:question, :reason, :note)"
SCORES = "SELECT user_id, score FROM quiz_attempts WHERE set_id = :set"


@dataclass(frozen=True, slots=True)
class People:
    developer: UUID
    other: UUID
    third: UUID
    fourth: UUID
    org_only: UUID  # a member of an organisation, no developer profile
    admin: UUID  # staff admin with TOTP, no developer profile
    moderator: UUID  # staff moderator with TOTP


async def developer(conn: AsyncConnection, label: str) -> UUID:
    """As the owner: an active user with a developer profile (handle ``<label>-<hex>``)."""
    user = await w.add_user(conn, f"{label}-{uuid7().hex}@example.test", label.title())
    await t.run(
        conn, "INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)", u=user, h=f"{label}-{user.hex}"
    )
    return user


async def people(conn: AsyncConnection) -> People:
    devs = [await developer(conn, label) for label in ("dev", "other", "third", "fourth")]
    org_only = await w.add_user(conn, f"org-{uuid7().hex}@example.test", "Org member")
    org = uuid7()
    await t.run(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source) VALUES (:id, 'company', 'Quiz Ltd', :slug,"
        " 'self_signup')",
        id=org,
        slug=f"quiz-{org.hex}",
    )
    await t.member(conn, org, org_only, "{owner,admin}")
    admin = await w.add_user(conn, f"admin-{uuid7().hex}@example.test", "Admin", staff_role="admin")
    moderator = await w.add_user(conn, f"mod-{uuid7().hex}@example.test", "Moderator", staff_role="moderator")
    return People(devs[0], devs[1], devs[2], devs[3], org_only=org_only, admin=admin, moderator=moderator)


async def free_day(conn: AsyncConnection, *, offset_days: int = 120) -> date:
    """As the owner, in this transaction only: move the shared clock ahead to a Nairobi day with no set within a week
    before its Monday or two weeks after (other tests of the session may have committed sets), and return it."""
    for days in range(offset_days, 358, 9):
        await t.run(conn, "UPDATE test_clock SET enabled = true, clock_offset = make_interval(days => :d)", d=days)
        today: date = await t.run(conn, "SELECT app_nairobi_today()")
        monday = today - timedelta(days=today.weekday())
        busy = "SELECT EXISTS (SELECT 1 FROM quiz_sets WHERE quiz_date BETWEEN :a AND :b)"
        if not await t.run(conn, busy, a=monday - timedelta(days=7), b=monday + timedelta(days=13)):
            return today
    raise AssertionError("no free quiz day within the test clock's reach")


def question(set_id: UUID, position: int, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid7(),
        "set": set_id,
        "position": position,
        "prompt": f"Which option is the right one for question {position}?",
        "options": ["Alpha", "Beta", "Gamma", "Delta"],
        "answer": KEY[position - 1],
        "why": "Because the documentation says so.",
        "source_id": "python-docs",
        "source_title": "Python documentation",
        "source_url": "https://docs.python.org/3/",
        "topic": "python",
        "hash": hashlib.sha256(f"{set_id} {position}".encode()).digest(),
    }
    return params | overrides


async def draft(conn: AsyncConnection, day: date, *, count: int = 5) -> tuple[UUID, list[UUID]]:
    """As the job (bridge_app, no user bound): a draft set for ``day`` and its first ``count`` questions."""
    await t.act(conn, None)
    set_id = uuid7()
    await t.run(conn, JOB_SET, id=set_id, day=day, trace=f"quiz-{set_id.hex}")
    ids = []
    for position in range(1, count + 1):
        params = question(set_id, position)
        await t.run(conn, JOB_QUESTION, **params)
        ids.append(params["id"])
    return set_id, ids


async def approved(conn: AsyncConnection, day: date, admin: UUID) -> tuple[UUID, list[UUID]]:
    """A set for ``day`` (today or later) drafted by the job and approved by ``admin``."""
    set_id, ids = await draft(conn, day)
    await t.act(conn, admin)
    await t.run(conn, DECIDE, set=set_id, decision="approved")
    return set_id, ids


async def owner_set(conn: AsyncConnection, day: date) -> tuple[UUID, list[UUID]]:
    """As the owner (as the seed may): an approved seeded set for any ``day``, past ones included."""
    await t.as_owner(conn)
    set_id = uuid7()
    await t.run(conn, "INSERT INTO quiz_sets (id, quiz_date, origin) VALUES (:id, :day, 'seeded')", id=set_id, day=day)
    ids = []
    for position in range(1, 6):
        params = question(set_id, position)
        await t.run(conn, JOB_QUESTION, **params)
        ids.append(params["id"])
    approve = "UPDATE quiz_sets SET status = 'approved', decided_at = app_clock_now() WHERE id = :id"
    await t.run(conn, approve, id=set_id)
    return set_id, ids


async def attempt(conn: AsyncConnection, set_id: UUID, user: UUID, answers: list[int | None], ms: int = 60000) -> int:
    """As ``user`` (bridge_app): their attempt; returns the database's score."""
    await t.act(conn, user)
    score: int = await t.run(conn, ATTEMPT, id=uuid7(), set=set_id, user=user, answers=answers, ms=ms)
    return score


async def scores(conn: AsyncConnection, set_id: UUID) -> dict[UUID, int]:
    await t.as_owner(conn)
    return {row.user_id: row.score for row in await conn.execute(sa.text(SCORES), {"set": set_id})}


async def flag(conn: AsyncConnection, user: UUID, question_id: UUID, reason: str = "wrong_answer") -> bool:
    """As ``user``: flag the question; returns whether the flag pulled it."""
    await t.act(conn, user)
    row = (await conn.execute(sa.text(FLAG), {"question": question_id, "reason": reason, "note": None})).one()
    return bool(row.pulled)
