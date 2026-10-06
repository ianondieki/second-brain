"""Today's five: the daily quiz's tables (P22 track A, REQ-DEV-01, D-59; revision 0009).

One set of five multiple-choice questions per Nairobi day, drafted by the nightly job (bridge_app with no user bound,
``origin`` ``model``) or written by the seed (``seeded``), approved or rejected once by a staff admin
(``app_decide_quiz_set``), then played once per developer (``quiz_attempts``). Rules the database enforces (revision
0009; the generation checks, streaks and the API's codes are the application's):

- Sets and questions (tenancy CURATED): staff admin reads every row; a developer (an active user with a developer
  profile) reads the approved sets and their questions, live and pulled; nobody else reads any. bridge_app never
  reads a question's ``answer`` or ``why`` (column grant): ``app_quiz_answers(set)`` returns them to a caller with an
  attempt on the set, or to staff admin. Map them deferred with raiseload; never select them.
- A set's status moves once, from ``draft`` to ``approved`` (with its five questions) or ``rejected``; one draft or
  approved set per day (a rejected day may be drafted again). Questions are added only to a draft and never change but
  by a pull or restore (``app_set_quiz_question_status`` for staff admin, or the third developer's flag through
  ``app_flag_question``), each of which rescores the set's attempts in the same transaction.
- An attempt is the developer's own, on the approved set of the current Nairobi day (``app_nairobi_today()``, on the
  shared clock), once per set; its ``answers`` are five values, each NULL or 0 to 3. Its ``score`` is the database's:
  the number of live questions answered correctly, computed at insert whatever is sent (bridge_app cannot name the
  column; read it back) and again on every pull and restore (``app_rescore_quiz_set``). ``finished_at`` and
  ``created_at`` are the database's clock. Append-only for the app. Nobody but its developer reads an attempt row:
  staff admin reads a set's attempts in aggregate through ``app_quiz_set_stats(set)``.
- A flag is filed only through ``app_flag_question(question, reason, note)``: by a developer who played the set
  (insufficient_privilege otherwise: 403 ``play_first``), once per developer per question, at most 10 a Nairobi day,
  on a live question of an approved set; three counted flags (from accounts with a verified email and at least 3
  attempts on sets of earlier days) pull the question (reason ``three_flags``) and rescore the set, unless staff
  restored it.
- ``quiz_profiles`` is the developer's own row (leaderboard opt-in and the streak, kept in code at finish time). The
  weekly board reads other developers only through ``app_quiz_board()``, and only of the caller's kind: real accounts
  for a real caller, demo accounts for a demo caller.

The nightly job (no user bound) asks ``app_quiz_day_taken(day)`` and ``app_quiz_recent_prompt_hashes(since)`` (it
reads no quiz row itself), then inserts the set and its five questions without RETURNING (``eager_defaults`` is off on
both mappers: an unbound session reads no quiz row).
"""

from __future__ import annotations

from datetime import date, datetime
from itertools import combinations
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, IdMixin, Tenancy

CURATED = {"info": {"tenancy": Tenancy.CURATED}}
USER = {"info": {"tenancy": Tenancy.USER, "tenant_column": "user_id"}}

SET_STATUSES = ("draft", "approved", "rejected")
SET_ORIGINS = ("model", "seeded")
QUESTION_STATUSES = ("live", "pulled")
FLAG_REASONS = ("wrong_answer", "unclear", "outdated", "other")
QUESTIONS_PER_SET = 5
OPTIONS_PER_QUESTION = 4
PROMPT_MAX_CHARS = 300
OPTION_MAX_CHARS = 120
WHY_MAX_CHARS = 600
SOURCE_ID_MAX_CHARS = 80
SOURCE_TITLE_MAX_CHARS = 160
SOURCE_URL_MAX_CHARS = 400
TOPIC_MAX_CHARS = 60
REASON_MAX_CHARS = 300  # a pull's reason and a flag's note
RAW_TEXT_MAX_CHARS = 8 * REASON_MAX_CHARS  # the API's bound on a note or reason as sent, before collapsing whitespace
MAX_TIME_MS = 86_400_000  # an attempt's total time: at most a day
FLAGS_TO_PULL = 3  # distinct developers whose flags pull a question (app_flag_question)
FLAGS_PER_DAY = 10  # per developer and Nairobi day (app_flag_question)
AUTO_PULL_REASON = "three_flags"  # pulled_reason of a question the flags pulled (a staff pull carries their text)


def _text(column: str, max_chars: int) -> str:
    """Not blank, at most ``max_chars`` characters, no control character."""
    return f"{column} ~ '[^[:space:]]' AND char_length({column}) <= {max_chars} AND {column} !~ '[[:cntrl:]]'"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


# Four options, each 1 to 120 characters without a control character, pairwise distinct (the app also compares them
# after NFKC and whitespace collapsing); no NULL element; indexed from 1.
OPTIONS_VALID = (
    f"cardinality(options) = {OPTIONS_PER_QUESTION} AND array_ndims(options) = 1 AND array_lower(options, 1) = 1"
    " AND array_position(options, NULL) IS NULL AND "
    + " AND ".join(_text(f"options[{n}]", OPTION_MAX_CHARS) for n in range(1, OPTIONS_PER_QUESTION + 1))
    + " AND "
    + " AND ".join(f"options[{a}] <> options[{b}]" for a, b in combinations(range(1, OPTIONS_PER_QUESTION + 1), 2))
)
# Five answers indexed from 1 (answers[p] answers the question at position p), each NULL (skipped) or 0 to 3.
ANSWERS_VALID = (
    f"cardinality(answers) = {QUESTIONS_PER_SET} AND array_ndims(answers) = 1 AND array_lower(answers, 1) = 1"
    f" AND 0 <= ALL (answers) AND {OPTIONS_PER_QUESTION - 1} >= ALL (answers)"
)
TRACE_ID = "^[A-Za-z0-9._:-]{1,64}$"  # llm_calls.trace_id (bridge.llm.types.TRACE_ID)


class QuizSet(IdMixin, Base):
    """The five questions of one Nairobi day (``quiz_date``). Drafted by the nightly job (bridge_app with no user bound
    inserts ``id``, ``quiz_date`` (today or later), ``origin`` and ``llm_trace_id``, the generating call's trace id,
    which joins its ``llm_calls`` rows: required for ``model``) or written by the seed (``seeded``, the trace id
    optional; the owner writes a past day). ``status`` moves
    once, ``draft`` to ``approved`` (only with its five questions) or ``rejected``, through
    ``app_decide_quiz_set(set, decision)`` (staff admin; ``decided_by`` and ``decided_at`` are set with it); then
    nothing changes. At most one draft or approved set per day (``uq_quiz_sets_quiz_date``, partial): a rejected day
    may be drafted again."""

    __tablename__ = "quiz_sets"
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012  # the job inserts and reads no quiz row back
    __table_args__ = (
        Index("uq_quiz_sets_quiz_date", "quiz_date", unique=True, postgresql_where=text("status <> 'rejected'")),
        CheckConstraint(_in("status", SET_STATUSES), name="status_known"),
        CheckConstraint(_in("origin", SET_ORIGINS), name="origin_known"),
        CheckConstraint(
            f"(llm_trace_id IS NULL OR llm_trace_id ~ '{TRACE_ID}')"
            " AND (origin = 'seeded' OR llm_trace_id IS NOT NULL)",
            name="trace_of_model",
        ),
        CheckConstraint(
            "CASE status WHEN 'draft' THEN decided_at IS NULL AND decided_by IS NULL"
            " ELSE decided_at IS NOT NULL AND (decided_by IS NOT NULL OR origin = 'seeded') END",
            name="decision_complete",
        ),
        CURATED,
    )

    quiz_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))  # SET_STATUSES
    origin: Mapped[str] = mapped_column(Text)  # SET_ORIGINS
    # Written by the job, read by staff only (app_quiz_set_detail): bridge_app holds no SELECT on the three.
    llm_trace_id: Mapped[str | None] = mapped_column(String(64), deferred=True, deferred_raiseload=True)
    decided_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), deferred=True, deferred_raiseload=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), deferred=True, deferred_raiseload=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))


class QuizQuestion(IdMixin, Base):
    """One question of a set, at ``position`` 1 to 5: a prompt, four distinct options, the ``answer`` index (0 to 3)
    and a ``why``, a source of the curated list (``source_id``, its title and https URL copied at generation), a topic
    and ``prompt_hash`` (SHA-256 of the NFKC- and whitespace-collapsed prompt, written by the app, for the 60-day
    no-repeat check). Added only to a draft set; never changed but by its pull (``status`` ``pulled`` with
    ``pulled_at`` and ``pulled_reason``) or restore (``live``, with ``restored_at``: flags never pull a question staff
    restored), which rescore the set's attempts. bridge_app reads every
    column but ``answer`` and ``why`` (``app_quiz_answers``): both are deferred with raiseload."""

    __tablename__ = "quiz_questions"
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012  # the job inserts and reads no quiz row back
    __table_args__ = (
        UniqueConstraint("set_id", "position"),
        CheckConstraint(f"position BETWEEN 1 AND {QUESTIONS_PER_SET}", name="position_range"),
        CheckConstraint(_text("prompt", PROMPT_MAX_CHARS), name="prompt_valid"),
        CheckConstraint(OPTIONS_VALID, name="options_valid"),
        CheckConstraint(f"answer BETWEEN 0 AND {OPTIONS_PER_QUESTION - 1}", name="answer_range"),
        CheckConstraint(_text("why", WHY_MAX_CHARS), name="why_valid"),
        CheckConstraint(
            f"source_id ~ '^[[:graph:]]+$' AND char_length(source_id) <= {SOURCE_ID_MAX_CHARS}", name="source_id_valid"
        ),
        CheckConstraint(_text("source_title", SOURCE_TITLE_MAX_CHARS), name="source_title_valid"),
        CheckConstraint(
            f"char_length(source_url) <= {SOURCE_URL_MAX_CHARS} AND source_url ~ '^https://[^[:space:][:cntrl:]]+$'",
            name="source_url_valid",
        ),
        CheckConstraint(_text("topic", TOPIC_MAX_CHARS), name="topic_valid"),
        CheckConstraint("octet_length(prompt_hash) = 32", name="prompt_hash_length"),
        CheckConstraint(_in("status", QUESTION_STATUSES), name="status_known"),
        CheckConstraint(
            "(status = 'pulled') = (pulled_at IS NOT NULL) AND (status = 'pulled') = (pulled_reason IS NOT NULL)"
            f" AND (pulled_reason IS NULL OR (pulled_reason ~ '[^[:space:]]'"
            f" AND char_length(pulled_reason) <= {REASON_MAX_CHARS} AND pulled_reason !~ '[[:cntrl:]]'))",
            name="pull_complete",
        ),
        CURATED,
    )

    set_id: Mapped[UUID] = mapped_column(ForeignKey("quiz_sets.id"))
    position: Mapped[int] = mapped_column(SmallInteger)
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(ARRAY(Text))
    answer: Mapped[int] = mapped_column(SmallInteger, deferred=True, deferred_raiseload=True)
    why: Mapped[str] = mapped_column(Text, deferred=True, deferred_raiseload=True)
    source_id: Mapped[str] = mapped_column(Text)
    source_title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text)
    prompt_hash: Mapped[bytes] = mapped_column(LargeBinary, index=True)
    status: Mapped[str] = mapped_column(Text, server_default=text("'live'"))  # QUESTION_STATUSES
    pulled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pulled_reason: Mapped[str | None] = mapped_column(Text)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # flags never re-pull after it
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))


class QuizAttempt(IdMixin, Base):
    """A developer's one finished attempt on a set: the app inserts ``id``, ``set_id``, ``user_id`` (the caller),
    ``started_at`` (optional, not after the finish), ``answers`` (five, each NULL or 0 to 3) and ``time_ms``, on the
    approved set of the current Nairobi day only. ``score`` is the database's (computed at insert whatever is sent and
    on every rescore: read it back), as are ``finished_at`` and ``created_at``. Never updated or deleted by the app;
    read by its developer only (staff: ``app_quiz_set_stats``)."""

    __tablename__ = "quiz_attempts"
    __table_args__ = (
        UniqueConstraint("set_id", "user_id"),
        Index("ix_quiz_attempts_user_id_finished_at", "user_id", "finished_at"),
        CheckConstraint(ANSWERS_VALID, name="answers_valid"),
        CheckConstraint(f"score BETWEEN 0 AND {QUESTIONS_PER_SET}", name="score_range"),
        CheckConstraint(f"time_ms BETWEEN 0 AND {MAX_TIME_MS}", name="time_ms_range"),
        CheckConstraint("started_at IS NULL OR started_at <= finished_at", name="started_before_finished"),
        USER,
    )

    set_id: Mapped[UUID] = mapped_column(ForeignKey("quiz_sets.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
    answers: Mapped[list[int | None]] = mapped_column(ARRAY(SmallInteger))
    score: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    time_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))


class QuizFlag(IdMixin, Base):
    """A developer's flag on a question of a set they played, written only by ``app_flag_question`` (bridge_app reads
    its own and staff admin every flag; no direct write). ``created_at`` is the database's clock."""

    __tablename__ = "quiz_flags"
    __table_args__ = (
        UniqueConstraint("question_id", "user_id"),
        Index("ix_quiz_flags_user_id_created_at", "user_id", "created_at"),
        CheckConstraint(_in("reason", FLAG_REASONS), name="reason_known"),
        CheckConstraint(
            f"note IS NULL OR (note ~ '[^[:space:]]' AND char_length(note) <= {REASON_MAX_CHARS}"
            " AND note !~ '[[:cntrl:]]')",
            name="note_length",
        ),
        USER,
    )

    question_id: Mapped[UUID] = mapped_column(ForeignKey("quiz_questions.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    reason: Mapped[str] = mapped_column(Text)  # FLAG_REASONS
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))


class QuizProfile(Base):
    """A developer's quiz settings and streak, their own row only (bridge_app: read, insert, update every column but
    the key and ``created_at``). ``current_streak`` counts consecutive days that had an approved set played, up to
    ``last_played_on`` (a day without a set is skipped); ``best_streak`` is never below it. Kept in code when an attempt
    finishes (``bridge.quiz.streaks``)."""

    __tablename__ = "quiz_profiles"
    __table_args__ = (
        CheckConstraint("current_streak >= 0 AND best_streak >= current_streak", name="streaks_valid"),
        USER,
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    leaderboard_opt_in: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    current_streak: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    best_streak: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    last_played_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
