"""Schema v5 (P19): engagement notes, and marking in-app notifications read.

REQ-ENG-10 (part: ``INFO_REQUESTED`` and ``ON_HOLD`` before the agreement, task P19-A: ``engagement_notes``) and
REQ-NOT-03 (the in-app channel, task P19-C: a user marks their own notifications read). Design:
``docs/platform/tasks/P19-M.md``. Additive: one new table with its policies, triggers and grants, and bridge_app's
table-wide UPDATE on ``in_app_notifications`` (revision 0001) narrowed to ``UPDATE (read_at)`` (the table-wide grant
is restored on downgrade). No enum type and no function: the triggers reuse ``tracker_engagement_visible()``
(revision 0003) and ``block_mutation()`` (revision 0002). Nothing else of revisions 0001 to 0005 is changed or dropped.
The upgrade is additive; the downgrade is destructive (it drops the notes: see ``downgrade()``).

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
  no note), is still the engagement's latest event (the chain's row lock keeps it so until commit), and its transition
  is the kind's: ``info_request`` enters ``INFO_REQUESTED`` and ``hold`` enters ``ON_HOLD``, each from a state that
  is neither a side state nor terminal; ``info_answer`` leaves ``INFO_REQUESTED`` and ``resume`` leaves ``ON_HOLD``,
  each for such a state (the state it was entered from: the chain enforces that). One note per event (UNIQUE
  (engagement_id, event_seq)). Who may enter or leave a side state is the event's policy and the state machine's.
- Append-only: no UPDATE or DELETE grant, and ``engagement_notes_no_update_delete`` and ``_no_truncate``
  (``block_mutation()``) refuse them for every role, the owner included. ``engagement_notes_0_visible``
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
- A note is free text a party typed and is never changed or deleted: keep it out of event payloads, logs and audit
  details. Its erasure under a data-subject request (REQ-SEC-02, AC-SEC-3) is not decided here (see the P19-M report).

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
# INSERT only, the INSERT without created_at (the database's clock).
APP_GRANTS: dict[str, str] = {
    "engagement_notes": "SELECT, INSERT (id, engagement_id, event_seq, kind, body, resume_at, created_by)",
}
# bridge_app's table-wide UPDATE on in_app_notifications (revision 0001) becomes an UPDATE of read_at only (restored to
# the table-wide grant on downgrade).
IN_APP_UPDATABLE_COLUMNS = "read_at"

# CHECK expressions, verbatim from the ORM model (bridge.engagements.models.EngagementNote).
NOTE_KINDS = ("info_request", "info_answer", "hold", "resume")


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
# The note's event (read under the caller's RLS, so its engagement is visible): appended by the caller as themselves,
# still the engagement's latest event, and of the kind's transition. A NULL from_state (the genesis) matches no kind.
NOTE_INSERT = (
    "created_by = app_user_id()"
    " AND EXISTS (SELECT 1 FROM engagement_events ev"
    " WHERE ev.engagement_id = engagement_notes.engagement_id AND ev.seq = engagement_notes.event_seq"
    " AND ev.actor_user_id = app_user_id()"
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

# Every tracker table's triggers (revision 0003): the visibility check fires first on INSERT (<table>_0_visible sorts
# first by name), and the append-only refusals hold for every role.
TRIGGERS_SQL = r"""
CREATE TRIGGER engagement_notes_0_visible
    BEFORE INSERT ON engagement_notes
    FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();
CREATE TRIGGER engagement_notes_no_update_delete
    BEFORE UPDATE OR DELETE ON engagement_notes
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
CREATE TRIGGER engagement_notes_no_truncate
    BEFORE TRUNCATE ON engagement_notes
    FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();
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
    return "\n".join(grants)


def upgrade() -> None:
    _create_tables()
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
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
    # Dropping the table drops its policies, triggers, indexes and grants (the trigger functions are revision 0002's
    # and 0003's and stay).
    op.drop_table("engagement_notes")
    _run_sql(
        "REVOKE UPDATE ON TABLE in_app_notifications FROM bridge_app;"
        " GRANT UPDATE ON TABLE in_app_notifications TO bridge_app;"
    )


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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_engagement_notes_created_by_users")),
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
