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

A "developer" is ``app_is_developer()`` (revision 0009): an active user with a developer profile and no staff role. A
"visible peer" is ``app_is_visible_peer(user)``: a developer whose profile has ``peers_visible`` (answered only to a
caller who is a developer). Organisation-only accounts and staff read nothing of the new tables (every policy needs
``app_is_developer()``); staff read one reported team message through ``app_reported_team_message`` only.

- ``developer_profiles`` (revision 0001): ``peers_visible`` (default false; bridge_app UPDATE, own row by 0001's
  policy, as ``headline``) and ``peers_opted_in_at``, the database's (``developer_profiles_peers_opt_in``, BEFORE
  INSERT OR UPDATE, every role): the shared clock when the flag turns true, kept while it stays true, NULL when false,
  whatever was sent (CHECK ``peers_opt_in_complete``). Nothing else of a profile reaches another developer but through
  the definers below (D-58: handle, headline, county and shared liked niches only).
- ``developer_blocks`` (USER; bridge_app: SELECT, INSERT of the two ids, DELETE): the blocker's own rows, written and
  read by a developer as the blocker (``blocker_user_id = app_user_id()``); never another's (the blocked side learns of
  a block only through ``app_blocked_either_way``, and only for a pair it is in). PK (blocker, blocked); CHECK not
  self. A block ends everything between the two in its own transaction, by whichever path it is inserted
  (``app_block_developer`` or a direct INSERT): ``developer_blocks_0_lock`` (BEFORE INSERT) takes the pair's advisory
  lock and ``developer_blocks_end_pair`` (AFTER INSERT) ends every pending invitation between them (``ended``) and
  closes every open thread (``blocked``); contributor credit already given stays (D-62). Unblocking deletes the row
  only: threads stay closed, ended invitations ended.
- ``team_invitations`` (USER; bridge_app: SELECT, INSERT of ``id``, ``from_user_id``, ``to_user_id``,
  ``problem_id``, ``note``): read by its two parties (developers). Sent by a visible peer as themselves to another
  visible peer on a problem every signed-in user reads that is published and clear (``app_team_problem_open``: a
  developer's problem, or a public published Brief; an invited or closed Brief is not), with no block either way; a
  note of 1 to 300 characters (line breaks allowed, no other control character) or none. The contact-details rule does
  not apply between developers (the API's). One pending invitation per pair and problem, in either direction: the
  partial unique index ``uq_team_invitations_pending_pair`` on (LEAST, GREATEST of the two, problem) WHERE pending.
  ``team_invitations_open`` (BEFORE INSERT, SECURITY DEFINER) answers the sender of their own invitation, when they
  are a visible peer, with a precise refusal before the policy's generic one: the recipient is not a visible peer
  (no_data_found), the problem is not open to teams (no_data_found), a block stands between them
  (insufficient_privilege, read under the pair's lock so a block in flight is waited for); it says nothing to anyone
  else. ``status`` moves once, from ``pending`` to ``accepted``, ``declined`` or ``withdrawn``
  (``app_decide_team_invitation``) or ``ended`` (a block), with ``decided_at``; ``team_invitations_guard`` (every
  role): its parties, problem, note and creation time never change, a decided invitation never changes.
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
  never themselves); the owner removes a contributor, or a contributor removes themselves, by setting ``removed_at``
  (the database's clock, ``proposal_contributors_guard``), once and for good: a removed contributor is never listed
  again and cannot be added back (the primary key). Read directly by a developer who reads the proposal (the proposals'
  own SELECT policy, through the subquery) and by the contributor; organisations and staff read the credit only as
  handles, through ``app_contributor_handles(proposal)``. Never part of the manifest or its hash.

Indexes: ``pk_developer_blocks`` (blocker, blocked) and ``ix_developer_blocks_blocked_user_id`` (blocks either way);
``uq_team_invitations_pending_pair`` (it also serves a block's ending of the pair's pending invitations),
``ix_team_invitations_from_user_id`` and ``_to_user_id`` (sent and received); ``ix_team_threads_pair`` (a, b) and
``ix_team_threads_b_user_id`` (a developer's threads), ``uq_team_threads_invitation_id``; ``ix_team_messages_thread``;
``pk_team_thread_reads`` and ``ix_team_thread_reads_user_id``; ``pk_proposal_contributors`` (proposal, user) and
``ix_proposal_contributors_user_id``; ``uq_moderation_cases_team_message_report`` (one report per reporter and team
message).

Functions (SECURITY DEFINER unless noted; pinned search_path; EXECUTE revoked from PUBLIC; granted to bridge_app where
listed in ``FUNCTION_GRANTS``; each refuses with a message naming itself):

- ``app_is_visible_peer(user)`` -> boolean: ``user`` is an active, non-staff developer with ``peers_visible``; false to
  a caller who is not a developer. ``app_blocked_either_way(a, b)`` -> boolean: a block stands between ``a`` and ``b``
  either way; NULL unless the caller is ``a`` or ``b``. ``app_team_problem_open(problem)`` -> boolean: published,
  clear and readable by every signed-in user (see ``team_invitations``).
- ``app_peers(limit, offset)`` -> (user_id, handle, headline, county_code, county_name, shared_niches, same_county,
  opted_in_at): a visible peer only (insufficient_privilege otherwise: not opted in, staff, organisation-only,
  unbound); a limit of 1 to 50 and an offset of 0 or more (invalid_parameter_value). The other visible peers of the
  caller's kind (real accounts for a real caller, demo accounts for a demo caller, as ``app_quiz_board``) with no
  block either way, who share a liked niche with the caller or are in the caller's county (a ``regions`` row of kind
  county, never the country); ``shared_niches`` the shared liked niches' slugs, sorted; ordered by the number of shared
  niches, then same county first, then the newest opt-in, then handle (the profile embedding is never computed in the
  prototype; its order replaces this one behind the same function when it is). Nothing else of a profile.
- ``app_developer_card(user)`` -> (user_id, handle, headline): one row when the caller is a developer, ``user`` is
  another developer, no block stands between them either way, and ``user`` is the other party of an invitation of the
  caller's (any status: every thread comes from one) or one of the caller's peers (``app_peers``' rule); no row
  otherwise. ``app_blocked_developers()`` -> (user_id, handle, blocked_at): the caller's own blocks with the blocked
  developers' handles, newest first (developers only).
- ``app_decide_team_invitation(invitation, decision)`` -> the new thread's id for ``accept``, NULL otherwise:
  ``accept`` or ``decline`` by the recipient, ``withdraw`` by the sender (invalid_parameter_value for another word;
  insufficient_privilege for the wrong party, and "no invitation of the caller's" for a non-party, a non-developer and
  an unknown id alike); a pending invitation only (object_not_in_prerequisite_state). ``accept`` also needs the sender
  still an active, non-staff developer and the problem still open to teams, and creates the thread.
- ``app_close_team_thread(thread, reason)``: a party (developer) closes an open thread with ``left`` (the only reason
  it takes; ``blocked`` is a block's). ``app_block_developer(blocked)`` -> rows changed (the block inserted, 0 or 1,
  plus invitations ended and threads closed): developers only, another user with a developer profile (no_data_found
  otherwise); idempotent. ``app_unblock_developer(blocked)`` -> rows deleted (SECURITY INVOKER: the caller's own
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
  ``team_end_pair(a, b)`` (ends the pair's pending invitations and closes its open threads; returns the count) and
  ``team_peers_of(caller)`` (the peer set, unordered).

Lock order: the pair's advisory lock first (an invitation's insert, a block by either path), then rows: an invitation
FOR UPDATE (a decision; a block's ending), a thread FOR UPDATE (a close; a block's closing) or FOR SHARE (a message).

Operating rules for the code that uses this schema:

- Peers: ``SELECT * FROM app_peers(:limit, :offset)`` for a visible peer (check ``app_is_visible_peer(app_user_id())``
  first and answer an empty page to a developer who is not opted in); the switch is an UPDATE of ``peers_visible`` on
  the caller's own profile (read ``peers_opted_in_at`` back: it is the database's).
- Invite: INSERT the invitation as the sender leaving ``status``, ``created_at`` and ``decided_at`` out (read them
  back). Map ``team_invitations_open``'s refusals: "the recipient is not a developer who opted in to peers" (404),
  "no published problem with that id" (404), "a block stands between the two developers" (403); a unique violation on
  ``uq_team_invitations_pending_pair`` (409); any other row-level security refusal (404). Decisions only through
  ``app_decide_team_invitation`` (insufficient_privilege "no invitation of the caller's" is 404, the wrong party 403,
  object_not_in_prerequisite_state 409).
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


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def upgrade() -> None:
    _add_profile_columns()
    _create_tables()


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
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    op.drop_constraint(op.f("ck_developer_profiles_peers_opt_in_complete"), "developer_profiles", type_="check")
    op.drop_column("developer_profiles", "peers_opted_in_at")
    op.drop_column("developer_profiles", "peers_visible")


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
