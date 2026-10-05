"""Schema v6 (P21): the engagement thread, the organisation shortlist and saved searches.

REQ-ENG-11 (R37, AC-TRACK-9, N18; track A: ``engagement_messages``, ``engagement_message_attachments``,
``engagement_message_reads`` and the message report), REQ-REPO-02 (R10; track B: ``org_shortlist``) and REQ-PERS-03
(R27, with REQ-TREND-02; track C: ``saved_searches``). Design: ``docs/platform/tasks/P21.md`` and D-57's defaults.
Additive but for one narrowing of an earlier object, restored on downgrade: five new tables with their policies,
triggers and grants; nine new functions; one new partial unique index on ``moderation_cases``; and bridge_app's INSERT
policy on ``moderation_cases`` (revision 0002) narrowed so that the app files a message report only through
``app_report_message``. No enum type: the tables reuse ``engagement_party`` (revision 0003) and ``av_status`` (revision
0002), and the triggers reuse ``tracker_engagement_visible()`` (revision 0003), ``block_mutation()`` (revision 0002) and
``app_xid_is_current()`` (revision 0006). Nothing else of revisions 0001 to 0007 is changed or dropped. The upgrade is
additive; the downgrade is destructive (it drops the new tables: see ``downgrade()``). Moderation case subjects
(``subject_type``, ``String(40)``) and notification kinds (``in_app_notifications``, ``notification_preferences`` and
``notification_deliveries``, ``String(40)``) are free strings: ``'message'`` and the new N18 and saved-search kinds need
no schema change.

The thread (track A; tenancy ORG_OR_USER through the engagement, like every tracker table, but parties only):

- Read: the engagement's developer and the members of its organisation (narrowed by ``app.org_id``), viewers included;
  never staff, who read every other tracker row (D-57 (4): staff read one message through a report, never the
  thread). Read stays open after the engagement ends.
- ``engagement_messages`` (bridge_app: SELECT and INSERT only, the INSERT without ``created_at`` and the redaction
  columns): written by a party as themselves (``sender_user_id = app_user_id()``) on their own side
  (``sender_party``): ``developer`` for the engagement's developer, ``org`` for a member who may act on the tracker
  (owner, admin, reviewer, signatory, finance: viewers read, never post, as they never act) and is not the
  engagement's developer (a developer who is also a member of the counterpart organisation posts as ``developer``
  only: one person never speaks for both sides). The body is 1 to 4,000
  characters and not blank (plain text; the database never interprets it).
- The stage gate (``engagement_thread_open()``, BEFORE INSERT, SECURITY DEFINER, every role, right after the
  visibility check): the thread opens once an event of the engagement's chain has entered stage 3
  (``INTEREST_CONFIRMED``) or a later main-path stage (``CONTACT_MADE`` to ``PAYMENT_FINAL``), whatever state it is in
  now, and closes for good at ``DECLINED``, ``WITHDRAWN``, ``EXPIRED``, ``TERMINATED`` and ``CLOSED`` (read-only from
  then on). 3b ``PROCUREMENT_ROUTE`` does not count: revision 0003 lets a public entity enter it from
  ``UNDER_REVIEW``, before any approval, and leave it for ``INTEREST_CONFIRMED`` or straight for ``CONTACT_MADE``, so
  on that path the thread opens at ``CONTACT_MADE``. Every main-path state after ``CONTACT_MADE`` has it among its
  chain's predecessors, and a chain that begins later (the owner's insert, as revision 0003's backfill) begins at a
  counted state, so the rule covers every path 0003 allows to stage 3 and beyond. "Has entered", not "is at or after":
  the state order is not linear (``PROCUREMENT_ROUTE`` comes before or after stage 3; a disputed first contact returns
  from ``CONTACT_MADE`` to stage 3; the side states ``ON_HOLD``, ``INFO_REQUESTED`` and ``DISPUTED`` can be entered
  from any stage and resume only where they were entered), so an engagement on hold at ``UNDER_REVIEW`` or at a
  ``PROCUREMENT_ROUTE`` entered from it stays closed, and one on hold after stage 3 stays open. Both sides are refused
  before (D-57 (1); the organisation's 403 of AC-TRACK-9 is the API's), so no message can exist before the thread
  opens and the read policy needs no stage. The trigger locks the engagement's row FOR KEY SHARE first: an
  append in flight (the chain holds FOR UPDATE until commit) is waited for and its outcome read, so no message is
  written once the engagement's end has committed; concurrent messages do not wait for each other. SQLSTATE 55000
  (object_not_in_prerequisite_state) with "the thread opens at INTEREST_CONFIRMED" or "its thread is read-only".
- Append-only, but for its redaction (D-54's default (a), D-57 (3)): no UPDATE or DELETE grant;
  ``engagement_messages_no_delete`` and ``_no_truncate`` (``block_mutation()``) refuse DELETE and TRUNCATE for every
  role; ``engagement_messages_redaction_guard`` admits an UPDATE only from the table's owner or a SECURITY DEFINER
  function it owns, once, setting ``body`` to ``'[redacted]'`` with ``redacted_at`` and ``redacted_by`` and nothing
  else (as ``engagement_notes``, revision 0006). The CHECK ``redaction_complete`` keeps a party from writing a body
  that looks redacted. The staff-only redaction function does not exist yet; when written it sets
  ``redacted_at = app_clock_now()`` and ``redacted_by = app_user_id()``.
- ``created_at`` is the database's clock (default ``app_clock_now()``; bridge_app's INSERT is column-scoped without
  it). The thread reads by ``ix_engagement_messages_thread (engagement_id, created_at, id)``.
- ``engagement_message_attachments`` (bridge_app: SELECT, INSERT without ``message_id``, ``av_status`` and
  ``created_at``, UPDATE of ``message_id`` and ``av_status``, DELETE): an upload is staged first, then joins its
  message. A party who may post inserts it as themselves (``uploader_user_id = app_user_id()``) with ``message_id``
  NULL while the thread is open (the same gate), always pending (``av_status`` takes its default, ``pending_scan``);
  only a later UPDATE gives it a scan verdict (``clean``, ``infected`` or ``failed``), which is final. A staged
  upload is read, scanned and deleted by its uploader only (the scan, too, runs bound to the uploader). The verdict
  itself is the API's responsibility: the database checks who writes it, when and that it is final, not that
  ``storage/scanner.py`` ran, so the API writes the scanner's result and never a value from the client.
  ``engagement_message_attachments_guard`` (BEFORE UPDATE OR DELETE, SECURITY INVOKER, every role): an upload joins
  only its uploader's own message, in the transaction that inserted the message (``app_xid_is_current(m.xmin)``, so a
  sent message never gains a file later), and only clean (CHECK ``attached_only_when_clean``); its file, keys and time
  never change; once sent nothing changes and nothing is deleted, but by the owner (room for D-54's erasure). Every
  party reads a sent attachment. At most 5 per message (``engagement_message_attachments_cap``, AFTER INSERT OR UPDATE
  OF message_id, every role; check_violation with constraint name ``engagement_message_attachments_at_most_5``). Each
  is 1 byte to 20 MB with its SHA-256; the object key is the row's own, ``messages/<engagement_id>/<id>`` in the uuid
  text form (CHECK ``object_key_is_its_own``: ids only, no file name, and never another object of the bucket, such as
  a proposal's Tier-2 file under ``attachments/``); the file name is 1 to 255 characters without a control character
  or a path separator.
- ``engagement_message_reads`` (USER; bridge_app: SELECT, INSERT, UPDATE of ``last_read_at``): one row per party
  and engagement, the user's own, on an engagement they are a party of.
- The report (D-57 (4)): ``app_report_message(message, reasons)`` (SECURITY DEFINER, EXECUTE bridge_app) files a
  ``moderation_cases`` row (``subject_type = 'message'``, ``source = 'report'``, the caller as ``reporter_id``) for a
  message the caller reads as a party (insufficient_privilege, "no message of the caller's with that id",
  otherwise), once per reporter and message (a repeat returns the same case, ``created`` false; the partial unique
  index ``uq_moderation_cases_message_report`` backs it), with reasons that are one or more of the fixed codes
  ``spam``, ``abuse``, ``contact_details``, ``confidential`` and ``other`` (never free text; each kept once; SQLSTATE
  22023, invalid_parameter_value, otherwise), and at most 10 message reports per reporter in 24 hours, a limit fixed
  in the function that no caller can raise (SQLSTATE 54000, program_limit_exceeded). bridge_app's direct INSERT of a
  report is narrowed to every other subject type, so every message case has been filed by a party.
  ``app_reported_message(case)`` (SECURITY DEFINER, EXECUTE bridge_app, staff admin|moderator only) returns the one
  message of a message report (id, engagement, sender party, body, time): the only way staff read a message.

The shortlist (track B; tenancy ORG): ``org_shortlist`` (bridge_app: SELECT, INSERT without ``added_at``, DELETE),
one row per (organisation, proposal). Every member reads (narrowed by ``app.org_id``); members with a Tier-2 role
(reviewer, signatory, admin) add as themselves (``added_by``) and remove. A proposal is added only while
``app_org_sees_proposal(org, proposal)`` (SECURITY DEFINER, EXECUTE bridge_app; the API calls it too, for its 404):
the caller is a member of the organisation (narrowed by ``app.org_id``; false for anyone else, so it tells nobody
what another organisation's Inbox holds) and the proposal is published and clear and is in the organisation's Inbox:
pitched to it (a delivered tag), matched by its scout (``agent_matches``) or answering its Brief (the proposal's
current version links a problem whose Brief is the organisation's).

Saved searches (track C; tenancy USER): ``saved_searches`` (bridge_app: SELECT, INSERT without ``last_alerted_at``
and ``created_at``, UPDATE of ``name``, ``alerts`` and ``last_alerted_at``, DELETE), the owner's only. A name of 1
to 60 characters, the Discover view (``problems`` or ``briefs``), an optional niche (``niches.slug``) and county
(``regions.code``), optional words (1 to 100 characters), ``alerts`` (default on) and ``last_alerted_at``. At most 10
per user (``saved_searches_cap``, AFTER INSERT, every role, serialised per user; check_violation with constraint name
``saved_searches_at_most_10``). The daily alert job runs as bridge_app like every job: ``app_saved_searches_due(now)``
(SECURITY DEFINER, EXECUTE bridge_app) lists, to a session with no user bound only, the (user, saved search) ids with
alerts on, of active users, not alerted since 00:00 Africa/Nairobi of ``now``'s day; the job then binds to each user
and reads, matches and advances ``last_alerted_at`` under that user's own RLS.

Operating rules for the code that uses this schema:

- Map the tracker's refusal for an engagement the caller cannot see ("no engagement of the caller's with that id",
  insufficient_privilege) to 404, and an RLS refusal of a message to 404 for a non-party (staff included) or 403 for a
  viewer. Check the stage before writing with the gate's rule (the organisation's 403 before the thread opens: at
  ``INTEREST_CONFIRMED``, or ``CONTACT_MADE`` on a procurement route; 409 after an end); SQLSTATE 55000 from the gate
  is the race of the two.
- Post a message as the sender, leaving ``created_at`` out (read it back), then attach the staged uploads in the same
  transaction: ``UPDATE engagement_message_attachments SET message_id = :m WHERE id = ANY(:ids) AND message_id IS
  NULL`` and check the row count (a missing, foreign, unclean or already-sent upload matches nothing or is refused).
- A message is free text a party typed and is never deleted: keep it out of event payloads, logs, audit details and
  emails (N18 says who wrote, never the text). Its erasure is D-54 (a staff-only definer redaction, not written yet).
- File a report only with ``SELECT * FROM app_report_message(:message, :reasons)`` (the codes of
  ``bridge.engagements.models.MESSAGE_REPORT_REASONS``); staff read a reported message only with
  ``app_reported_message(:case)``.
- Call ``app_org_sees_proposal`` before adding to the shortlist (404 when false); a repeat add is a unique violation
  (or ``ON CONFLICT DO NOTHING``).
- The alert job calls ``app_saved_searches_due(now)`` with no user bound, then acts per user in a session bound to
  that user (``bind_tenant``), deciding again there; it advances ``last_alerted_at`` in the transaction that writes the
  notification.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = (
    "engagement_messages",
    "engagement_message_attachments",
    "engagement_message_reads",
    "org_shortlist",
    "saved_searches",
)
RLS_TABLES = NEW_TABLES

# Table privileges of bridge_app on this revision's tables; anything not listed is not granted. Column-scoped where the
# database owns a column (times, redaction) or a column is written later (an upload's message and scan verdict, a
# search's last alert).
APP_GRANTS: dict[str, str] = {
    "engagement_messages": "SELECT, INSERT (id, engagement_id, sender_user_id, sender_party, body)",
    "engagement_message_attachments": (
        "SELECT, INSERT (id, engagement_id, uploader_user_id, file_name, content_type, size_bytes, sha256, object_key),"
        " UPDATE (message_id, av_status), DELETE"
    ),
    "engagement_message_reads": "SELECT, INSERT (engagement_id, user_id, last_read_at), UPDATE (last_read_at)",
    "org_shortlist": "SELECT, INSERT (org_id, proposal_id, added_by), DELETE",
    "saved_searches": (
        "SELECT, INSERT (id, user_id, name, view, niche_slug, county_code, words, alerts),"
        " UPDATE (name, alerts, last_alerted_at), DELETE"
    ),
}

# Labels of the enum types this revision's tables reuse (revisions 0002 and 0003), frozen here.
ENGAGEMENT_PARTY = ("developer", "org")
AV_STATUS = ("pending_upload", "pending_scan", "clean", "infected", "failed")

# CHECK expressions, verbatim from the ORM models (bridge.engagements.models, bridge.profiles.models).
REDACTED = "'[redacted]'"  # D-54: the one body a message may be changed to
MESSAGE_BODY = "body ~ '[^[:space:]]' AND char_length(body) <= 4000"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
# An upload's object is its own: messages/<engagement>/<id> (the uuid text form), never another object of the bucket.
OBJECT_KEY = "object_key = 'messages/' || engagement_id::text || '/' || id::text"
SAVED_SEARCH_VIEWS = ("problems", "briefs")

# moderation_cases (revision 0002): bridge_app's INSERT policy, as it was and narrowed (restored on downgrade).
REPORTS_INSERT_0002 = (
    "source = 'report' AND reporter_id = app_user_id() AND status = 'open' AND classifier IS NULL"
    " AND assigned_to IS NULL AND decided_by IS NULL AND decided_at IS NULL"
)
REPORTS_INSERT = REPORTS_INSERT_0002 + " AND subject_type <> 'message'"  # message reports: app_report_message only
MESSAGE_REPORT = "subject_type = 'message' AND source = 'report'"


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


# Predicates. The engagement is read under the caller's own RLS (the engagements policies: its developer, members of its
# organisation narrowed by app.org_id, staff admin), and the party condition then leaves staff out: the thread is the
# parties' only (D-57 (4)).
_IN_ORG = "(app_org_id() IS NULL OR e.org_id = app_org_id())"
_PARTY = f"e.developer_id = app_user_id() OR (app_is_member(e.org_id) AND {_IN_ORG})"
# Who may post: the developer, or a member who may act on the tracker (never a viewer; revision 0003's acting roles).
_ACTING_MEMBER = f"app_is_member(e.org_id, '{{owner,admin,reviewer,signatory,finance}}') AND {_IN_ORG}"


def _engagement(table: str, condition: str) -> str:
    """The row's engagement is visible to the caller and meets ``condition`` (over ``e``)."""
    return f"EXISTS (SELECT 1 FROM engagements e WHERE e.id = {table}.engagement_id AND ({condition}))"


MESSAGE_INSERT = "sender_user_id = app_user_id() AND " + _engagement(
    "engagement_messages",
    "CASE engagement_messages.sender_party WHEN 'developer' THEN e.developer_id = app_user_id()"
    f" WHEN 'org' THEN e.developer_id <> app_user_id() AND {_ACTING_MEMBER} ELSE false END",
)
_UPLOADER = "uploader_user_id = app_user_id()"
_UNSENT = "message_id IS NULL"
# An upload joins its uploader's own message of the same engagement (the composite foreign key, the guard and its
# transaction rule do the rest).
_OWN_MESSAGE = (
    "EXISTS (SELECT 1 FROM engagement_messages m WHERE m.id = engagement_message_attachments.message_id"
    " AND m.engagement_id = engagement_message_attachments.engagement_id AND m.sender_user_id = app_user_id())"
)
_ORG_MEMBER = "app_is_member(org_id) AND (app_org_id() IS NULL OR org_id = app_org_id())"
# docs/spec/06 6.1's Tier-2 roles (reviewer, signatory, admin) edit the shortlist.
_TIER2_MEMBER = (
    "app_is_member(org_id, '{admin,reviewer,signatory}') AND (app_org_id() IS NULL OR org_id = app_org_id())"
)
_OWN = "user_id = app_user_id()"
_OWN_READ = f"{_OWN} AND " + _engagement("engagement_message_reads", _PARTY)

POLICIES: tuple[Policy, ...] = (
    # --- engagement_messages: the parties read; a party posts on their own side (append-only) ---
    Policy("engagement_messages", "SELECT", _engagement("engagement_messages", _PARTY)),
    Policy("engagement_messages", "INSERT", check=MESSAGE_INSERT),
    # --- engagement_message_attachments: a sent file is the parties'; a staged upload its uploader's ---
    Policy(
        "engagement_message_attachments",
        "SELECT",
        f"({_UPLOADER} OR message_id IS NOT NULL) AND " + _engagement("engagement_message_attachments", _PARTY),
    ),
    Policy(
        "engagement_message_attachments",
        "INSERT",
        check=f"{_UPLOADER} AND {_UNSENT} AND "
        + _engagement("engagement_message_attachments", f"e.developer_id = app_user_id() OR ({_ACTING_MEMBER})"),
    ),
    Policy(
        "engagement_message_attachments",
        "UPDATE",
        f"{_UPLOADER} AND {_UNSENT} AND " + _engagement("engagement_message_attachments", _PARTY),
        f"{_UPLOADER} AND ({_UNSENT} OR {_OWN_MESSAGE})",
    ),
    Policy("engagement_message_attachments", "DELETE", f"{_UPLOADER} AND {_UNSENT}"),
    # --- engagement_message_reads: a party's own marker of the thread ---
    Policy("engagement_message_reads", "SELECT", _OWN_READ),
    Policy("engagement_message_reads", "INSERT", check=_OWN_READ),
    Policy("engagement_message_reads", "UPDATE", _OWN_READ, _OWN_READ),
    # --- org_shortlist: every member reads; the Tier-2 roles add (a proposal of the Inbox) and remove ---
    Policy("org_shortlist", "SELECT", _ORG_MEMBER),
    Policy(
        "org_shortlist",
        "INSERT",
        check=f"added_by = app_user_id() AND {_TIER2_MEMBER} AND app_org_sees_proposal(org_id, proposal_id)",
    ),
    Policy("org_shortlist", "DELETE", _TIER2_MEMBER),
    # --- saved_searches: the owner's only ---
    Policy("saved_searches", "SELECT", _OWN),
    Policy("saved_searches", "INSERT", check=_OWN),
    Policy("saved_searches", "UPDATE", _OWN, _OWN),
    Policy("saved_searches", "DELETE", _OWN),
)

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0007: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS; trigger functions to nobody). SECURITY
# DEFINER functions run as bridge_owner, which bypasses RLS (ENABLED, not FORCED).
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- The thread's stage gate (REQ-ENG-11, D-57 (1)): a message, or an upload for one, is written only once an event of the
-- engagement's chain has entered stage 3 (INTEREST_CONFIRMED) or a later main-path stage (CONTACT_MADE to
-- PAYMENT_FINAL), and only until it ends (DECLINED, WITHDRAWN, EXPIRED, TERMINATED, CLOSED: the thread is read-only
-- from then on). 3b PROCUREMENT_ROUTE does not count (a public entity may enter it from UNDER_REVIEW, before any
-- approval, and go on to CONTACT_MADE without INTEREST_CONFIRMED: the thread then opens at CONTACT_MADE). "Has
-- entered", not "is in": the order of states is not linear and the side states resume where they were entered.
-- Locks the engagement's row FOR KEY SHARE first, so an append in flight (the chain holds FOR UPDATE until commit) is
-- waited for and its outcome read (each statement below takes a new snapshot): no message is written once the
-- engagement's end has committed, and concurrent messages do not wait for each other. Fires right after
-- tracker_engagement_visible() (<table>_1_open sorts second), so it locks and reports only an engagement the caller
-- can see. For every role. SECURITY DEFINER: reads the chain whatever the caller's grants.
CREATE FUNCTION engagement_thread_open() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_state public.engagement_state;
BEGIN
    SELECT e.state INTO v_state FROM public.engagements e WHERE e.id = NEW.engagement_id FOR KEY SHARE;
    IF v_state IN ('DECLINED', 'WITHDRAWN', 'EXPIRED', 'TERMINATED', 'CLOSED') THEN
        RAISE EXCEPTION '%: the engagement ended in %; its thread is read-only', TG_TABLE_NAME, v_state
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.engagement_events ev
                    WHERE ev.engagement_id = NEW.engagement_id
                      AND ev.to_state IN ('INTEREST_CONFIRMED', 'CONTACT_MADE', 'NDA_PENDING', 'NDA_SIGNED',
                                          'NEGOTIATION', 'AGREEMENT_SIGNING', 'IN_IMPLEMENTATION', 'DELIVERED',
                                          'SIGN_OFF', 'PAYMENT_FINAL')) THEN
        RAISE EXCEPTION '%: the thread opens at INTEREST_CONFIRMED (at CONTACT_MADE on a procurement route)',
            TG_TABLE_NAME USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    RETURN NEW;
END;
$$;

-- D-54 (default (a)), D-57 (3): a message changes only by its redaction, once: its body becomes the fixed marker
-- '[redacted]' with redacted_at and redacted_by set in the same statement, and nothing else changes. Only the table's
-- owner, or a SECURITY DEFINER function it owns (a staff-only redaction function: none exists yet), may do it;
-- bridge_app holds no UPDATE on the table at all. DELETE and TRUNCATE stay refused for every role (block_mutation()).
-- SECURITY INVOKER, so current_user is the writer (as engagement_notes_redaction_guard() of revision 0006).
CREATE FUNCTION engagement_messages_redaction_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF current_user <> (SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID)
       OR OLD.redacted_at IS NOT NULL OR NEW.body IS DISTINCT FROM '[redacted]'
       OR NEW.redacted_at IS NULL OR NEW.redacted_by IS NULL
       OR (NEW.id, NEW.engagement_id, NEW.sender_user_id, NEW.sender_party, NEW.created_at)
          IS DISTINCT FROM (OLD.id, OLD.engagement_id, OLD.sender_user_id, OLD.sender_party, OLD.created_at) THEN
        RAISE EXCEPTION 'engagement_messages: a message changes only by its redaction, once, by the owner (D-54)'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

-- An upload's life (REQ-ENG-11): its file (name, type, size, digest, object key), engagement, uploader and time never
-- change; it is inserted pending (bridge_app cannot name av_status) and its scan verdict (clean, infected, failed),
-- given by an UPDATE, is final; it joins only its uploader's own message, in
-- the transaction that inserted the message (app_xid_is_current(xmin): its own id or a savepoint's), so a sent message
-- never gains a file later (and only clean: CHECK attached_only_when_clean); once sent it never changes and is never
-- deleted, but by the table's owner (room for D-54's erasure). A staged upload is deleted by its uploader (policy).
-- For every role; RLS has already narrowed an UPDATE or DELETE to the caller's own staged uploads. SECURITY INVOKER:
-- current_user is the writer, and the uploader reads their own message under their RLS.
CREATE FUNCTION engagement_message_attachments_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.message_id IS NOT NULL AND current_user <> (
            SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID) THEN
            RAISE EXCEPTION 'engagement_message_attachments: a sent attachment is never deleted'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.message_id IS NOT NULL THEN
        RAISE EXCEPTION 'engagement_message_attachments: a sent attachment never changes'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (NEW.id, NEW.engagement_id, NEW.uploader_user_id, NEW.file_name, NEW.content_type, NEW.size_bytes, NEW.sha256,
        NEW.object_key, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.engagement_id, OLD.uploader_user_id, OLD.file_name, OLD.content_type,
                         OLD.size_bytes, OLD.sha256, OLD.object_key, OLD.created_at) THEN
        RAISE EXCEPTION 'engagement_message_attachments: an upload''s file, keys and time never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.av_status NOT IN ('pending_upload', 'pending_scan') AND NEW.av_status IS DISTINCT FROM OLD.av_status THEN
        RAISE EXCEPTION 'engagement_message_attachments: a scan verdict (%) is final', OLD.av_status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.message_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.engagement_messages m
         WHERE m.id = NEW.message_id AND m.engagement_id = NEW.engagement_id
           AND m.sender_user_id = NEW.uploader_user_id AND public.app_xid_is_current(m.xmin)
    ) THEN
        RAISE EXCEPTION 'engagement_message_attachments: an upload joins only its uploader''s own message, in the'
            ' transaction that sends it' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- At most 5 attachments per message (REQ-ENG-11). AFTER the statement's rows are in (an AFTER row trigger sees them
-- all), for every role; only the message's own transaction can attach (the guard), so no other writer races it.
-- SECURITY DEFINER: counts whatever the caller sees.
CREATE FUNCTION engagement_message_attachments_cap() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.message_id IS NOT NULL AND (
        SELECT count(*) FROM public.engagement_message_attachments a WHERE a.message_id = NEW.message_id) > 5 THEN
        RAISE EXCEPTION 'engagement_message_attachments: at most 5 attachments per message'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'engagement_message_attachments_at_most_5';
    END IF;
    RETURN NULL;
END;
$$;

-- At most 10 saved searches per user (P21 track C, D-57 (7)). AFTER INSERT: after RLS, so a row for another user is
-- refused before anything is counted; serialised per user (advisory lock), and the count then reads every committed
-- row (a new snapshot), the new one included. For every role. SECURITY DEFINER: counts whatever the caller sees.
CREATE FUNCTION saved_searches_cap() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('saved_searches:' || NEW.user_id::text, 0));
    IF (SELECT count(*) FROM public.saved_searches s WHERE s.user_id = NEW.user_id) > 10 THEN
        RAISE EXCEPTION 'saved_searches: at most 10 per user'
            USING ERRCODE = 'check_violation', CONSTRAINT = 'saved_searches_at_most_10';
    END IF;
    RETURN NULL;
END;
$$;

-- Whether p_proposal is in p_org's Inbox (P21 track B, REQ-REPO-02): the caller is an active member of p_org (narrowed
-- by app.org_id; false for anyone else, so nobody learns what another organisation's Inbox holds), and the proposal is
-- published and clear and was pitched to the organisation (a delivered tag), matched by its scout (agent_matches) or
-- answers its Brief (the proposal's current version links a problem whose Brief is the organisation's). The
-- shortlist's INSERT policy and the API (its 404) call it. SECURITY DEFINER: reads the tags, matches and Briefs
-- whatever the caller sees; returns the boolean only.
CREATE FUNCTION app_org_sees_proposal(p_org uuid, p_proposal uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT coalesce(public.app_is_member(p_org) AND (public.app_org_id() IS NULL OR p_org = public.app_org_id())
       AND EXISTS (
           SELECT 1 FROM public.proposals p
            WHERE p.id = p_proposal AND p.status = 'published' AND p.moderation_state = 'clear'
              AND (EXISTS (SELECT 1 FROM public.tags t
                            WHERE t.proposal_id = p.id AND t.org_id = p_org AND t.status = 'delivered')
                   OR EXISTS (SELECT 1 FROM public.agent_matches m WHERE m.proposal_id = p.id AND m.org_id = p_org)
                   OR EXISTS (SELECT 1 FROM public.proposal_problems pp
                                JOIN public.problem_briefs b ON b.problem_id = pp.problem_id
                               WHERE pp.proposal_version_id = p.current_version_id AND b.org_id = p_org))), false)
$$;

-- The saved searches the daily alert job may act on at p_now (P21 track C): ids only, so the job binds to their users
-- instead of walking every user (no application role reads every user's searches). Called with no user bound (a
-- signed-in request learns nothing about other users' searches), as app_engagements_due_for_expiry (revision 0007).
-- Alerts on, the user active, and not alerted since 00:00 Africa/Nairobi of p_now's day (a re-run on the same day
-- lists nothing the first run advanced). A superset of what is due: the job decides again, bound to the user.
CREATE FUNCTION app_saved_searches_due(p_now timestamptz)
    RETURNS TABLE (user_id uuid, saved_search_id uuid)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_saved_searches_due: the saved-search alert job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_now IS NULL THEN
        RAISE EXCEPTION 'app_saved_searches_due: name the time' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT s.user_id, s.id
      FROM public.saved_searches s
      JOIN public.users u ON u.id = s.user_id
     WHERE s.alerts AND u.status = 'active'
       AND (s.last_alerted_at IS NULL
            OR s.last_alerted_at
               < (date_trunc('day', p_now AT TIME ZONE 'Africa/Nairobi') AT TIME ZONE 'Africa/Nairobi'))
     ORDER BY s.user_id, s.id;
END;
$$;

-- A party reports a message (REQ-ENG-11, D-57 (4)): files one moderation case (subject_type 'message', source
-- 'report', the caller as reporter_id) for a message the caller reads as a party (its engagement's developer, or a
-- member of its organisation narrowed by app.org_id; anyone else gets one refusal, the same as for a message that does
-- not exist), once per reporter and message (a repeat returns the same case with created false). The reasons are one
-- or more of the fixed codes spam, abuse, contact_details, confidential, other (never free text: the case is staff's
-- to read; each kept once, in code order; invalid_parameter_value otherwise). At most 10 message reports per reporter
-- in 24 hours, fixed here (no caller names the limit; program_limit_exceeded). Serialised per reporter (an advisory
-- lock; the count then reads every committed report, at READ COMMITTED, the application's level). The report is the
-- reporter sharing that one message with staff (app_reported_message). SECURITY DEFINER: reads the message and writes
-- the case whatever the caller's RLS (bridge_app's own INSERT of a message report is refused).
CREATE FUNCTION app_report_message(p_message uuid, p_reasons text[])
    RETURNS TABLE (case_id uuid, created boolean)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_case uuid;
BEGIN
    IF v_user IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.engagement_messages m JOIN public.engagements e ON e.id = m.engagement_id
         WHERE m.id = p_message
           AND (e.developer_id = v_user
                OR (public.app_is_member(e.org_id) AND (public.app_org_id() IS NULL OR e.org_id = public.app_org_id())))
    ) THEN
        RAISE EXCEPTION 'app_report_message: no message of the caller''s with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_reasons IS NULL OR cardinality(p_reasons) = 0 OR array_ndims(p_reasons) <> 1
       OR array_position(p_reasons, NULL) IS NOT NULL
       OR NOT (p_reasons <@ ARRAY['spam', 'abuse', 'contact_details', 'confidential', 'other']) THEN
        RAISE EXCEPTION 'app_report_message: the reasons are one or more of spam, abuse, contact_details,'
            ' confidential, other' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('moderation_cases:message_report:' || v_user::text, 0));
    SELECT c.id INTO v_case FROM public.moderation_cases c
     WHERE c.subject_type = 'message' AND c.source = 'report' AND c.subject_id = p_message AND c.reporter_id = v_user;
    IF FOUND THEN
        RETURN QUERY SELECT v_case, false;
        RETURN;
    END IF;
    IF (SELECT count(*) FROM public.moderation_cases c
         WHERE c.subject_type = 'message' AND c.source = 'report' AND c.reporter_id = v_user
           AND c.created_at > now() - interval '24 hours') >= 10 THEN
        RAISE EXCEPTION 'app_report_message: at most 10 message reports a day' USING ERRCODE = 'program_limit_exceeded';
    END IF;
    v_case := public.uuid7();
    INSERT INTO public.moderation_cases (id, subject_type, subject_id, reasons, source, reporter_id)
    VALUES (v_case, 'message', p_message,
            ARRAY(SELECT r.code FROM unnest(ARRAY['spam', 'abuse', 'contact_details', 'confidential', 'other'])
                                     WITH ORDINALITY AS r(code, n)
                   WHERE r.code = ANY (p_reasons) ORDER BY r.n),
            'report', v_user);
    RETURN QUERY SELECT v_case, true;
END;
$$;

-- The one message a report shared (REQ-ENG-11, D-57 (4)): staff admin or moderator only (the moderation queue's
-- readers), and only the message of a message report (every such case was filed by a party: app_report_message);
-- no row for any other case. Staff read no message otherwise (the thread's policies leave them out). SECURITY
-- DEFINER: reads the message whatever the caller's RLS.
CREATE FUNCTION app_reported_message(p_case uuid)
    RETURNS TABLE (message_id uuid, engagement_id uuid, sender_party engagement_party, body text,
                   created_at timestamptz)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_staff('{admin,moderator}') THEN
        RAISE EXCEPTION 'app_reported_message: staff admin or moderator only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN QUERY
    SELECT m.id, m.engagement_id, m.sender_party, m.body, m.created_at
      FROM public.moderation_cases c JOIN public.engagement_messages m ON m.id = c.subject_id
     WHERE c.id = p_case AND c.subject_type = 'message' AND c.source = 'report';
END;
$$;
"""

# EXECUTE grants (EXECUTE revoked from PUBLIC first): a policy runs its functions with the caller's privileges.
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_org_sees_proposal(uuid, uuid)": ("bridge_app",),  # the shortlist's INSERT policy and the API's 404
    "app_saved_searches_due(timestamptz)": ("bridge_app",),  # the alert job, with no user bound (ids only)
    "app_report_message(uuid, text[])": ("bridge_app",),  # a party's report of one message
    "app_reported_message(uuid)": ("bridge_app",),  # staff admin|moderator read the reported message
}
TRIGGER_FUNCTIONS = (
    "engagement_thread_open()",
    "engagement_messages_redaction_guard()",
    "engagement_message_attachments_guard()",
    "engagement_message_attachments_cap()",
    "saved_searches_cap()",
)

# The tracker tables' pattern (revisions 0003 and 0006): the visibility check fires first on INSERT (<table>_0_visible
# sorts first by name), then the stage gate (<table>_1_open); the append-only refusals hold for every role.
TRIGGERS_SQL = r"""
CREATE TRIGGER engagement_messages_0_visible
    BEFORE INSERT ON engagement_messages
    FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();
CREATE TRIGGER engagement_messages_1_open
    BEFORE INSERT ON engagement_messages
    FOR EACH ROW EXECUTE FUNCTION engagement_thread_open();
CREATE TRIGGER engagement_messages_no_delete
    BEFORE DELETE ON engagement_messages
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
CREATE TRIGGER engagement_messages_redaction_guard
    BEFORE UPDATE ON engagement_messages
    FOR EACH ROW EXECUTE FUNCTION engagement_messages_redaction_guard();
CREATE TRIGGER engagement_messages_no_truncate
    BEFORE TRUNCATE ON engagement_messages
    FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();
CREATE TRIGGER engagement_message_attachments_0_visible
    BEFORE INSERT ON engagement_message_attachments
    FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();
CREATE TRIGGER engagement_message_attachments_1_open
    BEFORE INSERT ON engagement_message_attachments
    FOR EACH ROW EXECUTE FUNCTION engagement_thread_open();
CREATE TRIGGER engagement_message_attachments_guard
    BEFORE UPDATE OR DELETE ON engagement_message_attachments
    FOR EACH ROW EXECUTE FUNCTION engagement_message_attachments_guard();
CREATE TRIGGER engagement_message_attachments_cap
    AFTER INSERT OR UPDATE OF message_id ON engagement_message_attachments
    FOR EACH ROW EXECUTE FUNCTION engagement_message_attachments_cap();
CREATE TRIGGER engagement_message_attachments_no_truncate
    BEFORE TRUNCATE ON engagement_message_attachments
    FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();
CREATE TRIGGER engagement_message_reads_0_visible
    BEFORE INSERT ON engagement_message_reads
    FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();
CREATE TRIGGER saved_searches_cap
    AFTER INSERT ON saved_searches
    FOR EACH ROW EXECUTE FUNCTION saved_searches_cap();
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
    grants += [f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in TRIGGER_FUNCTIONS]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    _create_tables()
    _run_sql(FUNCTIONS_SQL)  # before the policies: the shortlist's INSERT policy calls app_org_sees_proposal
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(f"ALTER POLICY bridge_app_insert ON moderation_cases WITH CHECK ({REPORTS_INSERT});")
    op.create_index(
        "uq_moderation_cases_message_report",
        "moderation_cases",
        ["subject_id", "reporter_id"],
        unique=True,
        postgresql_where=sa.text(MESSAGE_REPORT),
    )
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Destructive: drops the engagement threads (the parties' messages, their attachments' records and read markers),
    the organisations' shortlists and the developers' saved searches. Under the CLAUDE.md stop rule a downgrade of a
    database holding any of them is a destructive migration: back the database up (and the object store: the
    attachments' files stay there, unreferenced) and get the human's decision first. The downgrade refuses while any
    of the tables has rows unless it is run with ``-x allow_p21_loss=true`` (``alembic -x allow_p21_loss=true
    downgrade 0007``). Message reports already filed stay in ``moderation_cases``."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_p21_loss") == "true"
    holding = [
        table
        for table in NEW_TABLES
        if op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
    ]
    if holding and not allowed:
        raise RuntimeError(
            f"revision 0008 downgrade: {', '.join(holding)} hold the parties' messages, shortlists or saved searches;"
            " back the database (and the object store) up, get the human's decision (CLAUDE.md: destructive"
            " migration), then run with -x allow_p21_loss=true"
        )
    # Revision 0002's report policy as it was (first: nothing depends on it), and no message-report index.
    _run_sql(f"ALTER POLICY bridge_app_insert ON moderation_cases WITH CHECK ({REPORTS_INSERT_0002});")
    op.drop_index("uq_moderation_cases_message_report", table_name="moderation_cases")
    # Dropping a table drops its policies, triggers, indexes and grants (block_mutation(), tracker_engagement_visible()
    # and app_xid_is_current() are revisions 0002, 0003 and 0006's and stay); the shortlist's policy goes with its table
    # before the function it calls.
    for table in ("engagement_message_attachments", "engagement_message_reads", "engagement_messages"):
        op.drop_table(table)
    op.drop_table("org_shortlist")
    op.drop_table("saved_searches")
    _run_sql("\n".join(f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS)))


def _enum(name: str, labels: tuple[str, ...]) -> postgresql.ENUM:
    return postgresql.ENUM(*labels, name=name, create_type=False)


def _create_tables() -> None:
    op.create_table(
        "engagement_messages",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("sender_user_id", sa.Uuid(), nullable=False),
        sa.Column("sender_party", _enum("engagement_party", ENGAGEMENT_PARTY), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redacted_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(MESSAGE_BODY, name=op.f("ck_engagement_messages_body_length")),
        sa.CheckConstraint(
            f"(redacted_at IS NOT NULL) = (body = {REDACTED}) AND (redacted_at IS NULL) = (redacted_by IS NULL)",
            name=op.f("ck_engagement_messages_redaction_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_engagement_messages_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(["redacted_by"], ["users.id"], name=op.f("fk_engagement_messages_redacted_by_users")),
        sa.ForeignKeyConstraint(
            ["sender_user_id"], ["users.id"], name=op.f("fk_engagement_messages_sender_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_messages")),
        sa.UniqueConstraint("id", "engagement_id", name=op.f("uq_engagement_messages_id_engagement_id")),
    )
    op.create_index(
        "ix_engagement_messages_thread", "engagement_messages", ["engagement_id", "created_at", "id"], unique=False
    )
    op.create_table(
        "engagement_message_attachments",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=True),
        sa.Column("uploader_user_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("av_status", _enum("av_status", AV_STATUS), server_default=sa.text("'pending_scan'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "file_name ~ '[^[:space:]]' AND char_length(file_name) <= 255 AND file_name !~ '[[:cntrl:]/\\\\]'",
            name=op.f("ck_engagement_message_attachments_file_name_valid"),
        ),
        sa.CheckConstraint(
            f"size_bytes BETWEEN 1 AND {MAX_ATTACHMENT_BYTES}",
            name=op.f("ck_engagement_message_attachments_size_limit"),
        ),
        sa.CheckConstraint("octet_length(sha256) = 32", name=op.f("ck_engagement_message_attachments_sha256_length")),
        sa.CheckConstraint(OBJECT_KEY, name=op.f("ck_engagement_message_attachments_object_key_is_its_own")),
        sa.CheckConstraint(
            "message_id IS NULL OR av_status = 'clean'",
            name=op.f("ck_engagement_message_attachments_attached_only_when_clean"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_engagement_message_attachments_engagement_id_engagements"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "engagement_id"],
            ["engagement_messages.id", "engagement_messages.engagement_id"],
            name="fk_engagement_message_attachments_message",
        ),
        sa.ForeignKeyConstraint(
            ["uploader_user_id"], ["users.id"], name=op.f("fk_engagement_message_attachments_uploader_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_message_attachments")),
        sa.UniqueConstraint("object_key", name=op.f("uq_engagement_message_attachments_object_key")),
    )
    op.create_index(
        op.f("ix_engagement_message_attachments_message_id"),
        "engagement_message_attachments",
        ["message_id"],
        unique=False,
    )
    op.create_table(
        "engagement_message_reads",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "last_read_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_engagement_message_reads_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_engagement_message_reads_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("engagement_id", "user_id", name=op.f("pk_engagement_message_reads")),
    )
    op.create_index(op.f("ix_engagement_message_reads_user_id"), "engagement_message_reads", ["user_id"], unique=False)
    op.create_table(
        "org_shortlist",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.ForeignKeyConstraint(["added_by"], ["users.id"], name=op.f("fk_org_shortlist_added_by_users")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_org_shortlist_org_id_organizations")),
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], name=op.f("fk_org_shortlist_proposal_id_proposals")),
        sa.PrimaryKeyConstraint("org_id", "proposal_id", name=op.f("pk_org_shortlist")),
    )
    op.create_table(
        "saved_searches",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("view", sa.Text(), nullable=False),
        sa.Column("niche_slug", sa.String(length=80), nullable=True),
        sa.Column("county_code", sa.String(length=8), nullable=True),
        sa.Column("words", sa.Text(), nullable=True),
        sa.Column("alerts", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "name ~ '[^[:space:]]' AND char_length(name) <= 60", name=op.f("ck_saved_searches_name_length")
        ),
        sa.CheckConstraint(
            f"view IN ({', '.join(repr(view) for view in SAVED_SEARCH_VIEWS)})",
            name=op.f("ck_saved_searches_view_known"),
        ),
        sa.CheckConstraint(
            "words IS NULL OR (words ~ '[^[:space:]]' AND char_length(words) <= 100)",
            name=op.f("ck_saved_searches_words_length"),
        ),
        sa.ForeignKeyConstraint(["county_code"], ["regions.code"], name=op.f("fk_saved_searches_county_code_regions")),
        sa.ForeignKeyConstraint(["niche_slug"], ["niches.slug"], name=op.f("fk_saved_searches_niche_slug_niches")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_saved_searches_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_searches")),
    )
    op.create_index(op.f("ix_saved_searches_user_id"), "saved_searches", ["user_id"], unique=False)
