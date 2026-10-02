"""Schema v5 (P19): engagement notes, marking in-app notifications read, and Briefs published by moderation.

REQ-ENG-10 (part: ``INFO_REQUESTED`` and ``ON_HOLD`` before the agreement, task P19-A: ``engagement_notes``),
REQ-NOT-03 (the in-app channel, task P19-C: a user marks their own notifications read) and REQ-DIR-05 (Problem
Briefs, task P19-B: a Brief is published with its problem by moderation, stays readable once closed, and keeps its
moderated text). Design: ``docs/platform/tasks/P19-M.md`` and the coordinator's P19-B additions. Additive but for
three narrowings or replacements of earlier objects, each restored on downgrade: one new table with its policies,
triggers and grants; bridge_app's table-wide UPDATE on ``in_app_notifications`` (revision 0001) narrowed to
``UPDATE (read_at)``; the SELECT policy of ``problem_briefs`` (revision 0002) widened to closed public Briefs;
``app_moderate_problem`` (revision 0002) replaced to publish a Brief with its problem; two new triggers,
``problem_briefs_status_guard`` on ``problem_briefs`` and ``problems_brief_text_guard`` on ``problems``; and one new
definer helper, ``app_brief_problem_is_public``, for that policy. No enum type; the notes' triggers also reuse
``tracker_engagement_visible()`` (revision 0003) and ``block_mutation()`` (revision 0002). Nothing else of revisions
0001 to 0005 is changed or dropped. The upgrade is additive; the downgrade is destructive (it drops the notes: see
``downgrade()``).

``engagement_notes`` (ORG_OR_USER through the engagement, like every tracker table): the text a side-state command
carries, a sibling row of the event it explains (``event_seq``), never part of the hash chain (the chain and its
canonical form are unchanged): ``info_request`` (the organisation's question), ``info_answer`` (the developer's
answer), ``hold`` (the reason of a pause, with ``resume_at``, the Africa/Nairobi date it resumes) and ``resume`` (the
reason of an early resume). The body is 1 to 2000 characters and not blank; ``resume_at`` is set for a hold and only
for a hold.

- Read: exactly who reads the engagement's events (its developer, the members of its organisation narrowed by
  ``app.org_id``, staff admin); nobody else sees a row.
- Written (bridge_app: SELECT and INSERT only) by the party who wrote the event, as themselves
  (``created_by = app_user_id()``), in the event's transaction: the event exists (composite foreign key to
  ``engagement_events (engagement_id, seq)``), names the caller as its actor (a system event, written by a job, takes
  no note), was appended in the note's transaction (its time is at or after the transaction's start on the shared
  clock: ``now()`` plus the test clock's offset), is still the engagement's latest event, and its transition is the
  kind's: ``info_request`` enters ``INFO_REQUESTED`` and ``hold`` enters ``ON_HOLD``, each from a state that
  is neither a side state nor terminal; ``info_answer`` leaves ``INFO_REQUESTED`` and ``resume`` leaves ``ON_HOLD``,
  each for such a state (the state it was entered from: the chain enforces that). One note per event (UNIQUE
  (engagement_id, event_seq)). Who may enter or leave a side state is the event's policy and the state machine's.
  "Still the latest" is checked twice: by the policy, and by ``engagement_notes_1_latest_event`` (SECURITY DEFINER,
  BEFORE INSERT, every role, right after the visibility check), which locks the engagement's row FOR NO KEY UPDATE
  (it waits for any append in flight: the chain holds FOR UPDATE until commit) and then compares ``event_seq`` with
  the chain's current ``max(seq)``, so a note can never be written once a later event has committed, whatever the
  policy's snapshot saw.
- Append-only, but for its redaction (D-54, default (a)): no UPDATE or DELETE grant; ``engagement_notes_no_delete``
  and ``_no_truncate`` (``block_mutation()``) refuse DELETE and TRUNCATE for every role, the owner included; and
  ``engagement_notes_redaction_guard`` admits an UPDATE only from the table's owner or a SECURITY DEFINER function it
  owns (``current_user``), only once, and only when it sets ``body`` to the fixed marker ``'[redacted]'`` with
  ``redacted_at`` and ``redacted_by`` in the same statement and changes nothing else. bridge_app holds no privilege on
  ``redacted_at`` or ``redacted_by``. The staff-only redaction function D-54 foresees does not exist yet.
  ``engagement_notes_0_visible``
  (``tracker_engagement_visible()``) fires first on INSERT, so a note naming an engagement the caller cannot see gets
  the tracker's one refusal before any unique or foreign key check could tell anything about it.
- ``created_at`` is the database's clock (default ``app_clock_now()``, the shared clock): bridge_app's INSERT is
  column-scoped without it, so a note is never forward- or back-dated.

``in_app_notifications``: bridge_app held a table-wide UPDATE since revision 0001; it now updates ``read_at`` only, so
the title, body, link, kind, recipient and organisation of a notification never change after it is written. The
UPDATE policy of revision 0001 (``bridge_app_update``: USING and WITH CHECK ``user_id = app_user_id()``) is already
the one marking read needs (a user changes only their own rows, and a row cannot be handed to another user) and stays
as it is: a second permissive policy would only be OR-ed with it, and the column grant, not a policy, keeps every
other column unchanged (a policy cannot compare a row with its old version).

``problem_briefs`` (REQ-DIR-05): a Brief is written as a draft with its problem (``pending_review``) and published by
moderation, never by its organisation ahead of it, so nothing of a Brief awaiting review (its budget band, deadline,
visibility) is readable beyond its organisation and staff:

- ``app_moderate_problem`` (replaced; same signature, grants and refusals): approving a Brief's problem (``clear``,
  ``published``) also publishes the Brief when it is a draft of an E2 organisation that is not delisted (the E2
  guard on ``published``); any other decision returns a published Brief to ``draft``. A closed Brief, and on approval
  a Brief of an organisation that is not a listed E2 one, are left as they are (the problem is still decided; such a
  Brief's problem stays unreadable to other users, as the problems policy reads it through its Brief).
- ``problem_briefs_status_guard`` (AFTER INSERT OR UPDATE, after RLS, SECURITY INVOKER, every role): a Brief enters
  ``published`` only from the owner, that is from ``app_moderate_problem`` (``current_user``: no organisation
  republishes a Brief it returned to draft), and only while its problem is published and clear and its organisation
  is E2 and not delisted; it enters ``closed`` only from ``published``, so closing never makes a Brief that was never
  approved readable; and ``closed`` is terminal (no change away from it, for any role). The policy's E2 guard on
  ``published`` (bridge_app) stays.
- The SELECT policy reads a public Brief while ``published`` or ``closed`` and while its problem is published and
  clear (``app_brief_problem_is_public``: SECURITY DEFINER, because a policy of ``problem_briefs`` reading
  ``problems``, whose own policy reads ``problem_briefs``, is an infinite recursion): a closed Brief leaves the feed
  (which reads ``published`` only) but its problem page and the proposals' links to it stay; a Brief whose problem
  is rejected, held or back in review is not read beyond its organisation and staff. An invited Brief is read by its
  invited users while ``published`` only, as before (invited Briefs are not offered yet).
- ``problems_brief_text_guard`` (BEFORE UPDATE OF title, statement, affected_group on ``problems``, SECURITY INVOKER,
  every role; the P19-B security review): a published ``org_brief`` problem keeps the text staff approved unless the
  same statement returns it to review (``status = 'pending_review'``); refused with SQLSTATE 55000
  (object_not_in_prerequisite_state). bridge_app holds no UPDATE on ``status`` or ``moderation_state`` (moderation
  decisions are staff's, revision 0002), so for the app the text of a published Brief is frozen; returning one to
  review is the owner's or a definer function's (none exists yet: see the P19-M report).

``originality_checks`` needs nothing: bridge_app holds SELECT and INSERT on it (revision 0002) under Tenancy.USER
(``user_id = app_user_id()``), so the owner counts their own checks of the day directly (P19-D; no function, no
grant).

Operating rules for the code that uses this schema:

- Append the event first, read its ``seq`` back (the database's), then insert the note with that ``seq`` in the same
  transaction, as the event's actor; leave ``created_at`` out. A refused note rolls the event back with it.
- Map the tracker's refusal for an engagement the caller cannot see ("no engagement of the caller's with that id",
  insufficient_privilege) to 404, as for the other tracker tables.
- Mark read with ``UPDATE in_app_notifications SET read_at = ... WHERE read_at IS NULL`` (RLS scopes it to the user);
  never write another column.
- Insert a Brief as a draft; never set ``published`` yourself (``app_moderate_problem`` does it on approval: the
  database refuses it to the app); close only a published Brief, for good; never edit a published Brief's title,
  statement or affected group (SQLSTATE 55000: map it to 409).
- A note is free text a party typed and is never deleted: keep it out of event payloads, logs and audit details. Its
  erasure under a data-subject request (REQ-SEC-02, AC-SEC-3) is D-54: by default (a) its body may later be redacted
  by a staff-only SECURITY DEFINER function (not written yet), which the redaction guard already admits.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-02
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import context, op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RLS_TABLES = ("engagement_notes",)

# Table privileges of bridge_app on this revision's table; anything not listed is not granted. Append-only: SELECT and
# INSERT only, the INSERT without created_at (the database's clock) and the redaction columns (D-54: the owner's).
APP_GRANTS: dict[str, str] = {
    "engagement_notes": "SELECT, INSERT (id, engagement_id, event_seq, kind, body, resume_at, created_by)",
}
# bridge_app's table-wide UPDATE on in_app_notifications (revision 0001) becomes an UPDATE of read_at only (restored to
# the table-wide grant on downgrade).
IN_APP_UPDATABLE_COLUMNS = "read_at"

# CHECK expressions, verbatim from the ORM model (bridge.engagements.models.EngagementNote).
NOTE_KINDS = ("info_request", "info_answer", "hold", "resume")
REDACTED = "'[redacted]'"  # D-54: the one body a note may be changed to


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


# Predicates. A note is visible exactly when its engagement is (the engagements SELECT policies of revisions 0002 and
# 0003: the developer, members of the organisation narrowed by app.org_id, and staff admin), as for every tracker row.
NOTE_VISIBLE = "EXISTS (SELECT 1 FROM engagements e WHERE e.id = engagement_notes.engagement_id)"
# Side and terminal states: a note explains entering a side state from the main path, or leaving it back to it.
_OFF_MAIN_PATH = "('INFO_REQUESTED', 'ON_HOLD', 'DISPUTED', 'DECLINED', 'WITHDRAWN', 'EXPIRED', 'TERMINATED', 'CLOSED')"
# The note's event (read under the caller's RLS, so its engagement is visible): appended by the caller as themselves in
# this transaction, still the engagement's latest event, and of the kind's transition. A NULL from_state (the genesis)
# matches no kind. "In this transaction": the chain stamps an event with app_clock_now() (clock_timestamp() plus the
# test clock's offset), which is never before now() (the transaction's start) plus that offset; an equality with
# app_clock_now() would never hold, as the clock moves on between the event and its note.
NOTE_INSERT = (
    "created_by = app_user_id()"
    " AND EXISTS (SELECT 1 FROM engagement_events ev"
    " WHERE ev.engagement_id = engagement_notes.engagement_id AND ev.seq = engagement_notes.event_seq"
    " AND ev.actor_user_id = app_user_id()"
    " AND ev.created_at >= now() + coalesce((SELECT c.clock_offset FROM test_clock c WHERE c.enabled), interval '0')"
    " AND CASE engagement_notes.kind"
    f" WHEN 'info_request' THEN ev.to_state = 'INFO_REQUESTED' AND ev.from_state NOT IN {_OFF_MAIN_PATH}"
    f" WHEN 'info_answer' THEN ev.from_state = 'INFO_REQUESTED' AND ev.to_state NOT IN {_OFF_MAIN_PATH}"
    f" WHEN 'hold' THEN ev.to_state = 'ON_HOLD' AND ev.from_state NOT IN {_OFF_MAIN_PATH}"
    f" WHEN 'resume' THEN ev.from_state = 'ON_HOLD' AND ev.to_state NOT IN {_OFF_MAIN_PATH}"
    " ELSE false END"
    " AND NOT EXISTS (SELECT 1 FROM engagement_events later"
    " WHERE later.engagement_id = ev.engagement_id AND later.seq > ev.seq))"
)

POLICIES: tuple[Policy, ...] = (
    # --- engagement_notes: both parties (and staff admin) read; the event's actor writes its one note ---
    Policy("engagement_notes", "SELECT", NOTE_VISIBLE),
    Policy("engagement_notes", "INSERT", check=NOTE_INSERT),
)

# problem_briefs' SELECT policy (revision 0002's bridge_app_select): the public branch also reads closed Briefs, and
# only while the Brief's problem is published and clear. The revision 0002 text is restored on downgrade.
_SIGNED_IN = "app_user_id() IS NOT NULL"
_ORG_MEMBER = "app_is_member(org_id) AND (app_org_id() IS NULL OR org_id = app_org_id())"
_STAFF = "app_is_staff('{admin,moderator}')"
_BRIEF_INVITED = (
    " OR (status = 'published' AND EXISTS (SELECT 1 FROM brief_invitations i"
    " WHERE i.brief_id = problem_briefs.problem_id AND i.user_id = app_user_id()))"
)
BRIEFS_SELECT_0002 = (
    f"({_SIGNED_IN} AND visibility = 'public' AND status = 'published') OR ({_ORG_MEMBER}){_BRIEF_INVITED} OR {_STAFF}"
)
BRIEFS_SELECT = (
    f"({_SIGNED_IN} AND visibility = 'public' AND status IN ('published', 'closed')"
    " AND app_brief_problem_is_public(problem_id))"
    f" OR ({_ORG_MEMBER}){_BRIEF_INVITED} OR {_STAFF}"
)

FUNCTIONS_SQL = r"""
-- A note is written only while its event is the engagement's latest (the policy says so too, under its snapshot).
-- Locks the engagement's row FOR NO KEY UPDATE, so an append in flight (the chain holds FOR UPDATE until commit) is
-- waited for, then reads the chain's head anew: a note is never written once a later event has committed. Fires
-- right after tracker_engagement_visible() (<table>_1_latest_event sorts second), so it locks and reports only an
-- engagement the caller can see. SECURITY DEFINER: locks and reads the chain whatever the caller's grants.
CREATE FUNCTION engagement_notes_latest_event() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_latest bigint;
BEGIN
    PERFORM 1 FROM public.engagements e WHERE e.id = NEW.engagement_id FOR NO KEY UPDATE;
    SELECT max(ev.seq) INTO v_latest FROM public.engagement_events ev WHERE ev.engagement_id = NEW.engagement_id;
    IF NEW.event_seq IS DISTINCT FROM v_latest THEN
        RAISE EXCEPTION 'engagement_notes: a note is written only while its event is the engagement''s latest'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- D-54 (default (a)): a note changes only by its redaction, once: its body becomes the fixed marker '[redacted]' with
-- redacted_at and redacted_by set in the same statement, and nothing else changes. Only the table's owner, or a
-- SECURITY DEFINER function it owns (a staff-only redaction function: none exists yet), may do it; bridge_app holds no
-- UPDATE on the table at all. DELETE and TRUNCATE stay refused for every role (block_mutation()). SECURITY INVOKER, so
-- current_user is the writer (as org_claims_status_guard() of revision 0002).
CREATE FUNCTION engagement_notes_redaction_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF current_user <> (SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID)
       OR OLD.redacted_at IS NOT NULL OR NEW.body IS DISTINCT FROM '[redacted]'
       OR NEW.redacted_at IS NULL OR NEW.redacted_by IS NULL
       OR (NEW.id, NEW.engagement_id, NEW.event_seq, NEW.kind, NEW.resume_at, NEW.created_by, NEW.created_at)
          IS DISTINCT FROM (OLD.id, OLD.engagement_id, OLD.event_seq, OLD.kind, OLD.resume_at, OLD.created_by,
                            OLD.created_at) THEN
        RAISE EXCEPTION 'engagement_notes: a note changes only by its redaction, once, by the owner (D-54)'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

-- Whether a Brief's problem is published and clear: the public read of problem_briefs needs it, and a policy of
-- problem_briefs cannot read problems (whose own policy reads problem_briefs: infinite recursion). Briefs' problems
-- only (source org_brief). SECURITY DEFINER: reads the problem whatever the caller sees; returns the boolean only.
CREATE FUNCTION app_brief_problem_is_public(p_problem uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (SELECT 1 FROM public.problems p
                    WHERE p.id = p_problem AND p.source = 'org_brief' AND p.status = 'published'
                      AND p.moderation_state = 'clear')
$$;

-- A Brief enters 'published' only by moderation: from the table's owner, that is app_moderate_problem() (current_user;
-- an organisation never publishes, nor republishes a Brief it returned to draft), and only while its problem is
-- published and clear and its organisation is E2 and not delisted, so nothing of a Brief awaiting review is readable
-- beyond its organisation and staff. It enters 'closed' only from 'published', so closing never makes a Brief that was
-- never approved readable (a closed public Brief stays readable while its problem is public), and 'closed' is
-- terminal. Checked for every role (the owner and the definer functions too); the INSERT and UPDATE policies' E2 guard
-- on 'published' stays. AFTER: runs after RLS, so a caller the policies refuse learns nothing here. SECURITY INVOKER:
-- current_user is the writer, and the owner reads the problem and organisation unhindered.
CREATE FUNCTION problem_briefs_status_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND OLD.status = 'closed' AND NEW.status <> 'closed' THEN
        RAISE EXCEPTION 'problem_briefs: a closed Brief stays closed' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'published' AND (TG_OP = 'INSERT' OR OLD.status <> 'published')
       AND current_user <> (SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c
                             WHERE c.oid = TG_RELID) THEN
        RAISE EXCEPTION 'problem_briefs: only moderation publishes a Brief (app_moderate_problem)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'published' AND (TG_OP = 'INSERT' OR OLD.status <> 'published') AND NOT (
        EXISTS (SELECT 1 FROM public.problems p
                 WHERE p.id = NEW.problem_id AND p.status = 'published' AND p.moderation_state = 'clear')
        AND EXISTS (SELECT 1 FROM public.organizations o
                     WHERE o.id = NEW.org_id AND o.verification = 'e2' AND o.delisted_at IS NULL)
    ) THEN
        RAISE EXCEPTION 'problem_briefs: a Brief is published only once its problem is published and clear, for a'
            ' listed E2 organisation' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'closed' AND (TG_OP = 'INSERT' OR OLD.status NOT IN ('published', 'closed')) THEN
        RAISE EXCEPTION 'problem_briefs: only a published Brief is closed' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

-- The moderated text of a published Brief (REQ-DIR-05; the P19-B security review): a problem of source org_brief that
-- is published keeps the title, statement and affected group staff approved unless the same statement returns it to
-- review (status pending_review), so developers read what was moderated. For every role; bridge_app holds no UPDATE on
-- status, so for the app that text is frozen. Fires only on an UPDATE naming one of the three columns; RLS has already
-- narrowed the rows to the caller's own. SECURITY INVOKER: reads nothing.
CREATE FUNCTION problems_brief_text_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF OLD.source = 'org_brief' AND OLD.status = 'published' AND NEW.status IS DISTINCT FROM 'pending_review'
       AND (NEW.title IS DISTINCT FROM OLD.title OR NEW.statement IS DISTINCT FROM OLD.statement
            OR NEW.affected_group IS DISTINCT FROM OLD.affected_group) THEN
        RAISE EXCEPTION 'problems: the moderated text of a published Brief changes only with a return to review'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    RETURN NEW;
END;
$$;

-- Revision 0002's moderation decision on a problem, plus (REQ-DIR-05): approving a Brief's problem (clear, published)
-- publishes the Brief with it when the Brief is a draft of an E2 organisation that is not delisted (the E2 guard on
-- 'published'); any other decision (a rejection, a hold) returns a published Brief to draft. A closed Brief stays
-- closed. Same signature, grants and refusals (CREATE OR REPLACE keeps the grants).
CREATE OR REPLACE FUNCTION app_moderate_problem(p_problem uuid, p_state moderation_state, p_status problem_status)
    RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_source public.problem_source;
BEGIN
    IF NOT public.app_is_staff('{admin,moderator}') THEN
        RAISE EXCEPTION 'app_moderate_problem: staff admin or moderator only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE public.problems
       SET moderation_state = p_state,
           status = p_status,
           moderator_id = public.app_user_id(),
           published_at = CASE WHEN p_status = 'published' THEN coalesce(published_at, now()) ELSE published_at END,
           updated_at = now()
     WHERE id = p_problem AND created_by IS DISTINCT FROM public.app_user_id()
    RETURNING source INTO v_source;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_moderate_problem: no such problem, or it is the moderator''s own'
            USING ERRCODE = 'no_data_found';
    END IF;
    IF v_source = 'org_brief' AND p_status = 'published' AND p_state = 'clear' THEN
        UPDATE public.problem_briefs b
           SET status = 'published', updated_at = now()
         WHERE b.problem_id = p_problem AND b.status = 'draft'
           AND EXISTS (SELECT 1 FROM public.organizations o
                        WHERE o.id = b.org_id AND o.verification = 'e2' AND o.delisted_at IS NULL);
    ELSIF v_source = 'org_brief' THEN
        UPDATE public.problem_briefs b
           SET status = 'draft', updated_at = now()
         WHERE b.problem_id = p_problem AND b.status = 'published';
    END IF;
END;
$$;
"""

# Revision 0002's app_moderate_problem, verbatim (its body must match byte for byte), restored on downgrade.
APP_MODERATE_PROBLEM_0002 = r"""
CREATE OR REPLACE FUNCTION app_moderate_problem(p_problem uuid, p_state moderation_state, p_status problem_status)
    RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_staff('{admin,moderator}') THEN
        RAISE EXCEPTION 'app_moderate_problem: staff admin or moderator only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE public.problems
       SET moderation_state = p_state,
           status = p_status,
           moderator_id = public.app_user_id(),
           published_at = CASE WHEN p_status = 'published' THEN coalesce(published_at, now()) ELSE published_at END,
           updated_at = now()
     WHERE id = p_problem AND created_by IS DISTINCT FROM public.app_user_id();
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_moderate_problem: no such problem, or it is the moderator''s own'
            USING ERRCODE = 'no_data_found';
    END IF;
END;
$$;
"""

# EXECUTE grants (EXECUTE revoked from PUBLIC first): a policy runs its functions with the caller's privileges.
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_brief_problem_is_public(uuid)": ("bridge_app",),  # the public read of problem_briefs
}
TRIGGER_FUNCTIONS = (
    "engagement_notes_latest_event()",
    "engagement_notes_redaction_guard()",
    "problem_briefs_status_guard()",
    "problems_brief_text_guard()",
)

# Every tracker table's triggers (revision 0003): the visibility check fires first on INSERT (<table>_0_visible sorts
# first by name), and the append-only refusals hold for every role (an UPDATE only as the owner's redaction, D-54).
TRIGGERS_SQL = r"""
CREATE TRIGGER engagement_notes_0_visible
    BEFORE INSERT ON engagement_notes
    FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();
CREATE TRIGGER engagement_notes_1_latest_event
    BEFORE INSERT ON engagement_notes
    FOR EACH ROW EXECUTE FUNCTION engagement_notes_latest_event();
CREATE TRIGGER engagement_notes_no_delete
    BEFORE DELETE ON engagement_notes
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
CREATE TRIGGER engagement_notes_redaction_guard
    BEFORE UPDATE ON engagement_notes
    FOR EACH ROW EXECUTE FUNCTION engagement_notes_redaction_guard();
CREATE TRIGGER engagement_notes_no_truncate
    BEFORE TRUNCATE ON engagement_notes
    FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();
CREATE TRIGGER problem_briefs_status_guard
    AFTER INSERT OR UPDATE ON problem_briefs
    FOR EACH ROW EXECUTE FUNCTION problem_briefs_status_guard();
CREATE TRIGGER problems_brief_text_guard
    BEFORE UPDATE OF title, statement, affected_group ON problems
    FOR EACH ROW EXECUTE FUNCTION problems_brief_text_guard();
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
    # REVOKE of a table privilege also revokes it on every column; the column grant follows.
    grants += [
        "REVOKE UPDATE ON TABLE in_app_notifications FROM bridge_app;",
        f"GRANT UPDATE ({IN_APP_UPDATABLE_COLUMNS}) ON TABLE in_app_notifications TO bridge_app;",
    ]
    grants += [f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in TRIGGER_FUNCTIONS]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    _create_tables()
    _run_sql(FUNCTIONS_SQL)
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(f"ALTER POLICY bridge_app_select ON problem_briefs USING ({BRIEFS_SELECT});")
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Destructive: drops ``engagement_notes``, the parties' questions, answers and reasons, which are part of the
    engagements' record. Under the CLAUDE.md stop rule a downgrade of a database holding any note is a destructive
    migration: back the database up and get the human's decision first. The downgrade refuses while the table has rows
    unless it is run with ``-x allow_note_loss=true`` (``alembic -x allow_note_loss=true downgrade 0005``)."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_note_loss") == "true"
    if not allowed and op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM engagement_notes)")).scalar():
        raise RuntimeError(
            "revision 0006 downgrade: engagement_notes holds the parties' questions, answers and reasons; back the"
            " database up, get the human's decision (CLAUDE.md: destructive migration), then run with"
            " -x allow_note_loss=true"
        )
    # Dropping the table drops its policies, triggers, indexes and grants (block_mutation() and
    # tracker_engagement_visible() are revision 0002's and 0003's and stay; this revision's functions go below).
    op.drop_table("engagement_notes")
    _run_sql(
        "REVOKE UPDATE ON TABLE in_app_notifications FROM bridge_app;"
        " GRANT UPDATE ON TABLE in_app_notifications TO bridge_app;"
    )
    # Revision 0002's Brief rules as they were: the policy (first: it uses the helper), the moderation function (its
    # grants stay), no guards, no helper.
    _run_sql(f"ALTER POLICY bridge_app_select ON problem_briefs USING ({BRIEFS_SELECT_0002});")
    _run_sql(APP_MODERATE_PROBLEM_0002)
    _run_sql(
        "DROP TRIGGER problem_briefs_status_guard ON problem_briefs;"
        " DROP TRIGGER problems_brief_text_guard ON problems;"
    )
    _run_sql("\n".join(f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS)))


def _create_tables() -> None:
    op.create_table(
        "engagement_notes",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("event_seq", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("resume_at", sa.Date(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redacted_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"kind IN ({', '.join(repr(kind) for kind in NOTE_KINDS)})", name=op.f("ck_engagement_notes_kind_known")
        ),
        sa.CheckConstraint(
            "btrim(body) <> '' AND char_length(body) <= 2000", name=op.f("ck_engagement_notes_body_length")
        ),
        sa.CheckConstraint(
            "(kind = 'hold') = (resume_at IS NOT NULL)", name=op.f("ck_engagement_notes_resume_at_only_for_hold")
        ),
        sa.CheckConstraint(
            f"(redacted_at IS NULL) = (redacted_by IS NULL) AND (redacted_at IS NULL OR body = {REDACTED})",
            name=op.f("ck_engagement_notes_redaction_complete"),
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_engagement_notes_created_by_users")),
        sa.ForeignKeyConstraint(["redacted_by"], ["users.id"], name=op.f("fk_engagement_notes_redacted_by_users")),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_engagement_notes_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id", "event_seq"],
            ["engagement_events.engagement_id", "engagement_events.seq"],
            name="fk_engagement_notes_event",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_notes")),
        sa.UniqueConstraint("engagement_id", "event_seq", name=op.f("uq_engagement_notes_engagement_id_event_seq")),
    )
