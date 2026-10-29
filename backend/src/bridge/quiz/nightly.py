"""Today's five's nightly pass (REQ-DEV-01; D-59; P22 card A): ``run_nightly`` is the job ``quiz.draft``
(``bridge.jobs.quiz``: 23:30 UTC, 02:30 in Nairobi).

The shared clock decides the day (``app_nairobi_today()``: the dev/test clock moves it). The pass looks at today and
the next Nairobi day, in that order, and drafts each that has no draft or approved set: the next day is the one the
card names, and today is looked at too so that a set staff rejected after the last run (or a night whose call failed)
is drafted again by the next run, as the card's test A2 asks. For each day, on a session with no user bound (the
job's role; the call is a platform call, so the global daily cap, the prototype total and the kill switch apply, and
its ledger rows name no user or organisation):

1. ``app_quiz_day_taken(day)``: a draft or approved set means nothing else happens for the day (no model call);
2. the prompt hashes of the last ``quiz.no_repeat_days`` days (``app_quiz_recent_prompt_hashes``);
3. one ``draft_set`` (``bridge.quiz.run``: one ``quiz_generation`` call and one retry on a discarded draft; an LLM
   refusal such as the kill switch or a spent cap ends the day without a call, with a log line);
4. ``store_draft`` of an accepted draft (``bridge.quiz.store``), which asks the database again and commits.

Every outcome is one log line (``bridge.quiz.run`` and ``bridge.quiz.store`` write them); nothing is retried here and
nobody is notified: a staff admin finds the draft in the queue (``/admin/quiz``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.llm.client import LLMClient
from bridge.logging import get_logger
from bridge.quiz.policy import QuizPolicy
from bridge.quiz.run import Accepted, QuizDeps, Refused, draft_set
from bridge.quiz.sources import SourceList
from bridge.quiz.store import DAY_TAKEN, NotStored, Stored, day_taken, recent_hashes, store_draft

_TODAY: Final = text("SELECT app_nairobi_today()")
log = get_logger(__name__)

DayOutcome = Stored | NotStored | Refused


@dataclass(frozen=True)
class NightlyDeps:
    """The job's sessions (bridge_app; never bound to a user here), its LLM client of such a session, the curated
    list and the policy."""

    factory: async_sessionmaker[AsyncSession]
    llm: Callable[[AsyncSession], LLMClient]
    sources: SourceList
    policy: QuizPolicy


async def draft_day(deps: NightlyDeps, day: date) -> DayOutcome:
    """Draft and store the set of ``day`` unless the day has one (see the module docstring)."""
    async with deps.factory() as db:
        if await day_taken(db, day):
            log.info("quiz.draft_skipped", day=day.isoformat(), reason=DAY_TAKEN)
            return NotStored(day, DAY_TAKEN)
        recent = await recent_hashes(db, day, deps.policy.no_repeat_days)
        await db.commit()  # nothing is held open while the model answers
        quiz = QuizDeps(client=deps.llm(db), sources=deps.sources, policy=deps.policy)
        outcome = await draft_set(quiz, day, recent_hashes=recent)
        if not isinstance(outcome, Accepted):
            return outcome
        await db.commit()  # the client's own reads (caps, consents) end here: the set is one transaction
        return await store_draft(
            db,
            day,
            outcome.questions,
            origin="model",
            trace_id=outcome.trace_id,
            no_repeat_days=deps.policy.no_repeat_days,
        )


async def run_nightly(deps: NightlyDeps) -> tuple[DayOutcome, ...]:
    """Today's and the next Nairobi day's drafts, on the shared clock."""
    async with deps.factory() as db:
        today: date = (await db.execute(_TODAY)).scalar_one()
    return tuple([await draft_day(deps, day) for day in (today, today + timedelta(days=1))])
