"""Today's five, the staff admin's API (REQ-DEV-01, REQ-ADM-01; D-59; P22 card A): ``/api/admin/quiz/*``.

Every route needs a staff admin whose TOTP is enrolled and whose second factor is fresh (``bridge.admin.deps``: 404
for everyone else, a developer included; 403 for a moderator; 403 ``step_up_required`` for an old second factor); the
database repeats the rule (staff admin reads every set, question and flag; the decisions and pulls are its definer
functions, which refuse anyone else).

- ``GET /sets?status=draft|approved|rejected``: newest day first, with the flag and pull counts of each set.
- ``GET /sets/{id}``: the set with who decided it, when and its generating call (``app_quiz_set_detail``), its
  attempts in aggregate (``app_quiz_set_stats``: counts from 3 attempts on), each question with its answer and why
  (``app_quiz_answers``), source, pull state and flags (reason counts and the notes, never who flagged).
- ``POST /sets/{id}/decision`` ``{decision: approve|reject}``: one decision per set through ``app_decide_quiz_set``
  (409 ``already_decided`` after; 409 ``incomplete_set`` for an approval without five questions; 409 ``day_over`` for
  an approval of a set whose day is over on the shared clock, which may only be rejected: an approved set nobody could
  play would end every streak), audited ``quiz.set_decided``.
- ``POST /questions/{id}/pull`` ``{reason}`` and ``POST /questions/{id}/restore``: through
  ``app_set_quiz_question_status``, which rescores the set's attempts in the same transaction (409 ``already_pulled``
  or ``already_live``); audited ``quiz.question_pulled`` (reason ``staff``) and ``quiz.question_restored``, with the
  number of attempts whose score changed. A restored question is never pulled again by flags.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Final, Literal
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import Label, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.admin.deps import StaffAdmin
from bridge.audit.service import record as audit
from bridge.auth.deps import Db
from bridge.errors import ERROR_RESPONSES, ApiError, ApiErrorBody, not_found
from bridge.models.enums import AuditActor
from bridge.quiz.models import FLAG_REASONS, REASON_MAX_CHARS, QuizFlag, QuizQuestion, QuizSet

router = APIRouter(prefix="/api/admin/quiz", tags=["admin"], responses=ERROR_RESPONSES)
SetStatus = Literal["draft", "approved", "rejected"]
Q, F, S = QuizQuestion, QuizFlag, QuizSet

_DECIDE: Final = text("SELECT app_decide_quiz_set(:s, :d)")
_DAY_OVER: Final = text("SELECT quiz_date < app_nairobi_today() FROM quiz_sets WHERE id = :s")
DECISION_CONFLICTS: Final = "already_decided, incomplete_set (an approval without five questions) or day_over"
_SET_STATUS: Final = text("SELECT app_set_quiz_question_status(:q, :status, :reason)")
_ANSWERS: Final = text("SELECT question_id, answer, why FROM app_quiz_answers(:s)")
_FIGURES: Final = text(
    "SELECT d.decided_by, d.decided_at, d.llm_trace_id, t.attempts, t.average_score, t.per_question_correct"
    " FROM app_quiz_set_detail(:s) d CROSS JOIN app_quiz_set_stats(:s) t"
)


class QuizSetSummaryOut(BaseModel):
    id: UUID
    quiz_date: date
    status: SetStatus
    origin: Literal["model", "seeded"]
    created_at: datetime
    flags: int = Field(description="Flags on the set's questions")
    pulled: int = Field(description="Questions withdrawn")


class QuizSetListOut(BaseModel):
    items: list[QuizSetSummaryOut]


class QuizFlagNoteOut(BaseModel):
    reason: str
    note: str
    created_at: datetime


class QuizAdminQuestionOut(BaseModel):
    id: UUID
    position: int
    prompt: str
    options: list[str]
    answer: int
    why: str
    topic: str
    source_id: str
    source_title: str
    source_url: str
    status: Literal["live", "pulled"]
    pulled_at: datetime | None
    pulled_reason: str | None = Field(description="three_flags, or the staff member's reason")
    restored_at: datetime | None = Field(description="Restored by staff: flags never pull it again")
    flags: int
    flag_reasons: dict[str, int] = Field(description="Flags by reason code")
    notes: list[QuizFlagNoteOut] = Field(description="The flags' notes for staff, oldest first (never who flagged)")


class QuizStatsOut(BaseModel):
    attempts: int
    average_score: Decimal | None = Field(description="From 3 attempts on; else null")
    per_question_correct: list[int] | None = Field(description="By position, from 3 attempts on; else null")


class QuizSetDetailOut(QuizSetSummaryOut):
    decided_by: UUID | None
    decided_at: datetime | None
    llm_trace_id: str | None = Field(description="The generating call's trace id (llm_calls), null when seeded")
    stats: QuizStatsOut
    questions: list[QuizAdminQuestionOut]


class QuizDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]


class QuizPullIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(description="Why it is withdrawn: one line, at most 300 characters")

    @field_validator("reason")
    @classmethod
    def _one_line(cls, value: str) -> str:
        reason = " ".join(value.split())
        if not reason or len(reason) > REASON_MAX_CHARS or any(unicodedata.category(c) == "Cc" for c in reason):
            raise ValueError(f"a reason is one line of 1 to {REASON_MAX_CHARS} characters")
        return reason


class QuizQuestionStatusOut(BaseModel):
    question_id: UUID
    set_id: UUID
    status: Literal["live", "pulled"]
    rescored: int = Field(description="Attempts whose score changed")


def _counts() -> tuple[Label[int], Label[int]]:
    flags = select(func.count()).select_from(F).join(Q, Q.id == F.question_id).where(Q.set_id == S.id).scalar_subquery()
    pulled = select(func.count()).select_from(Q).where(Q.set_id == S.id, Q.status == "pulled").scalar_subquery()
    return flags.label("flags"), pulled.label("pulled")


async def _summaries(
    db: AsyncSession, *, status: SetStatus | None = None, set_id: UUID | None = None, limit: int = 100
) -> list[QuizSetSummaryOut]:
    stmt = select(S.id, S.quiz_date, S.status, S.origin, S.created_at, *_counts())
    if status is not None:
        stmt = stmt.where(S.status == status)
    if set_id is not None:
        stmt = stmt.where(S.id == set_id)
    rows = (await db.execute(stmt.order_by(S.quiz_date.desc(), S.created_at.desc(), S.id.desc()).limit(limit))).all()
    return [QuizSetSummaryOut.model_validate(row, from_attributes=True) for row in rows]


@router.get("/sets")
async def list_quiz_sets(
    staff: StaffAdmin,
    db: Db,
    status: SetStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> QuizSetListOut:
    """The sets, newest day first (``status`` filters), with their flag and pull counts."""
    return QuizSetListOut(items=await _summaries(db, status=status, limit=limit))


@router.get("/sets/{set_id}")
async def get_quiz_set(set_id: UUID, staff: StaffAdmin, db: Db) -> QuizSetDetailOut:
    found = await _summaries(db, set_id=set_id)
    if not found:
        raise not_found("No such quiz set.")
    figures = (await db.execute(_FIGURES, {"s": set_id})).one()
    key = {row.question_id: (row.answer, row.why) for row in (await db.execute(_ANSWERS, {"s": set_id})).all()}
    columns = (
        Q.id,
        Q.position,
        Q.prompt,
        Q.options,
        Q.topic,
        Q.source_id,
        Q.source_title,
        Q.source_url,
        Q.status,
        Q.pulled_at,
        Q.pulled_reason,
        Q.restored_at,
    )
    questions = (await db.execute(select(*columns).where(Q.set_id == set_id).order_by(Q.position))).all()
    flags = (
        await db.execute(
            select(F.question_id, F.reason, F.note, F.created_at)
            .where(F.question_id.in_([q.id for q in questions]))
            .order_by(F.created_at, F.id)
        )
    ).all()
    reasons: dict[UUID, Counter[str]] = {q.id: Counter() for q in questions}
    notes: dict[UUID, list[QuizFlagNoteOut]] = {q.id: [] for q in questions}
    for flag in flags:
        reasons[flag.question_id][flag.reason] += 1
        if flag.note is not None:
            notes[flag.question_id].append(
                QuizFlagNoteOut(reason=flag.reason, note=flag.note, created_at=flag.created_at)
            )
    return QuizSetDetailOut(
        **found[0].model_dump(),
        decided_by=figures.decided_by,
        decided_at=figures.decided_at,
        llm_trace_id=figures.llm_trace_id,
        stats=QuizStatsOut(
            attempts=figures.attempts,
            average_score=figures.average_score,
            per_question_correct=figures.per_question_correct,
        ),
        questions=[
            QuizAdminQuestionOut(
                id=q.id,
                position=q.position,
                prompt=q.prompt,
                options=list(q.options),
                answer=key[q.id][0],
                why=key[q.id][1],
                topic=q.topic,
                source_id=q.source_id,
                source_title=q.source_title,
                source_url=q.source_url,
                status=q.status,
                pulled_at=q.pulled_at,
                pulled_reason=q.pulled_reason,
                restored_at=q.restored_at,
                flags=sum(reasons[q.id].values()),
                flag_reasons={reason: reasons[q.id][reason] for reason in FLAG_REASONS if reasons[q.id][reason]},
                notes=notes[q.id],
            )
            for q in questions
        ],
    )


def _sqlstate(exc: DBAPIError) -> str:
    return str(getattr(exc.orig, "sqlstate", None))


@router.post(
    "/sets/{set_id}/decision",
    responses={409: {"model": ApiErrorBody, "description": f"{DECISION_CONFLICTS} (approving a set of a past day)"}},
)
async def decide_quiz_set(set_id: UUID, body: QuizDecisionIn, staff: StaffAdmin, db: Db) -> QuizSetSummaryOut:
    """Approve or reject a draft set, once (see the module docstring). A set of a day that is over on the shared clock
    may be rejected but not approved (409 ``day_over``): nobody could play it any more, and an approved set nobody
    played would end every streak."""
    decision = "approved" if body.decision == "approve" else "rejected"
    try:
        await db.execute(_DECIDE, {"s": set_id, "d": decision})
    except DBAPIError as exc:
        await db.rollback()
        sqlstate = _sqlstate(exc)
        if sqlstate in ("P0002", "42501"):
            raise not_found("No such quiz set.") from None
        if sqlstate == "55000":
            raise ApiError(409, "already_decided", "This set was already decided.") from None
        if sqlstate == "23514":
            raise ApiError(409, "incomplete_set", "A set is approved only with its five questions.") from None
        raise
    if decision == "approved" and await db.scalar(_DAY_OVER, {"s": set_id}):  # read after the set's lock: the day now
        await db.rollback()
        raise ApiError(409, "day_over", "This set's day is over. It can be rejected, not approved.")
    [summary] = await _summaries(db, set_id=set_id)
    await audit(
        db,
        "quiz.set_decided",
        actor_user_id=staff.live.user.id,
        actor_kind=AuditActor.STAFF,
        subject_type="quiz_set",
        subject_id=set_id,
        payload={"decision": decision, "quiz_date": summary.quiz_date.isoformat(), "origin": summary.origin},
    )
    await db.commit()
    return summary


async def _set_status(
    db: AsyncSession, staff: StaffAdmin, question_id: UUID, status: Literal["live", "pulled"], reason: str | None
) -> QuizQuestionStatusOut:
    set_id = await db.scalar(select(Q.set_id).where(Q.id == question_id))
    if set_id is None:
        raise not_found("No such question.")
    try:
        rescored = int(await db.scalar(_SET_STATUS, {"q": question_id, "status": status, "reason": reason}) or 0)
    except DBAPIError as exc:
        await db.rollback()
        sqlstate = _sqlstate(exc)
        if sqlstate in ("P0002", "42501"):
            raise not_found("No such question.") from None
        if sqlstate == "55000":
            code = "already_pulled" if status == "pulled" else "already_live"
            raise ApiError(409, code, f"This question is already {status}.") from None
        if sqlstate == "22023":
            raise ApiError(422, "invalid_reason", "A reason is one line of 1 to 300 characters.") from None
        raise
    action = "quiz.question_pulled" if status == "pulled" else "quiz.question_restored"
    payload: dict[str, object] = {"set_id": str(set_id), "rescored": rescored}
    if status == "pulled":
        payload["reason"] = "staff"
    await audit(
        db,
        action,
        actor_user_id=staff.live.user.id,
        actor_kind=AuditActor.STAFF,
        subject_type="quiz_question",
        subject_id=question_id,
        payload=payload,
    )
    await db.commit()
    return QuizQuestionStatusOut(question_id=question_id, set_id=set_id, status=status, rescored=rescored)


@router.post("/questions/{question_id}/pull")
async def pull_quiz_question(question_id: UUID, body: QuizPullIn, staff: StaffAdmin, db: Db) -> QuizQuestionStatusOut:
    """Withdraw a question (it counts for nobody) and rescore its set's attempts."""
    return await _set_status(db, staff, question_id, "pulled", body.reason)


@router.post("/questions/{question_id}/restore")
async def restore_quiz_question(question_id: UUID, staff: StaffAdmin, db: Db) -> QuizQuestionStatusOut:
    """Put a withdrawn question back and rescore its set's attempts; flags never pull it again."""
    return await _set_status(db, staff, question_id, "live", None)
