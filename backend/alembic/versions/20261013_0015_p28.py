"""Schema v12 (P28-M): the procurement route (3b).

REQ-ENG-06 (AC-TRACK-5). Design: ``docs/platform/tasks/P28.md``, "Feature tracks", the contract's A. Additive but for
one looser CHECK and two narrower main-path predecessors (both restored on downgrade): one enum type
(``procurement_route``), four columns of ``engagements`` with three CHECKs and bridge_app's UPDATE of two of them, two
new triggers on ``engagements`` and their functions, and revision 0003's ``engagement_main_path_predecessors``
replaced in place. Nothing else of revisions 0001 to 0014 is changed or dropped. Times written here are the shared
clock's (``app_clock_now()``).

The procurement route (docs/spec/06 6.9 stage 3b; ``PROCUREMENT_ROUTE`` has been a value of ``engagement_state``
since revision 0002, so no enum value is added and nothing needs an autocommit block):

- Where 3b sits. The contract puts it between ``UNDER_REVIEW`` and ``INTEREST_CONFIRMED``: a public entity's
  signatory approves to proceed (``UNDER_REVIEW -> PROCUREMENT_ROUTE``, naming the contact person and channel, not yet
  the contact-by date), then its owner or admin chooses the route (``PROCUREMENT_ROUTE -> INTEREST_CONFIRMED``, with
  the contact-by date). Revision 0003's backstop admitted 3b "around stage 3" (``PROCUREMENT_ROUTE`` from
  ``UNDER_REVIEW`` or ``INTEREST_CONFIRMED``; ``CONTACT_MADE`` from ``INTEREST_CONFIRMED`` or ``PROCUREMENT_ROUTE``);
  ``engagement_main_path_predecessors`` is replaced in place (``CREATE OR REPLACE``: same signature, owner, IMMUTABLE,
  pinned search_path, no EXECUTE for any role) so that ``PROCUREMENT_ROUTE`` follows ``UNDER_REVIEW`` only and
  ``CONTACT_MADE`` follows ``INTEREST_CONFIRMED`` only. ``INTEREST_CONFIRMED``'s predecessors are unchanged
  (``ORG_INTEREST``, ``UNDER_REVIEW``, ``PROCUREMENT_ROUTE``, ``CONTACT_MADE``). No engagement of any database took
  either removed step (the state machine never offered 3b), and existing chains are never re-checked.
- Side branches. Revision 0003's chain lets a side state (``DECLINED``, ``WITHDRAWN``, ``EXPIRED``, ``ON_HOLD``,
  ``INFO_REQUESTED``, ``DISPUTED``, ``TERMINATED``) be entered from any open state and resumes ``ON_HOLD``,
  ``INFO_REQUESTED`` and ``DISPUTED`` only to the state they were entered from, so 3b has every side branch
  ``INTEREST_CONFIRMED`` has (decline, withdraw, hold, request for information, the expiry job's ``EXPIRED``), each
  resuming to ``PROCUREMENT_ROUTE``. Unchanged here.
- Public entities only (AC-TRACK-5). ``engagements_procurement_guard`` (BEFORE INSERT OR UPDATE on ``engagements``,
  every role, SECURITY INVOKER) refuses an engagement inserted in ``PROCUREMENT_ROUTE``, and the projection's move into
  it from the main path (the chain's event, revision 0003: the error aborts the event's INSERT), for an organisation
  whose ``public_entity`` is not true (check_violation). A resume into 3b from a side state it was entered from is not
  re-judged.
- The decision. ``procurement_route`` (``direct``, ``rfq_tender``, ``ppp_pip``, ``innovation_challenge``,
  ``pilot_mou``) and ``procurement_justification`` (plain text, line breaks allowed, not blank, at most 1,000
  characters; ``direct`` needs at least 20 characters once the ends are trimmed: CHECKs
  ``procurement_justification_valid`` and ``procurement_direct_justified``) are bridge_app's to write (column UPDATE;
  the UPDATE policy of revision 0003 lets the organisation's owner, admin or signatory write the row);
  ``procurement_decided_at`` (the shared clock) and ``procurement_decided_by`` (the bound user) are the database's
  (CHECK ``procurement_decided``: all three or none). The guard: an engagement starts undecided (every role); the route
  is decided only while the engagement is in ``PROCUREMENT_ROUTE`` (object_not_in_prerequisite_state, every role) and
  only by an active owner or admin of its organisation (insufficient_privilege; a signatory, a reviewer and the
  developer are refused), but for the table's owner in its own session with no user bound (a migration, the seed, a
  backfill, the test world: it names the decider), the same rule as revision 0013's declarations; a decided route,
  justification, time and decider never change, for every role, the owner included (check_violation).
- Together with the move. The projection's move out of ``PROCUREMENT_ROUTE`` goes to ``INTEREST_CONFIRMED`` only with
  the route decided and the contact named with its contact-by date, and a decided route leaves 3b for
  ``INTEREST_CONFIRMED`` only (check_violation: a decline, hold or withdrawal is taken undecided). And
  ``engagements_procurement_moved``, a constraint trigger DEFERRABLE INITIALLY DEFERRED (AFTER UPDATE OF
  ``procurement_route``, when it is set; SECURITY DEFINER), refuses at commit a decision whose engagement is still in
  ``PROCUREMENT_ROUTE``. So the decision and the move are made in one transaction, decision first.
- The contact. Revision 0003's ``contact_complete`` (person, channel and contact-by date all or none) is replaced by
  ``contact_consistent``: person and channel together; a contact-by date only with them; once the route is decided, a
  named contact has its date. Restored on downgrade.

Functions (pinned search_path; EXECUTE revoked from PUBLIC; no EXECUTE for any role): the trigger functions
``engagements_procurement_guard()`` (SECURITY INVOKER: ``current_user`` is the writer; the organisation's
``public_entity`` is read as the projection's owner on a state change) and ``engagements_procurement_moved()``
(SECURITY DEFINER: reads the engagement whatever the committing session's RLS), and the replaced
``engagement_main_path_predecessors(engagement_state)``.

Operating rules for the code that uses this schema:

- Approve (``UNDER_REVIEW``) for a public entity: name the contact person and channel and leave ``contact_by`` NULL,
  then append the event to ``PROCUREMENT_ROUTE`` (refused for a private organisation: check_violation, the API's 409;
  a private organisation's approve goes to ``INTEREST_CONFIRMED`` as before).
- Choose the route (an owner or admin; check the role first, 403): in one transaction, ``UPDATE engagements SET
  procurement_route = :route, procurement_justification = :text, contact_by = :by`` (one statement: the CHECKs see
  them together; trim the justification first; leave ``procurement_decided_at`` and ``procurement_decided_by`` out
  and read them back), then append the event ``PROCUREMENT_ROUTE -> INTEREST_CONFIRMED``. check_violation from the
  justification CHECKs is the API's 422; object_not_in_prerequisite_state (not in 3b) and "never changes" its 409.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROCUREMENT_ROUTES = ("direct", "rfq_tender", "ppp_pip", "innovation_challenge", "pilot_mou")
PROCUREMENT_COLUMNS = (
    "procurement_route",
    "procurement_justification",
    "procurement_decided_at",
    "procurement_decided_by",
)
# bridge_app writes the route and its justification; the time and the decider are the guard's.
ENGAGEMENT_GRANT = "GRANT UPDATE (procurement_route, procurement_justification) ON TABLE engagements TO bridge_app;"

# CHECK expressions, verbatim from bridge.engagements.models (alembic check compares no CHECK).
CONTACT_CONSISTENT = (
    "(contact_user_id IS NULL) = (contact_channel IS NULL)"
    " AND (contact_by IS NULL OR contact_user_id IS NOT NULL)"
    " AND (contact_by IS NOT NULL OR contact_user_id IS NULL OR procurement_route IS NULL)"
)
PROCUREMENT_DECIDED = (
    "(procurement_route IS NULL) = (procurement_decided_at IS NULL)"
    " AND (procurement_route IS NULL) = (procurement_decided_by IS NULL)"
)
PROCUREMENT_JUSTIFICATION_VALID = (
    "procurement_justification IS NULL OR (procurement_route IS NOT NULL"
    " AND procurement_justification ~ '[^[:space:]]'"
    " AND char_length(procurement_justification) <= 1000)"
)
PROCUREMENT_DIRECT_JUSTIFIED = (
    "procurement_route IS DISTINCT FROM 'direct' OR char_length(btrim(coalesce(procurement_justification, ''))) >= 20"
)
ENGAGEMENT_CHECKS = (
    ("procurement_decided", PROCUREMENT_DECIDED),
    ("procurement_justification_valid", PROCUREMENT_JUSTIFICATION_VALID),
    ("procurement_direct_justified", PROCUREMENT_DIRECT_JUSTIFIED),
    ("contact_consistent", CONTACT_CONSISTENT),
)
# Revision 0003's contact CHECK, verbatim, dropped here and restored on downgrade.
CONTACT_COMPLETE_0003 = (
    "(contact_user_id IS NULL) = (contact_channel IS NULL) AND (contact_channel IS NULL) = (contact_by IS NULL)"
)

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0014: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (trigger and internal functions to nobody). SECURITY DEFINER
# functions run as bridge_owner, which bypasses RLS (ENABLED, not FORCED). CREATE OR REPLACE keeps a function's owner,
# ACL and triggers.
# ---------------------------------------------------------------------------------------------------------------------

# The main path's legal predecessors with 3b between stages 2 and 3 (the P28 contract): PROCUREMENT_ROUTE follows
# UNDER_REVIEW only, CONTACT_MADE follows INTEREST_CONFIRMED only. Every other row is revision 0003's.
PREDECESSORS_SQL = r"""
CREATE OR REPLACE FUNCTION engagement_main_path_predecessors(p_state engagement_state) RETURNS engagement_state[]
    LANGUAGE sql IMMUTABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT CAST(CASE p_state
        WHEN 'ORG_INTEREST' THEN '{}'
        WHEN 'SUBMITTED' THEN '{}'
        WHEN 'UNDER_REVIEW' THEN '{SUBMITTED}'
        WHEN 'INTEREST_CONFIRMED' THEN '{ORG_INTEREST,UNDER_REVIEW,PROCUREMENT_ROUTE,CONTACT_MADE}'
        WHEN 'PROCUREMENT_ROUTE' THEN '{UNDER_REVIEW}'
        WHEN 'CONTACT_MADE' THEN '{INTEREST_CONFIRMED}'
        WHEN 'NDA_PENDING' THEN '{CONTACT_MADE}'
        WHEN 'NDA_SIGNED' THEN '{NDA_PENDING}'
        WHEN 'NEGOTIATION' THEN '{NDA_SIGNED,AGREEMENT_SIGNING}'
        WHEN 'AGREEMENT_SIGNING' THEN '{NEGOTIATION}'
        WHEN 'IN_IMPLEMENTATION' THEN '{AGREEMENT_SIGNING}'
        WHEN 'DELIVERED' THEN '{IN_IMPLEMENTATION}'
        WHEN 'SIGN_OFF' THEN '{DELIVERED}'
        WHEN 'PAYMENT_FINAL' THEN '{SIGN_OFF}'
        WHEN 'CLOSED' THEN '{PAYMENT_FINAL,DISPUTED}'
    END AS public.engagement_state[])
$$;
"""

# Revision 0003's engagement_main_path_predecessors, verbatim (its body must match byte for byte), restored on
# downgrade.
PREDECESSORS_0003 = r"""
CREATE OR REPLACE FUNCTION engagement_main_path_predecessors(p_state engagement_state) RETURNS engagement_state[]
    LANGUAGE sql IMMUTABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT CAST(CASE p_state
        WHEN 'ORG_INTEREST' THEN '{}'
        WHEN 'SUBMITTED' THEN '{}'
        WHEN 'UNDER_REVIEW' THEN '{SUBMITTED}'
        WHEN 'INTEREST_CONFIRMED' THEN '{ORG_INTEREST,UNDER_REVIEW,PROCUREMENT_ROUTE,CONTACT_MADE}'
        WHEN 'PROCUREMENT_ROUTE' THEN '{UNDER_REVIEW,INTEREST_CONFIRMED}'
        WHEN 'CONTACT_MADE' THEN '{INTEREST_CONFIRMED,PROCUREMENT_ROUTE}'
        WHEN 'NDA_PENDING' THEN '{CONTACT_MADE}'
        WHEN 'NDA_SIGNED' THEN '{NDA_PENDING}'
        WHEN 'NEGOTIATION' THEN '{NDA_SIGNED,AGREEMENT_SIGNING}'
        WHEN 'AGREEMENT_SIGNING' THEN '{NEGOTIATION}'
        WHEN 'IN_IMPLEMENTATION' THEN '{AGREEMENT_SIGNING}'
        WHEN 'DELIVERED' THEN '{IN_IMPLEMENTATION}'
        WHEN 'SIGN_OFF' THEN '{DELIVERED}'
        WHEN 'PAYMENT_FINAL' THEN '{SIGN_OFF}'
        WHEN 'CLOSED' THEN '{PAYMENT_FINAL,DISPUTED}'
    END AS public.engagement_state[])
$$;
"""

FUNCTIONS_SQL = r"""
-- engagements, BEFORE INSERT OR UPDATE (after engagements_guard: triggers fire in name order), every role (REQ-ENG-06,
-- AC-TRACK-5). PROCUREMENT_ROUTE is a public entity's only: an engagement inserted in it, and the projection's move
-- into it from the main path, are refused for an organisation whose public_entity is not true (a resume into 3b from a
-- side state entered there is not re-judged). An engagement starts with no procurement decision. The route is decided
-- while the engagement is in PROCUREMENT_ROUTE only, by an active owner or admin of its organisation (but for the
-- table's owner in its own session with no user bound: the session's login is the owner itself or a superuser, as
-- revision 0013's declarations; it names the decider), the time the shared clock's and the decider the bound user,
-- whatever was sent; once decided, the route, justification, time and decider never change, for every role. The move
-- out of PROCUREMENT_ROUTE (the projection's) goes to INTEREST_CONFIRMED only with the route decided and the contact
-- named with its contact-by date; a decided route leaves 3b for INTEREST_CONFIRMED only. SECURITY INVOKER: current_user
-- is the writer (the projection's state change runs as the owner, which reads the organisation; a member's decision
-- runs as bridge_app, judged by app_is_member).
CREATE FUNCTION engagements_procurement_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.procurement_route IS NOT NULL OR NEW.procurement_justification IS NOT NULL
           OR NEW.procurement_decided_at IS NOT NULL OR NEW.procurement_decided_by IS NOT NULL THEN
            RAISE EXCEPTION 'engagements: an engagement starts with no procurement decision'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.state = 'PROCUREMENT_ROUTE'
           AND NOT coalesce((SELECT o.public_entity FROM public.organizations o WHERE o.id = NEW.org_id), false) THEN
            RAISE EXCEPTION 'engagements: PROCUREMENT_ROUTE is for a public entity only'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.procurement_route IS NOT NULL THEN
        IF (NEW.procurement_route, NEW.procurement_justification, NEW.procurement_decided_at,
            NEW.procurement_decided_by)
           IS DISTINCT FROM (OLD.procurement_route, OLD.procurement_justification, OLD.procurement_decided_at,
                             OLD.procurement_decided_by) THEN
            RAISE EXCEPTION 'engagements: a procurement decision never changes' USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.procurement_route IS NOT NULL THEN
        IF OLD.state <> 'PROCUREMENT_ROUTE' OR NEW.state <> 'PROCUREMENT_ROUTE' THEN
            RAISE EXCEPTION 'engagements: the procurement route is decided in PROCUREMENT_ROUTE only, not in %',
                OLD.state USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
        IF current_user = (SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c
                            WHERE c.oid = TG_RELID)
           AND (session_user = current_user
                OR EXISTS (SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname = session_user AND r.rolsuper))
           AND public.app_user_id() IS NULL THEN
            NULL;  -- the owner's own session names the decider
        ELSIF public.app_is_member(NEW.org_id, '{owner,admin}') THEN
            NEW.procurement_decided_by := public.app_user_id();
        ELSE
            RAISE EXCEPTION 'engagements: an owner or admin of the organisation decides its procurement route'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        NEW.procurement_decided_at := public.app_clock_now();
    END IF;
    IF NEW.state IS DISTINCT FROM OLD.state THEN
        IF NEW.state = 'PROCUREMENT_ROUTE' AND OLD.state NOT IN ('ON_HOLD', 'INFO_REQUESTED', 'DISPUTED')
           AND NOT coalesce((SELECT o.public_entity FROM public.organizations o WHERE o.id = NEW.org_id), false) THEN
            RAISE EXCEPTION 'engagements: PROCUREMENT_ROUTE is for a public entity only'
                USING ERRCODE = 'check_violation';
        END IF;
        IF OLD.state = 'PROCUREMENT_ROUTE' THEN
            IF NEW.state = 'INTEREST_CONFIRMED' THEN
                IF NEW.procurement_route IS NULL THEN
                    RAISE EXCEPTION 'engagements: PROCUREMENT_ROUTE moves to INTEREST_CONFIRMED once its route is'
                        ' decided' USING ERRCODE = 'check_violation';
                END IF;
                IF NEW.contact_user_id IS NULL OR NEW.contact_by IS NULL THEN
                    RAISE EXCEPTION 'engagements: PROCUREMENT_ROUTE moves to INTEREST_CONFIRMED with the named contact'
                        ' and its contact-by date' USING ERRCODE = 'check_violation';
                END IF;
            ELSIF NEW.procurement_route IS NOT NULL THEN
                RAISE EXCEPTION 'engagements: a decided procurement route leaves PROCUREMENT_ROUTE for'
                    ' INTEREST_CONFIRMED only, not %', NEW.state USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- engagements, a constraint trigger DEFERRABLE INITIALLY DEFERRED (AFTER UPDATE OF procurement_route, when it is set),
-- every role: at commit, an engagement whose procurement route was decided is no longer in PROCUREMENT_ROUTE, so the
-- decision and the move to INTEREST_CONFIRMED are made in one transaction (the guard refuses the move without it).
-- SECURITY DEFINER: reads the engagement as it is at commit, whatever the committing session's RLS.
CREATE FUNCTION engagements_procurement_moved() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.engagements e WHERE e.id = NEW.id AND e.state = 'PROCUREMENT_ROUTE') THEN
        RAISE EXCEPTION 'engagements: a procurement route is decided in the transaction that moves the engagement to'
            ' INTEREST_CONFIRMED' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;
"""

TRIGGER_FUNCTIONS = ("engagements_procurement_guard()", "engagements_procurement_moved()")
# Triggers this revision puts on earlier revisions' tables (dropped by name on downgrade; the tables stay).
EXISTING_TABLE_TRIGGERS = (
    ("engagements_procurement_guard", "engagements"),
    ("engagements_procurement_moved", "engagements"),
)

TRIGGERS_SQL = r"""
CREATE TRIGGER engagements_procurement_guard
    BEFORE INSERT OR UPDATE ON engagements
    FOR EACH ROW EXECUTE FUNCTION engagements_procurement_guard();
CREATE CONSTRAINT TRIGGER engagements_procurement_moved
    AFTER UPDATE OF procurement_route ON engagements
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW WHEN (OLD.procurement_route IS NULL AND NEW.procurement_route IS NOT NULL)
    EXECUTE FUNCTION engagements_procurement_moved();
"""


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _grant_sql() -> str:
    grants = [ENGAGEMENT_GRANT]
    grants += [f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in TRIGGER_FUNCTIONS]
    return "\n".join(grants)


def upgrade() -> None:
    postgresql.ENUM(*PROCUREMENT_ROUTES, name="procurement_route").create(op.get_bind(), checkfirst=False)
    _alter_engagements()
    _run_sql(PREDECESSORS_SQL)
    _run_sql(FUNCTIONS_SQL)
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Destructive: drops every procurement decision (a public entity's route and justification, shown to both
    parties). Under the CLAUDE.md stop rule a downgrade of a database holding one is a destructive migration: back the
    database up and get the human's decision first. The downgrade refuses while any engagement holds a decision, unless
    run with ``-x allow_p28_loss=true`` (``alembic -x allow_p28_loss=true downgrade 0014``). It refuses in any case
    while an engagement names a contact without a contact-by date (revision 0003's CHECK would refuse the row: give it
    its date, or end the engagement, first)."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_p28_loss") == "true"
    bind = op.get_bind()
    undated = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM engagements WHERE contact_user_id IS NOT NULL AND contact_by IS NULL)")
    ).scalar()
    if undated:
        raise RuntimeError(
            "revision 0015 downgrade: an engagement names a contact without a contact-by date (a public entity's"
            " procurement route); revision 0003's contact CHECK would refuse it. Give it its date or end it first."
        )
    holding = []
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM engagements WHERE procurement_route IS NOT NULL)")).scalar():
        holding.append("engagements (procurement decisions)")
    if holding and not allowed:
        raise RuntimeError(
            f"revision 0015 downgrade: {', '.join(holding)} hold data this revision's downgrade drops; back the"
            " database up, get the human's decision (CLAUDE.md: destructive migration), then run with"
            " -x allow_p28_loss=true"
        )
    # This revision's triggers on engagements first (the table stays); dropping a column drops its grant.
    _run_sql("\n".join(f"DROP TRIGGER {trigger} ON {table};" for trigger, table in EXISTING_TABLE_TRIGGERS))
    _run_sql("\n".join(f"DROP FUNCTION {signature};" for signature in TRIGGER_FUNCTIONS))
    _run_sql(PREDECESSORS_0003)
    for name, _expression in reversed(ENGAGEMENT_CHECKS):
        op.drop_constraint(op.f(f"ck_engagements_{name}"), "engagements", type_="check")
    op.create_check_constraint(op.f("ck_engagements_contact_complete"), "engagements", CONTACT_COMPLETE_0003)
    op.drop_constraint(op.f("fk_engagements_procurement_decided_by_users"), "engagements", type_="foreignkey")
    for column in reversed(PROCUREMENT_COLUMNS):
        op.drop_column("engagements", column)
    postgresql.ENUM(name="procurement_route").drop(bind, checkfirst=False)


def _alter_engagements() -> None:
    route = postgresql.ENUM(*PROCUREMENT_ROUTES, name="procurement_route", create_type=False)
    op.add_column("engagements", sa.Column("procurement_route", route, nullable=True))
    op.add_column("engagements", sa.Column("procurement_justification", sa.Text(), nullable=True))
    op.add_column("engagements", sa.Column("procurement_decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("engagements", sa.Column("procurement_decided_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_engagements_procurement_decided_by_users"), "engagements", "users", ["procurement_decided_by"], ["id"]
    )
    # Looser than revision 0003's (a contact named without its date while the route is undecided): every existing row
    # passes it.
    op.drop_constraint(op.f("ck_engagements_contact_complete"), "engagements", type_="check")
    for name, expression in ENGAGEMENT_CHECKS:
        op.create_check_constraint(op.f(f"ck_engagements_{name}"), "engagements", expression)
