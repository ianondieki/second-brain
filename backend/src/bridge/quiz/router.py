"""Today's five, the developer's API (REQ-DEV-01; D-59; P22 card A): ``/api/me/quiz/*``.

Developers only: every route asks ``app_is_developer()`` first (an active user with a developer profile and no staff
role), so an organisation-only account and staff (who approve the sets, so never play or rank) get 404 on every route;
signed out is 401 as on every ``/api/me`` route. Row-Level Security repeats the rule: a developer reads approved sets
up to today and their questions (never ``answer`` or ``why``: those come from ``app_quiz_answers`` once the caller has
an attempt on the set), and their own attempts, flags and quiz profile only.

- ``GET /today``: the approved set of the current Nairobi day on the shared clock, its questions in order (the answer
  and the why only once the caller finished), the caller's attempt, streak and leaderboard opt-in; 404 ``no_quiz``
  when the day has no approved set (a draft is never served).
- ``POST /today/answers`` ``{set_id, answers, time_ms}``: 201, the one finished attempt on that set, scored by the
  database from the live questions (a pulled question counts for nobody), with the answer key, whys and sources and the
  streak after it (kept in code: ``bridge.quiz.streaks``: consecutive days that had an approved set played; a day
  without one breaks nobody's streak). 404 ``no_quiz`` (no approved set with that id), 409
  ``set_closed`` (the set's day is over on the shared clock), 409 ``already_played``, 422 on shape. The profile is
  written first and the attempt last, outside any savepoint, and nothing of the score or key is returned before the
  commit succeeded (revision 0009's operating rules: no rolled-back insert can be an oracle for the key).
- ``POST /questions/{id}/flag`` ``{reason, note?}``: 201 ``{flag_id, pulled}`` through ``app_flag_question``: 404
  (no question of an approved set of the caller's), 403 ``play_first``, 409 ``already_flagged`` or
  ``question_pulled``, 429 ``flag_limit`` (10 a Nairobi day). When the flag pulled the question (three counted flags),
  the audit event ``quiz.question_pulled`` (system actor, reason ``flags``). The note is for staff only: never logged
  or audited.
- ``GET /leaderboard``: this ISO week (Monday to Sunday, Nairobi), the first 20 opted-in developers of the caller's
  kind (real or demo accounts) by points then less time, by handle, and the caller's own points and rank (the rank
  they would have, also when not opted in; null when they did not play this week). One statement
  (``app_quiz_board()``).
- ``PUT /settings`` ``{leaderboard_opt_in}``: the caller's opt-in (their own state: no audit event).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated, Any, Final, Literal, get_args
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import Row, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db
from bridge.auth.sessions import LiveSession
from bridge.errors import ERROR_RESPONSES, ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.models.enums import AuditActor
from bridge.quiz.models import (
    FLAG_REASONS,
    MAX_TIME_MS,
    OPTIONS_PER_QUESTION,
    QUESTIONS_PER_SET,
    REASON_MAX_CHARS,
    QuizAttempt,
    QuizProfile,
    QuizQuestion,
    QuizSet,
)
from bridge.quiz.streaks import Streak, after_playing, missed_sets, shown

router = APIRouter(prefix="/api/me/quiz", tags=["developer"], responses=ERROR_RESPONSES)
BOARD_SIZE: Final = 20
ATTEMPT_UNIQUE: Final = "uq_quiz_attempts_set_id_user_id"
FlagReason = Literal["wrong_answer", "unclear", "outdated", "other"]
assert set(get_args(FlagReason)) == set(FLAG_REASONS)

_IS_DEVELOPER: Final = text("SELECT app_is_developer()")
_ANSWERS: Final = text("SELECT question_id, answer, why FROM app_quiz_answers(:s)")
_FLAG: Final = text("SELECT flag_id, pulled FROM app_flag_question(:q, :r, :n)")
_BOARD: Final = text(
    "SELECT b.rank, b.handle, b.points, b.is_caller, app_nairobi_today() AS today,"
    " coalesce((SELECT p.leaderboard_opt_in FROM quiz_profiles p WHERE p.user_id = app_user_id()), false)"
    " AS opted_in FROM app_quiz_board() b"
)
Q = QuizQuestion
_QUESTION_COLUMNS: Final = (
    Q.id,
    Q.position,
    Q.prompt,
    Q.options,
    Q.topic,
    Q.source_id,
    Q.source_title,
    Q.source_url,
    Q.status,
)

# [[COPY-REVIEW]] error messages (the web app shows its own words for each code).
NO_QUIZ: Final = "There is no quiz today. Come back tomorrow."
SET_CLOSED: Final = "This quiz's day is over. Today's quiz is a new one."
ALREADY_PLAYED: Final = "You already played this quiz."
PLAY_FIRST: Final = "Play this quiz before you flag its questions."
ALREADY_FLAGGED: Final = "You already flagged this question."
QUESTION_PULLED: Final = "This question was already withdrawn."
FLAG_LIMIT: Final = "You can flag up to 10 questions a day. Try again tomorrow."


async def quiz_developer(live: CurrentSession, db: Db) -> LiveSession:
    """A developer who plays (``app_is_developer()``); 404 for everyone else signed in."""
    if not await db.scalar(_IS_DEVELOPER):
        raise not_found()
    return live


Developer = Annotated[LiveSession, Depends(quiz_developer)]


# ------------------------------------------------------------------------------------------------------------ shapes


class QuizSourceOut(BaseModel):
    id: str = Field(description="The curated page's id (backend/ai/quiz_sources.yaml)")
    title: str
    url: str = Field(description="An official documentation page (https), copied from the curated list")


class QuizQuestionOut(BaseModel):
    id: UUID
    position: int = Field(ge=1, le=QUESTIONS_PER_SET)
    prompt: str
    options: list[str] = Field(min_length=OPTIONS_PER_QUESTION, max_length=OPTIONS_PER_QUESTION)
    topic: str
    source: QuizSourceOut
    pulled: bool = Field(description="Withdrawn (after flags or by staff): it counts for nobody")
    answer: int | None = Field(description="The correct option's index (0-3); null until the caller finished")
    why: str | None = Field(description="Why that option is right; null until the caller finished")


class QuizAttemptOut(BaseModel):
    answers: list[int | None] = Field(description="The caller's five answers by position (null: skipped)")
    correct: list[bool | None] = Field(description="Per position: right or wrong; null for a withdrawn question")
    score: int = Field(description="Live questions answered correctly (rescored when a question is withdrawn)")
    out_of: int = Field(description="Live questions of the set")
    time_ms: int
    finished_at: datetime


class QuizStreakOut(BaseModel):
    current: int = Field(
        description="Consecutive days with an approved set played (a day without a set is skipped); 0 once a set"
        " was missed"
    )
    best: int


class QuizTodayOut(BaseModel):
    set_id: UUID
    quiz_date: date = Field(description="The Nairobi day of the set")
    questions: list[QuizQuestionOut]
    attempt: QuizAttemptOut | None = Field(description="The caller's finished attempt, or null before they play")
    streak: QuizStreakOut
    leaderboard_opt_in: bool


class QuizAnswersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_id: UUID = Field(description="The set GET /today served (a set of another day is 409 set_closed)")
    answers: list[Annotated[StrictInt, Field(ge=0, le=OPTIONS_PER_QUESTION - 1)] | None] = Field(
        min_length=QUESTIONS_PER_SET, max_length=QUESTIONS_PER_SET, description="Five option indexes (0-3) or null"
    )
    time_ms: StrictInt = Field(ge=0, le=MAX_TIME_MS, description="Milliseconds spent: only a tiebreak on the board")


class QuizFlagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: FlagReason
    note: str | None = Field(default=None, description="For staff only: at most 300 characters on one line")

    @field_validator("note")
    @classmethod
    def _one_line(cls, value: str | None) -> str | None:
        if value is None:
            return None
        note = " ".join(value.split())
        if any(unicodedata.category(c) == "Cc" for c in note):
            raise ValueError("a note has no control characters")
        if len(note) > REASON_MAX_CHARS:
            raise ValueError(f"a note has at most {REASON_MAX_CHARS} characters")
        return note or None


class QuizFlagOut(BaseModel):
    flag_id: UUID
    pulled: bool = Field(description="True when this flag withdrew the question (three counted flags)")


class QuizBoardRowOut(BaseModel):
    rank: int = Field(description="Equal points and time share a rank")
    handle: str
    points: int
    you: bool = Field(description="The caller's own row")


class QuizBoardMeOut(BaseModel):
    points: int = Field(description="The caller's points this week (0 when they did not play)")
    rank: int | None = Field(
        description="Their rank among this week's board (also when not opted in); null when they did not play this week"
    )
    opted_in: bool
    played: bool = Field(description="Whether they played this week")


class QuizBoardOut(BaseModel):
    week_start: date = Field(description="Monday of this ISO week (Nairobi)")
    week_end: date = Field(description="Sunday of this ISO week (Nairobi)")
    rows: list[QuizBoardRowOut] = Field(description="At most 20, by rank then handle; opted-in developers only")
    me: QuizBoardMeOut


class QuizSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    leaderboard_opt_in: bool = Field(description="Show my handle and this week's points to other developers")


class QuizSettingsOut(BaseModel):
    leaderboard_opt_in: bool


# ------------------------------------------------------------------------------------------------------------- reads


@dataclass(frozen=True, slots=True)
class Profile:
    streak: Streak
    opted_in: bool


async def _profile(db: AsyncSession, user_id: UUID, *, lock: bool = False) -> Profile | None:
    P = QuizProfile
    stmt = select(P.current_streak, P.best_streak, P.last_played_on, P.leaderboard_opt_in).where(P.user_id == user_id)
    row = (await db.execute(stmt.with_for_update() if lock else stmt)).one_or_none()
    if row is None:
        return None
    return Profile(Streak(row.current_streak, row.best_streak, row.last_played_on), row.leaderboard_opt_in)


async def _questions(db: AsyncSession, set_id: UUID) -> Sequence[Row[Any]]:
    return (await db.execute(select(*_QUESTION_COLUMNS).where(Q.set_id == set_id).order_by(Q.position))).all()


async def _key(db: AsyncSession, set_id: UUID) -> dict[UUID, tuple[int, str]]:
    """The set's answers and whys (``app_quiz_answers``: rows only after the caller's attempt)."""
    return {row.question_id: (row.answer, row.why) for row in (await db.execute(_ANSWERS, {"s": set_id})).all()}


@dataclass(frozen=True, slots=True)
class Played:
    answers: list[int | None]
    score: int
    time_ms: int
    finished_at: datetime


def _today_out(
    set_id: UUID,
    quiz_date: date,
    today: date,
    questions: Sequence[Row[Any]],
    played: Played | None,
    key: Mapping[UUID, tuple[int, str]],
    profile: Profile | None,
    missed: int,
) -> QuizTodayOut:
    out = []
    for q in questions:
        answer, why = key.get(q.id, (None, None))
        out.append(
            QuizQuestionOut(
                id=q.id,
                position=q.position,
                prompt=q.prompt,
                options=list(q.options),
                topic=q.topic,
                source=QuizSourceOut(id=q.source_id, title=q.source_title, url=q.source_url),
                pulled=q.status == "pulled",
                answer=answer if played else None,
                why=why if played else None,
            )
        )
    attempt = None
    if played is not None:
        correct = [None if q.pulled else played.answers[q.position - 1] == q.answer for q in out]
        attempt = QuizAttemptOut(
            answers=played.answers,
            correct=correct,
            score=played.score,
            out_of=sum(not q.pulled for q in out),
            time_ms=played.time_ms,
            finished_at=played.finished_at,
        )
    current, best = shown(profile.streak if profile else None, today, missed=missed)
    return QuizTodayOut(
        set_id=set_id,
        quiz_date=quiz_date,
        questions=out,
        attempt=attempt,
        streak=QuizStreakOut(current=current, best=best),
        leaderboard_opt_in=bool(profile and profile.opted_in),
    )


def _no_quiz() -> ApiError:
    return ApiError(404, "no_quiz", NO_QUIZ)


@router.get("/today")
async def quiz_today(live: Developer, db: Db) -> QuizTodayOut:
    """Today's approved set with the caller's attempt, streak and opt-in; 404 ``no_quiz`` without one."""
    me = live.user.id
    today_set = (
        await db.execute(
            select(QuizSet.id, QuizSet.quiz_date).where(
                QuizSet.status == "approved", QuizSet.quiz_date == func.app_nairobi_today()
            )
        )
    ).one_or_none()
    if today_set is None:
        raise _no_quiz()
    A = QuizAttempt
    attempt = (
        await db.execute(
            select(A.answers, A.score, A.time_ms, A.finished_at).where(A.set_id == today_set.id, A.user_id == me)
        )
    ).one_or_none()
    played = (
        None if attempt is None else Played(list(attempt.answers), attempt.score, attempt.time_ms, attempt.finished_at)
    )
    key = await _key(db, today_set.id) if played else {}
    profile = await _profile(db, me)
    missed = await missed_sets(db, profile.streak if profile else None, today_set.quiz_date)
    return _today_out(
        today_set.id,
        today_set.quiz_date,
        today_set.quiz_date,
        await _questions(db, today_set.id),
        played,
        key,
        profile,
        missed,
    )


# ------------------------------------------------------------------------------------------------------------ writes


def _attempt_refusal(exc: DBAPIError) -> ApiError | None:
    """The database's refusal of the attempt: a second attempt (the unique key), a set whose day ended since it was
    read (the insert policy: today's set only), or a set that is not approved (the scoring trigger)."""
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None)
    constraint = getattr(getattr(orig, "diag", None), "constraint_name", None)
    if sqlstate == "23505" and constraint == ATTEMPT_UNIQUE:
        return ApiError(409, "already_played", ALREADY_PLAYED)
    if sqlstate == "42501":
        return ApiError(409, "set_closed", SET_CLOSED)
    if sqlstate == "55000":
        return _no_quiz()
    return None


@router.post("/today/answers", status_code=201)
async def finish_today(body: QuizAnswersIn, live: Developer, db: Db) -> QuizTodayOut:
    """The caller's one attempt on today's set (see the module docstring); the response only after the commit."""
    me = live.user.id
    found = (
        await db.execute(
            select(QuizSet.id, QuizSet.quiz_date, func.app_nairobi_today().label("today")).where(
                QuizSet.id == body.set_id, QuizSet.status == "approved"
            )
        )
    ).one_or_none()
    if found is None:
        raise _no_quiz()
    if found.quiz_date != found.today:
        raise ApiError(409, "set_closed", SET_CLOSED)
    A = QuizAttempt
    if await db.scalar(select(A.id).where(A.set_id == found.id, A.user_id == me)) is not None:
        raise ApiError(409, "already_played", ALREADY_PLAYED)
    before = await _profile(db, me, lock=True)
    stored = before.streak if before else None
    streak = after_playing(stored, found.today, missed=await missed_sets(db, stored, found.today))
    kept = {"current_streak": streak.current, "best_streak": streak.best, "last_played_on": streak.last_played_on}
    await db.execute(
        pg_insert(QuizProfile)
        .values(user_id=me, **kept)
        .on_conflict_do_update(index_elements=[QuizProfile.user_id], set_=kept)
    )
    try:  # the attempt is the transaction's last write: no savepoint, no retry
        attempt = (
            await db.execute(
                insert(A)
                .values(id=uuid7(), set_id=found.id, user_id=me, answers=body.answers, time_ms=body.time_ms)
                .returning(A.score, A.finished_at)
            )
        ).one()
    except DBAPIError as exc:
        await db.rollback()
        refusal = _attempt_refusal(exc)
        if refusal is None:
            raise
        raise refusal from None
    questions = await _questions(db, found.id)
    key = await _key(db, found.id)
    await db.commit()  # nothing of the score or the key leaves before this succeeded
    profile = Profile(streak, before.opted_in if before else False)
    played = Played(list(body.answers), attempt.score, body.time_ms, attempt.finished_at)
    return _today_out(found.id, found.quiz_date, found.today, questions, played, key, profile, missed=0)


_FLAG_REFUSALS: Final[Mapping[str, tuple[int, str, str]]] = {
    "42501": (403, "play_first", PLAY_FIRST),
    "23505": (409, "already_flagged", ALREADY_FLAGGED),
    "55000": (409, "question_pulled", QUESTION_PULLED),
    "54000": (429, "flag_limit", FLAG_LIMIT),
    "22023": (422, "invalid_flag", "A flag has a reason and at most a one-line note of 300 characters."),
}


@router.post("/questions/{question_id}/flag", status_code=201)
async def flag_question(question_id: UUID, body: QuizFlagIn, live: Developer, db: Db) -> QuizFlagOut:
    """Flag a question of a set the caller played, through ``app_flag_question`` (see the module docstring)."""
    try:
        row = (await db.execute(_FLAG, {"q": question_id, "r": body.reason, "n": body.note})).one()
    except DBAPIError as exc:
        await db.rollback()
        sqlstate = str(getattr(exc.orig, "sqlstate", None))
        if sqlstate == "P0002":
            raise not_found("No such question.") from None
        if sqlstate not in _FLAG_REFUSALS:
            raise
        status, code, message = _FLAG_REFUSALS[sqlstate]
        if status == 403:
            raise forbidden(code, message) from None
        raise ApiError(status, code, message) from None
    if row.pulled:
        set_id = await db.scalar(select(Q.set_id).where(Q.id == question_id))
        await audit(
            db,
            "quiz.question_pulled",
            actor_user_id=None,
            actor_kind=AuditActor.SYSTEM,
            subject_type="quiz_question",
            subject_id=question_id,
            payload={"set_id": str(set_id), "reason": "flags"},
        )
    await db.commit()
    return QuizFlagOut(flag_id=row.flag_id, pulled=row.pulled)


@router.get("/leaderboard")
async def quiz_leaderboard(live: Developer, db: Db) -> QuizBoardOut:
    """This week's board and the caller's own numbers, in one statement (``app_quiz_board()``)."""
    rows = (await db.execute(_BOARD)).all()
    mine = next(row for row in rows if row.is_caller)  # the board always answers the caller's own row
    others = [row for row in rows if not row.is_caller]
    played = mine.rank is not None
    listed = mine.opted_in and played and len(others) < BOARD_SIZE  # the caller's row is one of the first 20
    monday = mine.today - timedelta(days=mine.today.weekday())
    return QuizBoardOut(
        week_start=monday,
        week_end=monday + timedelta(days=6),
        rows=[
            QuizBoardRowOut(rank=row.rank, handle=row.handle, points=row.points, you=row.is_caller)
            for row in rows
            if not row.is_caller or listed
        ],
        me=QuizBoardMeOut(points=mine.points, rank=mine.rank, opted_in=mine.opted_in, played=played),
    )


@router.put("/settings")
async def quiz_settings(body: QuizSettingsIn, live: Developer, db: Db) -> QuizSettingsOut:
    """The caller's leaderboard opt-in (off until they turn it on)."""
    await db.execute(
        pg_insert(QuizProfile)
        .values(user_id=live.user.id, leaderboard_opt_in=body.leaderboard_opt_in)
        .on_conflict_do_update(
            index_elements=[QuizProfile.user_id], set_={"leaderboard_opt_in": body.leaderboard_opt_in}
        )
    )
    await db.commit()
    return QuizSettingsOut(leaderboard_opt_in=body.leaderboard_opt_in)
