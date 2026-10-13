"""Schema v12 (P28-M): the procurement route (3b), the nudges ledger and the organisation's team.

REQ-ENG-06 (AC-TRACK-5), REQ-NOT-05 (with REQ-NOT-03 and REQ-ENG-05; AC-MAIL-2) and REQ-TEN-02. Design:
``docs/platform/tasks/P28.md``, "Feature tracks", the contract's A, B and C. Additive but for what is stricter or looser
in place, each restored on downgrade: revision 0003's main-path predecessors (two narrower) and contact CHECK (looser),
and revision 0001's invitation policies (INSERT and UPDATE, stricter) and bridge_app's table-wide INSERT and UPDATE of
``invitations`` and UPDATE of ``memberships`` (now column-scoped). New: one enum type (``procurement_route``); four
columns of ``engagements`` with three CHECKs and bridge_app's UPDATE of two of them;
``organizations.escalation_contact_user_id`` and bridge_app's UPDATE of it; two tables (``engagement_nudges``,
``org_niche_defaults``) with their policies, triggers and grants; on ``invitations`` a CHECK, a partial unique index
and a guard; on ``memberships`` the last-owner guard and the clearing of a leaver's team seats; four functions
bridge_app executes and seven trigger functions. Nothing else of revisions 0001 to 0014 is changed or dropped. Times
written here are the shared clock's (``app_clock_now()``).

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

The nudges ledger (REQ-NOT-05; the contract's B):

- ``engagement_nudges`` (ORG; bridge_app: SELECT only): one row per nudge the job sends, recorded before sending, once
  per engagement, kind and key (``uq_engagement_nudges_engagement_id_kind_key``). ``kind`` is one of
  ``contact_escalation``, ``contact_overdue``, ``nda_reminder``, ``procurement_escalation``, ``milestone_reminder``,
  ``milestone_escalation`` (CHECK ``kind_known``; text, not an enum type, so a later kind is a CHECK change); ``key``
  is a code of 1 to 120 characters of ``[A-Za-z0-9_.:+-]`` (CHECK ``key_valid``: a business-day count, a milestone id,
  a date; no free text, address or name fits); ``org_id`` is the engagement's (a column, as revision 0013's triage
  tables, so the policy and the RLS tests are the organisation's); ``sent_at`` is the shared clock's. Read by the
  organisation's members (narrowed by ``app.org_id``), never by the engagement's own developer even as a member (D-68's
  rule, as the assignments), nor by staff or another organisation. Append-only for every role, the owner included
  (``engagement_nudges_no_update_delete`` and ``_no_truncate``: ``block_mutation()`` of revision 0002).
- How the job gets there, as the expiry job (revision 0007): no application role reads every tenant's engagements, so
  ``app_nudge_candidates()`` lists, to a session with no user bound only, the open engagements a nudge may be due for
  (ids only) with a member of the organisation to bind for its side, and ``app_record_nudge(engagement, kind, key)``
  records a nudge for a session with no user bound only. bridge_app holds no INSERT on the ledger: no request can
  record (and so suppress) a nudge.

The team (REQ-TEN-02; the contract's C). "An admin" is an active owner or admin of the row's organisation, narrowed by
``app.org_id`` when one is set (revision 0001's rule); "a triage member" an active owner, admin, reviewer or signatory
(revision 0013's).

- ``organizations.escalation_contact_user_id`` (uuid, NULL; FK ``users`` ON DELETE SET NULL): who, besides the admins,
  hears of escalations. bridge_app gains UPDATE of it (the organisation's UPDATE policy of revision 0001: an owner or
  admin). ``organizations_escalation_contact_guard`` (BEFORE INSERT OR UPDATE OF the column, every role, SECURITY
  INVOKER): NULL or an active member of the organisation, read under the writer's RLS (check_violation).
- ``org_niche_defaults`` (ORG; bridge_app: SELECT, INSERT of ``id``, ``org_id``, ``niche_id``, ``user_id``, UPDATE of
  ``user_id``, DELETE): one default reviewer per organisation and niche (``uq_org_niche_defaults_org_id_niche_id``; FK
  ``organizations`` and ``users`` ON DELETE CASCADE, ``niches``). Members read; an admin inserts, updates and deletes
  (role checks in SQL, as revision 0001's ``org_niches``). ``org_niche_defaults_guard`` (BEFORE INSERT OR UPDATE, every
  role, SECURITY INVOKER: the roster under the writer's RLS): the user is a triage member of the organisation
  (check_violation; the API narrows it to reviewer, signatory or admin); the organisation, niche and creation time
  never change (check_violation); ``updated_at`` is the shared clock on every update.
- ``memberships``: bridge_app's UPDATE becomes ``roles``, ``status`` and ``updated_at`` (revision 0001 granted the
  table; a membership's organisation and user never move, members leave by ``status = 'removed'``); its policies are
  revision 0001's (an admin removes or changes a member who holds neither owner nor signatory, an owner anyone).
  ``memberships_last_owner_guard`` (BEFORE UPDATE, SECURITY INVOKER) refuses removing or demoting the organisation's
  last active owner (object_not_in_prerequisite_state, the API's 409 ``last_owner``); concurrent removals of two owners
  are serialised on a transaction advisory lock per organisation, so one of them sees the other. It judges the
  organisation's own writes only: the table's owner (the definer functions, a claim's transfer and staff's roster
  correction of revision 0002 which may leave an organisation without an owner by design; the seed) is not judged.
  ``memberships_clear_team_seats`` (AFTER UPDATE OF status, roles, when an active membership leaves ``active`` or keeps
  none of the triage roles; SECURITY DEFINER, as revision 0013's feed revocation): a leaver's niche defaults go and the
  escalation contact is cleared if it is them; a member who loses the triage roles loses their niche defaults.
- ``invitations`` (revision 0001; tenancy ORG): bridge_app's table-wide INSERT and UPDATE become INSERT of ``id``,
  ``org_id``, ``email``, ``roles``, ``token_hash``, ``invited_by``, ``expires_at`` and UPDATE of ``token_hash``,
  ``expires_at`` (a resend: the old token dies) and ``revoked_at``. The SELECT policy stays revision 0001's (an admin
  lists the organisation's; a member who is not an admin, another organisation, the invitee read none); the INSERT
  policy adds ``invited_by = app_user_id()`` and the ``app.org_id`` narrowing to revision 0001's rule (an admin; only
  an owner invites an owner or a signatory); the UPDATE policy reaches open invitations only (neither accepted nor
  revoked) with the same narrowing. ``invitations_guard`` (BEFORE INSERT OR UPDATE, every role, SECURITY INVOKER): an
  invitation is created open; its organisation, address, roles, inviter and creation time never change
  (check_violation); an accepted or revoked invitation never changes (object_not_in_prerequisite_state);
  ``revoked_at`` and ``accepted_at`` are the shared clock whatever is sent. CHECK ``accepted_or_revoked`` (never
  both). ``uq_invitations_open`` (org_id, email) WHERE neither accepted nor revoked: an address has one open invitation
  per organisation (citext: case-insensitive); an expired one stays open until it is revoked or resent.

Functions (pinned search_path; EXECUTE revoked from PUBLIC; granted to bridge_app where listed in ``FUNCTION_GRANTS``):

- ``app_nudge_candidates()`` -> (engagement_id, org_id, developer_id, member_id), SECURITY DEFINER, STABLE: the job
  only, with no user bound (a bound session is refused, insufficient_privilege). Every engagement that has not ended
  and is in ``INTEREST_CONFIRMED`` (a contact escalation, the contact-by date), ``NDA_PENDING`` (the NDA reminders),
  ``PROCUREMENT_ROUTE`` (the procurement escalation) or ``IN_IMPLEMENTATION`` with a milestone
  ``SUBMITTED_FOR_REVIEW`` (the milestone reminder and escalation): a superset of what is due, never less (no time
  filter: a hold's resume moves ``stage_entered_at``, and the policy's day counts are the job's); the job decides
  each again. ``member_id`` is an active member of the organisation to bind for the organisation's side (its roster,
  its escalation contact, the assignments): the named contact while an active member, else the earliest active owner
  or admin, else the earliest active member; never the engagement's developer; NULL when it has none. Ordered by
  organisation, creation and id.
- ``app_record_nudge(engagement uuid, kind text, key text)`` -> boolean, SECURITY DEFINER: the job only, with no user
  bound (insufficient_privilege otherwise); NULL arguments are refused (invalid_parameter_value), an unknown engagement
  too (no_data_found), a kind or key the CHECKs refuse is check_violation. Locks the engagement FOR KEY SHARE (an
  append in flight is waited for and its outcome read, as the thread's gate), then records the nudge with the
  engagement's organisation and the shared clock's time: true when this call recorded it (send it), false when it was
  already recorded or the engagement has ended (send nothing).
- ``app_accept_invitation(token_hash bytea, user_id uuid)`` -> uuid (the organisation), SECURITY DEFINER: for the
  signed-in user only (``user_id`` is ``app.user_id``; insufficient_privilege otherwise). The invitation with that
  hash, locked FOR UPDATE, is open: neither accepted nor revoked and ``expires_at`` after ``app_clock_now()``
  (no_data_found otherwise, one refusal for an unknown, spent, revoked, resent-over or expired token: the API's 404);
  the user is active with a verified email equal to the invitation's, case-insensitive (insufficient_privilege: the
  API's 403 ``invitation_email_mismatch``); an active membership already there is unique_violation (the API's 409).
  Then the membership is inserted with the invitation's roles, or a removed one reactivated with them, and the
  invitation marked accepted (the shared clock).
- ``app_invitation_preview(token_hash bytea)`` -> (org_name text, roles org_role[]), SECURITY DEFINER, STABLE: one row
  for an open invitation (as above), the organisation's legal name and the roles, nothing else; no row otherwise.
  Answers any session: the hash is the capability.
- Trigger and internal functions (no EXECUTE for any role): ``engagements_procurement_guard()``,
  ``org_niche_defaults_guard()``, ``invitations_guard()``, ``organizations_escalation_contact_guard()`` and
  ``memberships_last_owner_guard()`` (SECURITY INVOKER: ``current_user`` is the writer, the roster read under its RLS;
  the procurement guard reads the organisation's ``public_entity`` as the projection's owner on a state change);
  ``engagements_procurement_moved()`` and ``memberships_clear_team_seats()`` (SECURITY DEFINER); the replaced
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
- The nudge job (every 15 minutes, on the shared clock): ``SELECT * FROM app_nudge_candidates()`` with no user bound;
  for each, decide in a session bound to the developer (the engagement, its chain, holds, milestones) and to
  ``member_id`` (the organisation's roster, escalation contact and assignments) what is due; then, with no user bound,
  ``SELECT app_record_nudge(:engagement, :kind, :key)`` and queue the notifications in the same transaction only when
  it returns true. Keys are the job's: the stage entry's event id or seq with the business-day count, the milestone id,
  the contact-by date; never a name, address or free text. Org-side reads of the ledger (``escalated_at``) bind a
  member; a developer-side response never reads it.
- Invite (an admin; check the role first, 403, and the 20-open cap and an existing member's address, 409): INSERT the
  invitation with ``invited_by`` the caller, ``expires_at`` seven days on the shared clock and the SHA-256 of the
  token; ``uq_invitations_open`` is the race of two invitations to one address (409). Revoke: ``UPDATE invitations SET
  revoked_at = now() WHERE id = :id`` (no row: it was not open, 404 or 409). Resend: ``UPDATE invitations SET
  token_hash = :new, expires_at = :at WHERE id = :id``. An expired invitation blocks a new one to the same address
  until it is revoked or resent.
- The public preview: ``SELECT * FROM app_invitation_preview(:hash)`` (no row: 404). Accept (signed in):
  ``SELECT app_accept_invitation(:hash, :me)``; map no_data_found to 404, insufficient_privilege to 403
  ``invitation_email_mismatch``, unique_violation to 409; audit it.
- Remove a member: ``UPDATE memberships SET status = 'removed'`` (an admin for an unprotected member, an owner for
  anyone); change roles with ``UPDATE memberships SET roles``; SQLSTATE 55000 from ``memberships_last_owner_guard`` is
  the 409 ``last_owner`` (check it first, as today). Clear the removed member's open assignments in the same
  transaction (the database clears their niche defaults and escalation-contact seat).
- Niche defaults: an admin upserts ``INSERT ... ON CONFLICT (org_id, niche_id) DO UPDATE SET user_id =
  EXCLUDED.user_id`` and deletes; check_violation from the guard is the 422 (not a triage member). Escalation contact:
  ``UPDATE organizations SET escalation_contact_user_id = :user`` (check_violation: not an active member, 422).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = ("engagement_nudges", "org_niche_defaults")
RLS_TABLES = NEW_TABLES
PROCUREMENT_ROUTES = ("direct", "rfq_tender", "ppp_pip", "innovation_challenge", "pilot_mou")
NUDGE_KINDS = (
    "contact_escalation",
    "contact_overdue",
    "nda_reminder",
    "procurement_escalation",
    "milestone_reminder",
    "milestone_escalation",
)
PROCUREMENT_COLUMNS = (
    "procurement_route",
    "procurement_justification",
    "procurement_decided_at",
    "procurement_decided_by",
)
# Table privileges of bridge_app on this revision's tables; anything not listed is not granted. The ledger is
# written only by app_record_nudge.
APP_GRANTS: dict[str, str] = {
    "engagement_nudges": "SELECT",
    "org_niche_defaults": "SELECT, INSERT (id, org_id, niche_id, user_id), UPDATE (user_id), DELETE",
}
# New column grants of bridge_app on earlier tables (dropped with their columns on downgrade): the route and its
# justification (the time and the decider are the guard's); the escalation contact.
COLUMN_GRANTS = (
    "GRANT UPDATE (procurement_route, procurement_justification) ON TABLE engagements TO bridge_app;",
    "GRANT UPDATE (escalation_contact_user_id) ON TABLE organizations TO bridge_app;",
)
# Revision 0001's table-wide grants of bridge_app made column-scoped here: table -> (the privileges revoked, the
# column-scoped grant). The downgrade restores the table-wide grant (a table-level REVOKE also revokes the columns').
NARROWED_GRANTS: dict[str, tuple[str, str]] = {
    "memberships": ("UPDATE", "UPDATE (roles, status, updated_at)"),
    "invitations": (
        "INSERT, UPDATE",
        "INSERT (id, org_id, email, roles, token_hash, invited_by, expires_at),"
        " UPDATE (token_hash, expires_at, revoked_at)",
    ),
}

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
NUDGE_KIND_KNOWN = f"kind IN ({', '.join(repr(kind) for kind in NUDGE_KINDS)})"
NUDGE_KEY_VALID = "key ~ '^[A-Za-z0-9_.:+-]{1,120}$'"
INVITATION_ACCEPTED_OR_REVOKED = "accepted_at IS NULL OR revoked_at IS NULL"
OPEN_INVITATION = "accepted_at IS NULL AND revoked_at IS NULL"


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


# Predicates: revision 0001's member rule (narrowed by app.org_id), and D-68's rule of revision 0013 (the engagement's
# own developer reads none of the organisation's rows about it, even as a member).
_IN_ORG = "(app_org_id() IS NULL OR org_id = app_org_id())"
_MEMBER = f"app_is_member(org_id) AND {_IN_ORG}"
_ADMIN = f"app_is_member(org_id, '{{owner,admin}}') AND {_IN_ORG}"
# Revision 0001's invitation rule, verbatim: an admin, and only an owner for the protected roles (owner, signatory).
_ORG_ADMIN_0001 = "app_is_member(org_id, '{owner,admin}')"
_ORG_ADMIN_UNPROTECTED_0001 = (
    f"{_ORG_ADMIN_0001} AND (NOT (roles && '{{owner,signatory}}'::org_role[]) OR app_is_member(org_id, '{{owner}}'))"
)


def _not_its_developer(table: str) -> str:
    return (
        f"NOT EXISTS (SELECT 1 FROM engagements e WHERE e.id = {table}.engagement_id"
        " AND e.developer_id = app_user_id())"
    )


POLICIES: tuple[Policy, ...] = (
    # --- engagement_nudges: the organisation's members read (never the engagement's developer); nobody writes ---
    Policy("engagement_nudges", "SELECT", f"{_MEMBER} AND " + _not_its_developer("engagement_nudges")),
    # --- org_niche_defaults: members read; an admin writes (the guard: the user is a triage member) ---
    Policy("org_niche_defaults", "SELECT", _MEMBER),
    Policy("org_niche_defaults", "INSERT", check=_ADMIN),
    Policy("org_niche_defaults", "UPDATE", _ADMIN, _ADMIN),
    Policy("org_niche_defaults", "DELETE", _ADMIN),
)
# Revision 0001's invitation policies replaced here (dropped by name, created again on downgrade), and their
# replacements: the inviter is the caller; open invitations only are updated; both narrowed by app.org_id.
INVITATION_POLICIES_0001: tuple[Policy, ...] = (
    Policy("invitations", "INSERT", check=_ORG_ADMIN_UNPROTECTED_0001),
    Policy("invitations", "UPDATE", _ORG_ADMIN_0001, _ORG_ADMIN_UNPROTECTED_0001),
)
INVITATION_POLICIES: tuple[Policy, ...] = (
    Policy(
        "invitations", "INSERT", check=f"invited_by = app_user_id() AND {_ORG_ADMIN_UNPROTECTED_0001} AND {_IN_ORG}"
    ),
    Policy(
        "invitations",
        "UPDATE",
        f"{OPEN_INVITATION} AND {_ORG_ADMIN_0001} AND {_IN_ORG}",
        f"{_ORG_ADMIN_UNPROTECTED_0001} AND {_IN_ORG}",
    ),
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

-- The open engagements a nudge may be due for (REQ-NOT-05; the nudge job, every 15 minutes): ids only, to a session
-- with no user bound (the job; a signed-in request learns nothing about other tenants' engagements). A superset, never
-- less: INTEREST_CONFIRMED (contact escalation, contact overdue), NDA_PENDING (NDA reminders), PROCUREMENT_ROUTE
-- (procurement escalation) and IN_IMPLEMENTATION with a milestone submitted for review (milestone reminder and
-- escalation), with no time filter (a resume moves stage_entered_at; the day counts are the policy's, the job's). With
-- each, a member of the organisation the job binds for its side: the named contact while an active member, else the
-- earliest active owner or admin, else the earliest active member, never the engagement's developer; NULL for none.
CREATE FUNCTION app_nudge_candidates()
    RETURNS TABLE (engagement_id uuid, org_id uuid, developer_id uuid, member_id uuid)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_nudge_candidates: the nudge job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN QUERY
    SELECT e.id, e.org_id, e.developer_id,
           coalesce(
               (SELECT m.user_id FROM public.memberships m
                 WHERE m.org_id = e.org_id AND m.user_id = e.contact_user_id AND m.status = 'active'
                   AND m.user_id <> e.developer_id),
               (SELECT m.user_id FROM public.memberships m
                 WHERE m.org_id = e.org_id AND m.status = 'active' AND m.user_id <> e.developer_id
                   AND m.roles && CAST('{owner,admin}' AS public.org_role[])
                 ORDER BY m.created_at, m.id LIMIT 1),
               (SELECT m.user_id FROM public.memberships m
                 WHERE m.org_id = e.org_id AND m.status = 'active' AND m.user_id <> e.developer_id
                 ORDER BY m.created_at, m.id LIMIT 1))
      FROM public.engagements e
     WHERE e.ended_at IS NULL
       AND (e.state IN ('INTEREST_CONFIRMED', 'NDA_PENDING', 'PROCUREMENT_ROUTE')
            OR (e.state = 'IN_IMPLEMENTATION'
                AND EXISTS (SELECT 1 FROM public.milestones ms
                             WHERE ms.engagement_id = e.id AND ms.state = 'SUBMITTED_FOR_REVIEW')))
     ORDER BY e.org_id, e.created_at, e.id;
END;
$$;

-- Records one nudge before it is sent (REQ-NOT-05): the job only, with no user bound (bridge_app holds no INSERT on
-- the ledger, so no request records, and so suppresses, a nudge). Locks the engagement FOR KEY SHARE first (an append
-- in flight is waited for and its outcome read). Returns true when this call recorded it (send it), false when it was
-- already recorded or the engagement has ended (send nothing). The organisation is the engagement's; the time the
-- shared clock's. The kind and key CHECKs refuse what is not a nudge's (check_violation).
CREATE FUNCTION app_record_nudge(p_engagement uuid, p_kind text, p_key text) RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_org uuid;
    v_ended timestamptz;
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_record_nudge: the nudge job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_engagement IS NULL OR p_kind IS NULL OR p_key IS NULL THEN
        RAISE EXCEPTION 'app_record_nudge: name the engagement, the kind and the key'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    SELECT e.org_id, e.ended_at INTO v_org, v_ended FROM public.engagements e WHERE e.id = p_engagement FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'app_record_nudge: no engagement %', p_engagement USING ERRCODE = 'no_data_found';
    END IF;
    IF v_ended IS NOT NULL THEN
        RETURN false;
    END IF;
    INSERT INTO public.engagement_nudges (id, engagement_id, org_id, kind, key, sent_at)
    VALUES (public.uuid7(), p_engagement, v_org, p_kind, p_key, public.app_clock_now())
    ON CONFLICT (engagement_id, kind, key) DO NOTHING;
    RETURN FOUND;
END;
$$;

-- Accepts an invitation for the signed-in user (REQ-TEN-02; POST /api/invitations/{token}/accept): p_user is
-- app.user_id (insufficient_privilege otherwise). The invitation with that hash, locked FOR UPDATE, is open: neither
-- accepted nor revoked, and expiring after the shared clock's now (no_data_found otherwise: one refusal for an unknown,
-- spent, revoked, resent-over or expired token). The user is active with a verified email equal to the invitation's,
-- case-insensitive (insufficient_privilege otherwise); an active membership already there is unique_violation. Then
-- the membership is inserted with the invitation's roles, or a removed one reactivated with them, the invitation is
-- marked accepted (its guard stamps the shared clock) and the organisation returned. SECURITY DEFINER: the invitee is
-- not a member yet, so neither the invitation nor the roster is theirs to read or write.
CREATE FUNCTION app_accept_invitation(p_token_hash bytea, p_user uuid) RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_invitation public.invitations%ROWTYPE;
    v_status public.membership_status;
BEGIN
    IF p_user IS NULL OR public.app_user_id() IS DISTINCT FROM p_user THEN
        RAISE EXCEPTION 'app_accept_invitation: the signed-in user accepts for themselves only'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO v_invitation FROM public.invitations i WHERE i.token_hash = p_token_hash FOR UPDATE;
    IF NOT FOUND OR v_invitation.accepted_at IS NOT NULL OR v_invitation.revoked_at IS NOT NULL
       OR v_invitation.expires_at <= public.app_clock_now() THEN
        RAISE EXCEPTION 'app_accept_invitation: no open invitation with that token' USING ERRCODE = 'no_data_found';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.users u
         WHERE u.id = p_user AND u.status = 'active' AND u.email_verified_at IS NOT NULL
           AND lower(u.email::text) = lower(v_invitation.email::text)) THEN
        RAISE EXCEPTION 'app_accept_invitation: the invitation is for another email address, or yours is not verified'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT m.status INTO v_status FROM public.memberships m
     WHERE m.org_id = v_invitation.org_id AND m.user_id = p_user FOR UPDATE;
    IF v_status = 'active' THEN
        RAISE EXCEPTION 'app_accept_invitation: already an active member of the organisation'
            USING ERRCODE = 'unique_violation';
    ELSIF v_status IS NOT NULL THEN
        UPDATE public.memberships m SET status = 'active', roles = v_invitation.roles, updated_at = now()
         WHERE m.org_id = v_invitation.org_id AND m.user_id = p_user;
    ELSE
        INSERT INTO public.memberships (id, org_id, user_id, roles, status)
        VALUES (public.uuid7(), v_invitation.org_id, p_user, v_invitation.roles, 'active');
    END IF;
    UPDATE public.invitations i SET accepted_at = public.app_clock_now() WHERE i.id = v_invitation.id;
    RETURN v_invitation.org_id;
END;
$$;

-- The public preview of an invitation (GET /api/invitations/{token}): the organisation's legal name and the roles of
-- the open invitation with that hash (neither accepted nor revoked, expiring after the shared clock's now), nothing
-- else; no row otherwise. Answers any session: the hash is the capability.
CREATE FUNCTION app_invitation_preview(p_token_hash bytea)
    RETURNS TABLE (org_name text, roles public.org_role[])
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT CAST(o.legal_name AS text), i.roles
      FROM public.invitations i
      JOIN public.organizations o ON o.id = i.org_id
     WHERE i.token_hash = p_token_hash AND i.accepted_at IS NULL AND i.revoked_at IS NULL
       AND i.expires_at > public.app_clock_now()
$$;

-- organizations, BEFORE INSERT OR UPDATE OF escalation_contact_user_id, every role (REQ-TEN-02): the escalation contact
-- is NULL or an active member of the organisation (check_violation). SECURITY INVOKER: the roster is read under the
-- writer's RLS (an admin reads their organisation's; the owner everything), so a refusal tells a writer who is not a
-- member nothing about who is.
CREATE FUNCTION organizations_escalation_contact_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.escalation_contact_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.memberships m
         WHERE m.org_id = NEW.id AND m.user_id = NEW.escalation_contact_user_id AND m.status = 'active') THEN
        RAISE EXCEPTION 'organizations: the escalation contact is an active member of the organisation'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- org_niche_defaults, BEFORE INSERT OR UPDATE, every role (REQ-TEN-02): the default reviewer is an active owner,
-- admin, reviewer or signatory of the organisation (check_violation: the assignments' rule of revision 0013, which a
-- default feeds); a default's organisation, niche and creation time never change (check_violation); updated_at is the
-- shared clock on every update. SECURITY INVOKER: the roster is read under the writer's RLS.
CREATE FUNCTION org_niche_defaults_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF (NEW.id, NEW.org_id, NEW.niche_id, NEW.created_at) IS DISTINCT FROM
           (OLD.id, OLD.org_id, OLD.niche_id, OLD.created_at) THEN
            RAISE EXCEPTION 'org_niche_defaults: a default''s organisation, niche and creation time never change'
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.updated_at := public.app_clock_now();
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.memberships m
         WHERE m.org_id = NEW.org_id AND m.user_id = NEW.user_id AND m.status = 'active'
           AND m.roles && CAST('{owner,admin,reviewer,signatory}' AS public.org_role[])) THEN
        RAISE EXCEPTION 'org_niche_defaults: the default reviewer is an active owner, admin, reviewer or signatory of'
            ' the organisation' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- invitations, BEFORE INSERT OR UPDATE, every role (REQ-TEN-02): an invitation is created open (check_violation); its
-- organisation, address, roles, inviter and creation time never change (check_violation); an accepted or revoked
-- invitation never changes (object_not_in_prerequisite_state); revoked_at and accepted_at are the shared clock
-- whatever is sent. A resend changes token_hash and expires_at of an open invitation.
CREATE FUNCTION invitations_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.accepted_at IS NOT NULL OR NEW.revoked_at IS NOT NULL THEN
            RAISE EXCEPTION 'invitations: an invitation is created open' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.id, NEW.org_id, NEW.email, NEW.roles, NEW.invited_by, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.org_id, OLD.email, OLD.roles, OLD.invited_by, OLD.created_at) THEN
        RAISE EXCEPTION 'invitations: an invitation''s organisation, address, roles, inviter and creation time never'
            ' change' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.accepted_at IS NOT NULL OR OLD.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'invitations: an accepted or revoked invitation never changes'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF NEW.revoked_at IS NOT NULL THEN
        NEW.revoked_at := public.app_clock_now();
    END IF;
    IF NEW.accepted_at IS NOT NULL THEN
        NEW.accepted_at := public.app_clock_now();
    END IF;
    RETURN NEW;
END;
$$;

-- memberships, BEFORE UPDATE (REQ-TEN-02): the organisation's own writes never remove or demote its last active owner
-- (object_not_in_prerequisite_state). Concurrent removals are serialised on a transaction advisory lock per
-- organisation, so the second sees the first (each statement of this function takes a new snapshot at READ COMMITTED).
-- The table's owner is not judged: the definer functions (a claim's transfer and staff's roster correction, revision
-- 0002, may leave an organisation without an owner by design), the seed, a migration. SECURITY INVOKER: current_user is
-- the writer, and the roster is read under its RLS (only an owner changes a membership holding owner, revision 0001,
-- and reads the roster; a forged app.org_id hides it, and the refusal fails safe).
CREATE FUNCTION memberships_last_owner_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF current_user = (SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID)
    THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'active' AND 'owner' = ANY (OLD.roles)
       AND NOT (NEW.status = 'active' AND 'owner' = ANY (NEW.roles) AND NEW.org_id = OLD.org_id) THEN
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended('memberships.owners:' || OLD.org_id::text, 0));
        IF NOT EXISTS (
            SELECT 1 FROM public.memberships m
             WHERE m.org_id = OLD.org_id AND m.id <> OLD.id AND m.status = 'active' AND 'owner' = ANY (m.roles)) THEN
            RAISE EXCEPTION 'memberships: the organisation''s last active owner is neither removed nor demoted'
                USING ERRCODE = 'object_not_in_prerequisite_state';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- memberships, AFTER UPDATE OF status, roles WHEN an active membership leaves active or keeps none of owner, admin,
-- reviewer and signatory (REQ-TEN-02): a leaver's niche defaults go and the organisation's escalation contact is
-- cleared if it is them; a member who loses those roles loses their niche defaults (the default feeds an assignment,
-- whose assignee is a triage member). SECURITY DEFINER: whoever removes or demotes the member (an admin, staff, a
-- claim's transfer, the owner) holds no write of these rows for them.
CREATE FUNCTION memberships_clear_team_seats() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    DELETE FROM public.org_niche_defaults d WHERE d.org_id = OLD.org_id AND d.user_id = OLD.user_id;
    IF NEW.status IS DISTINCT FROM 'active' THEN
        UPDATE public.organizations o SET escalation_contact_user_id = NULL
         WHERE o.id = OLD.org_id AND o.escalation_contact_user_id = OLD.user_id;
    END IF;
    RETURN NULL;
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

# EXECUTE grants (EXECUTE revoked from PUBLIC first).
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_nudge_candidates()": ("bridge_app",),  # the nudge job, no user bound
    "app_record_nudge(uuid, text, text)": ("bridge_app",),  # the nudge job, no user bound
    "app_accept_invitation(bytea, uuid)": ("bridge_app",),  # the signed-in invitee
    "app_invitation_preview(bytea)": ("bridge_app",),  # the public preview (the hash is the capability)
}
TRIGGER_FUNCTIONS = (
    "engagements_procurement_guard()",
    "engagements_procurement_moved()",
    "organizations_escalation_contact_guard()",
    "org_niche_defaults_guard()",
    "invitations_guard()",
    "memberships_last_owner_guard()",
    "memberships_clear_team_seats()",
)
# Triggers this revision puts on earlier revisions' tables (dropped by name on downgrade; the tables stay).
EXISTING_TABLE_TRIGGERS = (
    ("engagements_procurement_guard", "engagements"),
    ("engagements_procurement_moved", "engagements"),
    ("organizations_escalation_contact_guard", "organizations"),
    ("invitations_guard", "invitations"),
    ("memberships_last_owner_guard", "memberships"),
    ("memberships_clear_team_seats", "memberships"),
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
CREATE TRIGGER engagement_nudges_no_update_delete
    BEFORE UPDATE OR DELETE ON engagement_nudges
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
CREATE TRIGGER engagement_nudges_no_truncate
    BEFORE TRUNCATE ON engagement_nudges
    FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();
CREATE TRIGGER org_niche_defaults_guard
    BEFORE INSERT OR UPDATE ON org_niche_defaults
    FOR EACH ROW EXECUTE FUNCTION org_niche_defaults_guard();
CREATE TRIGGER organizations_escalation_contact_guard
    BEFORE INSERT OR UPDATE OF escalation_contact_user_id ON organizations
    FOR EACH ROW EXECUTE FUNCTION organizations_escalation_contact_guard();
CREATE TRIGGER invitations_guard
    BEFORE INSERT OR UPDATE ON invitations
    FOR EACH ROW EXECUTE FUNCTION invitations_guard();
CREATE TRIGGER memberships_last_owner_guard
    BEFORE UPDATE ON memberships
    FOR EACH ROW EXECUTE FUNCTION memberships_last_owner_guard();
CREATE TRIGGER memberships_clear_team_seats
    AFTER UPDATE OF status, roles ON memberships
    FOR EACH ROW WHEN (OLD.status = 'active' AND (NEW.status IS DISTINCT FROM 'active'
                       OR NOT (NEW.roles && CAST('{owner,admin,reviewer,signatory}' AS org_role[]))))
    EXECUTE FUNCTION memberships_clear_team_seats();
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
    grants += COLUMN_GRANTS
    for table, (revoked, scoped) in NARROWED_GRANTS.items():
        grants.append(f"REVOKE {revoked} ON TABLE {table} FROM bridge_app;")
        grants.append(f"GRANT {scoped} ON TABLE {table} TO bridge_app;")
    grants += [f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in TRIGGER_FUNCTIONS]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    postgresql.ENUM(*PROCUREMENT_ROUTES, name="procurement_route").create(op.get_bind(), checkfirst=False)
    _alter_engagements()
    _alter_team_tables()
    _create_tables()
    _run_sql(PREDECESSORS_SQL)
    _run_sql(FUNCTIONS_SQL)  # after the tables: app_invitation_preview's body reads invitations
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql("\n".join(f"DROP POLICY {policy.name} ON {policy.table};" for policy in INVITATION_POLICIES_0001))
    _run_sql("\n".join(policy.create_sql() for policy in INVITATION_POLICIES))
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Destructive: drops every procurement decision (a public entity's route and justification, shown to both
    parties), the nudges ledger (after a downgrade and a new upgrade, the job would send again every nudge still due),
    the organisations' niche defaults and escalation contacts. Under the CLAUDE.md stop rule a downgrade of a database
    holding any of them is a destructive migration: back the database up and get the human's decision first. The
    downgrade refuses while any engagement holds a decision, either table has a row or an organisation names an
    escalation contact, unless run with ``-x allow_p28_loss=true`` (``alembic -x allow_p28_loss=true downgrade
    0014``). It refuses in any case while an engagement names a contact without a contact-by date (revision 0003's
    CHECK would refuse the row: give it its date, or end the engagement, first). Invitations and memberships keep their
    rows (an accepted invitation stays accepted); their grants and policies go back to revision 0001's."""
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
    holding = [
        table for table in NEW_TABLES if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
    ]
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM engagements WHERE procurement_route IS NOT NULL)")).scalar():
        holding.append("engagements (procurement decisions)")
    escalation = "SELECT EXISTS (SELECT 1 FROM organizations WHERE escalation_contact_user_id IS NOT NULL)"
    if bind.execute(sa.text(escalation)).scalar():
        holding.append("organizations (escalation contacts)")
    if holding and not allowed:
        raise RuntimeError(
            f"revision 0015 downgrade: {', '.join(holding)} hold data this revision's downgrade drops; back the"
            " database up, get the human's decision (CLAUDE.md: destructive migration), then run with"
            " -x allow_p28_loss=true"
        )
    # This revision's triggers on engagements first (the table stays). Dropping a table drops its policies, triggers,
    # indexes and grants (block_mutation() is revision 0002's and stays); dropping a column drops its grant.
    _run_sql("\n".join(f"DROP TRIGGER {trigger} ON {table};" for trigger, table in EXISTING_TABLE_TRIGGERS))
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    _run_sql("\n".join(f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS)))
    _run_sql("\n".join(f"DROP POLICY {policy.name} ON {policy.table};" for policy in INVITATION_POLICIES))
    _run_sql("\n".join(policy.create_sql() for policy in INVITATION_POLICIES_0001))
    _run_sql(
        "\n".join(
            f"REVOKE {revoked} ON TABLE {table} FROM bridge_app; GRANT {revoked} ON TABLE {table} TO bridge_app;"
            for table, (revoked, _scoped) in NARROWED_GRANTS.items()
        )
    )
    op.drop_index("uq_invitations_open", table_name="invitations")
    op.drop_constraint(op.f("ck_invitations_accepted_or_revoked"), "invitations", type_="check")
    op.drop_constraint(op.f("fk_organizations_escalation_contact_user_id_users"), "organizations", type_="foreignkey")
    op.drop_column("organizations", "escalation_contact_user_id")
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


def _create_tables() -> None:
    op.create_table(
        "engagement_nudges",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(NUDGE_KIND_KNOWN, name=op.f("ck_engagement_nudges_kind_known")),
        sa.CheckConstraint(NUDGE_KEY_VALID, name=op.f("ck_engagement_nudges_key_valid")),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_engagement_nudges_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_engagement_nudges_org_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_nudges")),
        sa.UniqueConstraint("engagement_id", "kind", "key", name=op.f("uq_engagement_nudges_engagement_id_kind_key")),
    )
    op.create_table(
        "org_niche_defaults",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("niche_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], name=op.f("fk_org_niche_defaults_niche_id_niches")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_org_niche_defaults_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_org_niche_defaults_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_niche_defaults")),
        sa.UniqueConstraint("org_id", "niche_id", name=op.f("uq_org_niche_defaults_org_id_niche_id")),
    )


def _alter_team_tables() -> None:
    op.add_column("organizations", sa.Column("escalation_contact_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_organizations_escalation_contact_user_id_users"),
        "organizations",
        "users",
        ["escalation_contact_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Validated: no invitation of any database was both accepted and revoked, nor two open for one address (the app
    # wrote none before P28; the claim transfer revokes open ones only).
    op.create_check_constraint(
        op.f("ck_invitations_accepted_or_revoked"), "invitations", INVITATION_ACCEPTED_OR_REVOKED
    )
    op.create_index(
        "uq_invitations_open",
        "invitations",
        ["org_id", "email"],
        unique=True,
        postgresql_where=sa.text(OPEN_INVITATION),
    )
