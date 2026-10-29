"""Schema v9 (P22 track C): peers, blocks, team-up invitations, team threads and proposal contributors.

REQ-DEV-03 (D-58, D-62). Design: ``docs/platform/tasks/P22.md`` section "C — Peers and team up" and its "Defaults
taken" paragraph. Additive but for one narrowing of an earlier object, restored on downgrade: two new columns of
``developer_profiles`` (``peers_visible``, ``peers_opted_in_at``) with a CHECK, a trigger and bridge_app's UPDATE of
``peers_visible``; six new tables (``developer_blocks``, ``team_invitations``, ``team_threads``, ``team_messages``,
``team_thread_reads``, ``proposal_contributors``) with their policies, triggers and grants; twenty-five new functions
(nine of them trigger functions, three internal); one new partial unique index on ``moderation_cases``; and
bridge_app's INSERT policy on ``moderation_cases`` (revisions 0002 and 0008) narrowed so that the app files a team
message report only through ``app_report_team_message``. No enum type (text columns with CHECKs); no new tenancy class
(every new table is USER). Moderation case subjects (``subject_type``, ``String(40)``, revision 0002) are free
strings, so ``'team_message'`` needs no type change. Nothing else of revisions 0001 to 0010 is changed or dropped; the
triggers reuse ``block_mutation()`` (revision 0002) and the clock ``app_clock_now()`` (revision 0003), the policies
``app_is_developer()`` (revision 0009). The upgrade is additive; the downgrade is destructive (see ``downgrade()``).

A "developer" is ``app_is_developer()`` (revision 0009): an active user with a developer profile and no staff role.
"Counterparts" are the two parties of a team thread or of a pending invitation (``team_counterparts``); a declined,
withdrawn or ended invitation makes nobody a counterpart. Whom the caller may invite is ``app_is_visible_peer(user)``
(answered only to a caller who is a developer): the caller themselves when they opted in (``peers_visible``); anyone
else who opted in now and is one of the caller's peers (both opted in, the caller's county or a shared liked niche, no
block) or a counterpart of the caller's, active and not staff, with no block. Organisation-only accounts and staff read
nothing of the new tables (every policy needs ``app_is_developer()``); staff read one reported team message through
``app_reported_team_message`` only.

- ``developer_profiles`` (revision 0001): ``peers_visible`` (default false; bridge_app UPDATE, own row by 0001's
  policy, as ``headline``) and ``peers_opted_in_at``, the database's (``developer_profiles_peers_opt_in``, BEFORE
  INSERT OR UPDATE, every role): the shared clock when the flag turns true, kept while it stays true, NULL when false,
  whatever was sent (CHECK ``peers_opt_in_complete``). Nothing else of a profile reaches another developer but through
  the definers below (D-58: handle, headline, county and shared liked niches only).
- ``developer_blocks`` (USER; bridge_app: SELECT and DELETE, no INSERT): the blocker's own rows, read and deleted by a
  developer as the blocker (``blocker_user_id = app_user_id()``); never another's (the blocked side learns of a block
  only through ``app_blocked_either_way``, and only for a pair it is in). Inserted only through
  ``app_block_developer`` (bridge_app holds no INSERT, so no foreign key or policy refusal tells an unknown id from an
  account that is no developer: the function answers 0 to both). PK (blocker, blocked); CHECK not self. A block ends
  everything between the two in its own transaction, however it is inserted (the function, or the owner's seed):
  ``developer_blocks_0_lock`` (BEFORE INSERT) takes the pair's advisory lock and ``developer_blocks_end_pair`` (AFTER
  INSERT) ends every pending invitation between them (``ended``) and closes every open thread (``blocked``);
  contributor credit already given stays (D-62). Unblocking deletes the row only: threads stay closed, ended
  invitations ended.
- ``team_invitations`` (USER; bridge_app: SELECT, INSERT of ``id``, ``from_user_id``, ``to_user_id``, ``problem_id``,
  ``note``): read by its two parties (developers). Sent by a developer who opted in, as themselves, to a developer who
  opted in and is their peer or counterpart (never one outside their county and liked niches with no thread or pending
  invitation between them, never one who turned the switch off) on a problem every signed-in user reads that is
  published and clear (``app_team_problem_open``: a developer's problem, or a public published Brief; an invited or
  closed Brief is not), with no block either way; a note of 1 to 300 characters (line breaks allowed, no other control
  character) or none. The contact-details rule does not apply between developers (the API's). One pending invitation per
  pair and problem, in either direction: the partial unique index ``uq_team_invitations_pending_pair`` on (LEAST,
  GREATEST of the two, problem) WHERE pending. ``team_invitations_open`` (BEFORE INSERT, SECURITY DEFINER) answers the
  sender of their own invitation, when they opted in, with a precise refusal before the policy's generic one: the
  problem is not open to teams (no_data_found), the recipient may not be invited by them (no_data_found, read under the
  pair's lock so a block in flight is waited for; a blocked recipient gets the same refusal, so nothing tells the sender
  of a block); it says nothing to anyone else. ``status`` moves once, from ``pending`` to ``accepted``, ``declined`` or
  ``withdrawn`` (``app_decide_team_invitation``) or ``ended`` (a block), with ``decided_at``; ``team_invitations_guard``
  (every role): its parties, problem, note and creation time never change, a decided invitation never changes.
- ``team_threads`` (USER; bridge_app: SELECT only): one per accepted invitation (``invitation_id`` unique), between
  ``a_user_id < b_user_id`` (the canonical pair), on the invitation's problem; read by its two parties (developers);
  written only by ``app_decide_team_invitation`` (accept), ``app_close_team_thread`` (``left``) and a block
  (``blocked``). ``team_threads_guard`` (every role): the parties, problem, invitation and creation time never change;
  a closed thread never changes again (it never reopens). CHECKs: closed together with its reason, a known reason.
- ``team_messages`` (USER; bridge_app: SELECT, INSERT of ``id``, ``thread_id``, ``sender_user_id``, ``body``): the
  thread's parties read every message; a party posts as themselves while the thread is open and no block stands
  between them. The body is 1 to 4,000 characters and not blank (plain text). Append-only but for its redaction, as
  0008's ``engagement_messages``: ``team_messages_no_delete`` and ``_no_truncate`` (``block_mutation()``),
  ``team_messages_redaction_guard`` (only the owner, or a definer function it owns, once, to ``'[redacted]'`` with
  ``redacted_at`` and ``redacted_by``; none exists yet, D-54) and CHECK ``redaction_complete``. On INSERT
  ``team_messages_0_visible`` (SECURITY INVOKER: the caller's RLS) refuses a thread the caller does not read, the same
  for one that does not exist; then ``team_messages_1_open`` (SECURITY DEFINER, every role) reads the thread FOR SHARE
  (a close or a block in flight is waited for and its outcome read; concurrent messages do not wait for each other)
  and refuses a sender who is not a party (check_violation) and a closed thread (object_not_in_prerequisite_state).
  ``created_at`` is the database's clock. The thread reads by ``ix_team_messages_thread (thread_id, created_at, id)``.
  The 60-an-hour limit is the application's, as for engagement messages.
- ``team_thread_reads`` (USER; bridge_app: SELECT, INSERT, UPDATE of ``last_read_at``): a party's own marker of a
  thread they read.
- ``proposal_contributors`` (USER through the proposal; bridge_app: SELECT, INSERT of ``proposal_id``, ``user_id``,
  ``thread_id``, UPDATE of ``removed_at``): D-62 (a): the registrant stays one person; the proposal's owner (a
  developer) adds the other party of one of their team threads, open or closed, naming that thread (never a stranger,
  never themselves, never across a block either way); the owner removes a contributor, or a contributor removes
  themselves, by setting ``removed_at`` (the database's clock, ``proposal_contributors_guard``), once and for good: a
  removed contributor is never listed again and cannot be added back (the primary key). Read directly by the owner and
  the contributor (every row of theirs, removed ones included) and by another developer who reads the proposal (the
  proposals' own SELECT policy, through the subquery), who sees only the credit not removed; organisations and staff
  read the credit only as handles, through ``app_contributor_handles(proposal)``. Never part of the manifest or its
  hash.

Indexes: ``pk_developer_blocks`` (blocker, blocked) and ``ix_developer_blocks_blocked_user_id`` (blocks either way);
``uq_team_invitations_pending_pair`` (it also serves a block's ending of the pair's pending invitations),
``ix_team_invitations_from_user_id`` and ``_to_user_id`` (sent and received); ``ix_team_threads_pair`` (a, b) and
``ix_team_threads_b_user_id`` (a developer's threads), ``uq_team_threads_invitation_id``; ``ix_team_messages_thread``;
``pk_team_thread_reads`` and ``ix_team_thread_reads_user_id``; ``pk_proposal_contributors`` (proposal, user) and
``ix_proposal_contributors_user_id``; ``uq_moderation_cases_team_message_report`` (one report per reporter and team
message).

Functions (SECURITY DEFINER unless noted; pinned search_path; EXECUTE revoked from PUBLIC; granted to bridge_app where
listed in ``FUNCTION_GRANTS``; each refuses with a message naming itself):

- ``app_is_visible_peer(user)`` -> boolean: ``user`` is the caller who opted in, or opted in now and is one of the
  caller's peers or a counterpart of theirs (active, not staff), with no block either way; false to a caller who is not
  a developer. ``app_blocked_either_way(a, b)`` -> boolean: a block stands between ``a`` and ``b``
  either way; NULL unless the caller is ``a`` or ``b``. ``app_team_problem_open(problem)`` -> boolean: published,
  clear and readable by every signed-in user (see ``team_invitations``).
- ``app_peers(limit, offset)`` -> (user_id, handle, headline, county_code, county_name, shared_niches,
  same_county): a visible peer only (insufficient_privilege otherwise: not opted in, staff, organisation-only,
  unbound); a limit of 1 to 50 and an offset of 0 or more (invalid_parameter_value). The other visible peers of the
  caller's kind (real accounts for a real caller, demo accounts for a demo caller, as ``app_quiz_board``) with no
  block either way, who share a liked niche with the caller or are in the caller's county (a ``regions`` row of kind
  county, never the country); ``shared_niches`` the shared liked niches' slugs, sorted; ordered by the number of shared
  niches, then same county first, then the newest opt-in (the order only: the time is never returned, so nobody
  learns when another developer turned the switch on), then handle (the profile embedding is never computed in the
  prototype; its order replaces this one behind the same function when it is). Nothing else of a profile.
- ``app_developer_card(user)`` -> (user_id, handle, headline): one row when the caller is a developer, ``user`` is
  another developer, no block stands between them either way, and ``user`` is a counterpart of the caller's (a thread
  or a pending invitation, whatever ``user``'s switch says now) or one of the caller's peers (``app_peers``' rule); no
  row otherwise. ``app_blocked_developers()`` -> (user_id, handle, blocked_at): the caller's own blocks with the blocked
  developers' handles, newest first (developers only).
- ``app_decide_team_invitation(invitation, decision)`` -> the new thread's id for ``accept``, NULL otherwise:
  ``accept`` or ``decline`` by the recipient, ``withdraw`` by the sender (invalid_parameter_value for another word;
  insufficient_privilege for the wrong party, and "no invitation of the caller's" for a non-party, a non-developer and
  an unknown id alike); a pending invitation only (object_not_in_prerequisite_state). ``accept`` also needs the sender
  still an active, non-staff developer and the problem still open to teams, and creates the thread.
- ``app_close_team_thread(thread, reason)``: a party (developer) closes an open thread with ``left`` (the only reason
  it takes; ``blocked`` is a block's). ``app_block_developer(blocked)`` -> rows changed (the block inserted, 0 or 1,
  plus invitations ended and threads closed): developers only; for an unknown id or a user who is no developer (staff,
  an organisation-only account) it does nothing and returns 0, as for a repeat, so nothing tells the cases apart;
  idempotent. ``app_unblock_developer(blocked)`` -> rows deleted (SECURITY INVOKER: the caller's own
  block, under its RLS).
- ``app_report_team_message(message, reasons)`` -> (case_id, created) and ``app_reported_team_message(case)`` ->
  (message_id, thread_id, sender_user_id, sender_handle, body, created_at): 0008's message report pair for
  ``subject_type = 'team_message'``: a party of the message's thread files one case per message, a repeat returns the
  same case with created false; the reasons are the message report codes; at most 10 team message reports per
  reporter in 24 hours (fixed); staff admin or moderator read the one reported message, nothing else of the thread.
- ``app_contributor_handles(proposal)`` -> text[]: the handles of the proposal's contributors not removed, by
  ``added_at``, for a caller who may read the proposal (its owner, any signed-in user when it is published and clear,
  staff admin or moderator: the proposals' SELECT policy of revision 0002, restated); NULL for anyone else.
- Internal (no EXECUTE grant; called as the owner): ``team_pair_lock(a, b)`` (the pair's transaction advisory lock),
  ``team_end_pair(a, b)`` (ends the pair's pending invitations and closes its open threads; returns the count),
  ``team_peers_of(caller)`` (the peer set, unordered) and ``team_counterparts(a, b)`` (a thread or a pending
  invitation between the two).

Lock order: the pair's advisory lock first (an invitation's insert, a block by either path), then rows: an invitation
FOR UPDATE (a decision; a block's ending), a thread FOR UPDATE (a close; a block's closing) or FOR SHARE (a message).

Operating rules for the code that uses this schema:

- Peers: ``SELECT * FROM app_peers(:limit, :offset)`` for a visible peer (check ``app_is_visible_peer(app_user_id())``
  first and answer an empty page to a developer who is not opted in); the switch is an UPDATE of ``peers_visible`` on
  the caller's own profile (read ``peers_opted_in_at`` back: it is the database's).
- Invite: INSERT the invitation as the sender leaving ``status``, ``created_at`` and ``decided_at`` out (read them
  back). Map ``team_invitations_open``'s refusals: "the recipient is neither a peer nor a counterpart of the sender"
  (404, a blocked recipient included), "no published problem with that id" (404); a unique
  violation on ``uq_team_invitations_pending_pair`` (409); any other row-level security refusal (404). Decisions only
  through ``app_decide_team_invitation`` (insufficient_privilege "no invitation of the caller's" is 404, the wrong party
  403, object_not_in_prerequisite_state 409).
- Threads: post a message leaving ``created_at`` out (read it back); insufficient_privilege from
  ``team_messages_0_visible`` is 404; object_not_in_prerequisite_state from ``team_messages_1_open`` is 409
  ``thread_closed``. Close only through ``app_close_team_thread(thread, 'left')``. A message is free text a developer
  typed: keep it out of event payloads, logs, audit details and notices.
- Blocks through ``app_block_developer`` (it ends everything and says how much); unblock through
  ``app_unblock_developer``; list through ``app_blocked_developers()``. Counterparts' handles through
  ``app_developer_card`` (no row: render nothing of them).
- Reports only with ``SELECT * FROM app_report_team_message(:message, :reasons)``; staff read a reported team message
  only with ``app_reported_team_message(:case)``. There is no redaction function: an upheld team message report
  records the outcome only.
- Contributors: INSERT (proposal_id, user_id, thread_id) as the owner, naming a thread of the owner and that user
  (a refusal is 404 ``not_a_counterpart``; a repeat, or a removed contributor, is the primary key's 409); remove with
  ``UPDATE proposal_contributors SET removed_at = now()`` (the database sets the time). Show the credit only through
  ``app_contributor_handles(proposal)``: never from the manifest, never in its hash.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import context, op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = (
    "developer_blocks",
    "team_invitations",
    "team_threads",
    "team_messages",
    "team_thread_reads",
    "proposal_contributors",
)
RLS_TABLES = NEW_TABLES

# Table privileges of bridge_app on this revision's tables; anything not listed is not granted. Column-scoped where the
# database owns a column (status, decisions, closing, times, redaction) or a column is written later (a removal).
APP_GRANTS: dict[str, str] = {
    "developer_blocks": "SELECT, DELETE",  # inserted only through app_block_developer
    "team_invitations": "SELECT, INSERT (id, from_user_id, to_user_id, problem_id, note)",
    "team_threads": "SELECT",
    "team_messages": "SELECT, INSERT (id, thread_id, sender_user_id, body)",
    "team_thread_reads": "SELECT, INSERT (thread_id, user_id, last_read_at), UPDATE (last_read_at)",
    "proposal_contributors": "SELECT, INSERT (proposal_id, user_id, thread_id), UPDATE (removed_at)",
}
# revision 0001's developer_profiles grant gains the switch (own row: 0001's UPDATE policy)
PROFILE_GRANT = "GRANT UPDATE (peers_visible) ON TABLE developer_profiles TO bridge_app;"

# CHECK expressions, verbatim from the ORM models (bridge.teams.models, bridge.profiles.models).
INVITATION_STATUSES = ("pending", "accepted", "declined", "withdrawn", "ended")
CLOSE_REASONS = ("left", "blocked")
REDACTED = "'[redacted]'"  # D-54: the one body a message may be changed to (as revision 0008's)
MESSAGE_BODY = "body ~ '[^[:space:]]' AND char_length(body) <= 4000"
# Plain text over lines: tab, line feed and carriage return are allowed, no other control character.
NOTE_VALID = (
    "note IS NULL OR (note ~ '[^[:space:]]' AND char_length(note) <= 300"
    " AND note !~ '[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]')"
)
PEERS_OPT_IN_COMPLETE = "peers_visible = (peers_opted_in_at IS NOT NULL)"

# moderation_cases (revisions 0002 and 0008): bridge_app's INSERT policy, as 0008 left it and narrowed again (restored
# on downgrade).
REPORTS_INSERT_0008 = (
    "source = 'report' AND reporter_id = app_user_id() AND status = 'open' AND classifier IS NULL"
    " AND assigned_to IS NULL AND decided_by IS NULL AND decided_at IS NULL AND subject_type <> 'message'"
)
REPORTS_INSERT = REPORTS_INSERT_0008 + " AND subject_type <> 'team_message'"  # app_report_team_message only
TEAM_MESSAGE_REPORT = "subject_type = 'team_message' AND source = 'report'"


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


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


# Predicates. Every reader and writer is a developer (app_is_developer(): organisation-only accounts and staff read and
# write nothing here). A thread's parties are its canonical pair.
_DEV = "app_is_developer()"
_BLOCKER = f"blocker_user_id = app_user_id() AND {_DEV}"
_PARTIES = f"app_user_id() IN (from_user_id, to_user_id) AND {_DEV}"
_PAIR = f"app_user_id() IN (a_user_id, b_user_id) AND {_DEV}"


def _thread(table: str, condition: str = "") -> str:
    """The row's thread is one the caller is a party of (and meets ``condition``, over ``t``)."""
    return (
        f"EXISTS (SELECT 1 FROM team_threads t WHERE t.id = {table}.thread_id"
        f" AND app_user_id() IN (t.a_user_id, t.b_user_id){condition})"
    )


INVITE = (
    "from_user_id = app_user_id() AND app_is_visible_peer(from_user_id) AND app_is_visible_peer(to_user_id)"
    " AND app_team_problem_open(problem_id) AND NOT app_blocked_either_way(from_user_id, to_user_id)"
)
MESSAGE_INSERT = f"sender_user_id = app_user_id() AND {_DEV} AND " + _thread(
    "team_messages", " AND t.closed_at IS NULL AND NOT app_blocked_either_way(t.a_user_id, t.b_user_id)"
)
_OWN_READ = f"user_id = app_user_id() AND {_DEV} AND " + _thread("team_thread_reads")
_PROPOSAL = "EXISTS (SELECT 1 FROM proposals p WHERE p.id = proposal_contributors.proposal_id{condition})"
_OWNED = _PROPOSAL.format(condition=" AND p.owner_id = app_user_id()")
CONTRIBUTOR_INSERT = (
    f"{_DEV} AND user_id <> app_user_id() AND {_OWNED} AND EXISTS (SELECT 1 FROM team_threads t"
    " WHERE t.id = proposal_contributors.thread_id"
    " AND t.a_user_id = LEAST(app_user_id(), proposal_contributors.user_id)"
    " AND t.b_user_id = GREATEST(app_user_id(), proposal_contributors.user_id))"
    " AND NOT app_blocked_either_way(app_user_id(), user_id)"
)
CONTRIBUTOR_REMOVE = f"{_DEV} AND (user_id = app_user_id() OR {_OWNED})"

POLICIES: tuple[Policy, ...] = (
    # --- developer_blocks: the blocker's own rows (inserted only through app_block_developer) ---
    Policy("developer_blocks", "SELECT", _BLOCKER),
    Policy("developer_blocks", "DELETE", _BLOCKER),
    # --- team_invitations: the two parties read; a visible peer invites another on an open problem ---
    Policy("team_invitations", "SELECT", _PARTIES),
    Policy("team_invitations", "INSERT", check=INVITE),
    # --- team_threads: the two parties read (written by the definers only) ---
    Policy("team_threads", "SELECT", _PAIR),
    # --- team_messages: the thread's parties read; a party posts while it is open (append-only) ---
    Policy("team_messages", "SELECT", f"{_DEV} AND " + _thread("team_messages")),
    Policy("team_messages", "INSERT", check=MESSAGE_INSERT),
    # --- team_thread_reads: a party's own marker ---
    Policy("team_thread_reads", "SELECT", _OWN_READ),
    Policy("team_thread_reads", "INSERT", check=_OWN_READ),
    Policy("team_thread_reads", "UPDATE", _OWN_READ, _OWN_READ),
    # --- proposal_contributors: the owner and the contributor every row, other developers who read the proposal the
    # credit not removed; the owner adds a counterpart (no block); the owner or the contributor removes ---
    Policy(
        "proposal_contributors",
        "SELECT",
        f"{_DEV} AND (user_id = app_user_id() OR {_OWNED}"
        f" OR (removed_at IS NULL AND {_PROPOSAL.format(condition='')}))",
    ),
    Policy("proposal_contributors", "INSERT", check=CONTRIBUTOR_INSERT),
    Policy("proposal_contributors", "UPDATE", CONTRIBUTOR_REMOVE, CONTRIBUTOR_REMOVE),
)

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0010: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS; internal and trigger functions to nobody).
# SECURITY DEFINER functions run as bridge_owner, which bypasses RLS (ENABLED, not FORCED).
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- Whether a block stands between p_a and p_b, in either direction (D-58: a block hides both from each other
-- everywhere). Answered only when the caller is one of the two: NULL otherwise, so nobody learns whether two other
-- users blocked each other, and a policy's NOT of it refuses. The policies call it with the caller as one side.
-- SECURITY DEFINER: the blocked side does not read the block (developer_blocks is the blocker's own).
CREATE FUNCTION app_blocked_either_way(p_a uuid, p_b uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT CASE WHEN public.app_user_id() IN (p_a, p_b) THEN EXISTS (
        SELECT 1 FROM public.developer_blocks b
         WHERE (b.blocker_user_id = p_a AND b.blocked_user_id = p_b)
            OR (b.blocker_user_id = p_b AND b.blocked_user_id = p_a)) END
$$;

-- Whether a team may form on p_problem (D-58, the card's "a published problem or Brief"): it is published and clear,
-- and every signed-in user reads it: a developer's problem, or a Brief that is public and published (an invited Brief
-- is its invitees' and organisation's, so it never reaches another developer through an invitation; a closed Brief
-- takes no new team). SECURITY DEFINER: the same answer whoever asks; it says only what any signed-in user reads.
CREATE FUNCTION app_team_problem_open(p_problem uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM public.problems p
         WHERE p.id = p_problem AND p.status = 'published' AND p.moderation_state = 'clear'
           AND (p.org_id IS NULL OR EXISTS (SELECT 1 FROM public.problem_briefs b
                                             WHERE b.problem_id = p.id AND b.visibility = 'public'
                                               AND b.status = 'published')))
$$;

-- The pair's transaction-scoped advisory lock, the same whichever way round the two are named: an invitation's insert
-- and a block (either path) take it, so a block and an invitation between the same two never pass each other.
-- Internal (no EXECUTE grant): the triggers and definers below, as the owner.
CREATE FUNCTION team_pair_lock(p_a uuid, p_b uuid) RETURNS void
    LANGUAGE sql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(
        'team_pair:' || least(p_a, p_b)::text || ':' || greatest(p_a, p_b)::text, 0))
$$;

-- A block's consequences (D-58: a block ends everything): every pending invitation between the two is ended and every
-- open thread between them closed with the reason blocked, at the shared clock; returns how many rows changed.
-- Contributor credit already given stays (D-62). Internal (no EXECUTE grant): app_block_developer and the blocks'
-- AFTER INSERT trigger, as the owner, under the pair's lock.
CREATE FUNCTION team_end_pair(p_a uuid, p_b uuid) RETURNS integer
    LANGUAGE plpgsql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_ended integer;
    v_closed integer;
    v_now timestamptz := public.app_clock_now();
BEGIN
    UPDATE public.team_invitations i SET status = 'ended', decided_at = v_now
     WHERE i.status = 'pending' AND least(i.from_user_id, i.to_user_id) = least(p_a, p_b)
       AND greatest(i.from_user_id, i.to_user_id) = greatest(p_a, p_b);
    GET DIAGNOSTICS v_ended = ROW_COUNT;
    UPDATE public.team_threads t SET closed_at = v_now, closed_reason = 'blocked'
     WHERE t.closed_at IS NULL AND t.a_user_id = least(p_a, p_b) AND t.b_user_id = greatest(p_a, p_b);
    GET DIAGNOSTICS v_closed = ROW_COUNT;
    RETURN v_ended + v_closed;
END;
$$;

-- The peers of p_caller (D-58), unordered: nothing when p_caller is not an active, non-staff developer who opted in;
-- otherwise the other such developers of the same kind (real or demo: users.demo_account, as app_quiz_board) with no
-- block either way, who share a liked niche with p_caller or are in p_caller's county (a regions row of kind county,
-- never the country). Only the handle, headline, county (code and name), the shared liked niches' slugs (sorted),
-- whether the county is the caller's and the opt-in time. Internal (no EXECUTE grant): app_peers and
-- app_developer_card, as the owner.
CREATE FUNCTION team_peers_of(p_caller uuid)
    RETURNS TABLE (user_id uuid, handle citext, headline text, county_code text, county_name text,
                   shared_niches text[], same_county boolean, opted_in_at timestamptz)
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    WITH me AS (
        SELECT d.user_id, d.county_code, u.demo_account,
               coalesce((SELECT r.kind = 'county' FROM public.regions r WHERE r.code = d.county_code), false)
                   AS in_county
          FROM public.developer_profiles d JOIN public.users u ON u.id = d.user_id
         WHERE d.user_id = p_caller AND d.peers_visible AND u.status = 'active' AND u.staff_role IS NULL
    ), others AS (
        SELECT d.user_id, d.handle, d.headline::text AS headline, d.county_code::text AS county_code,
               r.name::text AS county_name,
               ARRAY(SELECT n.slug::text
                       FROM public.developer_niches mine
                       JOIN public.developer_niches theirs
                         ON theirs.niche_id = mine.niche_id AND theirs.kind = 'liked' AND theirs.user_id = d.user_id
                       JOIN public.niches n ON n.id = mine.niche_id
                      WHERE mine.user_id = me.user_id AND mine.kind = 'liked'
                      ORDER BY n.slug) AS shared,
               me.in_county AND d.county_code IS NOT DISTINCT FROM me.county_code AS same,
               d.peers_opted_in_at
          FROM me
          JOIN public.developer_profiles d ON d.user_id <> me.user_id AND d.peers_visible
          JOIN public.users u
            ON u.id = d.user_id AND u.status = 'active' AND u.staff_role IS NULL AND u.demo_account = me.demo_account
          LEFT JOIN public.regions r ON r.code = d.county_code
         WHERE NOT EXISTS (SELECT 1 FROM public.developer_blocks b
                            WHERE (b.blocker_user_id = me.user_id AND b.blocked_user_id = d.user_id)
                               OR (b.blocker_user_id = d.user_id AND b.blocked_user_id = me.user_id))
    )
    SELECT o.user_id, o.handle, o.headline, o.county_code, o.county_name, o.shared, o.same, o.peers_opted_in_at
      FROM others o
     WHERE cardinality(o.shared) > 0 OR o.same
$$;

-- Whether p_a and p_b are counterparts (REQ-DEV-03): the two parties of a team thread (an accepted invitation) or of a
-- pending invitation between them, either way round; a declined, withdrawn or ended invitation counts for nothing.
-- Internal (no EXECUTE grant): app_is_visible_peer and app_developer_card, as the owner.
CREATE FUNCTION team_counterparts(p_a uuid, p_b uuid) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (SELECT 1 FROM public.team_threads t
                    WHERE t.a_user_id = least(p_a, p_b) AND t.b_user_id = greatest(p_a, p_b))
        OR EXISTS (SELECT 1 FROM public.team_invitations i
                    WHERE i.status = 'pending' AND least(i.from_user_id, i.to_user_id) = least(p_a, p_b)
                      AND greatest(i.from_user_id, i.to_user_id) = greatest(p_a, p_b))
$$;

-- Whether p_user may be invited by the caller (D-58), answered only to a caller who is a developer (anyone else always
-- gets false, so an organisation-only account or an unbound session learns nothing): the caller themselves when they
-- opted in to peers; anyone else who opted in now and is either one of the caller's peers (team_peers_of: both opted
-- in, the same kind, the caller's county or a shared liked niche, no block either way) or a counterpart of the caller's
-- (team_counterparts: a team thread or a pending invitation between the two; a declined, withdrawn or ended invitation
-- counts for nothing) who is an active, non-staff developer, with no block either way. So a developer invites only
-- those the peers page shows them or those they team up with now, never anyone whose id they learned elsewhere, and
-- never anyone who turned the switch off. The invitations' INSERT policy and trigger, app_peers and the API call it.
-- SECURITY DEFINER: reads other developers' profiles, niches, invitations and threads.
CREATE FUNCTION app_is_visible_peer(p_user uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT public.app_is_developer() AND coalesce(CASE WHEN p_user = public.app_user_id() THEN
        EXISTS (SELECT 1 FROM public.developer_profiles d WHERE d.user_id = p_user AND d.peers_visible)
    ELSE
        EXISTS (SELECT 1 FROM public.team_peers_of(public.app_user_id()) p WHERE p.user_id = p_user)
        OR (EXISTS (SELECT 1 FROM public.developer_profiles d JOIN public.users u ON u.id = d.user_id
                     WHERE d.user_id = p_user AND d.peers_visible AND u.status = 'active' AND u.staff_role IS NULL)
            AND public.team_counterparts(public.app_user_id(), p_user)
            AND NOT EXISTS (SELECT 1 FROM public.developer_blocks b
                             WHERE (b.blocker_user_id = public.app_user_id() AND b.blocked_user_id = p_user)
                                OR (b.blocker_user_id = p_user AND b.blocked_user_id = public.app_user_id())))
    END, false)
$$;

-- A page of the caller's peers (D-58): the caller is a developer who opted in (anyone else, staff and organisation-
-- only accounts included, is refused); team_peers_of's set, ordered by the number of shared liked niches, then the
-- caller's county first, then the newest opt-in (ordered by, never returned), then handle (the profile embedding is
-- never computed in the prototype: its order replaces this one here when it is). At most 50 a page. SECURITY DEFINER:
-- reads other developers' profiles and niches, returns the card's fields only.
CREATE FUNCTION app_peers(p_limit integer, p_offset integer)
    RETURNS TABLE (user_id uuid, handle citext, headline text, county_code text, county_name text,
                   shared_niches text[], same_county boolean)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
BEGIN
    IF v_user IS NULL OR NOT public.app_is_visible_peer(v_user) THEN
        RAISE EXCEPTION 'app_peers: developers who opted in to peers only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 OR p_offset IS NULL OR p_offset < 0 THEN
        RAISE EXCEPTION 'app_peers: a limit of 1 to 50 and an offset of 0 or more'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT p.user_id, p.handle, p.headline, p.county_code, p.county_name, p.shared_niches, p.same_county
      FROM public.team_peers_of(v_user) p
     ORDER BY cardinality(p.shared_niches) DESC, p.same_county DESC, p.opted_in_at DESC, p.handle
     LIMIT p_limit OFFSET p_offset;
END;
$$;

-- Another developer's card for the caller (D-58): their handle and headline, never anything else, when the caller is a
-- developer, p_user is another user with a developer profile, no block stands between the two either way, and p_user
-- is a counterpart of the caller's (team_counterparts: a team thread or a pending invitation between the two, whatever
-- p_user's switch now says; a declined, withdrawn or ended invitation counts for nothing) or one of the caller's peers
-- (team_peers_of). No row otherwise. SECURITY DEFINER: reads the profile and the pair's rows.
CREATE FUNCTION app_developer_card(p_user uuid)
    RETURNS TABLE (user_id uuid, handle citext, headline text)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT d.user_id, d.handle, d.headline::text
      FROM public.developer_profiles d
     WHERE d.user_id = p_user AND p_user <> public.app_user_id() AND public.app_is_developer()
       AND NOT EXISTS (SELECT 1 FROM public.developer_blocks b
                        WHERE (b.blocker_user_id = public.app_user_id() AND b.blocked_user_id = p_user)
                           OR (b.blocker_user_id = p_user AND b.blocked_user_id = public.app_user_id()))
       AND (public.team_counterparts(public.app_user_id(), p_user)
            OR EXISTS (SELECT 1 FROM public.team_peers_of(public.app_user_id()) p WHERE p.user_id = p_user))
$$;

-- The caller's own blocks, newest first, with each blocked developer's handle (the blocker knew it; the blocked side
-- never reads a block). Developers only. SECURITY DEFINER: reads the blocked developers' handles.
CREATE FUNCTION app_blocked_developers()
    RETURNS TABLE (user_id uuid, handle citext, blocked_at timestamptz)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_developer() THEN
        RAISE EXCEPTION 'app_blocked_developers: developers only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN QUERY
    SELECT b.blocked_user_id, d.handle, b.created_at
      FROM public.developer_blocks b JOIN public.developer_profiles d ON d.user_id = b.blocked_user_id
     WHERE b.blocker_user_id = public.app_user_id()
     ORDER BY b.created_at DESC, d.handle;
END;
$$;

-- An invitation's one decision (REQ-DEV-03): accept or decline by the recipient, withdraw by the sender, a pending
-- invitation only, at the shared clock. A non-party, a caller who is not a developer and an unknown id get one refusal.
-- accept also needs the sender still an active, non-staff developer and the problem still open to teams
-- (app_team_problem_open), and creates the pair's thread on the invitation's problem; it returns the thread's id (NULL
-- for the other decisions). The parties never change (team_invitations_guard), so the caller is checked before the row
-- is locked; a block in flight (it ends the pending invitation under its own row lock) is waited for and its outcome
-- read. The app writes the audit event in the same transaction.
CREATE FUNCTION app_decide_team_invitation(p_invitation uuid, p_decision text) RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_from uuid;
    v_to uuid;
    v_status text;
    v_problem uuid;
    v_thread uuid;
    v_now timestamptz := public.app_clock_now();
BEGIN
    IF p_decision IS NULL OR p_decision NOT IN ('accept', 'decline', 'withdraw') THEN
        RAISE EXCEPTION 'app_decide_team_invitation: the decision is accept, decline or withdraw'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT i.from_user_id, i.to_user_id INTO v_from, v_to FROM public.team_invitations i WHERE i.id = p_invitation;
    IF NOT FOUND OR v_user IS NULL OR v_user NOT IN (v_from, v_to) OR NOT public.app_is_developer() THEN
        RAISE EXCEPTION 'app_decide_team_invitation: no invitation of the caller''s with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_decision = 'withdraw' AND v_user <> v_from THEN
        RAISE EXCEPTION 'app_decide_team_invitation: only the sender withdraws an invitation'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_decision <> 'withdraw' AND v_user <> v_to THEN
        RAISE EXCEPTION 'app_decide_team_invitation: only the recipient accepts or declines an invitation'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT i.status, i.problem_id INTO v_status, v_problem
      FROM public.team_invitations i WHERE i.id = p_invitation FOR UPDATE;
    IF v_status <> 'pending' THEN
        RAISE EXCEPTION 'app_decide_team_invitation: the invitation was already decided (%)', v_status
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF p_decision = 'accept' THEN
        IF NOT EXISTS (SELECT 1 FROM public.users u JOIN public.developer_profiles d ON d.user_id = u.id
                        WHERE u.id = v_from AND u.status = 'active' AND u.staff_role IS NULL) THEN
            RAISE EXCEPTION 'app_decide_team_invitation: the sender is no longer an active developer'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        IF NOT public.app_team_problem_open(v_problem) THEN
            RAISE EXCEPTION 'app_decide_team_invitation: the problem is no longer open to teams'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        UPDATE public.team_invitations SET status = 'accepted', decided_at = v_now WHERE id = p_invitation;
        v_thread := public.uuid7();
        INSERT INTO public.team_threads (id, invitation_id, a_user_id, b_user_id, problem_id)
        VALUES (v_thread, p_invitation, least(v_from, v_to), greatest(v_from, v_to), v_problem);
        RETURN v_thread;
    END IF;
    UPDATE public.team_invitations
       SET status = CASE p_decision WHEN 'decline' THEN 'declined' ELSE 'withdrawn' END, decided_at = v_now
     WHERE id = p_invitation;
    RETURN NULL;
END;
$$;

-- A party leaves a thread (REQ-DEV-03): an open thread of the caller's (a developer) is closed with the reason left,
-- at the shared clock, for both (a closed thread is read-only and never reopens); blocked is a block's reason, never a
-- caller's. A non-party, a caller who is not a developer and an unknown id get one refusal. Locks the thread FOR
-- UPDATE, so a message in flight (FOR SHARE) is waited for.
CREATE FUNCTION app_close_team_thread(p_thread uuid, p_reason text) RETURNS void
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_a uuid;
    v_b uuid;
    v_closed timestamptz;
BEGIN
    IF p_reason IS DISTINCT FROM 'left' THEN
        RAISE EXCEPTION 'app_close_team_thread: a party closes a thread with the reason left'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT t.a_user_id, t.b_user_id INTO v_a, v_b FROM public.team_threads t WHERE t.id = p_thread;
    IF NOT FOUND OR v_user IS NULL OR v_user NOT IN (v_a, v_b) OR NOT public.app_is_developer() THEN
        RAISE EXCEPTION 'app_close_team_thread: no thread of the caller''s with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT t.closed_at INTO v_closed FROM public.team_threads t WHERE t.id = p_thread FOR UPDATE;
    IF v_closed IS NOT NULL THEN
        RAISE EXCEPTION 'app_close_team_thread: the thread is already closed'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    UPDATE public.team_threads SET closed_at = public.app_clock_now(), closed_reason = 'left' WHERE id = p_thread;
END;
$$;

-- A developer blocks another developer (D-58), idempotently: under the pair's lock, every pending invitation between
-- the two is ended and every open thread closed (team_end_pair), then the block is inserted (a repeat inserts nothing;
-- the blocks' own triggers find nothing left to end). Returns how many rows changed: the block (0 or 1) plus the
-- invitations ended and threads closed. Contributor credit already given stays: proposal_contributors is untouched
-- (D-62 is about credit given, and the owner or the contributor may remove it). A caller who is not a developer is
-- refused, so is naming nobody or oneself. An unknown id or a user who is no developer (no developer profile, or staff)
-- changes nothing and returns 0, like a repeat: no error tells an unknown id from an existing account. The app writes
-- the audit event in the same transaction.
CREATE FUNCTION app_block_developer(p_blocked uuid) RETURNS integer
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_changed integer;
    v_inserted integer;
BEGIN
    IF v_user IS NULL OR NOT public.app_is_developer() THEN
        RAISE EXCEPTION 'app_block_developer: developers only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_blocked IS NULL OR p_blocked = v_user THEN
        RAISE EXCEPTION 'app_block_developer: name another developer' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.developer_profiles d JOIN public.users u ON u.id = d.user_id
                    WHERE d.user_id = p_blocked AND u.staff_role IS NULL) THEN
        RETURN 0;  -- nobody to block: an unknown id, staff, an organisation-only account
    END IF;
    PERFORM public.team_pair_lock(v_user, p_blocked);
    v_changed := public.team_end_pair(v_user, p_blocked);
    INSERT INTO public.developer_blocks (blocker_user_id, blocked_user_id) VALUES (v_user, p_blocked)
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    RETURN v_changed + v_inserted;
END;
$$;

-- A developer lifts their own block (D-58): deletes the row only; the threads it closed stay closed and the invitations
-- it ended stay ended. Returns how many rows were deleted (0 when there was no such block). SECURITY INVOKER: the
-- caller's own block, under the blocks' RLS (bridge_app's DELETE policy); a caller who is not a developer is refused.
CREATE FUNCTION app_unblock_developer(p_blocked uuid) RETURNS integer
    LANGUAGE plpgsql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_deleted integer;
BEGIN
    IF NOT public.app_is_developer() THEN
        RAISE EXCEPTION 'app_unblock_developer: developers only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    DELETE FROM public.developer_blocks b
     WHERE b.blocker_user_id = public.app_user_id() AND b.blocked_user_id = p_blocked;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$;

-- A party reports a team message (REQ-DEV-03; 0008's app_report_message for subject_type 'team_message'): files one
-- moderation case (source 'report', the caller as reporter_id) for a message of a thread the caller is a party of (a
-- developer; anyone else gets one refusal, the same as for a message that does not exist), once per reporter and
-- message (a repeat returns the same case with created false; uq_moderation_cases_team_message_report backs it). The
-- reasons are one or more of the fixed codes spam, abuse, contact_details, confidential, other (never free text; each
-- kept once, in code order; invalid_parameter_value otherwise). At most 10 team message reports per reporter in 24
-- hours, fixed here (program_limit_exceeded). Serialised per reporter (an advisory lock; the count then reads every
-- committed report at READ COMMITTED, the application's level). SECURITY DEFINER: reads the message and writes the case
-- whatever the caller's RLS (bridge_app's own INSERT of a team message report is refused).
CREATE FUNCTION app_report_team_message(p_message uuid, p_reasons text[])
    RETURNS TABLE (case_id uuid, created boolean)
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_case uuid;
BEGIN
    IF v_user IS NULL OR NOT public.app_is_developer() OR NOT EXISTS (
        SELECT 1 FROM public.team_messages m JOIN public.team_threads t ON t.id = m.thread_id
         WHERE m.id = p_message AND v_user IN (t.a_user_id, t.b_user_id)
    ) THEN
        RAISE EXCEPTION 'app_report_team_message: no team message of the caller''s with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_reasons IS NULL OR cardinality(p_reasons) = 0 OR array_ndims(p_reasons) <> 1
       OR array_position(p_reasons, NULL) IS NOT NULL
       OR NOT (p_reasons <@ ARRAY['spam', 'abuse', 'contact_details', 'confidential', 'other']) THEN
        RAISE EXCEPTION 'app_report_team_message: the reasons are one or more of spam, abuse, contact_details,'
            ' confidential, other' USING ERRCODE = 'invalid_parameter_value';
    END IF;
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended('moderation_cases:team_message_report:' || v_user::text, 0));
    SELECT c.id INTO v_case FROM public.moderation_cases c
     WHERE c.subject_type = 'team_message' AND c.source = 'report' AND c.subject_id = p_message
       AND c.reporter_id = v_user;
    IF FOUND THEN
        RETURN QUERY SELECT v_case, false;
        RETURN;
    END IF;
    IF (SELECT count(*) FROM public.moderation_cases c
         WHERE c.subject_type = 'team_message' AND c.source = 'report' AND c.reporter_id = v_user
           AND c.created_at > now() - interval '24 hours') >= 10 THEN
        RAISE EXCEPTION 'app_report_team_message: at most 10 team message reports a day'
            USING ERRCODE = 'program_limit_exceeded';
    END IF;
    v_case := public.uuid7();
    INSERT INTO public.moderation_cases (id, subject_type, subject_id, reasons, source, reporter_id)
    VALUES (v_case, 'team_message', p_message,
            ARRAY(SELECT r.code FROM unnest(ARRAY['spam', 'abuse', 'contact_details', 'confidential', 'other'])
                                     WITH ORDINALITY AS r(code, n)
                   WHERE r.code = ANY (p_reasons) ORDER BY r.n),
            'report', v_user);
    RETURN QUERY SELECT v_case, true;
END;
$$;

-- The one team message a report shared (REQ-DEV-03; 0008's app_reported_message): staff admin or moderator only, and
-- only the message of a team message report (every such case was filed by a party: app_report_team_message), with its
-- sender's id and handle (staff act on the sender) and nothing else of the thread; no row for any other case. Staff
-- read no team message otherwise. SECURITY DEFINER: reads the message whatever the caller's RLS.
CREATE FUNCTION app_reported_team_message(p_case uuid)
    RETURNS TABLE (message_id uuid, thread_id uuid, sender_user_id uuid, sender_handle citext, body text,
                   created_at timestamptz)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT public.app_is_staff('{admin,moderator}') THEN
        RAISE EXCEPTION 'app_reported_team_message: staff admin or moderator only'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN QUERY
    SELECT m.id, m.thread_id, m.sender_user_id, d.handle, m.body, m.created_at
      FROM public.moderation_cases c
      JOIN public.team_messages m ON m.id = c.subject_id
      LEFT JOIN public.developer_profiles d ON d.user_id = m.sender_user_id
     WHERE c.id = p_case AND c.subject_type = 'team_message' AND c.source = 'report';
END;
$$;

-- A proposal's credit (D-62 (a), "Contributors: <handles>"): the handles of its contributors who were not removed, by
-- the time they were added, for a caller who may read the proposal: its owner, any signed-in user while it is published
-- and clear, staff admin or moderator (the proposals' SELECT policy of revision 0002, restated: keep the two the same).
-- NULL for anyone else (an empty array when there is no contributor). Read at render time; never part of the manifest
-- or its hash. SECURITY DEFINER: reads the contributors and their handles whatever the caller's RLS.
CREATE FUNCTION app_contributor_handles(p_proposal uuid) RETURNS text[]
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM public.proposals p
         WHERE p.id = p_proposal
           AND (p.owner_id = public.app_user_id()
                OR (public.app_user_id() IS NOT NULL AND p.status = 'published' AND p.moderation_state = 'clear')
                OR public.app_is_staff('{admin,moderator}')))
    THEN ARRAY(SELECT d.handle::text
                 FROM public.proposal_contributors c JOIN public.developer_profiles d ON d.user_id = c.user_id
                WHERE c.proposal_id = p_proposal AND c.removed_at IS NULL
                ORDER BY c.added_at, d.handle) END
$$;

-- A profile's opt-in time is the database's (D-58: the newest opt-in comes first among equals): the shared clock when
-- peers_visible turns true (on insert or update), kept while it stays true, NULL while it is false, whatever was sent.
-- For every role. SECURITY INVOKER (the clock is every writer's).
CREATE FUNCTION developer_profiles_peers_opt_in() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NOT NEW.peers_visible THEN
        NEW.peers_opted_in_at := NULL;
    ELSIF TG_OP = 'INSERT' OR NOT OLD.peers_visible THEN
        NEW.peers_opted_in_at := public.app_clock_now();
    ELSE
        NEW.peers_opted_in_at := OLD.peers_opted_in_at;
    END IF;
    RETURN NEW;
END;
$$;

-- A block ends everything between the two in its own transaction, however it is inserted (app_block_developer, the
-- only path bridge_app has, or the owner's seed): BEFORE INSERT (developer_blocks_0_lock) takes the pair's lock before
-- the row exists (so two inserts of the same pair wait for each other instead of deadlocking on the key), AFTER INSERT
-- (developer_blocks_end_pair) ends the pair's pending invitations and closes its open threads (team_end_pair). For
-- every role. SECURITY DEFINER: callable whoever inserts.
CREATE FUNCTION developer_blocks_pair() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    PERFORM public.team_pair_lock(NEW.blocker_user_id, NEW.blocked_user_id);
    IF TG_WHEN = 'AFTER' THEN
        PERFORM public.team_end_pair(NEW.blocker_user_id, NEW.blocked_user_id);
        RETURN NULL;
    END IF;
    RETURN NEW;
END;
$$;

-- The sender's precise refusals of their own invitation (the API's 404 and 403), ahead of the INSERT policy's generic
-- one: only when the row is the caller's own (from_user_id = app.user_id) and the caller opted in to peers; anything
-- else passes to the policy, which refuses it, so nothing is said here about anyone else's pair, opt-in or problem.
-- Then: the problem is open to teams; and, under the pair's lock, read afresh (a block in flight is waited for), the
-- recipient may be invited by the sender (app_is_visible_peer: opted in, a peer or a counterpart, no block either
-- way). A blocked recipient hears the same refusal as any other one who may not be invited: nothing tells the sender
-- that a block stands. SECURITY DEFINER: reads the pair's rows.
CREATE FUNCTION team_invitations_open() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.from_user_id IS DISTINCT FROM public.app_user_id() OR NOT public.app_is_visible_peer(NEW.from_user_id) THEN
        RETURN NEW;
    END IF;
    IF NOT public.app_team_problem_open(NEW.problem_id) THEN
        RAISE EXCEPTION 'team_invitations: no published problem with that id' USING ERRCODE = 'no_data_found';
    END IF;
    PERFORM public.team_pair_lock(NEW.from_user_id, NEW.to_user_id);
    IF NOT public.app_is_visible_peer(NEW.to_user_id) THEN
        RAISE EXCEPTION 'team_invitations: the recipient is neither a peer nor a counterpart of the sender'
            USING ERRCODE = 'no_data_found';
    END IF;
    RETURN NEW;
END;
$$;

-- An invitation's parties, problem, note and creation time never change; it changes once, by its decision, from pending
-- to accepted, declined, withdrawn or ended (decided_at with it: CHECK decision_complete). For every role (bridge_app
-- holds no UPDATE: app_decide_team_invitation and a block). SECURITY INVOKER (the writer is the owner).
CREATE FUNCTION team_invitations_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.id, NEW.from_user_id, NEW.to_user_id, NEW.problem_id, NEW.note, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.from_user_id, OLD.to_user_id, OLD.problem_id, OLD.note, OLD.created_at) THEN
        RAISE EXCEPTION 'team_invitations: an invitation''s parties, problem, note and creation time never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'pending' OR NEW.status = 'pending' THEN
        RAISE EXCEPTION 'team_invitations: an invitation changes only by its one decision, from pending'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    RETURN NEW;
END;
$$;

-- A thread's parties, problem, invitation and creation time never change; it changes once, when it closes (left or
-- blocked, with closed_at: CHECK close_complete), and a closed thread never changes again (it never reopens). For every
-- role (bridge_app holds no UPDATE). SECURITY INVOKER (the writer is the owner).
CREATE FUNCTION team_threads_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.id, NEW.invitation_id, NEW.a_user_id, NEW.b_user_id, NEW.problem_id, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.invitation_id, OLD.a_user_id, OLD.b_user_id, OLD.problem_id, OLD.created_at) THEN
        RAISE EXCEPTION 'team_threads: a thread''s parties, problem, invitation and creation time never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.closed_at IS NOT NULL THEN
        RAISE EXCEPTION 'team_threads: a closed thread never changes and never reopens'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    RETURN NEW;
END;
$$;

-- Runs first on a team message's insert (team_messages_0_visible sorts before team_messages_1_open): the message names
-- a thread the caller reads (a party who is a developer), else one refusal, the same for a thread that does not exist,
-- so the definer trigger after it reads, locks and reports nothing about another pair's thread. SECURITY INVOKER: the
-- caller's RLS decides; the owner sees every thread.
CREATE FUNCTION team_thread_visible() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.thread_id IS NULL OR NOT EXISTS (SELECT 1 FROM public.team_threads t WHERE t.id = NEW.thread_id) THEN
        RAISE EXCEPTION 'team_messages: no thread of the caller''s with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

-- A message is written only by a party of its thread and only while the thread is open (read-only once closed, by a
-- party leaving or by a block). Reads the thread FOR SHARE: a close or a block in flight (they update the thread) is
-- waited for and its outcome read, so no message is written once the close has committed; concurrent messages do not
-- wait for each other. For every role. SECURITY DEFINER: locks a row bridge_app may not update.
CREATE FUNCTION team_messages_open() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_a uuid;
    v_b uuid;
    v_closed timestamptz;
BEGIN
    SELECT t.a_user_id, t.b_user_id, t.closed_at INTO v_a, v_b, v_closed
      FROM public.team_threads t WHERE t.id = NEW.thread_id FOR SHARE;
    IF NEW.sender_user_id IS DISTINCT FROM v_a AND NEW.sender_user_id IS DISTINCT FROM v_b THEN
        RAISE EXCEPTION 'team_messages: the sender is a party of the thread' USING ERRCODE = 'check_violation';
    END IF;
    IF v_closed IS NOT NULL THEN
        RAISE EXCEPTION 'team_messages: the thread is closed; it is read-only'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    RETURN NEW;
END;
$$;

-- D-54 (default (a)), as engagement_messages_redaction_guard (revision 0008): a team message changes only by its
-- redaction, once: its body becomes '[redacted]' with redacted_at and redacted_by set in the same statement, and
-- nothing else changes; only the table's owner or a SECURITY DEFINER function it owns (none exists yet) may do it;
-- bridge_app holds no UPDATE. DELETE and TRUNCATE stay refused for every role (block_mutation()). SECURITY INVOKER, so
-- current_user is the writer.
CREATE FUNCTION team_messages_redaction_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF current_user <> (SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID)
       OR OLD.redacted_at IS NOT NULL OR NEW.body IS DISTINCT FROM '[redacted]'
       OR NEW.redacted_at IS NULL OR NEW.redacted_by IS NULL
       OR (NEW.id, NEW.thread_id, NEW.sender_user_id, NEW.created_at)
          IS DISTINCT FROM (OLD.id, OLD.thread_id, OLD.sender_user_id, OLD.created_at) THEN
        RAISE EXCEPTION 'team_messages: a message changes only by its redaction, once, by the owner (D-54)'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

-- A contributor's proposal, user, thread and time added never change; removed_at is set once, at the shared clock
-- (whatever was sent), and a removed contributor stays removed (never listed again; never added back: the primary
-- key). For every role (bridge_app's UPDATE is of removed_at, by the owner or the contributor). SECURITY INVOKER.
CREATE FUNCTION proposal_contributors_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.proposal_id, NEW.user_id, NEW.thread_id, NEW.added_at)
       IS DISTINCT FROM (OLD.proposal_id, OLD.user_id, OLD.thread_id, OLD.added_at) THEN
        RAISE EXCEPTION 'proposal_contributors: a contributor''s proposal, user, thread and time added never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.removed_at IS NOT NULL THEN
        RAISE EXCEPTION 'proposal_contributors: a removed contributor stays removed'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF NEW.removed_at IS NOT NULL THEN
        NEW.removed_at := public.app_clock_now();
    END IF;
    RETURN NEW;
END;
$$;
"""

# EXECUTE grants (EXECUTE revoked from PUBLIC first): a policy runs its functions with the caller's privileges.
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_is_visible_peer(uuid)": ("bridge_app",),  # the invitations' policy and trigger, the API
    "app_blocked_either_way(uuid, uuid)": ("bridge_app",),  # the invitations' and messages' INSERT policies
    "app_team_problem_open(uuid)": ("bridge_app",),  # the invitations' INSERT policy, the API
    "app_peers(integer, integer)": ("bridge_app",),  # a developer who opted in
    "app_developer_card(uuid)": ("bridge_app",),  # a developer: a counterpart's or a peer's handle and headline
    "app_blocked_developers()": ("bridge_app",),  # a developer: their own blocks
    "app_decide_team_invitation(uuid, text)": ("bridge_app",),  # the recipient or the sender
    "app_close_team_thread(uuid, text)": ("bridge_app",),  # a party
    "app_block_developer(uuid)": ("bridge_app",),  # a developer
    "app_unblock_developer(uuid)": ("bridge_app",),  # a developer (INVOKER)
    "app_report_team_message(uuid, text[])": ("bridge_app",),  # a party's report of one team message
    "app_reported_team_message(uuid)": ("bridge_app",),  # staff admin|moderator read the reported team message
    "app_contributor_handles(uuid)": ("bridge_app",),  # anyone who reads the proposal
}
INTERNAL_FUNCTIONS = (
    "team_pair_lock(uuid, uuid)",
    "team_end_pair(uuid, uuid)",
    "team_peers_of(uuid)",
    "team_counterparts(uuid, uuid)",
)
TRIGGER_FUNCTIONS = (
    "developer_profiles_peers_opt_in()",
    "developer_blocks_pair()",
    "team_invitations_open()",
    "team_invitations_guard()",
    "team_threads_guard()",
    "team_thread_visible()",
    "team_messages_open()",
    "team_messages_redaction_guard()",
    "proposal_contributors_guard()",
)

TRIGGERS_SQL = r"""
CREATE TRIGGER developer_profiles_peers_opt_in
    BEFORE INSERT OR UPDATE ON developer_profiles
    FOR EACH ROW EXECUTE FUNCTION developer_profiles_peers_opt_in();
CREATE TRIGGER developer_blocks_0_lock
    BEFORE INSERT ON developer_blocks
    FOR EACH ROW EXECUTE FUNCTION developer_blocks_pair();
CREATE TRIGGER developer_blocks_end_pair
    AFTER INSERT ON developer_blocks
    FOR EACH ROW EXECUTE FUNCTION developer_blocks_pair();
CREATE TRIGGER team_invitations_open
    BEFORE INSERT ON team_invitations
    FOR EACH ROW EXECUTE FUNCTION team_invitations_open();
CREATE TRIGGER team_invitations_guard
    BEFORE UPDATE ON team_invitations
    FOR EACH ROW EXECUTE FUNCTION team_invitations_guard();
CREATE TRIGGER team_threads_guard
    BEFORE UPDATE ON team_threads
    FOR EACH ROW EXECUTE FUNCTION team_threads_guard();
CREATE TRIGGER team_messages_0_visible
    BEFORE INSERT ON team_messages
    FOR EACH ROW EXECUTE FUNCTION team_thread_visible();
CREATE TRIGGER team_messages_1_open
    BEFORE INSERT ON team_messages
    FOR EACH ROW EXECUTE FUNCTION team_messages_open();
CREATE TRIGGER team_messages_no_delete
    BEFORE DELETE ON team_messages
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
CREATE TRIGGER team_messages_redaction_guard
    BEFORE UPDATE ON team_messages
    FOR EACH ROW EXECUTE FUNCTION team_messages_redaction_guard();
CREATE TRIGGER team_messages_no_truncate
    BEFORE TRUNCATE ON team_messages
    FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();
CREATE TRIGGER proposal_contributors_guard
    BEFORE UPDATE ON proposal_contributors
    FOR EACH ROW EXECUTE FUNCTION proposal_contributors_guard();
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
    grants.append(PROFILE_GRANT)
    grants += [
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in (*INTERNAL_FUNCTIONS, *TRIGGER_FUNCTIONS)
    ]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    _add_profile_columns()
    _create_tables()
    _run_sql(FUNCTIONS_SQL)  # before the policies: they call app_is_visible_peer and the others
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(f"ALTER POLICY bridge_app_insert ON moderation_cases WITH CHECK ({REPORTS_INSERT});")
    op.create_index(
        "uq_moderation_cases_team_message_report",
        "moderation_cases",
        ["subject_id", "reporter_id"],
        unique=True,
        postgresql_where=sa.text(TEAM_MESSAGE_REPORT),
    )
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Destructive: drops the developers' blocks, team-up invitations, team threads with their messages and read
    markers, the proposals' contributor credit, and every developer's peers opt-in (``peers_visible`` and its time).
    Under the CLAUDE.md stop rule a downgrade of a database holding any of them is a destructive migration: back the
    database up and get the human's decision first. The downgrade refuses while any of the tables has rows or any
    profile is opted in, unless it is run with ``-x allow_teams_loss=true`` (``alembic -x allow_teams_loss=true
    downgrade 0010``). Team message reports already filed stay in ``moderation_cases`` (their subjects gone)."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_teams_loss") == "true"
    bind = op.get_bind()
    holding = [
        table for table in NEW_TABLES if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
    ]
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM developer_profiles WHERE peers_visible)")).scalar():
        holding.append("developer_profiles (peers opt-ins)")
    if holding and not allowed:
        raise RuntimeError(
            f"revision 0011 downgrade: {', '.join(holding)} hold the developers' blocks, team-ups, team threads,"
            " contributor credit or peers opt-ins; back the database up, get the human's decision (CLAUDE.md:"
            " destructive migration), then run with -x allow_teams_loss=true"
        )
    # Revision 0008's report policy as it was (first: nothing depends on it), and no team message report index.
    _run_sql(f"ALTER POLICY bridge_app_insert ON moderation_cases WITH CHECK ({REPORTS_INSERT_0008});")
    op.drop_index("uq_moderation_cases_team_message_report", table_name="moderation_cases")
    # Dropping a table drops its policies, triggers, indexes and grants (block_mutation(), app_clock_now() and
    # app_is_developer() are revisions 0002, 0003 and 0009's and stay); the policies go with their tables before the
    # functions they call. Dropping a column drops its grant.
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    _run_sql("DROP TRIGGER developer_profiles_peers_opt_in ON developer_profiles;")
    op.drop_constraint(op.f("ck_developer_profiles_peers_opt_in_complete"), "developer_profiles", type_="check")
    op.drop_column("developer_profiles", "peers_opted_in_at")
    op.drop_column("developer_profiles", "peers_visible")
    _run_sql(
        "\n".join(
            f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS, *INTERNAL_FUNCTIONS)
        )
    )


def _add_profile_columns() -> None:
    op.add_column(
        "developer_profiles", sa.Column("peers_visible", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column("developer_profiles", sa.Column("peers_opted_in_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_developer_profiles_peers_opt_in_complete"), "developer_profiles", PEERS_OPT_IN_COMPLETE
    )


def _create_tables() -> None:
    op.create_table(
        "developer_blocks",
        sa.Column("blocker_user_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.CheckConstraint("blocker_user_id <> blocked_user_id", name=op.f("ck_developer_blocks_not_self")),
        sa.ForeignKeyConstraint(
            ["blocked_user_id"],
            ["users.id"],
            name=op.f("fk_developer_blocks_blocked_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blocker_user_id"],
            ["users.id"],
            name=op.f("fk_developer_blocks_blocker_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("blocker_user_id", "blocked_user_id", name=op.f("pk_developer_blocks")),
    )
    op.create_index(op.f("ix_developer_blocks_blocked_user_id"), "developer_blocks", ["blocked_user_id"], unique=False)
    op.create_table(
        "team_invitations",
        sa.Column("from_user_id", sa.Uuid(), nullable=False),
        sa.Column("to_user_id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("from_user_id <> to_user_id", name=op.f("ck_team_invitations_not_self")),
        sa.CheckConstraint(_in("status", INVITATION_STATUSES), name=op.f("ck_team_invitations_status_known")),
        sa.CheckConstraint(NOTE_VALID, name=op.f("ck_team_invitations_note_valid")),
        sa.CheckConstraint(
            "(status = 'pending') = (decided_at IS NULL)", name=op.f("ck_team_invitations_decision_complete")
        ),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"], name=op.f("fk_team_invitations_from_user_id_users")),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], name=op.f("fk_team_invitations_problem_id_problems")),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"], name=op.f("fk_team_invitations_to_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_invitations")),
    )
    op.create_index(op.f("ix_team_invitations_from_user_id"), "team_invitations", ["from_user_id"], unique=False)
    op.create_index(op.f("ix_team_invitations_to_user_id"), "team_invitations", ["to_user_id"], unique=False)
    op.create_index(
        "uq_team_invitations_pending_pair",
        "team_invitations",
        [sa.text("LEAST(from_user_id, to_user_id)"), sa.text("GREATEST(from_user_id, to_user_id)"), "problem_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "team_threads",
        sa.Column("invitation_id", sa.Uuid(), nullable=False),
        sa.Column("a_user_id", sa.Uuid(), nullable=False),
        sa.Column("b_user_id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_reason", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("a_user_id < b_user_id", name=op.f("ck_team_threads_pair_ordered")),
        sa.CheckConstraint(_in("closed_reason", CLOSE_REASONS), name=op.f("ck_team_threads_closed_reason_known")),
        sa.CheckConstraint(
            "(closed_at IS NULL) = (closed_reason IS NULL)", name=op.f("ck_team_threads_close_complete")
        ),
        sa.ForeignKeyConstraint(["a_user_id"], ["users.id"], name=op.f("fk_team_threads_a_user_id_users")),
        sa.ForeignKeyConstraint(["b_user_id"], ["users.id"], name=op.f("fk_team_threads_b_user_id_users")),
        sa.ForeignKeyConstraint(
            ["invitation_id"], ["team_invitations.id"], name=op.f("fk_team_threads_invitation_id_team_invitations")
        ),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"], name=op.f("fk_team_threads_problem_id_problems")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_threads")),
        sa.UniqueConstraint("invitation_id", name=op.f("uq_team_threads_invitation_id")),
    )
    op.create_index("ix_team_threads_pair", "team_threads", ["a_user_id", "b_user_id"], unique=False)
    op.create_index(op.f("ix_team_threads_b_user_id"), "team_threads", ["b_user_id"], unique=False)
    op.create_table(
        "team_messages",
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("sender_user_id", sa.Uuid(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redacted_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(MESSAGE_BODY, name=op.f("ck_team_messages_body_length")),
        sa.CheckConstraint(
            f"(redacted_at IS NOT NULL) = (body = {REDACTED}) AND (redacted_at IS NULL) = (redacted_by IS NULL)",
            name=op.f("ck_team_messages_redaction_complete"),
        ),
        sa.ForeignKeyConstraint(["redacted_by"], ["users.id"], name=op.f("fk_team_messages_redacted_by_users")),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], name=op.f("fk_team_messages_sender_user_id_users")),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["team_threads.id"], name=op.f("fk_team_messages_thread_id_team_threads")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_team_messages")),
    )
    op.create_index("ix_team_messages_thread", "team_messages", ["thread_id", "created_at", "id"], unique=False)
    op.create_table(
        "team_thread_reads",
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "last_read_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["team_threads.id"], name=op.f("fk_team_thread_reads_thread_id_team_threads")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_team_thread_reads_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("thread_id", "user_id", name=op.f("pk_team_thread_reads")),
    )
    op.create_index(op.f("ix_team_thread_reads_user_id"), "team_thread_reads", ["user_id"], unique=False)
    op.create_table(
        "proposal_contributors",
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "removed_at IS NULL OR removed_at >= added_at", name=op.f("ck_proposal_contributors_removed_after_added")
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["proposals.id"],
            name=op.f("fk_proposal_contributors_proposal_id_proposals"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id"], ["team_threads.id"], name=op.f("fk_proposal_contributors_thread_id_team_threads")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_proposal_contributors_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("proposal_id", "user_id", name=op.f("pk_proposal_contributors")),
    )
    op.create_index(op.f("ix_proposal_contributors_user_id"), "proposal_contributors", ["user_id"], unique=False)
