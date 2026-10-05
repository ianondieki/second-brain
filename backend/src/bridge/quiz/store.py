"""Today's five: storing a checked draft as a day's draft set (REQ-DEV-01; D-59; revision 0009).

``store_draft(db, day, questions, ...)`` writes the set and its five questions in one transaction and commits it. The
nightly job calls it on its own session with no user bound (bridge_app: revision 0009's job grants and policies, which
admit a draft for today or a later Nairobi day and read no quiz row back); the demo seed calls it as the owner role,
which may date a seeded set in the past. Before writing it asks the database, through the job's two functions (no
quiz row is read):

- ``app_quiz_day_taken(day)``: a draft or approved set for the day refuses the draft (``day_taken``; a rejected day
  may be drafted again);
- ``app_quiz_recent_prompt_hashes(day - no_repeat_days)``: a prompt hash of a draft or approved set dated in the
  window (or later) discards the draft (``repeated_prompt``, the rule of ``bridge.quiz.checks``, kept again here since
  a set may have been drafted between the model call and the store).

The set and its questions are inserted without RETURNING (``eager_defaults`` is off on both mappers). A unique
violation of ``uq_quiz_sets_quiz_date`` is a concurrent writer for the same day: the draft is dropped (``day_taken``).
The title, URL and topic stored with each question are the curated list's (``AcceptedQuestion`` carries them), and
``prompt_hash`` the checks' SHA-256 as 32 bytes. Nothing else is written: a staff admin approves or rejects the set.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import insert, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.quiz.checks import QUESTIONS_PER_SET, AcceptedQuestion, Reason
from bridge.quiz.models import QuizQuestion, QuizSet

Origin = Literal["model", "seeded"]
DAY_TAKEN: Final = "day_taken"
DAY_INDEX: Final = "uq_quiz_sets_quiz_date"
_TAKEN: Final = text("SELECT app_quiz_day_taken(:day)")
_RECENT: Final = text("SELECT prompt_hash FROM app_quiz_recent_prompt_hashes(:since)")
log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Stored:
    """The day's new draft set."""

    day: date
    set_id: UUID


@dataclass(frozen=True, slots=True)
class NotStored:
    """Nothing was written: ``reason`` is ``day_taken`` or ``repeated_prompt`` (``position`` names the question)."""

    day: date
    reason: str
    position: int | None = None


async def day_taken(db: AsyncSession, day: date) -> bool:
    """Whether ``day`` has a draft or approved set (the job's function: no user may be bound to ``db``)."""
    return bool(await db.scalar(_TAKEN, {"day": day}))


async def recent_hashes(db: AsyncSession, day: date, no_repeat_days: int) -> frozenset[str]:
    """The prompt hashes (hex, as ``bridge.quiz.checks.prompt_hash``) of draft and approved sets dated from
    ``no_repeat_days`` before ``day`` on (the job's function: no user may be bound to ``db``)."""
    since = day - timedelta(days=no_repeat_days)
    return frozenset(bytes(value).hex() for value in (await db.scalars(_RECENT, {"since": since})).all())


def _rows(set_id: UUID, questions: Sequence[AcceptedQuestion]) -> list[dict[str, object]]:
    return [
        {
            "id": uuid7(),
            "set_id": set_id,
            "position": q.position,
            "prompt": q.prompt,
            "options": list(q.options),
            "answer": q.answer,
            "why": q.why,
            "source_id": q.source_id,
            "source_title": q.source_title,
            "source_url": q.source_url,
            "topic": q.topic,
            "prompt_hash": bytes.fromhex(q.prompt_hash),
        }
        for q in questions
    ]


async def store_draft(
    db: AsyncSession,
    day: date,
    questions: Sequence[AcceptedQuestion],
    *,
    origin: Origin,
    trace_id: str | None,
    no_repeat_days: int,
) -> Stored | NotStored:
    """Write ``questions`` as the draft set of ``day`` and commit, or write nothing (see the module docstring).
    ``trace_id`` is the generating call's (``llm_calls.trace_id``; required for ``model``, None for ``seeded``)."""
    if [q.position for q in questions] != list(range(1, QUESTIONS_PER_SET + 1)):
        raise ValueError(f"a draft set is {QUESTIONS_PER_SET} accepted questions in positions 1 to 5")
    if (origin == "model") != (trace_id is not None):
        raise ValueError("a model's draft names its call's trace id; a seeded one names none")
    refused = await _refusal(db, day, questions, no_repeat_days)
    if refused is not None:
        await db.rollback()
        log.info("quiz.draft_not_stored", day=day.isoformat(), reason=refused.reason, position=refused.position)
        return refused
    set_id = uuid7()
    try:
        await db.execute(insert(QuizSet).values(id=set_id, quiz_date=day, origin=origin, llm_trace_id=trace_id))
        await db.execute(insert(QuizQuestion), _rows(set_id, questions))
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != DAY_INDEX:
            raise
        log.info("quiz.draft_not_stored", day=day.isoformat(), reason=DAY_TAKEN, position=None)
        return NotStored(day, DAY_TAKEN)
    log.info("quiz.draft_stored", day=day.isoformat(), set_id=str(set_id), origin=origin)
    return Stored(day, set_id)


async def _refusal(
    db: AsyncSession, day: date, questions: Sequence[AcceptedQuestion], no_repeat_days: int
) -> NotStored | None:
    if await day_taken(db, day):
        return NotStored(day, DAY_TAKEN)
    recent = await recent_hashes(db, day, no_repeat_days)
    repeated = next((q.position for q in questions if q.prompt_hash in recent), None)
    if repeated is not None:
        return NotStored(day, Reason.REPEATED_PROMPT.value, repeated)
    return None
