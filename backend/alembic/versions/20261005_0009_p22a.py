"""Schema v7 (P22 track A): Today's five, the daily developer quiz.

REQ-DEV-01 (D-59). Design: ``docs/platform/tasks/P22.md`` section "A — Today's five". Additive: five new tables
(``quiz_sets``, ``quiz_questions``, ``quiz_attempts``, ``quiz_flags``, ``quiz_profiles``) with their policies, triggers
and grants, and seventeen new functions (four of them trigger functions); one new tenancy class in the ORM
(``Tenancy.CURATED``: the sets and questions, which have no owner). No enum type (text columns with CHECKs). Nothing
of revisions 0001 to 0008 is changed or dropped; the triggers reuse ``block_mutation()`` (revision 0002) and the clock
``app_clock_now()`` (revision 0003). The upgrade is additive; the downgrade is destructive (it drops the quiz: see
``downgrade()``).

Who reads and writes what (bridge_app; there is no worker role: the nightly job is bridge_app with no user bound, as
revisions 0007 and 0008's jobs; a "developer" is an active user with a developer profile, ``app_is_developer()``):

- ``quiz_sets`` (CURATED; bridge_app: SELECT, INSERT of ``id``, ``quiz_date``, ``origin``, ``llm_trace_id``). Staff
  admin reads every set, a developer the approved ones, nobody else any. The job (no user bound) inserts a draft for
  today or a later Nairobi day. ``status`` moves once, ``draft`` to ``approved`` (only with its five questions) or
  ``rejected``, by ``app_decide_quiz_set(set, decision)`` (staff admin; sets ``decided_by`` and ``decided_at``); then
  nothing of the set changes (``quiz_sets_guard``, every role; its day, origin, trace id and creation time never
  change). One draft or approved set per day: the partial unique index ``uq_quiz_sets_quiz_date`` (``status <>
  'rejected'``), so a rejected day may be drafted again. ``llm_trace_id`` is the generating call's trace id (it joins
  that call's ``llm_calls`` rows, one per attempt; a ledger row's id is not returned to the caller and an in-memory
  ledger writes none, so there is no foreign key), required for ``origin = 'model'``, optional for ``seeded``.
- ``quiz_questions`` (CURATED; bridge_app: SELECT of every column but ``answer`` and ``why``, INSERT of the content
  columns). Staff admin reads every question, a developer those of approved sets, live and pulled. ``answer`` and
  ``why`` are read only through ``app_quiz_answers(set)``: rows only for a caller with an attempt on the set (attempts
  are inserted finished) or staff admin. The job (no user bound) inserts them; ``quiz_questions_guard`` (every role)
  admits a question only into a draft set (locked FOR SHARE, so a concurrent decision waits) and changes nothing but
  the pull columns (``status``, ``pulled_at``, ``pulled_reason``), which only the definer functions below write.
  CHECKs: position 1 to 5 (unique per set), a prompt of 1 to 300 characters, four pairwise distinct options of 1 to
  120, the answer 0 to 3, a why of 1 to 600 (none of them with a control character), a source id, title (160) and
  https URL (400), a topic (60), a 32-byte prompt hash, and a pull complete with its moment and reason (1 to 300).
- ``quiz_attempts`` (USER; bridge_app: SELECT, INSERT of ``id``, ``set_id``, ``user_id``, ``started_at``,
  ``answers``, ``time_ms``). The developer reads their own and nobody else any (minimisation: staff admin reads a
  set's attempts in aggregate only, through ``app_quiz_set_stats``). A developer inserts
  as themselves on the approved set of the current Nairobi day only (``app_nairobi_today()``, the shared clock at
  Africa/Nairobi), once per set (UNIQUE (set_id, user_id)). ``answers`` are five values indexed from 1 (``answers[p]``
  answers position p), each NULL or 0 to 3. ``score`` is the database's: ``quiz_attempts_score`` (BEFORE INSERT, every
  role) refuses a set that is not approved and sets the score to the number of live questions answered correctly,
  whatever was sent (the app cannot name the column, and it could not compute it: it never reads ``answer``); it reads
  the set FOR KEY SHARE, so a rescore in flight is waited for and an attempt is never scored against a stale pull.
  ``finished_at`` and ``created_at`` are the database's clock. No UPDATE or DELETE for the app; ``quiz_attempts_guard``
  (every role) lets an UPDATE change ``score`` only, and only to the computed one (the rescore's). Deleting a user
  deletes their attempts, flags and profile (ON DELETE CASCADE).
- ``quiz_flags`` (USER; bridge_app: SELECT only). The developer reads their own, staff admin every flag. Written only by
  ``app_flag_question``; never updated (``quiz_flags_no_update``, ``block_mutation()``, every role).
- ``quiz_profiles`` (USER; bridge_app: SELECT, INSERT, UPDATE of ``leaderboard_opt_in``, ``current_streak``,
  ``best_streak``, ``last_played_on``). The developer's own row only, inserted by a developer; the streak is kept in
  code when an attempt finishes (CHECK: ``best_streak >= current_streak >= 0``).

Indexes: the partial unique ``uq_quiz_sets_quiz_date``; ``uq_quiz_questions_set_id_position`` and
``ix_quiz_questions_prompt_hash`` (the no-repeat check); ``uq_quiz_attempts_set_id_user_id`` (it serves the set's
attempts, as ``uq_quiz_flags_question_id_user_id`` serves a question's flags, so neither needs an index of its own)
and ``ix_quiz_attempts_user_id_finished_at`` (a developer's history and streak); ``ix_quiz_flags_user_id_created_at``
(the daily cap).

Functions (SECURITY DEFINER unless noted; pinned search_path; EXECUTE revoked from PUBLIC; granted to bridge_app where
listed in ``FUNCTION_GRANTS``):

- ``app_nairobi_today()`` (INVOKER): the current Nairobi day on the shared clock. ``app_is_developer()``: the caller is
  an active user with a developer profile.
- ``app_quiz_answers(set)`` -> (question_id, answer, why) by position: a caller with an attempt on the set, or staff
  admin; no row otherwise.
- ``app_decide_quiz_set(set, decision)``: staff admin only (insufficient_privilege); ``approved`` or ``rejected``
  (invalid_parameter_value); the set locked FOR UPDATE; an unknown set no_data_found; a decided set
  object_not_in_prerequisite_state; approval without five questions check_violation (the guard).
- ``app_set_quiz_question_status(question, status, reason)`` -> attempts whose score changed: staff admin only; pull
  (``pulled`` with a reason of 1 to 300 characters) or restore (``live`` with no reason); an unknown question
  no_data_found; the same status again object_not_in_prerequisite_state. Locks the set FOR UPDATE, changes the
  question and rescores the set in the same transaction.
- ``app_flag_question(question, reason, note)`` -> (flag_id, pulled): a developer (anyone else, like an unknown
  question or one of a set not approved, gets no_data_found: they read no question), a reason of ``wrong_answer``,
  ``unclear``, ``outdated``, ``other`` and an optional note of 1 to 300 characters (invalid_parameter_value), who
  played the set (a finished attempt on it; insufficient_privilege, "play the set first", otherwise: accounts that
  never played cannot brigade a question out), on a live question (object_not_in_prerequisite_state when it was
  pulled); once per developer and question (unique_violation, constraint
  ``uq_quiz_flags_question_id_user_id``); at most 10 a Nairobi day per developer (program_limit_exceeded; serialised
  per developer by an advisory lock). Locks the set FOR UPDATE, inserts the flag and, when it is the question's third
  (from 3 distinct developers: one flag per developer), pulls it (``pulled_reason = 'three_flags'``) and rescores the
  set; ``pulled`` says so. Later flags on a question staff restored do not pull it again (the count passes 3 once).
- ``app_rescore_quiz_set(set)`` -> attempts whose score changed: staff admin, or a job with no user bound (a repair);
  an unknown set no_data_found. The flag and staff paths rescore through the internal ``quiz_rescore_set(set)``
  (INVOKER, no EXECUTE grant), which locks the set FOR UPDATE and sets every attempt's score to
  ``quiz_attempt_score(set, answers)`` (INVOKER, no EXECUTE grant: the live questions answered correctly, a pulled one
  counting for nobody).
- ``app_quiz_set_stats(set)`` -> (attempts, average_score, per_question_correct): staff admin only; a set's attempts in
  aggregate (their number, the average score to 2 decimals, and by position how many answered correctly).
- ``app_quiz_board()`` -> (rank, handle, points, time_ms, is_caller): a developer only. The ISO week (Monday to Sunday)
  of the current Nairobi day; the points and total time of each developer's attempts on that week's approved sets;
  ranked (``rank()``: more points first, then less time; equal points and time share a rank) among active developers
  who opted in and played this week and are of the caller's kind: real accounts for a real caller (demo accounts never
  show to one), demo accounts (``users.demo_account``) for a demo caller (the local demo shows its own people); the
  first 20 rows by rank and handle, plus the caller's own row when it is not among them (``is_caller``): their points
  and time (0 when they did not play), and the rank they would have among their kind (NULL when they did not play).
  Nothing of past weeks.
- ``app_quiz_day_taken(day)`` and ``app_quiz_recent_prompt_hashes(since)``: the quiz job only, with no user bound
  (insufficient_privilege otherwise; invalid_parameter_value for a NULL argument). Whether the day has a draft or
  approved set; the distinct prompt hashes of draft and approved sets dated ``since`` or later.

Operating rules for the code that uses this schema:

- The job, with no user bound: ``app_quiz_day_taken(day)`` (never call the model when true), the model call, the code
  checks against ``app_quiz_recent_prompt_hashes(day - 60)``, then one transaction inserting the set and its five
  questions, without RETURNING (``eager_defaults`` is off on both mappers: an unbound session reads no quiz row). A
  unique violation on ``uq_quiz_sets_quiz_date`` is a concurrent run: drop the draft.
- Serve sets and questions under the developer's own binding (RLS hides drafts); never select ``answer`` or ``why``
  (deferred with raiseload in the mappers): call ``app_quiz_answers(set)`` after the attempt is inserted (the same
  transaction sees it). Insert the attempt leaving ``score``, ``finished_at`` and ``created_at`` out and read them
  back (RETURNING). Map the policy's refusal of an approved set of another day (the day ended since the set was
  served) to 409 ``set_closed``, the unique violation ``uq_quiz_attempts_set_id_user_id`` to 409 ``already_played``;
  the trigger's object_not_in_prerequisite_state (no approved set with that id) cannot follow a served set.
- Staff decisions and pulls only through ``app_decide_quiz_set`` and ``app_set_quiz_question_status``; the app writes
  the audit events (``quiz.set_decided`` and the pull's) in the same transaction. Flags only through
  ``SELECT * FROM app_flag_question(:question, :reason, :note)`` (insufficient_privilege is 403 ``play_first``). The
  board only through ``app_quiz_board()``; the staff set page's numbers only through ``app_quiz_set_stats(set)``.
- The seed writes ``seeded`` sets as the owner (it may date them in the past, approve them directly with
  ``decided_at`` and leave ``decided_by`` NULL); questions go into a draft before it is approved, attempts onto an
  approved set (their scores are computed by the database).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import combinations
from typing import NamedTuple

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("quiz_sets", "quiz_questions", "quiz_attempts", "quiz_flags", "quiz_profiles")
RLS_TABLES = NEW_TABLES

# Table privileges of bridge_app on this revision's tables; anything not listed is not granted. Column-scoped where the
# database owns a column (status, decisions, pulls, scores, times) or the app must never read one (answer, why).
QUESTION_READABLE = (
    "id, set_id, position, prompt, options, source_id, source_title, source_url, topic, prompt_hash, status,"
    " pulled_at, pulled_reason, created_at"
)
APP_GRANTS: dict[str, str] = {
    "quiz_sets": "SELECT, INSERT (id, quiz_date, origin, llm_trace_id)",
    "quiz_questions": (
        f"SELECT ({QUESTION_READABLE}), INSERT (id, set_id, position, prompt, options, answer, why, source_id,"
        " source_title, source_url, topic, prompt_hash)"
    ),
    "quiz_attempts": "SELECT, INSERT (id, set_id, user_id, started_at, answers, time_ms)",
    "quiz_flags": "SELECT",
    "quiz_profiles": (
        "SELECT, INSERT (user_id, leaderboard_opt_in, current_streak, best_streak, last_played_on),"
        " UPDATE (leaderboard_opt_in, current_streak, best_streak, last_played_on)"
    ),
}

# CHECK expressions, verbatim from the ORM models (bridge.quiz.models).
SET_STATUSES = ("draft", "approved", "rejected")
SET_ORIGINS = ("model", "seeded")
QUESTION_STATUSES = ("live", "pulled")
FLAG_REASONS = ("wrong_answer", "unclear", "outdated", "other")
TRACE_ID = "^[A-Za-z0-9._:-]{1,64}$"


def _text(column: str, max_chars: int) -> str:
    return f"{column} ~ '[^[:space:]]' AND char_length({column}) <= {max_chars} AND {column} !~ '[[:cntrl:]]'"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


OPTIONS_VALID = (
    "cardinality(options) = 4 AND array_ndims(options) = 1 AND array_lower(options, 1) = 1"
    " AND array_position(options, NULL) IS NULL AND "
    + " AND ".join(_text(f"options[{n}]", 120) for n in range(1, 5))
    + " AND "
    + " AND ".join(f"options[{a}] <> options[{b}]" for a, b in combinations(range(1, 5), 2))
)
ANSWERS_VALID = (
    "cardinality(answers) = 5 AND array_ndims(answers) = 1 AND array_lower(answers, 1) = 1"
    " AND 0 <= ALL (answers) AND 3 >= ALL (answers)"
)


class Policy(NamedTuple):
    """One RLS policy for one command, named ``<role>_<command>[_<suffix>]`` (unique per table)."""

    table: str
    command: str
    using: str | None = None
    check: str | None = None
    role: str = "bridge_app"
    suffix: str = ""

    @property
    def name(self) -> str:
        return f"{self.role}_{self.command.lower()}" + (f"_{self.suffix}" if self.suffix else "")

    def create_sql(self) -> str:
        # USING filters existing rows (SELECT, UPDATE, DELETE); WITH CHECK validates new rows (INSERT, UPDATE).
        shape = {"SELECT": (True, False), "INSERT": (False, True), "UPDATE": (True, True), "DELETE": (True, False)}
        if shape.get(self.command) != (self.using is not None, self.check is not None):
            raise ValueError(f"malformed policy: {self}")
        sql = f"CREATE POLICY {self.name} ON {self.table} AS PERMISSIVE FOR {self.command} TO {self.role}"
        if self.using is not None:
            sql += f" USING ({self.using})"
        if self.check is not None:
            sql += f" WITH CHECK ({self.check})"
        return sql + ";"


_STAFF_ADMIN = "app_is_staff('{admin}')"
_JOB = "app_user_id() IS NULL"  # the nightly quiz job: bridge_app with no user bound
_OWN = "user_id = app_user_id()"
_APPROVED_SET = "EXISTS (SELECT 1 FROM quiz_sets s WHERE s.id = {table}.set_id AND s.status = 'approved'{today})"

POLICIES: tuple[Policy, ...] = (
    # --- quiz_sets (CURATED): staff admin reads all, a developer the approved ones; the job inserts drafts ---
    Policy("quiz_sets", "SELECT", f"{_STAFF_ADMIN} OR (status = 'approved' AND app_is_developer())"),
    Policy("quiz_sets", "INSERT", check=f"{_JOB} AND quiz_date >= app_nairobi_today()"),
    # --- quiz_questions (CURATED): those of the sets the caller reads (answer and why by column grant: never) ---
    Policy(
        "quiz_questions",
        "SELECT",
        f"{_STAFF_ADMIN} OR (app_is_developer() AND {_APPROVED_SET.format(table='quiz_questions', today='')})",
    ),
    Policy("quiz_questions", "INSERT", check=_JOB),
    # --- quiz_attempts (USER): the developer's own (staff admin reads all); today's approved set only ---
    Policy("quiz_attempts", "SELECT", _OWN),  # nobody else reads an attempt (staff: app_quiz_set_stats)
    Policy(
        "quiz_attempts",
        "INSERT",
        check=f"{_OWN} AND app_is_developer() AND "
        + _APPROVED_SET.format(table="quiz_attempts", today=" AND s.quiz_date = app_nairobi_today()"),
    ),
    # --- quiz_flags (USER): read only (written by app_flag_question) ---
    Policy("quiz_flags", "SELECT", f"{_OWN} OR {_STAFF_ADMIN}"),
    # --- quiz_profiles (USER): the developer's own row ---
    Policy("quiz_profiles", "SELECT", _OWN),
    Policy("quiz_profiles", "INSERT", check=f"{_OWN} AND app_is_developer()"),
    Policy("quiz_profiles", "UPDATE", _OWN, _OWN),
)

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0008: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS; internal and trigger functions to nobody).
# SECURITY DEFINER functions run as bridge_owner, which bypasses RLS (ENABLED, not FORCED). Lock order everywhere: the
# set's row first (FOR UPDATE by every path that pulls, restores or rescores; FOR KEY SHARE by an attempt's insert,
# FOR SHARE by a question's), then a developer's advisory lock (flags).
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- The current Nairobi day on the shared clock (dev, test and staging may move it: app_clock_now()). The attempts'
-- INSERT policy, the job's draft policy, the flag cap and the board read it.
CREATE FUNCTION app_nairobi_today() RETURNS date
    LANGUAGE sql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$ SELECT (public.app_clock_now() AT TIME ZONE 'Africa/Nairobi')::date $$;

-- The caller (app.user_id) is an active user with a developer profile: who plays the quiz. Organisation-only accounts,
-- and staff without a developer profile, are not. SECURITY DEFINER: reads users and profiles whatever the caller's RLS.
CREATE FUNCTION app_is_developer() RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.developer_profiles d JOIN public.users u ON u.id = d.user_id
         WHERE d.user_id = public.app_user_id() AND u.status = 'active'
    )
$$;

-- An attempt's score: the live questions of the set answered correctly (answers[p] against the question at position
-- p; NULL answers and pulled questions count for nobody). Internal (no EXECUTE grant): the attempts' triggers and the
-- rescore, all running as the owner.
CREATE FUNCTION quiz_attempt_score(p_set uuid, p_answers smallint[]) RETURNS smallint
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT count(*)::smallint FROM public.quiz_questions q
     WHERE q.set_id = p_set AND q.status = 'live' AND q.answer = p_answers[q.position]
$$;

-- Rescores every attempt of the set (quiz_attempt_score) and returns how many scores changed. Locks the set FOR UPDATE
-- first, so an attempt's insert in flight (FOR KEY SHARE) is waited for and then rescored, and a later one waits and
-- scores against the new statuses. Internal (no EXECUTE grant): app_rescore_quiz_set, app_set_quiz_question_status and
-- app_flag_question, which run as the owner.
CREATE FUNCTION quiz_rescore_set(p_set uuid) RETURNS integer
    LANGUAGE plpgsql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_changed integer;
BEGIN
    PERFORM 1 FROM public.quiz_sets s WHERE s.id = p_set FOR UPDATE;
    UPDATE public.quiz_attempts a
       SET score = public.quiz_attempt_score(a.set_id, a.answers)
     WHERE a.set_id = p_set AND a.score IS DISTINCT FROM public.quiz_attempt_score(a.set_id, a.answers);
    GET DIAGNOSTICS v_changed = ROW_COUNT;
    RETURN v_changed;
END;
$$;

-- Rescores a set's attempts on request (REQ-DEV-01): staff admin, or a job with no user bound (a repair); the pull and
-- restore paths rescore by themselves. Returns how many scores changed.
CREATE FUNCTION app_rescore_quiz_set(p_set uuid) RETURNS integer
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT (public.app_user_id() IS NULL OR public.app_is_staff('{admin}')) THEN
        RAISE EXCEPTION 'app_rescore_quiz_set: staff admin, or a job with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.quiz_sets s WHERE s.id = p_set) THEN
        RAISE EXCEPTION 'app_rescore_quiz_set: no quiz set with that id' USING ERRCODE = 'no_data_found';
    END IF;
    RETURN public.quiz_rescore_set(p_set);
END;
$$;

-- A staff admin decides a draft set once (D-59): approved (with its five questions: quiz_sets_guard) or rejected, as
-- themselves, at the shared clock. The app writes the audit event (quiz.set_decided) in the same transaction.
CREATE FUNCTION app_decide_quiz_set(p_set uuid, p_decision text) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_status text;
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_decide_quiz_set: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_decision IS NULL OR p_decision NOT IN ('approved', 'rejected') THEN
        RAISE EXCEPTION 'app_decide_quiz_set: the decision is approved or rejected'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT s.status INTO v_status FROM public.quiz_sets s WHERE s.id = p_set FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_decide_quiz_set: no quiz set with that id' USING ERRCODE = 'no_data_found';
    END IF;
    IF v_status <> 'draft' THEN
        RAISE EXCEPTION 'app_decide_quiz_set: the set was already decided (%)', v_status
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    UPDATE public.quiz_sets
       SET status = p_decision, decided_by = public.app_user_id(), decided_at = public.app_clock_now()
     WHERE id = p_set;
END;
$$;

-- A staff admin pulls a question (with a reason) or restores it, and the set's attempts are rescored in the same
-- transaction; returns how many scores changed. The app writes the audit event.
CREATE FUNCTION app_set_quiz_question_status(p_question uuid, p_status text, p_reason text) RETURNS integer
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_set uuid;
    v_status text;
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_set_quiz_question_status: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_status IS NULL OR p_status NOT IN ('live', 'pulled')
       OR (p_status = 'pulled' AND (p_reason IS NULL OR p_reason !~ '[^[:space:]]' OR char_length(p_reason) > 300))
       OR (p_status = 'live' AND p_reason IS NOT NULL) THEN
        RAISE EXCEPTION 'app_set_quiz_question_status: pulled with a reason of 1 to 300 characters, or live without one'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT q.set_id INTO v_set FROM public.quiz_questions q WHERE q.id = p_question;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_set_quiz_question_status: no quiz question with that id' USING ERRCODE = 'no_data_found';
    END IF;
    PERFORM 1 FROM public.quiz_sets s WHERE s.id = v_set FOR UPDATE;
    SELECT q.status INTO v_status FROM public.quiz_questions q WHERE q.id = p_question;
    IF v_status = p_status THEN
        RAISE EXCEPTION 'app_set_quiz_question_status: the question is already %', p_status
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    UPDATE public.quiz_questions
       SET status = p_status,
           pulled_at = CASE WHEN p_status = 'pulled' THEN public.app_clock_now() END,
           pulled_reason = CASE WHEN p_status = 'pulled' THEN p_reason END
     WHERE id = p_question;
    RETURN public.quiz_rescore_set(v_set);
END;
$$;

-- A developer flags a live question of an approved set (D-59) they played (a finished attempt on its set: accounts
-- that never played cannot brigade a question out), once per question, at most 10 a Nairobi day (fixed here: no caller
-- names the limit), a reason code and an optional note. A caller who is not a developer reads no question, so for them
-- the question does not exist. The question's third flag (one per developer, so three distinct developers who played)
-- pulls it with the reason 'three_flags' and rescores the set in the same transaction; a question staff restored
-- afterwards is not pulled again by later flags. Serialised per set (FOR UPDATE) and per developer (an advisory lock;
-- the count then reads every committed flag at READ COMMITTED, the application's level).
CREATE FUNCTION app_flag_question(p_question uuid, p_reason text, p_note text)
    RETURNS TABLE (flag_id uuid, pulled boolean)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_set uuid;
    v_flag uuid;
BEGIN
    IF v_user IS NULL OR NOT public.app_is_developer() THEN
        RAISE EXCEPTION 'app_flag_question: no question of an approved set with that id'
            USING ERRCODE = 'no_data_found';
    END IF;
    IF p_reason IS NULL OR p_reason NOT IN ('wrong_answer', 'unclear', 'outdated', 'other')
       OR (p_note IS NOT NULL AND (p_note !~ '[^[:space:]]' OR char_length(p_note) > 300)) THEN
        RAISE EXCEPTION 'app_flag_question: a reason of wrong_answer, unclear, outdated or other, and a note of 1'
            ' to 300 characters or none' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT q.set_id INTO v_set FROM public.quiz_questions q JOIN public.quiz_sets s ON s.id = q.set_id
     WHERE q.id = p_question AND s.status = 'approved';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_flag_question: no question of an approved set with that id'
            USING ERRCODE = 'no_data_found';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.quiz_attempts a WHERE a.set_id = v_set AND a.user_id = v_user) THEN
        RAISE EXCEPTION 'app_flag_question: play the set first' USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM 1 FROM public.quiz_sets s WHERE s.id = v_set FOR UPDATE;
    IF (SELECT q.status FROM public.quiz_questions q WHERE q.id = p_question) <> 'live' THEN
        RAISE EXCEPTION 'app_flag_question: the question was pulled' USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('quiz_flags:' || v_user::text, 0));
    IF EXISTS (SELECT 1 FROM public.quiz_flags f WHERE f.question_id = p_question AND f.user_id = v_user) THEN
        RAISE EXCEPTION 'app_flag_question: the question is already flagged by the caller'
            USING ERRCODE = 'unique_violation', CONSTRAINT = 'uq_quiz_flags_question_id_user_id';
    END IF;
    IF (SELECT count(*) FROM public.quiz_flags f
         WHERE f.user_id = v_user
           AND f.created_at >= (public.app_nairobi_today()::timestamp AT TIME ZONE 'Africa/Nairobi')) >= 10 THEN
        RAISE EXCEPTION 'app_flag_question: at most 10 flags a day' USING ERRCODE = 'program_limit_exceeded';
    END IF;
    v_flag := public.uuid7();
    INSERT INTO public.quiz_flags (id, question_id, user_id, reason, note)
    VALUES (v_flag, p_question, v_user, p_reason, p_note);
    IF (SELECT count(*) FROM public.quiz_flags f WHERE f.question_id = p_question) = 3 THEN
        UPDATE public.quiz_questions
           SET status = 'pulled', pulled_at = public.app_clock_now(), pulled_reason = 'three_flags'
         WHERE id = p_question;
        PERFORM public.quiz_rescore_set(v_set);
        RETURN QUERY SELECT v_flag, true;
        RETURN;
    END IF;
    RETURN QUERY SELECT v_flag, false;
END;
$$;

-- A set's answers and whys (D-59: never before the developer's attempt): rows only for a caller with an attempt on the
-- set (attempts are inserted finished) or staff admin, by position; no row otherwise. bridge_app holds no SELECT on
-- either column.
CREATE FUNCTION app_quiz_answers(p_set uuid) RETURNS TABLE (question_id uuid, answer smallint, why text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT q.id, q.answer, q.why
      FROM public.quiz_questions q
     WHERE q.set_id = p_set
       AND (public.app_is_staff('{admin}')
            OR EXISTS (SELECT 1 FROM public.quiz_attempts a
                        WHERE a.set_id = p_set AND a.user_id = public.app_user_id()))
     ORDER BY q.position
$$;

-- This week's board (D-59): the ISO week (Monday to Sunday) of the current Nairobi day, the points and total time of
-- each developer's attempts on the week's approved sets, ranked (more points first, then less time; equal points and
-- time share a rank) among active developers who opted in and played this week and are of the caller's kind: real
-- accounts for a real caller (a demo account never shows to one), demo accounts (users.demo_account) for a demo
-- caller (the local demo shows its own people). The first 20 rows by rank and handle, plus the caller's own row when
-- it is not among them (their points and time, 0 when they did not play, and the rank they would have among their
-- kind: NULL when they did not play). Developers only. SECURITY DEFINER: reads every developer's attempts, opt-in and
-- handle, and returns handles and sums only.
CREATE FUNCTION app_quiz_board()
    RETURNS TABLE (rank integer, handle text, points integer, time_ms bigint, is_caller boolean)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_demo boolean;
    v_today date;
    v_monday date;
BEGIN
    IF v_user IS NULL OR NOT public.app_is_developer() THEN
        RAISE EXCEPTION 'app_quiz_board: developers only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT u.demo_account INTO v_demo FROM public.users u WHERE u.id = v_user;
    v_today := public.app_nairobi_today();
    v_monday := v_today - (extract(isodow FROM v_today)::integer - 1);
    RETURN QUERY
    WITH week AS (
        SELECT a.user_id, sum(a.score)::integer AS pts, sum(a.time_ms)::bigint AS ms
          FROM public.quiz_attempts a JOIN public.quiz_sets s ON s.id = a.set_id
         WHERE s.status = 'approved' AND s.quiz_date BETWEEN v_monday AND v_monday + 6
         GROUP BY a.user_id
    ), board AS (
        SELECT w.user_id, d.handle::text AS who, w.pts, w.ms,
               (pg_catalog.rank() OVER (ORDER BY w.pts DESC, w.ms))::integer AS pos
          FROM week w
          JOIN public.quiz_profiles p ON p.user_id = w.user_id AND p.leaderboard_opt_in
          JOIN public.users u ON u.id = w.user_id AND u.status = 'active' AND u.demo_account = v_demo
          JOIN public.developer_profiles d ON d.user_id = w.user_id
    ), leaders AS (
        SELECT b.user_id, b.who, b.pts, b.ms, b.pos FROM board b ORDER BY b.pos, b.who LIMIT 20
    ), mine AS (
        SELECT coalesce(w.pts, 0) AS pts, coalesce(w.ms, 0::bigint) AS ms, w.user_id IS NOT NULL AS played
          FROM (SELECT v_user AS user_id) me LEFT JOIN week w ON w.user_id = me.user_id
    )
    SELECT l.pos, l.who, l.pts, l.ms, l.user_id = v_user FROM leaders l
    UNION ALL
    SELECT CASE WHEN m.played THEN
                coalesce((SELECT b.pos FROM board b WHERE b.user_id = v_user),
                         1 + (SELECT count(*) FROM board b
                               WHERE b.pts > m.pts OR (b.pts = m.pts AND b.ms < m.ms))::integer)
           END,
           d.handle::text, m.pts, m.ms, true
      FROM mine m
      JOIN public.developer_profiles d ON d.user_id = v_user
     WHERE NOT EXISTS (SELECT 1 FROM leaders l WHERE l.user_id = v_user)
     ORDER BY 1 NULLS LAST, 2;
END;
$$;

-- A set's attempts in aggregate, for the staff queue (D-59; minimisation: no role but the owner reads another
-- developer's attempt row): how many, their average score (2 decimals; NULL with none) and, by position, how many
-- answered the question correctly (pulled ones included, against their answer). Staff admin only; an unknown set
-- no_data_found. SECURITY DEFINER: reads the attempts and answers, returns counts only.
CREATE FUNCTION app_quiz_set_stats(p_set uuid)
    RETURNS TABLE (attempts integer, average_score numeric, per_question_correct integer[])
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_quiz_set_stats: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.quiz_sets s WHERE s.id = p_set) THEN
        RAISE EXCEPTION 'app_quiz_set_stats: no quiz set with that id' USING ERRCODE = 'no_data_found';
    END IF;
    RETURN QUERY
    SELECT (SELECT count(*)::integer FROM public.quiz_attempts a WHERE a.set_id = p_set),
           (SELECT round(avg(a.score), 2) FROM public.quiz_attempts a WHERE a.set_id = p_set),
           ARRAY(SELECT (SELECT count(*)::integer FROM public.quiz_attempts a
                          WHERE a.set_id = p_set AND a.answers[q.position] = q.answer)
                   FROM public.quiz_questions q WHERE q.set_id = p_set ORDER BY q.position);
END;
$$;

-- Whether p_day already has a draft or approved set (the quiz job never calls the model then; a rejected day may be
-- drafted again). The job only, with no user bound: a signed-in request learns nothing of drafts.
CREATE FUNCTION app_quiz_day_taken(p_day date) RETURNS boolean
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_quiz_day_taken: the quiz job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_day IS NULL THEN
        RAISE EXCEPTION 'app_quiz_day_taken: name the day' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN EXISTS (SELECT 1 FROM public.quiz_sets s WHERE s.quiz_date = p_day AND s.status <> 'rejected');
END;
$$;

-- The prompt hashes of the draft and approved sets dated p_since or later (the job's no-repeat check over 60 days):
-- hashes only. The job only, with no user bound.
CREATE FUNCTION app_quiz_recent_prompt_hashes(p_since date) RETURNS TABLE (prompt_hash bytea)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_quiz_recent_prompt_hashes: the quiz job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_since IS NULL THEN
        RAISE EXCEPTION 'app_quiz_recent_prompt_hashes: name the first day' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT DISTINCT q.prompt_hash FROM public.quiz_questions q JOIN public.quiz_sets s ON s.id = q.set_id
     WHERE s.quiz_date >= p_since AND s.status <> 'rejected'
     ORDER BY 1;
END;
$$;

-- A set changes once, by its decision: draft to approved (only with its five questions) or rejected; its day, origin,
-- trace id and creation time never change; a decided set never changes again. For every role (bridge_app holds no
-- UPDATE: app_decide_quiz_set). SECURITY INVOKER (the writer is the owner).
CREATE FUNCTION quiz_sets_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.id, NEW.quiz_date, NEW.origin, NEW.llm_trace_id, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.quiz_date, OLD.origin, OLD.llm_trace_id, OLD.created_at) THEN
        RAISE EXCEPTION 'quiz_sets: a set''s day, origin, generating call and creation time never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'draft' OR NEW.status = 'draft' THEN
        RAISE EXCEPTION 'quiz_sets: a set changes only by its one decision, from draft to approved or rejected'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF NEW.status = 'approved' AND (SELECT count(*) FROM public.quiz_questions q WHERE q.set_id = NEW.id) <> 5 THEN
        RAISE EXCEPTION 'quiz_sets: a set is approved only with its five questions' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- A question joins only a draft set (the set read FOR SHARE: a decision in flight is waited for and its outcome read),
-- and changes only by its pull or restore (status, pulled_at, pulled_reason: the definer functions). For every role.
-- SECURITY DEFINER: the job (no user bound) reads no set.
CREATE FUNCTION quiz_questions_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_status text;
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT s.status INTO v_status FROM public.quiz_sets s WHERE s.id = NEW.set_id FOR SHARE;
        IF v_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'quiz_questions: questions are added only to a draft set'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.id, NEW.set_id, NEW.position, NEW.prompt, NEW.options, NEW.answer, NEW.why, NEW.source_id,
        NEW.source_title, NEW.source_url, NEW.topic, NEW.prompt_hash, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.set_id, OLD.position, OLD.prompt, OLD.options, OLD.answer, OLD.why, OLD.source_id,
                         OLD.source_title, OLD.source_url, OLD.topic, OLD.prompt_hash, OLD.created_at) THEN
        RAISE EXCEPTION 'quiz_questions: a question changes only by its pull or restore'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- An attempt is made only on an approved set (one refusal for a draft, a rejected or an unknown set), and its score is
-- the database's: the live questions answered correctly, whatever was sent. Reads the set FOR KEY SHARE, so a rescore
-- in flight (FOR UPDATE) is waited for and the score reads the questions as it left them. For every role (bridge_app's
-- policy adds: the caller's own, on today's set). SECURITY DEFINER: reads the answers.
CREATE FUNCTION quiz_attempts_score() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_status text;
BEGIN
    SELECT s.status INTO v_status FROM public.quiz_sets s WHERE s.id = NEW.set_id FOR KEY SHARE;
    IF v_status IS DISTINCT FROM 'approved' THEN
        RAISE EXCEPTION 'quiz_attempts: an attempt is made only on an approved set'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    NEW.score := public.quiz_attempt_score(NEW.set_id, NEW.answers);
    RETURN NEW;
END;
$$;

-- An attempt changes only by its rescore: its score, and only to the computed one. For every role (bridge_app holds no
-- UPDATE). SECURITY INVOKER (the writer is the owner).
CREATE FUNCTION quiz_attempts_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.id, NEW.set_id, NEW.user_id, NEW.started_at, NEW.finished_at, NEW.answers, NEW.time_ms, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.set_id, OLD.user_id, OLD.started_at, OLD.finished_at, OLD.answers, OLD.time_ms,
                         OLD.created_at)
       OR NEW.score IS DISTINCT FROM public.quiz_attempt_score(NEW.set_id, NEW.answers) THEN
        RAISE EXCEPTION 'quiz_attempts: an attempt changes only by its rescore' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;
"""

# EXECUTE grants (EXECUTE revoked from PUBLIC first): a policy runs its functions with the caller's privileges.
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_nairobi_today()": ("bridge_app",),  # the policies, the API and the job
    "app_is_developer()": ("bridge_app",),  # the policies and the API's 404 for non-developers
    "app_rescore_quiz_set(uuid)": ("bridge_app",),  # staff admin or a job with no user bound
    "app_decide_quiz_set(uuid, text)": ("bridge_app",),  # staff admin
    "app_set_quiz_question_status(uuid, text, text)": ("bridge_app",),  # staff admin
    "app_flag_question(uuid, text, text)": ("bridge_app",),  # a developer
    "app_quiz_answers(uuid)": ("bridge_app",),  # after the caller's attempt, or staff admin
    "app_quiz_set_stats(uuid)": ("bridge_app",),  # staff admin: a set's attempts in aggregate
    "app_quiz_board()": ("bridge_app",),  # a developer
    "app_quiz_day_taken(date)": ("bridge_app",),  # the job, with no user bound
    "app_quiz_recent_prompt_hashes(date)": ("bridge_app",),  # the job, with no user bound
}
INTERNAL_FUNCTIONS = ("quiz_attempt_score(uuid, smallint[])", "quiz_rescore_set(uuid)")
TRIGGER_FUNCTIONS = (
    "quiz_sets_guard()",
    "quiz_questions_guard()",
    "quiz_attempts_score()",
    "quiz_attempts_guard()",
)

TRIGGERS_SQL = r"""
CREATE TRIGGER quiz_sets_guard
    BEFORE UPDATE ON quiz_sets
    FOR EACH ROW EXECUTE FUNCTION quiz_sets_guard();
CREATE TRIGGER quiz_questions_guard
    BEFORE INSERT OR UPDATE ON quiz_questions
    FOR EACH ROW EXECUTE FUNCTION quiz_questions_guard();
CREATE TRIGGER quiz_attempts_score
    BEFORE INSERT ON quiz_attempts
    FOR EACH ROW EXECUTE FUNCTION quiz_attempts_score();
CREATE TRIGGER quiz_attempts_guard
    BEFORE UPDATE ON quiz_attempts
    FOR EACH ROW EXECUTE FUNCTION quiz_attempts_guard();
CREATE TRIGGER quiz_flags_no_update
    BEFORE UPDATE ON quiz_flags
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
"""


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _grant_sql() -> str:
    grants = [f"GRANT {privileges} ON TABLE {table} TO bridge_app;" for table, privileges in APP_GRANTS.items()]
    grants += [
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in (*INTERNAL_FUNCTIONS, *TRIGGER_FUNCTIONS)
    ]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    _create_tables()
    _run_sql(FUNCTIONS_SQL)  # before the policies: they call app_is_developer() and app_nairobi_today()
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Destructive: drops the quiz (every set and question, the developers' attempts, flags, streaks and leaderboard
    opt-ins). Under the CLAUDE.md stop rule a downgrade of a database holding any of them is a destructive migration:
    back the database up and get the human's decision first. The downgrade refuses while any of the tables has rows
    unless it is run with ``-x allow_quiz_loss=true`` (``alembic -x allow_quiz_loss=true downgrade 0008``). The audit
    events of decisions and pulls stay in ``audit_events``."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_quiz_loss") == "true"
    holding = [
        table
        for table in NEW_TABLES
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
    ]
    if holding and not allowed:
        raise RuntimeError(
            f"revision 0009 downgrade: {', '.join(holding)} hold the quiz and the developers' attempts and streaks;"
            " back the database up, get the human's decision (CLAUDE.md: destructive migration), then run with"
            " -x allow_quiz_loss=true"
        )
    # Dropping a table drops its policies, triggers, indexes and grants (block_mutation() is revision 0002's and stays);
    # the policies go with their tables before the functions they call.
    for table in ("quiz_flags", "quiz_attempts", "quiz_profiles", "quiz_questions", "quiz_sets"):
        op.drop_table(table)
    _run_sql(
        "\n".join(
            f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS, *INTERNAL_FUNCTIONS)
        )
    )


def _create_tables() -> None:
    op.create_table(
        "quiz_sets",
        sa.Column("quiz_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("llm_trace_id", sa.String(length=64), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(_in("status", SET_STATUSES), name=op.f("ck_quiz_sets_status_known")),
        sa.CheckConstraint(_in("origin", SET_ORIGINS), name=op.f("ck_quiz_sets_origin_known")),
        sa.CheckConstraint(
            f"(llm_trace_id IS NULL OR llm_trace_id ~ '{TRACE_ID}')"
            " AND (origin = 'seeded' OR llm_trace_id IS NOT NULL)",
            name=op.f("ck_quiz_sets_trace_of_model"),
        ),
        sa.CheckConstraint(
            "CASE status WHEN 'draft' THEN decided_at IS NULL AND decided_by IS NULL"
            " ELSE decided_at IS NOT NULL AND (decided_by IS NOT NULL OR origin = 'seeded') END",
            name=op.f("ck_quiz_sets_decision_complete"),
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_quiz_sets_decided_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_sets")),
    )
    op.create_index(
        "uq_quiz_sets_quiz_date",
        "quiz_sets",
        ["quiz_date"],
        unique=True,
        postgresql_where=sa.text("status <> 'rejected'"),
    )
    op.create_table(
        "quiz_questions",
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("answer", sa.SmallInteger(), nullable=False),
        sa.Column("why", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("prompt_hash", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'live'"), nullable=False),
        sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pulled_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("position BETWEEN 1 AND 5", name=op.f("ck_quiz_questions_position_range")),
        sa.CheckConstraint(_text("prompt", 300), name=op.f("ck_quiz_questions_prompt_valid")),
        sa.CheckConstraint(OPTIONS_VALID, name=op.f("ck_quiz_questions_options_valid")),
        sa.CheckConstraint("answer BETWEEN 0 AND 3", name=op.f("ck_quiz_questions_answer_range")),
        sa.CheckConstraint(_text("why", 600), name=op.f("ck_quiz_questions_why_valid")),
        sa.CheckConstraint(
            "source_id ~ '^[[:graph:]]+$' AND char_length(source_id) <= 80",
            name=op.f("ck_quiz_questions_source_id_valid"),
        ),
        sa.CheckConstraint(_text("source_title", 160), name=op.f("ck_quiz_questions_source_title_valid")),
        sa.CheckConstraint(
            "char_length(source_url) <= 400 AND source_url ~ '^https://[^[:space:][:cntrl:]]+$'",
            name=op.f("ck_quiz_questions_source_url_valid"),
        ),
        sa.CheckConstraint(_text("topic", 60), name=op.f("ck_quiz_questions_topic_valid")),
        sa.CheckConstraint("octet_length(prompt_hash) = 32", name=op.f("ck_quiz_questions_prompt_hash_length")),
        sa.CheckConstraint(_in("status", QUESTION_STATUSES), name=op.f("ck_quiz_questions_status_known")),
        sa.CheckConstraint(
            "(status = 'pulled') = (pulled_at IS NOT NULL) AND (status = 'pulled') = (pulled_reason IS NOT NULL)"
            " AND (pulled_reason IS NULL OR (pulled_reason ~ '[^[:space:]]' AND char_length(pulled_reason) <= 300))",
            name=op.f("ck_quiz_questions_pull_complete"),
        ),
        sa.ForeignKeyConstraint(["set_id"], ["quiz_sets.id"], name=op.f("fk_quiz_questions_set_id_quiz_sets")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_questions")),
        sa.UniqueConstraint("set_id", "position", name=op.f("uq_quiz_questions_set_id_position")),
    )
    op.create_index(op.f("ix_quiz_questions_prompt_hash"), "quiz_questions", ["prompt_hash"], unique=False)
    op.create_table(
        "quiz_attempts",
        sa.Column("set_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("answers", postgresql.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column("score", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(ANSWERS_VALID, name=op.f("ck_quiz_attempts_answers_valid")),
        sa.CheckConstraint("score BETWEEN 0 AND 5", name=op.f("ck_quiz_attempts_score_range")),
        sa.CheckConstraint("time_ms BETWEEN 0 AND 86400000", name=op.f("ck_quiz_attempts_time_ms_range")),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at <= finished_at", name=op.f("ck_quiz_attempts_started_before_finished")
        ),
        sa.ForeignKeyConstraint(["set_id"], ["quiz_sets.id"], name=op.f("fk_quiz_attempts_set_id_quiz_sets")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_quiz_attempts_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_attempts")),
        sa.UniqueConstraint("set_id", "user_id", name=op.f("uq_quiz_attempts_set_id_user_id")),
    )
    op.create_index("ix_quiz_attempts_user_id_finished_at", "quiz_attempts", ["user_id", "finished_at"], unique=False)
    op.create_table(
        "quiz_flags",
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(_in("reason", FLAG_REASONS), name=op.f("ck_quiz_flags_reason_known")),
        sa.CheckConstraint(
            "note IS NULL OR (note ~ '[^[:space:]]' AND char_length(note) <= 300)",
            name=op.f("ck_quiz_flags_note_length"),
        ),
        sa.ForeignKeyConstraint(
            ["question_id"], ["quiz_questions.id"], name=op.f("fk_quiz_flags_question_id_quiz_questions")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_quiz_flags_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quiz_flags")),
        sa.UniqueConstraint("question_id", "user_id", name=op.f("uq_quiz_flags_question_id_user_id")),
    )
    op.create_index("ix_quiz_flags_user_id_created_at", "quiz_flags", ["user_id", "created_at"], unique=False)
    op.create_table(
        "quiz_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("leaderboard_opt_in", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("current_streak", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("best_streak", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_played_on", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.CheckConstraint(
            "current_streak >= 0 AND best_streak >= current_streak", name=op.f("ck_quiz_profiles_streaks_valid")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_quiz_profiles_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_quiz_profiles")),
    )
