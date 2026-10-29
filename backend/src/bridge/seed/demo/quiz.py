"""Demo seed steps for Today's five (P22 track A; REQ-DEV-01; D-59), so the Home card, ``/dev/quiz``, the board and
``/admin/quiz`` have something to show on ``make demo``. Part of ``python -m bridge.seed --demo``, after P21's beats.

- **Two sets** of ``origin`` seeded, for yesterday and today on the shared clock (``app_nairobi_today()``): ten
  questions written by hand below (``SEEDED_SETS``) from pages of the curated list (``backend/ai/quiz_sources.yaml``),
  each answer checkable on its page. No model is called. They go through the real path: the checks in code
  (``bridge.quiz.checks.check_draft``: counts, text rules, distinct options, one answer, a known source, no person
  named), ``store_draft`` as the owner role (which may date a seeded set in the past; it refuses a taken day and a
  prompt of the last 60 days). Today's is approved by the demo staff admin through ``POST
  /api/admin/quiz/sets/{id}/decision`` (``app_decide_quiz_set``, audited); yesterday's by the owner role (revision
  0009's seed path: ``decided_by`` left empty), since the API refuses to approve a set whose day is over.
- **Three attempts** (``PLAYS``): Amina's on yesterday's set, written as the owner role (the API takes only today's set;
  her streak is kept by the same code, ``bridge.quiz.streaks``), and Amina's and Brian's on today's set through
  ``POST /api/me/quiz/today/answers``, each signed in as themselves, so Amina has a streak of 2. Amina opts in to the
  board through ``PUT /api/me/quiz/settings`` (Brian does not); the board shows demo accounts to demo callers only.

Idempotent and safe on a used demo (P9's rules): a day that has any set gets nothing (a seeded draft a run left
behind is approved); an attempt that exists is left; the opt-in is set only for a developer the seed found with no
quiz profile at all, so a choice made in the app stays. Ten questions fill two days: on a later day the 60-day rule
refuses them again and the day is left without a set, with one line in the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.ids import uuid7
from bridge.quiz.checks import Discarded, Draft, DraftOption, DraftQuestion, check_draft
from bridge.quiz.policy import get_quiz_policy
from bridge.quiz.sources import get_sources
from bridge.quiz.store import Stored, store_draft
from bridge.quiz.streaks import Streak, after_playing, missed_sets
from bridge.seed.demo.data import AMINA, BRIAN, STAFF_ADMIN
from bridge.seed.demo.runtime import Actors, DemoReport, DemoSeedError, _execute, _one

Day = Literal["yesterday", "today"]


@dataclass(frozen=True, slots=True)
class SeededQuestion:
    source_id: str
    prompt: str
    options: tuple[str, str, str, str]
    answer: int
    why: str


@dataclass(frozen=True, slots=True)
class QuizPlay:
    email: str
    day: Day
    answers: tuple[int | None, ...]
    time_ms: int
    opt_in: bool = False


# Written by hand from the curated pages (their ids below), one fact each that the page states.
SEEDED_SETS: Final[dict[Day, tuple[SeededQuestion, ...]]] = {
    "yesterday": (
        SeededQuestion(
            "mdn-http-status",
            "Which HTTP status code means that the server cannot find the requested resource?",
            ("401 Unauthorized", "403 Forbidden", "404 Not Found", "410 Gone"),
            2,
            "MDN's list of HTTP response status codes describes 404 Not Found as the server cannot find the requested"
            " resource. 410 Gone is for content that was permanently deleted.",
        ),
        SeededQuestion(
            "git-bisect",
            "Which Git command uses a binary search to find the commit that introduced a bug?",
            ("git blame", "git bisect", "git reflog", "git cherry-pick"),
            1,
            "The git-bisect manual page says the command uses binary search to find the commit that introduced a"
            " bug: you mark commits as good or bad until one commit is left.",
        ),
        SeededQuestion(
            "pg-row-security",
            "A PostgreSQL table has row security enabled but no policy. What can a normal user see in it?",
            (
                "Every row",
                "No rows: a default-deny policy applies",
                "Only the rows they inserted",
                "An error on every query",
            ),
            1,
            "PostgreSQL's page on row security policies says that when no policy exists for a table with row security"
            " enabled, a default-deny policy is used: no rows are visible or can be modified. Table owners normally"
            " bypass it.",
        ),
        SeededQuestion(
            "man-chmod",
            "In a numeric chmod mode, which digit gives read and write permission but not execute?",
            ("4", "5", "6", "7"),
            2,
            "The chmod manual page builds a numeric mode by adding 4 for read, 2 for write and 1 for execute, so read"
            " and write without execute is 4 + 2 = 6.",
        ),
        SeededQuestion(
            "rfc-json",
            "According to RFC 8259, which encoding must JSON text use between systems that are not part of a closed"
            " ecosystem?",
            ("UTF-8", "UTF-16", "UTF-32", "ISO-8859-1"),
            0,
            "Section 8.1 of RFC 8259 says JSON text exchanged between systems that are not part of a closed ecosystem"
            " MUST be encoded using UTF-8.",
        ),
    ),
    "today": (
        SeededQuestion(
            "python-pep8",
            "How many spaces per indentation level does PEP 8 recommend for Python code?",
            ("2", "3", "4", "8"),
            2,
            "PEP 8, the style guide for Python code, says to use 4 spaces per indentation level.",
        ),
        SeededQuestion(
            "k8s-pods",
            "In Kubernetes, what are the smallest deployable units of computing that you can create and manage?",
            ("Nodes", "Pods", "Deployments", "Services"),
            1,
            "The Kubernetes documentation on Pods says they are the smallest deployable units of computing that you"
            " can create and manage in Kubernetes.",
        ),
        SeededQuestion(
            "mdn-cors",
            "Which HTTP method does a browser use for a CORS preflight request?",
            ("GET", "HEAD", "OPTIONS", "POST"),
            2,
            "MDN's CORS guide explains that for a preflighted request the browser first sends an HTTP request with the"
            " OPTIONS method, to check that the actual request is safe to send.",
        ),
        SeededQuestion(
            "owasp-sql-injection",
            "Which defence does the OWASP SQL Injection Prevention Cheat Sheet list first among its primary defences?",
            (
                "Escaping all user input",
                "Prepared statements with parameterized queries",
                "Stored procedures",
                "A web application firewall",
            ),
            1,
            "The cheat sheet's first primary defence is the use of prepared statements with parameterized queries; it"
            " strongly discourages escaping all user-supplied input.",
        ),
        SeededQuestion(
            "rust-ownership",
            "Under Rust's ownership rules, how many owners can a value have at one time?",
            ("Exactly one", "At most two", "One per thread", "Any number"),
            0,
            "The Rust book's chapter on ownership states the rules: each value has an owner, there can only be one"
            " owner at a time, and the value is dropped when its owner goes out of scope.",
        ),
    ),
}

# Amina: 4 of 5 yesterday and 5 of 5 today, on the board; Brian: 3 of 5 today, not on it.
PLAYS: Final = (
    QuizPlay(AMINA.email, "yesterday", (2, 1, 1, 1, 0), 96_000),
    QuizPlay(AMINA.email, "today", (2, 1, 2, 1, 0), 81_000, opt_in=True),
    QuizPlay(BRIAN.email, "today", (2, 0, 2, 0, 0), 132_000),
)

_TODAY: Final = "SELECT app_nairobi_today() AS today"
_ANY_SET: Final = "SELECT id, status, origin FROM quiz_sets WHERE quiz_date = :d ORDER BY created_at, id LIMIT 1"
_SEEDED_SET: Final = (
    "SELECT id, status FROM quiz_sets WHERE quiz_date = :d AND origin = 'seeded' AND status <> 'rejected' LIMIT 1"
)
_APPROVE_PAST: Final = (
    "UPDATE quiz_sets SET status = 'approved', decided_at = app_clock_now() WHERE id = :s AND status = 'draft'"
)
_ATTEMPT: Final = "SELECT 1 FROM quiz_attempts WHERE set_id = :s AND user_id = :u"
_PROFILE: Final = "SELECT current_streak, best_streak, last_played_on FROM quiz_profiles WHERE user_id = :u"


def days_of(today: date) -> dict[Day, date]:
    return {"yesterday": today - timedelta(days=1), "today": today}


async def nairobi_today(owner: AsyncEngine) -> date:
    found: date = (await _one(owner, _TODAY)).today
    return found


def checked(questions: tuple[SeededQuestion, ...]) -> Draft:
    """The hand-written set as a draft, for the same checks as a model's."""
    return Draft(
        injection_suspected=False,
        questions=tuple(
            DraftQuestion(
                prompt=q.prompt,
                options=tuple(DraftOption(text, index == q.answer) for index, text in enumerate(q.options)),
                why=q.why,
                source_id=q.source_id,
            )
            for q in questions
        ),
    )


async def ensure_sets(owner: AsyncEngine, actors: Actors, report: DemoReport) -> None:
    """Yesterday's and today's seeded sets: today's approved by the demo staff admin through the API, yesterday's by
    the owner role (module docstring)."""
    if STAFF_ADMIN.email not in report.users:
        raise DemoSeedError(f"no demo staff admin {STAFF_ADMIN.email} to approve the quiz")
    today = await nairobi_today(owner)
    for which, day in days_of(today).items():
        found = await _one(owner, _ANY_SET, d=day)
        if found is None:
            set_id = await _store(owner, which, day, report)
            if set_id is None:
                continue
        elif (found.origin, found.status) == ("seeded", "draft"):  # a run stopped before approving it
            set_id = UUID(str(found.id))
        else:
            continue
        if day < today:  # the API approves no set of a past day (409 day_over)
            await _execute(owner, _APPROVE_PAST, s=set_id)
            report.did(f"quiz set {day.isoformat()} approved (a past day, by the owner role)")
            continue
        admin = await actors.get(STAFF_ADMIN.email)
        await admin.call("POST", f"/api/admin/quiz/sets/{set_id}/decision", json={"decision": "approve"})
        report.did(f"quiz set {day.isoformat()} approved by {STAFF_ADMIN.email}")


async def _store(owner: AsyncEngine, which: Day, day: date, report: DemoReport) -> UUID | None:
    verdict = check_draft(checked(SEEDED_SETS[which]), get_sources().by_id())
    if isinstance(verdict, Discarded):
        raise DemoSeedError(f"the seeded quiz set of {which} fails the checks: {verdict}")
    async with AsyncSession(owner) as db:
        stored = await store_draft(
            db, day, verdict, origin="seeded", trace_id=None, no_repeat_days=get_quiz_policy().no_repeat_days
        )
    if not isinstance(stored, Stored):
        report.notes.append(f"quiz set {day.isoformat()}: left out ({stored.reason})")
        return None
    report.did(f"quiz set {day.isoformat()} (seeded)")
    return stored.set_id


async def ensure_play(owner: AsyncEngine, actors: Actors, play: QuizPlay, fresh: bool, report: DemoReport) -> None:
    """``play``'s attempt on the day's seeded approved set, unless it exists (module docstring). ``fresh``: the
    developer had no quiz profile when the step began (only then is the opt-in set)."""
    user_id = report.users.get(play.email)
    if user_id is None:
        raise DemoSeedError(f"{play.email} is not there to play the quiz")
    day = days_of(await nairobi_today(owner))[play.day]
    found = await _one(owner, _SEEDED_SET, d=day)
    if found is None or found.status != "approved":
        return  # no seeded set of that day (left out, or someone else's): nothing to play
    set_id = UUID(str(found.id))
    if await _one(owner, _ATTEMPT, s=set_id, u=user_id) is not None:
        return
    if play.day == "yesterday":
        await _past_attempt(owner, set_id, user_id, day, play)
    else:
        actor = await actors.get(play.email)
        body = {"set_id": str(set_id), "answers": list(play.answers), "time_ms": play.time_ms}
        await actor.call("POST", "/api/me/quiz/today/answers", json=body, expect=(201,))
        if play.opt_in and fresh:
            await actor.call("PUT", "/api/me/quiz/settings", json={"leaderboard_opt_in": True})
    report.did(f"quiz attempt of {play.email} on {day.isoformat()}")


async def _past_attempt(owner: AsyncEngine, set_id: UUID, user_id: UUID, day: date, play: QuizPlay) -> None:
    """As the owner role (the API takes today's set only): the attempt, scored by the database, and the streak the
    app would keep (``after_playing``), in one transaction."""
    async with owner.begin() as conn:
        row = (await conn.execute(text(_PROFILE + " FOR UPDATE"), {"u": user_id})).one_or_none()
        before = None if row is None else Streak(row.current_streak, row.best_streak, row.last_played_on)
        streak = after_playing(before, day, missed=await missed_sets(conn, before, day))
        await conn.execute(
            text(
                "INSERT INTO quiz_profiles (user_id, current_streak, best_streak, last_played_on)"
                " VALUES (:u, :c, :b, :d) ON CONFLICT (user_id) DO UPDATE SET current_streak = EXCLUDED.current_streak,"
                " best_streak = EXCLUDED.best_streak, last_played_on = EXCLUDED.last_played_on"
            ),
            {"u": user_id, "c": streak.current, "b": streak.best, "d": streak.last_played_on},
        )
        await conn.execute(
            text(
                "INSERT INTO quiz_attempts (id, set_id, user_id, answers, time_ms)"
                " VALUES (:id, :s, :u, CAST(:a AS smallint[]), :ms)"
            ),
            {"id": uuid7(), "s": set_id, "u": user_id, "a": list(play.answers), "ms": play.time_ms},
        )


async def has_profile(owner: AsyncEngine, user_id: UUID | None) -> bool:
    return user_id is not None and await _one(owner, _PROFILE, u=user_id) is not None


__all__ = ["PLAYS", "SEEDED_SETS", "QuizPlay", "SeededQuestion", "ensure_play", "ensure_sets", "has_profile"]
