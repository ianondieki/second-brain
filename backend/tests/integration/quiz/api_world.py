"""Helpers of the quiz API, job and store tests (REQ-DEV-01; P22 card A): a database of the module's own
(``conftest.quiz``), a fresh future week per test, the shared clock moved to a Nairobi day and time (committed, as the
dev and test clock is), the people (``schema_world.people``), sets written by ``store_draft`` and approved by a staff
admin through ``app_decide_quiz_set``, attempts written as the owner (as the seed may, on any day) and signed-in
clients of the in-process API."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Final, Literal
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.matching.trending import NAIROBI
from bridge.quiz.checks import AcceptedQuestion, prompt_hash
from bridge.quiz.store import Stored, store_draft
from tests.integration.api import make_client, sign_in_as
from tests.integration.quiz import schema_world as sw

KEY: Final = sw.KEY  # the answer of the question at each position 1 to 5
NO_REPEAT_DAYS: Final = 60
_CLOCK_TO: Final = text(
    "UPDATE test_clock SET enabled = true,"
    " clock_offset = (CAST(:day AS date) + CAST(:at AS time)) AT TIME ZONE 'Africa/Nairobi' - clock_timestamp()"
)


@dataclass
class QuizDb:
    """The module's database: the owner and bridge_app engines, and the weeks its tests took."""

    owner: AsyncEngine
    app: AsyncEngine
    weeks: list[date] = field(default_factory=list)

    def monday(self) -> date:
        """A Monday of the module's own, two weeks after the last one handed out (the first is three weeks ahead of
        the real date in Nairobi), so no two tests share a week, its neighbours or a 60-day window of prompts."""
        today = datetime.now(NAIROBI).date()
        first = today + timedelta(days=21 - today.weekday())
        monday = first + timedelta(days=14 * len(self.weeks))
        self.weeks.append(monday)
        return monday


async def at(quiz: QuizDb, day: date, clock: time = time(12, 0)) -> None:
    """Move the shared clock to ``clock`` in Nairobi on ``day`` (committed: the API reads it)."""
    async with quiz.owner.begin() as conn:
        await conn.execute(_CLOCK_TO, {"day": day, "at": clock})


async def owner_rows(quiz: QuizDb, sql: str, **params: object) -> list[Any]:
    async with quiz.owner.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def owner_run(quiz: QuizDb, sql: str, **params: object) -> None:
    async with quiz.owner.begin() as conn:
        await conn.execute(text(sql), params)


async def cast(quiz: QuizDb) -> sw.People:
    """Four developers, an organisation-only member, a staff admin and a staff moderator (committed)."""
    async with quiz.owner.begin() as conn:
        return await sw.people(conn)


async def developers(quiz: QuizDb, label: str, count: int) -> list[UUID]:
    async with quiz.owner.begin() as conn:
        return [await sw.developer(conn, f"{label}{n}") for n in range(count)]


async def handle_of(quiz: QuizDb, user: UUID) -> str:
    [row] = await owner_rows(quiz, "SELECT handle::text AS handle FROM developer_profiles WHERE user_id = :u", u=user)
    return str(row.handle)


def accepted(tag: str, position: int, answer: int) -> AcceptedQuestion:
    prompt = f"Which option is right for question {position} of set {tag}?"
    return AcceptedQuestion(
        position=position,
        prompt=prompt,
        options=("Alpha", "Beta", "Gamma", "Delta"),
        answer=answer,
        why=f"The page says option {answer} for question {position}.",
        source_id="python-datamodel",
        source_title="Python Language Reference: Data model",
        source_url="https://docs.python.org/3/reference/datamodel.html",
        topic="python",
        prompt_hash=prompt_hash(prompt),
    )


def accepted_set(key: Sequence[int] = KEY, tag: str | None = None) -> tuple[AcceptedQuestion, ...]:
    tag = tag or uuid7().hex
    return tuple(accepted(tag, position, answer) for position, answer in enumerate(key, start=1))


async def draft_set(
    quiz: QuizDb, day: date, key: Sequence[int] = KEY, *, role: Literal["job", "owner"] = "owner"
) -> UUID:
    """A draft set for ``day`` through ``store_draft``: as the job (bridge_app, no user bound: today or later) or as
    the owner (as the seed: any day)."""
    engine = quiz.app if role == "job" else quiz.owner
    origin: Literal["model", "seeded"] = "model" if role == "job" else "seeded"
    async with create_session_factory(engine)() as db:
        stored = await store_draft(
            db,
            day,
            accepted_set(key),
            origin=origin,
            trace_id=f"quiz:{day.isoformat()}:1" if role == "job" else None,
            no_repeat_days=NO_REPEAT_DAYS,
        )
    assert isinstance(stored, Stored), stored
    return stored.set_id


async def decide(quiz: QuizDb, set_id: UUID, admin: UUID, decision: str = "approved") -> None:
    """As the staff admin, through ``app_decide_quiz_set`` (the admin API's path)."""
    async with create_session_factory(quiz.app)() as db:
        await bind_tenant(db, user_id=admin)
        await db.execute(text("SELECT app_decide_quiz_set(:s, :d)"), {"s": set_id, "d": decision})
        await db.commit()


async def question_ids(quiz: QuizDb, set_id: UUID) -> list[UUID]:
    found = await owner_rows(quiz, "SELECT id FROM quiz_questions WHERE set_id = :s ORDER BY position", s=set_id)
    return [row.id for row in found]


async def approved_set(quiz: QuizDb, day: date, admin: UUID, key: Sequence[int] = KEY) -> tuple[UUID, list[UUID]]:
    set_id = await draft_set(quiz, day, key)
    await decide(quiz, set_id, admin)
    return set_id, await question_ids(quiz, set_id)


async def owner_attempt(
    quiz: QuizDb, set_id: UUID, user: UUID, answers: Sequence[int | None] = (None,) * 5, ms: int = 60_000
) -> None:
    """``user``'s attempt on an approved set of any day, as the owner (the score is the database's)."""
    await owner_run(
        quiz,
        "INSERT INTO quiz_attempts (id, set_id, user_id, answers, time_ms)"
        " VALUES (:id, :s, :u, CAST(:a AS smallint[]), :ms)",
        id=uuid7(),
        s=set_id,
        u=user,
        a=list(answers),
        ms=ms,
    )


async def established(quiz: QuizDb, today: date, admin: UUID, users: Sequence[UUID]) -> None:
    """Make ``users`` accounts whose flags count towards an automatic pull: a verified email and three attempts on
    sets of earlier days (sets 4 to 6 days before ``today``, made here)."""
    for back in (4, 5, 6):
        past, _ = await approved_set(quiz, today - timedelta(days=back), admin)
        for user in users:
            await owner_attempt(quiz, past, user)
    await owner_run(quiz, "UPDATE users SET email_verified_at = now() WHERE id = ANY(:u)", u=list(users))


async def scores(quiz: QuizDb, set_id: UUID) -> dict[UUID, int]:
    found = await owner_rows(quiz, "SELECT user_id, score FROM quiz_attempts WHERE set_id = :s", s=set_id)
    return {row.user_id: row.score for row in found}


async def audit_actions(quiz: QuizDb, subject: UUID) -> list[Any]:
    return await owner_rows(
        quiz,
        "SELECT action, actor_kind::text AS actor_kind, actor_user_id, payload FROM audit_events"
        " WHERE subject_id = :s ORDER BY occurred_at, seq",
        s=subject,
    )


class Clients:
    """Signed-in in-process API clients of the module's database (the second factor fresh unless asked)."""

    def __init__(self, quiz: QuizDb, stack: AsyncExitStack) -> None:
        self._quiz, self._stack = quiz, stack

    async def __call__(self, user_id: UUID, *, fresh: bool = True) -> httpx.AsyncClient:
        client = await self._stack.enter_async_context(make_client(self._quiz.app))
        await sign_in_as(client, self._quiz.app, user_id, mfa_verified=fresh)
        return client


@asynccontextmanager
async def clients(quiz: QuizDb) -> AsyncIterator[Clients]:
    async with AsyncExitStack() as stack:
        yield Clients(quiz, stack)


TODAY: Final = "/api/me/quiz/today"
ANSWERS: Final = "/api/me/quiz/today/answers"
BOARD: Final = "/api/me/quiz/leaderboard"
SETTINGS: Final = "/api/me/quiz/settings"
ADMIN: Final = "/api/admin/quiz"


def flag_path(question_id: UUID) -> str:
    return f"/api/me/quiz/questions/{question_id}/flag"


async def play(
    client: httpx.AsyncClient, set_id: UUID, answers: Sequence[int | None], ms: int = 30_000
) -> httpx.Response:
    return await client.post(ANSWERS, json={"set_id": str(set_id), "answers": list(answers), "time_ms": ms})


def code(response: httpx.Response) -> tuple[int, str | None]:
    """(status, error code) of a response."""
    detail = response.json().get("detail") if response.headers.get("content-type") == "application/json" else None
    return response.status_code, detail.get("code") if isinstance(detail, dict) else None
