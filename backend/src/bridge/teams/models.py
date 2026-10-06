"""Peers and team-up: the tables of revision 0011 (P22 track C, REQ-DEV-03, D-58, D-62).

Rules the database enforces (revision 0011; the 60-an-hour message limit, the daily invitation limit, the note's and
message's normalisation and every notice are the application's). A "developer" is ``app_is_developer()``: an active user
with a developer profile and no staff role; a "visible peer" of the caller (``app_is_visible_peer``) is the caller when
they opted in (``peers_visible``), one of their peers (opted in, same county or a shared liked niche, no block) or an
existing counterpart of theirs (an invitation in any state) with no block. Organisation-only accounts and staff read
none of these tables (every policy needs a developer); staff read one reported team message through
``app_reported_team_message`` only.

- ``developer_blocks`` (USER): the blocker's own rows (read, inserted, deleted by the blocker). A block ends every
  pending invitation between the two (``ended``) and closes every open thread (``blocked``) in its own transaction, by
  either path (``app_block_developer`` or a direct INSERT); unblocking (``app_unblock_developer``) deletes the row only.
  A block hides both from each other in ``app_peers`` and ``app_developer_card`` and refuses invitations and messages
  between them; contributor credit already given stays.
- ``team_invitations`` (USER): read by its two parties; inserted by a developer who opted in, as the sender, to one of
  their visible peers (a peer or an existing counterpart), on a problem open to teams (``app_team_problem_open``:
  published, clear, a developer's or a public published Brief), with no block either way and a note of 1 to 300
  characters or none; one pending invitation per pair and problem in either direction
  (``uq_team_invitations_pending_pair``). ``status``, ``created_at`` and ``decided_at`` are the database's: the status
  moves once, from ``pending``, only through ``app_decide_team_invitation`` (accept or decline by the recipient,
  withdraw by the sender) or a block (``ended``); nothing else of it ever changes.
- ``team_threads`` (USER): one per accepted invitation, between its canonical pair (``a_user_id < b_user_id``), read by
  the two; written only by ``app_decide_team_invitation`` (accept), ``app_close_team_thread`` (``left``) and a block
  (``blocked``); a closed thread never reopens.
- ``team_messages`` (USER, through the thread): the thread's parties read every message; a party posts as themselves
  while the thread is open (``sender_user_id`` the caller; ``created_at`` the database's). Append-only but for the
  owner's redaction (D-54, none exists yet). Reported only through ``app_report_team_message`` (the message report
  reasons, once per reporter and message, 10 a day).
- ``team_thread_reads`` (USER): a party's own read marker (upsert ``last_read_at``).
- ``proposal_contributors`` (USER, through the proposal): D-62 (a). The proposal's owner adds the other party of one of
  their team threads, naming it; the owner or the contributor removes the credit by setting ``removed_at`` (the
  database's time; once, for good). Developers who read the proposal read the rows; everyone who reads the proposal
  gets the handles through ``app_contributor_handles(proposal)``. Never part of the manifest or its hash.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, IdMixin, Tenancy

INVITATION_STATUSES = ("pending", "accepted", "declined", "withdrawn", "ended")
INVITATION_DECISIONS = ("accept", "decline", "withdraw")  # app_decide_team_invitation's p_decision
CLOSE_REASONS = ("left", "blocked")  # app_close_team_thread takes "left"; "blocked" is a block's
NOTE_MAX_CHARS = 300
MESSAGE_MAX_CHARS = 4000  # a team message's body: 1 to 4,000 characters, not blank
MESSAGE_REDACTED = "[redacted]"  # D-54: the one body a message may be changed to, by the owner's redaction
TEAM_MESSAGE = "team_message"  # moderation_cases.subject_type of a team message report
TEAM_MESSAGE_REPORTS_PER_DAY = 10  # fixed in app_report_team_message (the message report reasons are 0008's)
PEERS_PAGE_MAX = 50  # app_peers' largest page


def _user(column: str, **extra: str) -> dict[str, dict[str, object]]:
    return {"info": {"tenancy": Tenancy.USER, "tenant_column": column, **extra}}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


# Plain text over lines: tab, line feed and carriage return are allowed, no other control character.
NOTE_VALID = (
    f"note IS NULL OR (note ~ '[^[:space:]]' AND char_length(note) <= {NOTE_MAX_CHARS}"
    " AND note !~ '[\\x01-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]')"
)


class DeveloperBlock(Base):
    """A developer's block of another (D-58): the blocker inserts and deletes it (better: ``app_block_developer``,
    which says what it ended, and ``app_unblock_developer``); ``created_at`` is the database's clock. Read by the
    blocker only (``app_blocked_developers()`` adds the handles)."""

    __tablename__ = "developer_blocks"
    __table_args__ = (
        CheckConstraint("blocker_user_id <> blocked_user_id", name="not_self"),
        _user("blocker_user_id"),
    )

    blocker_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    blocked_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))


class TeamInvitation(IdMixin, Base):
    """A team-up invitation (REQ-DEV-03): the app inserts ``id``, ``from_user_id`` (the caller), ``to_user_id``,
    ``problem_id`` and ``note``; the status, its time and ``created_at`` are the database's (read them back). Decided
    only through ``app_decide_team_invitation``; ended by a block."""

    __tablename__ = "team_invitations"
    __table_args__ = (
        # One pending invitation per pair and problem, whichever of the two sent it.
        Index(
            "uq_team_invitations_pending_pair",
            text("LEAST(from_user_id, to_user_id)"),
            text("GREATEST(from_user_id, to_user_id)"),
            "problem_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        CheckConstraint("from_user_id <> to_user_id", name="not_self"),
        CheckConstraint(_in("status", INVITATION_STATUSES), name="status_known"),
        CheckConstraint(NOTE_VALID, name="note_valid"),
        CheckConstraint("(status = 'pending') = (decided_at IS NULL)", name="decision_complete"),
        _user("from_user_id", user_column="to_user_id"),
    )

    from_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    to_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    problem_id: Mapped[UUID] = mapped_column(ForeignKey("problems.id"))
    note: Mapped[str | None] = mapped_column(Text)  # free text: never in payloads, logs or notices
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))  # INVITATION_STATUSES
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TeamThread(IdMixin, Base):
    """A dev-to-dev thread of an accepted invitation, between its canonical pair (``a_user_id < b_user_id``), on the
    invitation's problem. Read by the two; never written by the app (``app_decide_team_invitation``,
    ``app_close_team_thread``, a block)."""

    __tablename__ = "team_threads"
    __table_args__ = (
        Index("ix_team_threads_pair", "a_user_id", "b_user_id"),
        CheckConstraint("a_user_id < b_user_id", name="pair_ordered"),
        CheckConstraint(_in("closed_reason", CLOSE_REASONS), name="closed_reason_known"),
        CheckConstraint("(closed_at IS NULL) = (closed_reason IS NULL)", name="close_complete"),
        _user("a_user_id", user_column="b_user_id"),
    )

    invitation_id: Mapped[UUID] = mapped_column(ForeignKey("team_invitations.id"), unique=True)
    a_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    b_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    problem_id: Mapped[UUID] = mapped_column(ForeignKey("problems.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_reason: Mapped[str | None] = mapped_column(Text)  # CLOSE_REASONS


class TeamMessage(IdMixin, Base):
    """One message of a team thread: the app inserts ``id``, ``thread_id``, ``sender_user_id`` (the caller, a party)
    and ``body`` while the thread is open; ``created_at`` is the database's clock. INSERT-only for the app; D-54: the
    owner (or a definer function it owns) may redact a body once."""

    __tablename__ = "team_messages"
    __table_args__ = (
        Index("ix_team_messages_thread", "thread_id", "created_at", "id"),
        CheckConstraint(f"body ~ '[^[:space:]]' AND char_length(body) <= {MESSAGE_MAX_CHARS}", name="body_length"),
        CheckConstraint(
            f"(redacted_at IS NOT NULL) = (body = {MESSAGE_REDACTED!r})"
            " AND (redacted_at IS NULL) = (redacted_by IS NULL)",
            name="redaction_complete",
        ),
        _user("sender_user_id", via="team_threads"),
    )

    thread_id: Mapped[UUID] = mapped_column(ForeignKey("team_threads.id"))
    sender_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)  # plain text, never interpreted; never in payloads, logs or notices
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redacted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class TeamThreadRead(Base):
    """How far a party has read a team thread: one row per party and thread, the user's own. Upsert ``last_read_at``
    (never another column)."""

    __tablename__ = "team_thread_reads"
    __table_args__ = (_user("user_id", via="team_threads"),)

    thread_id: Mapped[UUID] = mapped_column(ForeignKey("team_threads.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))


class ProposalContributor(Base):
    """D-62 (a): a contributor listed on a proposal ("Contributors: <handles>"), never a registrant. The owner inserts
    ``proposal_id``, ``user_id`` (the other party of one of the owner's team threads) and ``thread_id`` (that thread);
    ``added_at`` is the database's clock. The owner or the contributor sets ``removed_at`` (the database replaces the
    value with its clock), once and for good. Show the credit through ``app_contributor_handles(proposal)`` only."""

    __tablename__ = "proposal_contributors"
    __table_args__ = (
        CheckConstraint("removed_at IS NULL OR removed_at >= added_at", name="removed_after_added"),
        _user("user_id", via="proposals"),
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    thread_id: Mapped[UUID | None] = mapped_column(ForeignKey("team_threads.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("app_clock_now()"))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
