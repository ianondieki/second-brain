"""Schema v3 (prototype): the engagement tracker's tables, the dev/test clock and demo accounts (P1).

REQ-ENG-01 (engagement columns for stage deadlines, optimistic concurrency, the organisation's contact and the end of
an engagement; agreements, milestones, signatures and payment records), REQ-ENG-02 (``engagement_events``: append-only,
hash-chained, ``engagements.state`` its projection in the same statement; endorsements), D-37 (``users.demo_account``)
and the shared dev/test clock of PLAN.md §8 P5. Design: ``docs/platform/tasks/REQ-ENG-01.md``. Additive but for
one stricter CHECK: 7 new tables, 10 new enum types, new columns on ``engagements`` and ``users``, three new policies
and two triggers on ``engagements``, revision 0002's end-reason CHECK on ``engagements`` replaced by a NULL-safe one
(restored on downgrade), bridge_app's INSERT and column UPDATE on ``engagements``, and bridge_app's INSERT on
``users`` narrowed to every column but ``demo_account`` (the table-wide grant is restored on downgrade). Existing
engagements (fixtures only until now) get a genesis event, so every engagement has a chain. Nothing else of revisions
0001 and 0002 is changed or dropped.

The chain (``engagement_events_chain()``, BEFORE INSERT, SECURITY DEFINER). An append locks the engagement's row
(``SELECT ... FOR UPDATE``: appends to one engagement are serialised until commit, at any isolation level), reads the
chain head and sets ``seq`` (gapless from 1), ``prev_hash`` (32 zero bytes for the first event), ``created_at``
(``app_clock_now()``, under the lock) and ``hash = sha256(prev_hash || convert_to(canonical, 'UTF8'))``; values sent are
replaced. The canonical text (``engagement_event_canonical``, recomputed by ``bridge.engagements.chain``) is one JSON
object, keys in this order, no whitespace outside the payload:
``{"v":1,"id":…,"engagement_id":…,"seq":n,"created_at":µs,"actor_user_id":…|null,"actor_role":…,"command":…,``
``"from_state":…|null,"to_state":…,"end_reason":…|null,"stage_deadline_at":µs|null,"payload":<payload::text>}``, where
µs is integer microseconds since the Unix epoch and ``payload`` is PostgreSQL's jsonb text form (read it back as
``payload::text``). Any change here is a new canonical version ("v") and needs a new revision and verifier.

Rules of the chain: every engagement starts it when inserted (``engagements_genesis()``, AFTER INSERT: seq 1, command
``create``, from_state NULL, the engagement's state, its ``stage_entered_at`` as the time, actor the inserting party or
the system); an event names the engagement's current state as ``from_state`` (a stale one is refused) and none follows
a terminal state (DECLINED, WITHDRAWN, EXPIRED, TERMINATED, CLOSED); a main-path state is entered only from its legal
predecessors (``engagement_main_path_predecessors``, the database's backstop of the state machine's table; a side
branch, ON_HOLD, DISPUTED or INFO_REQUESTED, resumes only to the state it was entered from; a dispute's close,
DISPUTED -> CLOSED, is never the parties'); entering ``IN_IMPLEMENTATION``, ``DELIVERED``, ``SIGN_OFF`` or
``PAYMENT_FINAL`` needs a signed agreement, ``PAYMENT_FINAL`` also both parties' signatures of one acceptance
certificate, and ``CLOSED`` from ``PAYMENT_FINAL`` the developer's confirmation of the final payment (``milestone_id``
NULL) at the recorded amount (AC-TRACK-10, AC-TRACK-7, stage 13); "both parties" is always two people. The payload
holds only ids, codes, dates, amounts and digests (docs/spec/06 6.4 item 4; ``app_event_payload_is_valid``: an object
of at most 4 KB, keys ``[a-z][a-z0-9_]{0,62}``, strings ``[A-Za-z0-9_.:+-]{0,128}``, so no free text, e-mail address
or URL fits). UPDATE, DELETE and TRUNCATE are refused (trigger for every role, and no grant).

The projection (``engagement_events_project()``, AFTER INSERT, SECURITY DEFINER) writes ``state``, ``end_reason``,
``stage_entered_at`` (the event's time when the state changes), ``stage_deadline_at`` (the event's, when the state
changes; a same-state event may set a new one) and ``ended_at`` (the time a terminal state was entered) in the same
statement. ``engagements_guard()`` (BEFORE INSERT OR UPDATE, SECURITY DEFINER) sets ``stage_entered_at`` (the
database clock), ``ended_at`` and ``lock_version`` (0) on insert; on update it bumps ``lock_version``, keeps the
parties, proposal, version and origin, and refuses a ``state`` or ``end_reason`` that is not the latest event's (for
every role, the owner included: the state changes only by appending an event). ``engagements_members()`` (AFTER
INSERT OR UPDATE, after RLS) requires the named contact to be an active member of the organisation and the developer
not to be one. bridge_app holds no UPDATE on ``state``, ``end_reason``, the stage times or ``lock_version``.

Refusals reveal nothing about another party's engagement (review P1): on every tracker table the first BEFORE INSERT
trigger (``<table>_0_visible``, triggers fire in name order) is ``tracker_engagement_visible()``, SECURITY INVOKER,
which refuses a row naming an engagement the caller cannot see with one ``insufficient_privilege`` error, the same as
for an engagement that does not exist, before any SECURITY DEFINER trigger reads, locks or reports anything; checks
that read other users (the roster, TOTP enrolment) run in AFTER triggers, after RLS. Finalising an agreement and
planning its milestones are serialised on the agreement's row (``milestones_guard()`` reads it FOR SHARE).

Who writes what (RLS; parties only: the engagement's developer and the members of its organisation, narrowed by
``app.org_id``; staff admin reads every tracker row; the other tables' visibility follows the engagement's):

- ``engagements``: the developer inserts ``SUBMITTED`` (origin ``tagged``, with their open delivered tag, never with
  an organisation they belong to), an organisation signatory ``ORG_INTEREST`` (origin ``org_agent_match`` or
  ``org_browse``); both only for the proposal's current registered version of a published, clear proposal and an E2
  organisation that is neither suspended nor delisted. Its owner, admin or signatory names the contact (UPDATE of the
  contact columns only).
- ``engagement_events``: a party appends as themselves in their role (the developer as ``developer``, a member in a
  role they hold) or as the system (a job bound to the developer or to a member who may act, never a viewer; the row
  names no user).
- ``engagement_endorsements``: a party endorses the stage the engagement is in (a milestone only at
  ``IN_IMPLEMENTATION``; never a terminal stage), once per party, stage entry (``stage_round``, the database's) and
  milestone; ``auto`` names no user and is written for the bound party's own side (not by a viewer); a ``totp``
  endorsement needs TOTP enrolled. Append-only.
- Nothing is added to (endorsements, agreements, milestones, signatures) or changed in (agreements, milestones) an
  engagement that ended.
- ``agreements`` (developer, or the organisation's owner, admin or signatory, from ``NDA_SIGNED`` to
  ``AGREEMENT_SIGNING``): inserted as a draft; ``final`` needs the IP terms, the deemed-acceptance clause (days, 0 =
  never deemed accepted), the final PDF's SHA-256 and at least one milestone, and freezes them; ``signed`` needs both
  parties' (two people's) signatures of that PDF; one signed agreement per engagement; never deleted once final.
- ``milestones``: planned (inserted, edited, deleted) by the same editors while the agreement is a draft, then frozen;
  once it is signed and the engagement is ``IN_IMPLEMENTATION`` they move PLANNED -> IN_PROGRESS ->
  SUBMITTED_FOR_REVIEW (the developer) -> ACCEPTED or CHANGES_REQUESTED (the organisation's owner, admin, signatory or
  reviewer), CHANGES_REQUESTED -> IN_PROGRESS (the developer).
- ``signatures`` (internal simple e-signature, Release 1): the signer as themselves, the developer (D2 or above for an
  agreement) or an organisation signatory; an agreement only in its final version and at its PDF's hash, never with IP
  terms ``assignment`` or ``exclusive_licence`` (AC-TRACK-10); a ``totp`` step-up needs TOTP enrolled. Append-only.
- ``payment_records``: the organisation's owner, admin, signatory or finance member records a payment (from
  ``IN_IMPLEMENTATION`` to ``PAYMENT_FINAL``; not dated in the future); the engagement's developer confirms it once,
  with the amount received; nothing else ever changes and nothing is deleted. No code path moves money: the platform
  never holds funds (docs/spec/06 6.9 stage 12).

The dev/test clock (``test_clock``, one row, tenancy SYSTEM, SELECT for bridge_app): ``app_clock_now()`` is the database
clock plus the offset where the owner enabled the clock (``python -m bridge.seed`` enables it in dev, test and staging
databases and never in production), else the database clock; every tracker time above comes from it, so the API, the
worker and the database agree on "now". ``app_set_test_clock(offset)`` (SECURITY DEFINER, EXECUTE bridge_app) moves it
only forward, at most 366 days, and only where enabled. Its one caller is the test-clock router, which runs only when
``APP_ENV`` is not production and is left out of the production image.

``users.demo_account`` (D-37: only seeded demo data may go to a free LLM provider) is set only by the owner role (the
seed): bridge_app reads it but holds neither INSERT nor UPDATE on it.

Operating rules for the code that uses this schema:

- Append an event instead of writing ``engagements.state``; send ``from_state`` as the state the command was checked
  against and map a "the engagement is in state …" refusal to 409. Refresh the engagement after appending (its
  projection and ``lock_version`` changed in the database).
- Leave the database's columns out: ``seq``, ``prev_hash``, ``hash``, the event and evidence times, ``stage_round``,
  ``stage_entered_at``, ``ended_at``, ``lock_version``, ``confirmed_at``.
- Keep free text and personal data out of event payloads (a decline's free-text reason goes to a mutable store, with
  its salted digest in the payload), and out of ``payment_records.reference`` beyond the provider's reference.
- Close the tag when its engagement ends (``app_close_tag``); the projection does not.
- System events and ``auto`` endorsements are written by a job bound to the party it acts for (never a viewer).
- Map the tracker's one refusal for an engagement the caller cannot see ("no engagement of the caller's with that id",
  insufficient_privilege) to 404, like any cross-tenant reference.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types created by this revision, frozen here (the ORM enums in bridge.models.enums must match; a test compares).
ENUMS: dict[str, tuple[str, ...]] = {
    "engagement_actor_role": ("developer", "owner", "admin", "reviewer", "signatory", "finance", "system"),
    "engagement_party": ("developer", "org"),
    "endorsement_method": ("click", "totp", "passkey", "auto"),
    "contact_channel": ("email", "phone", "whatsapp", "video_call", "in_person"),
    "ip_terms": (
        "assignment",
        "exclusive_licence",
        "non_exclusive_licence",
        "development_contract",
        "revenue_share",
    ),
    "agreement_status": ("draft", "final", "signed"),
    "milestone_state": ("PLANNED", "IN_PROGRESS", "SUBMITTED_FOR_REVIEW", "ACCEPTED", "CHANGES_REQUESTED"),
    "signature_document_kind": ("mutual_nda", "agreement", "acceptance_certificate", "milestone_confirmation"),
    "step_up_method": ("totp", "passkey"),
    "payment_method": ("mpesa", "bank", "other"),
}
# Revision 0002's enums used by this revision's tables (not created or dropped here).
ENGAGEMENT_STATE = (
    "ORG_INTEREST",
    "SUBMITTED",
    "UNDER_REVIEW",
    "INTEREST_CONFIRMED",
    "PROCUREMENT_ROUTE",
    "CONTACT_MADE",
    "NDA_PENDING",
    "NDA_SIGNED",
    "NEGOTIATION",
    "AGREEMENT_SIGNING",
    "IN_IMPLEMENTATION",
    "DELIVERED",
    "SIGN_OFF",
    "PAYMENT_FINAL",
    "CLOSED",
    "DECLINED",
    "WITHDRAWN",
    "EXPIRED",
    "ON_HOLD",
    "DISPUTED",
    "TERMINATED",
    "INFO_REQUESTED",
)
ENGAGEMENT_END_REASON = (
    "NOT_PRIORITY",
    "ALREADY_IN_PROGRESS_INTERNALLY",
    "BUDGET",
    "NOT_RELEVANT",
    "NEEDS_MATURITY",
    "OTHER",
    "BY_DEVELOPER",
    "NO_REVIEW",
    "NO_DECISION",
    "CONTACT_NOT_MADE",
    "NO_DEV_RESPONSE",
)

# The tracker's tables (tenancy org_or_user, visibility via the engagement): Row-Level Security.
RLS_TABLES = (
    "engagement_events",
    "engagement_endorsements",
    "agreements",
    "milestones",
    "signatures",
    "payment_records",
)

# Table privileges of bridge_app on this revision's tables; anything not listed is not granted. Append-only tables get
# SELECT and INSERT only; UPDATE is column-scoped wherever some columns are never the app's.
APP_GRANTS: dict[str, str] = {
    "engagement_events": "SELECT, INSERT",
    "engagement_endorsements": "SELECT, INSERT",
    "agreements": (
        "SELECT, INSERT, UPDATE (ip_terms, exclusivity, deemed_acceptance_days, status, final_pdf_sha256, updated_at)"
    ),
    "milestones": (
        "SELECT, INSERT, DELETE, UPDATE (seq, deliverable, amount_kes_minor, due_date, review_window_bd, state,"
        " updated_at)"
    ),
    "signatures": "SELECT, INSERT",
    # The developer's one confirmation; confirmed_at is the database's.
    "payment_records": "SELECT, INSERT, UPDATE (confirmed_by, confirmed_amount_kes_minor)",
    "test_clock": "SELECT",  # moved only through app_set_test_clock()
}
# New grants of bridge_app on earlier tables (revoked on downgrade). Engagements: never state, end_reason, the stage
# times or lock_version (the database's), nor the keys.
APP_GRANTS_EARLIER_TABLES: dict[str, str] = {
    "engagements": "INSERT, UPDATE (contact_user_id, contact_channel, contact_by, updated_at)",
    "users": "SELECT (demo_account)",
}
# users.demo_account is the owner's (the seed): bridge_app's table-wide INSERT of revision 0001 becomes an INSERT of
# every other column. Restored to the table-wide grant on downgrade.
USERS_INSERTABLE_COLUMNS = (
    "id, email, email_verified_at, password_hash, display_name, locale, staff_role, status, totp_secret_enc,"
    " totp_pending_enc, totp_enabled_at, totp_last_counter, totp_recovery_hashes, updated_at, created_at, subject_salt"
)

TERMINAL = "'DECLINED', 'WITHDRAWN', 'EXPIRED', 'TERMINATED', 'CLOSED'"
DECLINED_REASONS = (
    "'NOT_PRIORITY', 'ALREADY_IN_PROGRESS_INTERNALLY', 'BUDGET', 'NOT_RELEVANT', 'NEEDS_MATURITY', 'OTHER',"
    " 'BY_DEVELOPER'"
)
EXPIRED_REASONS = "'NO_REVIEW', 'NO_DECISION', 'CONTACT_NOT_MADE', 'NO_DEV_RESPONSE'"


def _end_reason_matches(state_column: str) -> str:
    """Verbatim from bridge.engagements.models.end_reason_matches. NULL for DECLINED or EXPIRED without a reason (NULL
    IN (...) is NULL, which a CHECK lets through), so both CHECKs of this revision wrap it in coalesce(..., false):
    the events' and the replacement of revision 0002's ``ck_engagements_end_reason_matches_state``, which had that
    gap (restored on downgrade)."""
    return (
        f"({state_column} = 'DECLINED' AND end_reason IN ({DECLINED_REASONS}))"
        f" OR ({state_column} = 'EXPIRED' AND end_reason IN ({EXPIRED_REASONS}))"
        f" OR ({state_column} NOT IN ('DECLINED', 'EXPIRED') AND end_reason IS NULL)"
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


# Predicates. A tracker row is visible exactly when its engagement is (the engagements SELECT policies of revisions 0002
# and 0003: the developer, members of the organisation narrowed by app.org_id, and staff admin), so its policies read
# the engagement under the caller's own RLS.
_ORG_ROLES = "('owner', 'admin', 'reviewer', 'signatory', 'finance')"
_ENGAGEMENT_ROW = (
    "developer_id = app_user_id() OR (app_is_member(org_id) AND (app_org_id() IS NULL OR org_id = app_org_id()))"
)
_CONTACT_WRITER = "app_is_member(org_id, '{owner,admin,signatory}') AND (app_org_id() IS NULL OR org_id = app_org_id())"


def _engagement(table: str, condition: str = "true", column: str = "engagement_id") -> str:
    """The row's engagement is visible to the caller and meets ``condition`` (over ``e``)."""
    return f"EXISTS (SELECT 1 FROM engagements e WHERE e.id = {table}.{column} AND ({condition}))"


def _acts_in_role(table: str, role_column: str) -> str:
    """The caller holds the organisation role the row names (CASE: the cast runs only for an organisation role)."""
    return (
        f"CASE WHEN {table}.{role_column} IN {_ORG_ROLES}"
        f" THEN app_is_member(e.org_id, ARRAY[CAST(CAST({table}.{role_column} AS text) AS org_role)]) ELSE false END"
    )


_EDITOR = "e.developer_id = app_user_id() OR app_is_member(e.org_id, '{owner,admin,signatory}')"
# Who may bind a job that writes system events or automatic endorsements: the developer or an organisation member who
# may act (never a viewer; review P1, MINOR 5).
_ACTING_PARTY = "e.developer_id = app_user_id() OR app_is_member(e.org_id, '{owner,admin,signatory,reviewer,finance}')"
# Nothing is added to or changed in an engagement that ended (review P1, MINOR 6).
_OPEN = "e.ended_at IS NULL"

ENGAGEMENT_INSERT = (
    "end_reason IS NULL"
    " AND EXISTS (SELECT 1 FROM proposals p WHERE p.id = engagements.proposal_id"
    " AND p.owner_id = engagements.developer_id AND p.status = 'published' AND p.moderation_state = 'clear'"
    " AND p.current_version_id = engagements.version_id)"
    " AND EXISTS (SELECT 1 FROM organizations o WHERE o.id = engagements.org_id AND o.verification = 'e2'"
    " AND o.suspended_at IS NULL AND o.delisted_at IS NULL)"
    " AND ((state = 'SUBMITTED' AND origin = 'tagged' AND developer_id = app_user_id() AND contact_user_id IS NULL"
    " AND NOT app_is_member(org_id)"
    " AND EXISTS (SELECT 1 FROM tags t WHERE t.proposal_id = engagements.proposal_id AND t.org_id = engagements.org_id"
    " AND t.developer_id = app_user_id() AND t.status = 'delivered' AND t.closed_at IS NULL))"
    " OR (state = 'ORG_INTEREST' AND origin IN ('org_agent_match', 'org_browse')"
    " AND app_is_member(org_id, '{signatory}') AND (app_org_id() IS NULL OR org_id = app_org_id())))"
)

POLICIES: tuple[Policy, ...] = (
    # --- engagements (revision 0002 table): staff admin reads; the parties create and the organisation names a contact
    Policy("engagements", "SELECT", "app_is_staff('{admin}')", suffix="staff"),
    Policy("engagements", "INSERT", check=ENGAGEMENT_INSERT),
    # The developer passes USING too, so SELECT ... FOR UPDATE (optimistic concurrency) works for both parties.
    Policy("engagements", "UPDATE", _ENGAGEMENT_ROW, _CONTACT_WRITER),
    # --- engagement_events: a party appends as themselves in their role, or as the system (a job bound to a party;
    # staff, who read every engagement, write none) ---
    Policy("engagement_events", "SELECT", _engagement("engagement_events")),
    Policy(
        "engagement_events",
        "INSERT",
        check=_engagement(
            "engagement_events",
            "(engagement_events.actor_role = 'developer' AND engagement_events.actor_user_id = app_user_id()"
            " AND e.developer_id = app_user_id())"
            " OR (engagement_events.actor_user_id = app_user_id() AND "
            + _acts_in_role("engagement_events", "actor_role")
            + ") OR (engagement_events.actor_role = 'system' AND engagement_events.actor_user_id IS NULL"
            f" AND ({_ACTING_PARTY}))",
        )
        # A dispute's closing outcome is the mediator's (after the prototype), never the parties' (review P1, MAJOR 4).
        + " AND NOT (engagement_events.from_state = 'DISPUTED' AND engagement_events.to_state = 'CLOSED')",
    ),
    # --- engagement_endorsements: each party endorses its own side (auto: a job bound to that party) ---
    Policy("engagement_endorsements", "SELECT", _engagement("engagement_endorsements")),
    Policy(
        "engagement_endorsements",
        "INSERT",
        check=_engagement(
            "engagement_endorsements",
            f"{_OPEN} AND ((engagement_endorsements.party = 'developer' AND e.developer_id = app_user_id()"
            " AND (engagement_endorsements.user_id = app_user_id() OR engagement_endorsements.method = 'auto'))"
            " OR (engagement_endorsements.party = 'org' AND ((engagement_endorsements.method = 'auto'"
            " AND app_is_member(e.org_id, '{owner,admin,signatory,reviewer,finance}'))"
            " OR (engagement_endorsements.user_id = app_user_id() AND "
            + _acts_in_role("engagement_endorsements", "role")
            + "))))",
        ),
    ),
    # --- agreements: drafted by the developer or the organisation's owner, admin or signatory, from NDA_SIGNED ---
    Policy("agreements", "SELECT", _engagement("agreements")),
    Policy(
        "agreements",
        "INSERT",
        check="created_by = app_user_id() AND status = 'draft' AND "
        + _engagement(
            "agreements", f"{_OPEN} AND e.state IN ('NDA_SIGNED', 'NEGOTIATION', 'AGREEMENT_SIGNING') AND ({_EDITOR})"
        ),
    ),
    Policy(
        "agreements",
        "UPDATE",
        _engagement("agreements", _EDITOR),
        _engagement("agreements", f"{_OPEN} AND ({_EDITOR})"),
    ),
    # --- milestones: planned by the same editors; the developer moves them forward, the organisation decides ---
    Policy("milestones", "SELECT", _engagement("milestones")),
    Policy("milestones", "INSERT", check=_engagement("milestones", f"{_OPEN} AND ({_EDITOR})")),
    Policy("milestones", "DELETE", _engagement("milestones", _EDITOR)),
    Policy(
        "milestones",
        "UPDATE",
        _engagement(
            "milestones",
            "e.developer_id = app_user_id() OR app_is_member(e.org_id, '{owner,admin,signatory,reviewer}')",
        ),
        _engagement(
            "milestones",
            f"{_OPEN} AND ((milestones.state = 'PLANNED' AND ({_EDITOR}))"
            " OR (milestones.state IN ('IN_PROGRESS', 'SUBMITTED_FOR_REVIEW') AND e.developer_id = app_user_id())"
            " OR (milestones.state IN ('ACCEPTED', 'CHANGES_REQUESTED')"
            " AND app_is_member(e.org_id, '{owner,admin,signatory,reviewer}')))",
        ),
    ),
    # --- signatures: the signer as themselves; the developer (D2 for an agreement) or an organisation signatory ---
    Policy("signatures", "SELECT", _engagement("signatures")),
    Policy(
        "signatures",
        "INSERT",
        check="signer_user_id = app_user_id() AND "
        + _engagement(
            "signatures",
            f"{_OPEN} AND ((signatures.party = 'developer' AND e.developer_id = app_user_id()"
            " AND (signatures.document_kind <> 'agreement' OR EXISTS (SELECT 1 FROM developer_profiles d"
            " WHERE d.user_id = app_user_id() AND d.verification_level >= 'd2')))"
            " OR (signatures.party = 'org' AND app_is_member(e.org_id, '{signatory}')))",
        ),
    ),
    # --- payment_records: recorded by the organisation, confirmed once by the developer ---
    Policy("payment_records", "SELECT", _engagement("payment_records")),
    Policy(
        "payment_records",
        "INSERT",
        check="recorded_by = app_user_id() AND confirmed_by IS NULL AND "
        + _engagement(
            "payment_records",
            "e.state IN ('IN_IMPLEMENTATION', 'DELIVERED', 'SIGN_OFF', 'PAYMENT_FINAL')"
            " AND app_is_member(e.org_id, '{owner,admin,signatory,finance}')",
        ),
    ),
    Policy(
        "payment_records",
        "UPDATE",
        _engagement("payment_records", "e.developer_id = app_user_id()"),
        "confirmed_by = app_user_id() AND " + _engagement("payment_records", "e.developer_id = app_user_id()"),
    ),
)

# A CHECK helper, created before the tables (EXECUTE bridge_app: a CHECK runs its functions with the writer's
# privileges).
CHECK_HELPERS_SQL = r"""
-- An engagement event's payload (docs/spec/06 6.4 item 4: ids, enums, amounts and salted digests only): a JSON
-- object of at most 4 KB whose keys are lower-case codes and whose strings are ids, codes, dates, times or hex digests
-- (at most 128 characters of letters, digits and _ . : + -). Free text, e-mail addresses and URLs do not fit, so no
-- plaintext personal data enters the hash chain (AC-IP-7); they belong in a mutable store beside it.
CREATE FUNCTION app_event_payload_is_valid(p_payload jsonb) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT jsonb_typeof(p_payload) = 'object'
       AND octet_length(p_payload::text) <= 4096
       AND NOT jsonb_path_exists(p_payload,
               'strict $.** ? (@.type() == "object").keyvalue() ? (!(@.key like_regex "^[a-z][a-z0-9_]{0,62}$"))')
       AND NOT jsonb_path_exists(p_payload,
               'strict $.** ? (@.type() == "string" && !(@ like_regex "^[A-Za-z0-9_.:+-]{0,128}$"))')
$$;
"""

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 and 0002: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS). SECURITY DEFINER functions run as
# bridge_owner, which bypasses RLS (ENABLED, not FORCED).
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- The shared clock: the database clock plus the test clock's offset where the owner enabled it (dev, test and staging
-- databases), else the database clock. Every time the tracker's triggers set comes from it, and the API and the worker
-- read it, so a moved test clock moves deadlines, reminders and evidence times together.
CREATE FUNCTION app_clock_now() RETURNS timestamptz
    LANGUAGE sql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT clock_timestamp() + coalesce((SELECT c.clock_offset FROM public.test_clock c WHERE c.enabled), interval '0')
$$;

-- Moves the dev/test clock to p_offset ahead of the database clock and returns the clock's new now(): only forward,
-- at most 366 days (CHECK), and only where the owner enabled the clock. The test-clock router is the only caller; it
-- runs only when APP_ENV is not production and is not in the production image, and a production database never has
-- the clock enabled, so this refuses there whoever calls it.
CREATE FUNCTION app_set_test_clock(p_offset interval) RETURNS timestamptz
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_clock public.test_clock%ROWTYPE;
BEGIN
    SELECT * INTO v_clock FROM public.test_clock c WHERE c.singleton FOR UPDATE;
    IF NOT FOUND OR NOT v_clock.enabled THEN
        RAISE EXCEPTION 'app_set_test_clock: the test clock is not enabled in this database'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_offset IS NULL OR p_offset < v_clock.clock_offset THEN
        RAISE EXCEPTION 'app_set_test_clock: the test clock only moves forward (its offset is %)', v_clock.clock_offset
            USING ERRCODE = 'check_violation';
    END IF;
    UPDATE public.test_clock c
       SET clock_offset = p_offset, updated_at = now(), updated_by = public.app_user_id()
     WHERE c.singleton;
    RETURN public.app_clock_now();
END;
$$;

-- The canonical text hashed into engagement_events.hash (documented in this revision's docstring and recomputed by
-- bridge.engagements.chain). concat() skips NULLs, so every nullable field is coalesced to the JSON null.
CREATE FUNCTION engagement_event_canonical(e public.engagement_events) RETURNS text
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT concat(
        '{"v":1',
        ',"id":', to_json(e.id::text)::text,
        ',"engagement_id":', to_json(e.engagement_id::text)::text,
        ',"seq":', e.seq::text,
        ',"created_at":', ((extract(epoch FROM e.created_at) * 1000000)::bigint)::text,
        ',"actor_user_id":', coalesce(to_json(e.actor_user_id::text)::text, 'null'),
        ',"actor_role":', to_json(e.actor_role::text)::text,
        ',"command":', to_json(e.command)::text,
        ',"from_state":', coalesce(to_json(e.from_state::text)::text, 'null'),
        ',"to_state":', to_json(e.to_state::text)::text,
        ',"end_reason":', coalesce(to_json(e.end_reason::text)::text, 'null'),
        ',"stage_deadline_at":',
        coalesce(((extract(epoch FROM e.stage_deadline_at) * 1000000)::bigint)::text, 'null'),
        ',"payload":', e.payload::text,
        '}')
$$;
"""

TRIGGERS_SQL = r"""
-- Runs first on every tracker table (its trigger, <table>_0_visible, sorts before the table's other BEFORE INSERT
-- triggers, and triggers fire in name order): the new row names an engagement the caller can see (a party, or staff
-- admin, whom the table's RLS then refuses), else one refusal, the same for an engagement that does not exist and one
-- of other parties. So no SECURITY DEFINER trigger reads, locks (FOR UPDATE) or reports anything about another
-- party's engagement (its state, stage, agreement, members) before RLS refuses the row (review P1, MAJOR 1). SECURITY
-- INVOKER: the caller's RLS decides; the owner, and definer code such as the genesis, see every engagement.
CREATE FUNCTION tracker_engagement_visible() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.engagement_id IS NULL OR NOT EXISTS (SELECT 1 FROM public.engagements e WHERE e.id = NEW.engagement_id) THEN
        RAISE EXCEPTION 'no engagement of the caller''s with that id' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

-- The main path's legal predecessors (docs/spec/06 6.9 main path; 3b PROCUREMENT_ROUTE around stage 3; a disputed
-- first contact returns to stage 3; a new agreement version after a final one returns to NEGOTIATION; a dispute may
-- close as the mediator's outcome). The state machine's transition table stays the authority: this is the database's
-- backstop, so no evidence gate is skipped by jumping ahead (review P1, MAJOR 4). NULL for a side state (DECLINED,
-- WITHDRAWN, EXPIRED, ON_HOLD, DISPUTED, TERMINATED, INFO_REQUESTED), entered as the state machine allows; SUBMITTED
-- and ORG_INTEREST are only ever a genesis (or a resume). Internal: no EXECUTE for any role.
CREATE FUNCTION engagement_main_path_predecessors(p_state engagement_state) RETURNS engagement_state[]
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

-- Appends one event to its engagement's chain. The engagement's row lock serialises appends until commit (at READ
-- COMMITTED the head read below then sees the previous append; at REPEATABLE READ or SERIALIZABLE a concurrent append
-- makes the lock fail with a serialization error, so the caller retries). Sets seq, prev_hash, created_at and hash
-- whatever was sent. The first event records the engagement as inserted (engagements_genesis(), or this revision's
-- backfill); every later one starts from the engagement's current state, none follows a terminal state, a main-path
-- state is entered only from its legal predecessors (a side branch resumes only to the state it was entered from),
-- and the main path's legal steps need their evidence (AC-TRACK-10, AC-TRACK-7): IN_IMPLEMENTATION, DELIVERED,
-- SIGN_OFF and PAYMENT_FINAL a signed agreement, PAYMENT_FINAL also the acceptance certificate signed by both parties
-- (two people), CLOSED from PAYMENT_FINAL the final payment confirmed at the recorded amount. Runs after
-- tracker_engagement_visible(), so it locks and reports only an engagement the caller can see. SECURITY DEFINER:
-- reads the chain and the engagement's agreements, signatures and payments whatever the caller's visibility.
CREATE FUNCTION engagement_events_chain() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_engagement public.engagements%ROWTYPE;
    v_last public.engagement_events%ROWTYPE;
    v_resume public.engagement_state;
BEGIN
    IF NEW.id IS NULL OR NEW.engagement_id IS NULL THEN
        RAISE EXCEPTION 'engagement_events: id and engagement_id are required' USING ERRCODE = 'not_null_violation';
    END IF;
    SELECT * INTO v_engagement FROM public.engagements e WHERE e.id = NEW.engagement_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'engagement_events: no engagement %', NEW.engagement_id USING ERRCODE = 'foreign_key_violation';
    END IF;
    SELECT * INTO v_last FROM public.engagement_events ev
     WHERE ev.engagement_id = NEW.engagement_id ORDER BY ev.seq DESC LIMIT 1;
    IF v_last.id IS NULL THEN
        IF NEW.from_state IS NOT NULL OR NEW.to_state IS DISTINCT FROM v_engagement.state
           OR NEW.end_reason IS DISTINCT FROM v_engagement.end_reason THEN
            RAISE EXCEPTION 'engagement_events: the first event records the engagement as inserted'
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.seq := 1;
        NEW.prev_hash := decode(repeat('00', 32), 'hex');
        NEW.created_at := v_engagement.stage_entered_at;
        NEW.stage_deadline_at := v_engagement.stage_deadline_at;
    ELSE
        IF v_last.to_state IN ('DECLINED', 'WITHDRAWN', 'EXPIRED', 'TERMINATED', 'CLOSED') THEN
            RAISE EXCEPTION 'engagement_events: the engagement ended in % and takes no further event', v_last.to_state
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.from_state IS DISTINCT FROM v_last.to_state THEN
            RAISE EXCEPTION 'engagement_events: the engagement is in state %, not %', v_last.to_state,
                coalesce(NEW.from_state::text, 'NULL')
                USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.to_state IS DISTINCT FROM NEW.from_state
           AND public.engagement_main_path_predecessors(NEW.to_state) IS NOT NULL THEN
            IF NEW.from_state IN ('ON_HOLD', 'DISPUTED', 'INFO_REQUESTED')
               AND NOT (NEW.from_state = 'DISPUTED' AND NEW.to_state = 'CLOSED') THEN
                SELECT ev.from_state INTO v_resume FROM public.engagement_events ev
                 WHERE ev.engagement_id = NEW.engagement_id AND ev.to_state = NEW.from_state
                   AND ev.from_state IS DISTINCT FROM ev.to_state
                 ORDER BY ev.seq DESC LIMIT 1;
                IF NEW.to_state IS DISTINCT FROM v_resume THEN
                    RAISE EXCEPTION 'engagement_events: % resumes to % (the state it was entered from), not %',
                        NEW.from_state, coalesce(v_resume::text, 'NULL'), NEW.to_state
                        USING ERRCODE = 'check_violation';
                END IF;
            ELSIF NOT (NEW.from_state = ANY (public.engagement_main_path_predecessors(NEW.to_state))) THEN
                RAISE EXCEPTION 'engagement_events: % cannot follow %', NEW.to_state, NEW.from_state
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.to_state IN ('IN_IMPLEMENTATION', 'DELIVERED', 'SIGN_OFF', 'PAYMENT_FINAL') AND NOT EXISTS (
                SELECT 1 FROM public.agreements a WHERE a.engagement_id = NEW.engagement_id AND a.status = 'signed'
            ) THEN
                RAISE EXCEPTION 'engagement_events: % needs an agreement signed by both parties', NEW.to_state
                    USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.to_state = 'PAYMENT_FINAL' AND NOT EXISTS (
                SELECT 1 FROM public.signatures s
                 WHERE s.engagement_id = NEW.engagement_id AND s.document_kind = 'acceptance_certificate'
                 GROUP BY s.document_ref, s.document_sha256
                HAVING count(DISTINCT s.party) = 2 AND count(DISTINCT s.signer_user_id) = 2
            ) THEN
                RAISE EXCEPTION 'engagement_events: PAYMENT_FINAL needs the acceptance certificate signed by both'
                    ' parties' USING ERRCODE = 'check_violation';
            END IF;
            IF NEW.to_state = 'CLOSED' AND NEW.from_state = 'PAYMENT_FINAL' AND NOT EXISTS (
                SELECT 1 FROM public.payment_records p
                 WHERE p.engagement_id = NEW.engagement_id AND p.milestone_id IS NULL AND p.confirmed_at IS NOT NULL
                   AND p.confirmed_amount_kes_minor = p.amount_kes_minor
            ) THEN
                RAISE EXCEPTION 'engagement_events: CLOSED needs the developer''s confirmation of the final payment at'
                    ' the recorded amount' USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        NEW.seq := v_last.seq + 1;
        NEW.prev_hash := v_last.hash;
        NEW.created_at := public.app_clock_now();
    END IF;
    NEW.hash := sha256(NEW.prev_hash || convert_to(public.engagement_event_canonical(NEW), 'UTF8'));
    RETURN NEW;
END;
$$;

-- engagements.state (and its stage times and end) is the projection of the chain, written in the same statement as
-- the event. The genesis records the engagement as inserted, so there is nothing to project.
CREATE FUNCTION engagement_events_project() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.from_state IS NULL THEN
        RETURN NULL;
    END IF;
    UPDATE public.engagements e
       SET state = NEW.to_state,
           end_reason = NEW.end_reason,
           stage_entered_at = CASE WHEN NEW.to_state <> NEW.from_state THEN NEW.created_at ELSE e.stage_entered_at END,
           stage_deadline_at = CASE WHEN NEW.to_state <> NEW.from_state THEN NEW.stage_deadline_at
                                    ELSE coalesce(NEW.stage_deadline_at, e.stage_deadline_at) END,
           ended_at = CASE WHEN NEW.to_state IN ('DECLINED', 'WITHDRAWN', 'EXPIRED', 'TERMINATED', 'CLOSED')
                           THEN NEW.created_at END,
           updated_at = now()
     WHERE e.id = NEW.engagement_id;
    RETURN NULL;
END;
$$;

-- On insert: the database's stage time (its clock), end and lock_version. On update: lock_version moves on every
-- change (the ORM's server-side version counter), the parties, proposal, version and origin never change, and the
-- state and end reason are always the latest event's, for every role (the owner included), so they change only by
-- appending an event. (Who the contact and the developer may be is engagements_members(), after RLS.) SECURITY
-- DEFINER: reads the chain whatever the caller's visibility.
CREATE FUNCTION engagements_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_last public.engagement_events%ROWTYPE;
BEGIN
    IF TG_OP = 'INSERT' THEN
        NEW.stage_entered_at := public.app_clock_now();
        NEW.ended_at := CASE WHEN NEW.state IN ('DECLINED', 'WITHDRAWN', 'EXPIRED', 'TERMINATED', 'CLOSED')
                             THEN NEW.stage_entered_at END;
        NEW.lock_version := 0;
        RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id OR NEW.proposal_id <> OLD.proposal_id OR NEW.org_id <> OLD.org_id
       OR NEW.developer_id <> OLD.developer_id OR NEW.version_id <> OLD.version_id OR NEW.origin <> OLD.origin
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'engagements: the parties, proposal, version and origin never change'
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT * INTO v_last FROM public.engagement_events ev WHERE ev.engagement_id = NEW.id ORDER BY ev.seq DESC LIMIT 1;
    IF NEW.state IS DISTINCT FROM v_last.to_state OR NEW.end_reason IS DISTINCT FROM v_last.end_reason THEN
        RAISE EXCEPTION 'engagements: the state changes only by appending an engagement event'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.lock_version := OLD.lock_version + 1;
    RETURN NEW;
END;
$$;

-- Starts the chain of a new engagement: the genesis event (seq 1, command 'create') records it as inserted, acted by
-- the inserting party (the developer, or the organisation member in their strongest role) or else by the system.
CREATE FUNCTION engagements_genesis() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
    v_role public.engagement_actor_role;
BEGIN
    IF v_user = NEW.developer_id THEN
        v_role := 'developer';
    ELSIF v_user IS NOT NULL THEN
        SELECT CASE
                 WHEN m.roles && '{signatory}'::public.org_role[] THEN 'signatory'
                 WHEN m.roles && '{owner}'::public.org_role[] THEN 'owner'
                 WHEN m.roles && '{admin}'::public.org_role[] THEN 'admin'
                 WHEN m.roles && '{reviewer}'::public.org_role[] THEN 'reviewer'
                 WHEN m.roles && '{finance}'::public.org_role[] THEN 'finance'
               END
          INTO v_role
          FROM public.memberships m
         WHERE m.org_id = NEW.org_id AND m.user_id = v_user AND m.status = 'active';
    END IF;
    v_role := coalesce(v_role, 'system');
    INSERT INTO public.engagement_events (id, engagement_id, actor_user_id, actor_role, command, to_state, end_reason,
                                          payload)
    VALUES (public.uuid7(), NEW.id, CASE WHEN v_role = 'system' THEN NULL ELSE v_user END, v_role, 'create',
            NEW.state, NEW.end_reason,
            jsonb_build_object('origin', NEW.origin::text, 'version_id', NEW.version_id::text));
    RETURN NULL;
END;
$$;

-- An endorsement is of the stage the engagement is in (under its row lock, so no append slips in between), never of a
-- terminal one, and a milestone only at IN_IMPLEMENTATION. stage_round (the number of times the engagement entered
-- the stage) and endorsed_at are the database's. Runs after tracker_engagement_visible(); the TOTP check, which reads
-- another user, runs after RLS (engagement_endorsements_totp()). SECURITY DEFINER: reads the chain.
CREATE FUNCTION engagement_endorsements_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_state public.engagement_state;
BEGIN
    SELECT e.state INTO v_state FROM public.engagements e WHERE e.id = NEW.engagement_id FOR UPDATE;
    IF v_state IS DISTINCT FROM NEW.stage THEN
        RAISE EXCEPTION 'engagement_endorsements: only the stage the engagement is in (%) can be endorsed', v_state
            USING ERRCODE = 'check_violation';
    END IF;
    IF v_state IN ('DECLINED', 'WITHDRAWN', 'EXPIRED', 'TERMINATED', 'CLOSED') THEN
        RAISE EXCEPTION 'engagement_endorsements: the engagement ended in % and takes no endorsement', v_state
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.milestone_id IS NOT NULL AND NEW.stage <> 'IN_IMPLEMENTATION' THEN
        RAISE EXCEPTION 'engagement_endorsements: a milestone is endorsed at IN_IMPLEMENTATION'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.stage_round := (
        SELECT count(*) FROM public.engagement_events ev
         WHERE ev.engagement_id = NEW.engagement_id AND ev.to_state = NEW.stage
           AND ev.from_state IS DISTINCT FROM ev.to_state);
    NEW.endorsed_at := public.app_clock_now();
    RETURN NEW;
END;
$$;

-- An agreement version is inserted as a draft and edited while it is one. Marking it final needs at least one
-- milestone (the CHECK needs the IP terms, the deemed-acceptance clause and the PDF hash) and freezes it; a final
-- version only becomes signed, once both parties (two people) signed its PDF hash; a signed one never changes; only
-- drafts are ever deleted. The keys never change. Finalisation and milestone planning are serialised on the agreement's
-- row: this UPDATE holds its row lock, and milestones_guard() takes FOR SHARE on it before reading the status, so a
-- milestone written meanwhile waits for this transaction and then sees the final status, and a finalisation waits for
-- a milestone deletion in flight and then counts what is left (review P1, MAJOR 2). SECURITY DEFINER: reads milestones
-- and signatures whatever the caller sees.
CREATE FUNCTION agreements_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'draft' THEN
            RAISE EXCEPTION 'agreements: a version is inserted as a draft' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
            RAISE EXCEPTION 'agreements: a final or signed agreement is never deleted'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN OLD;
    END IF;
    IF NEW.id <> OLD.id OR NEW.engagement_id <> OLD.engagement_id OR NEW.version <> OLD.version
       OR NEW.created_by <> OLD.created_by OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'agreements: the engagement, version and author never change' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'draft' THEN
        IF NEW.status = 'signed' THEN
            RAISE EXCEPTION 'agreements: a draft is marked final before it is signed' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.status = 'final' AND NOT EXISTS (SELECT 1 FROM public.milestones m WHERE m.agreement_id = NEW.id) THEN
            RAISE EXCEPTION 'agreements: marking a version final needs at least one milestone'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.ip_terms, NEW.exclusivity, NEW.deemed_acceptance_days, NEW.final_pdf_sha256)
       IS DISTINCT FROM (OLD.ip_terms, OLD.exclusivity, OLD.deemed_acceptance_days, OLD.final_pdf_sha256)
       OR NEW.status = 'draft' OR (OLD.status = 'signed' AND NEW.status <> 'signed') THEN
        RAISE EXCEPTION 'agreements: a final or signed agreement is frozen' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'final' AND NEW.status = 'signed' AND NOT EXISTS (
        SELECT 1 FROM public.signatures s
         WHERE s.engagement_id = NEW.engagement_id AND s.document_kind = 'agreement' AND s.document_ref = NEW.id
           AND s.document_sha256 = NEW.final_pdf_sha256
        HAVING count(DISTINCT s.party) = 2 AND count(DISTINCT s.signer_user_id) = 2
    ) THEN
        RAISE EXCEPTION 'agreements: an agreement is signed once both parties signed its final PDF (two people)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- Milestones are planned (inserted, edited, deleted, all PLANNED) while their agreement is a draft, and frozen once it
-- is final. Once it is signed and the engagement is IN_IMPLEMENTATION they follow the sub-tracker (docs/spec/06 6.9);
-- which party makes each step is the UPDATE policy's. The agreement is read FOR SHARE (serialised with its
-- finalisation, agreements_guard()) and only as the agreement of the row's own engagement, so naming another
-- engagement's agreement reveals nothing of it. SECURITY DEFINER: reads the agreement and the engagement.
CREATE FUNCTION milestones_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_status public.agreement_status;
    v_state public.engagement_state;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT a.status INTO v_status FROM public.agreements a
         WHERE a.id = OLD.agreement_id AND a.engagement_id = OLD.engagement_id FOR SHARE;
        IF v_status IS DISTINCT FROM 'draft' THEN
            RAISE EXCEPTION 'milestones: a milestone of a final or signed agreement is never deleted'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN OLD;
    END IF;
    SELECT a.status INTO v_status FROM public.agreements a
     WHERE a.id = NEW.agreement_id AND a.engagement_id = NEW.engagement_id FOR SHARE;
    IF TG_OP = 'INSERT' THEN
        IF v_status IS DISTINCT FROM 'draft' OR NEW.state <> 'PLANNED' THEN
            RAISE EXCEPTION 'milestones: milestones are planned while their agreement is a draft'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id OR NEW.agreement_id <> OLD.agreement_id OR NEW.engagement_id <> OLD.engagement_id
       OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION 'milestones: the agreement of a milestone never changes' USING ERRCODE = 'check_violation';
    END IF;
    IF v_status = 'draft' THEN
        IF NEW.state <> 'PLANNED' THEN
            RAISE EXCEPTION 'milestones: a milestone of a draft agreement stays PLANNED'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.seq, NEW.deliverable, NEW.amount_kes_minor, NEW.due_date, NEW.review_window_bd)
       IS DISTINCT FROM (OLD.seq, OLD.deliverable, OLD.amount_kes_minor, OLD.due_date, OLD.review_window_bd) THEN
        RAISE EXCEPTION 'milestones: the plan of a final agreement is frozen' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.state IS DISTINCT FROM OLD.state THEN
        SELECT e.state INTO v_state FROM public.engagements e WHERE e.id = NEW.engagement_id;
        IF v_status <> 'signed' OR v_state IS DISTINCT FROM 'IN_IMPLEMENTATION' THEN
            RAISE EXCEPTION 'milestones: milestones progress once the agreement is signed, during IN_IMPLEMENTATION'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NOT ((OLD.state = 'PLANNED' AND NEW.state = 'IN_PROGRESS')
                OR (OLD.state = 'IN_PROGRESS' AND NEW.state = 'SUBMITTED_FOR_REVIEW')
                OR (OLD.state = 'SUBMITTED_FOR_REVIEW' AND NEW.state IN ('ACCEPTED', 'CHANGES_REQUESTED'))
                OR (OLD.state = 'CHANGES_REQUESTED' AND NEW.state = 'IN_PROGRESS')) THEN
            RAISE EXCEPTION 'milestones: % -> % is not a step of the milestone sub-tracker', OLD.state, NEW.state
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- An internal e-signature: an agreement only in its final version, at its final PDF's hash, and never with IP terms
-- that need an advanced e-signature (assignment, exclusive licence: AC-TRACK-10; "signed outside the platform" comes
-- later); a milestone confirmation names a milestone of the engagement. signed_at is the database's. Runs after
-- tracker_engagement_visible(); the TOTP check, which reads another user, runs after RLS (signatures_totp()). SECURITY
-- DEFINER: reads agreements and milestones whatever the caller sees.
CREATE FUNCTION signatures_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_agreement public.agreements%ROWTYPE;
BEGIN
    IF NEW.document_kind = 'agreement' THEN
        SELECT * INTO v_agreement FROM public.agreements a
         WHERE a.id = NEW.document_ref AND a.engagement_id = NEW.engagement_id;
        IF v_agreement.id IS NULL OR v_agreement.status <> 'final' THEN
            RAISE EXCEPTION 'signatures: an agreement is signed in its final version' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.document_sha256 IS DISTINCT FROM v_agreement.final_pdf_sha256 THEN
            RAISE EXCEPTION 'signatures: the signed hash must be the final PDF''s' USING ERRCODE = 'check_violation';
        END IF;
        IF v_agreement.ip_terms IN ('assignment', 'exclusive_licence') THEN
            RAISE EXCEPTION 'signatures: IP terms % need an advanced e-signature, not the internal one',
                v_agreement.ip_terms USING ERRCODE = 'check_violation';
        END IF;
    ELSIF NEW.document_kind = 'milestone_confirmation' AND NOT EXISTS (
        SELECT 1 FROM public.milestones m WHERE m.id = NEW.document_ref AND m.engagement_id = NEW.engagement_id
    ) THEN
        RAISE EXCEPTION 'signatures: a milestone confirmation names a milestone of the engagement'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.signed_at := public.app_clock_now();
    RETURN NEW;
END;
$$;

-- A payment is recorded unconfirmed, at the database's time and not dated in the future (Nairobi date). It changes
-- once: the engagement's developer confirms it with the amount received (confirmed_at is the database's); nothing
-- else ever changes. The platform never moves money. SECURITY DEFINER: reads the engagement's developer.
CREATE FUNCTION payment_records_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_developer uuid;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.confirmed_by IS NOT NULL OR NEW.confirmed_at IS NOT NULL OR NEW.confirmed_amount_kes_minor IS NOT NULL
        THEN
            RAISE EXCEPTION 'payment_records: a payment is recorded unconfirmed' USING ERRCODE = 'check_violation';
        END IF;
        NEW.recorded_at := public.app_clock_now();
        IF NEW.paid_on > (NEW.recorded_at AT TIME ZONE 'Africa/Nairobi')::date THEN
            RAISE EXCEPTION 'payment_records: a payment is not dated in the future' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.confirmed_at IS NOT NULL THEN
        RAISE EXCEPTION 'payment_records: a payment is confirmed once and never changes afterwards'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (NEW.id, NEW.engagement_id, NEW.milestone_id, NEW.amount_kes_minor, NEW.method, NEW.reference, NEW.paid_on,
        NEW.recorded_by, NEW.recorded_at)
       IS DISTINCT FROM (OLD.id, OLD.engagement_id, OLD.milestone_id, OLD.amount_kes_minor, OLD.method, OLD.reference,
                         OLD.paid_on, OLD.recorded_by, OLD.recorded_at) THEN
        RAISE EXCEPTION 'payment_records: only the developer''s confirmation changes a payment record'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT e.developer_id INTO v_developer FROM public.engagements e WHERE e.id = NEW.engagement_id;
    IF NEW.confirmed_by IS NULL OR NEW.confirmed_by IS DISTINCT FROM v_developer
       OR NEW.confirmed_amount_kes_minor IS NULL THEN
        RAISE EXCEPTION 'payment_records: the engagement''s developer confirms a payment with the amount received'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.confirmed_at := public.app_clock_now();
    RETURN NEW;
END;
$$;

-- Checks that read other users (the roster, TOTP enrolment) run AFTER the row passed RLS, so a caller RLS refuses
-- learns nothing from them (review P1, MAJOR 1). SECURITY DEFINER: read memberships and users.

-- The named contact is an active member of the organisation, and the developer is never an active member of the
-- counterpart organisation (review P1, MINOR 7: the two parties are two people).
CREATE FUNCTION engagements_members() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.contact_user_id IS NOT NULL
       AND (TG_OP = 'INSERT' OR NEW.contact_user_id IS DISTINCT FROM OLD.contact_user_id)
       AND NOT EXISTS (
            SELECT 1 FROM public.memberships m
             WHERE m.org_id = NEW.org_id AND m.user_id = NEW.contact_user_id AND m.status = 'active') THEN
        RAISE EXCEPTION 'engagements: the contact must be an active member of the organisation'
            USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'INSERT' AND EXISTS (
        SELECT 1 FROM public.memberships m
         WHERE m.org_id = NEW.org_id AND m.user_id = NEW.developer_id AND m.status = 'active'
    ) THEN
        RAISE EXCEPTION 'engagements: the developer may not be a member of the counterpart organisation'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION engagement_endorsements_totp() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.method = 'totp' AND NOT EXISTS (
        SELECT 1 FROM public.users u WHERE u.id = NEW.user_id AND u.totp_enabled_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'engagement_endorsements: a TOTP endorsement needs TOTP enrolled'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION signatures_totp() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.step_up_method = 'totp' AND NOT EXISTS (
        SELECT 1 FROM public.users u WHERE u.id = NEW.signer_user_id AND u.totp_enabled_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'signatures: a TOTP step-up needs TOTP enrolled' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER engagements_guard
    BEFORE INSERT OR UPDATE ON engagements
    FOR EACH ROW EXECUTE FUNCTION engagements_guard();
CREATE TRIGGER engagements_genesis
    AFTER INSERT ON engagements
    FOR EACH ROW EXECUTE FUNCTION engagements_genesis();
CREATE TRIGGER engagements_members
    AFTER INSERT OR UPDATE ON engagements
    FOR EACH ROW EXECUTE FUNCTION engagements_members();
CREATE TRIGGER engagement_endorsements_totp
    AFTER INSERT ON engagement_endorsements
    FOR EACH ROW EXECUTE FUNCTION engagement_endorsements_totp();
CREATE TRIGGER signatures_totp
    AFTER INSERT ON signatures
    FOR EACH ROW EXECUTE FUNCTION signatures_totp();
CREATE TRIGGER engagement_events_chain
    BEFORE INSERT ON engagement_events
    FOR EACH ROW EXECUTE FUNCTION engagement_events_chain();
CREATE TRIGGER engagement_events_project
    AFTER INSERT ON engagement_events
    FOR EACH ROW EXECUTE FUNCTION engagement_events_project();
CREATE TRIGGER engagement_endorsements_guard
    BEFORE INSERT ON engagement_endorsements
    FOR EACH ROW EXECUTE FUNCTION engagement_endorsements_guard();
CREATE TRIGGER agreements_guard
    BEFORE INSERT OR UPDATE OR DELETE ON agreements
    FOR EACH ROW EXECUTE FUNCTION agreements_guard();
CREATE TRIGGER milestones_guard
    BEFORE INSERT OR UPDATE OR DELETE ON milestones
    FOR EACH ROW EXECUTE FUNCTION milestones_guard();
CREATE TRIGGER signatures_guard
    BEFORE INSERT ON signatures
    FOR EACH ROW EXECUTE FUNCTION signatures_guard();
CREATE TRIGGER payment_records_guard
    BEFORE INSERT OR UPDATE ON payment_records
    FOR EACH ROW EXECUTE FUNCTION payment_records_guard();
CREATE TRIGGER payment_records_no_delete
    BEFORE DELETE ON payment_records
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
"""

# Append-only tables (block_mutation() of revision 0002 refuses UPDATE and DELETE for every role) and tables that are
# never truncated.
# Every tracker table: tracker_engagement_visible() fires first on INSERT (<table>_0_visible sorts first by name).
TRACKER_TABLES = RLS_TABLES
APPEND_ONLY_TABLES = ("engagement_events", "engagement_endorsements", "signatures")
NO_TRUNCATE_TABLES = (*APPEND_ONLY_TABLES, "agreements", "milestones", "payment_records")

# EXECUTE grants (every function of this revision has EXECUTE revoked from PUBLIC first).
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_event_payload_is_valid(jsonb)": ("bridge_app",),  # ck_engagement_events_payload_holds_ids_and_codes
    "app_clock_now()": ("bridge_app",),
    "app_set_test_clock(interval)": ("bridge_app",),  # the test-clock router (dev, test and staging only)
}
# Called only by the chain trigger, as the owner: no EXECUTE for any role.
INTERNAL_FUNCTIONS = (
    "engagement_event_canonical(engagement_events)",
    "engagement_main_path_predecessors(engagement_state)",
)
TRIGGER_FUNCTIONS = (
    "tracker_engagement_visible()",
    "engagements_members()",
    "engagement_endorsements_totp()",
    "signatures_totp()",
    "engagement_events_chain()",
    "engagement_events_project()",
    "engagements_guard()",
    "engagements_genesis()",
    "engagement_endorsements_guard()",
    "agreements_guard()",
    "milestones_guard()",
    "signatures_guard()",
    "payment_records_guard()",
)

# Every engagement that predates this revision (fixtures only) starts its chain: a genesis event by the system.
BACKFILL_SQL = r"""
INSERT INTO engagement_events (id, engagement_id, actor_role, command, to_state, end_reason, payload)
SELECT uuid7(), e.id, 'system', 'import', e.state, e.end_reason,
       jsonb_build_object('origin', e.origin::text, 'version_id', e.version_id::text)
  FROM engagements e
 ORDER BY e.created_at, e.id;
"""


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _state() -> postgresql.ENUM:
    return postgresql.ENUM(*ENGAGEMENT_STATE, name="engagement_state", create_type=False)


def _end_reason() -> postgresql.ENUM:
    return postgresql.ENUM(*ENGAGEMENT_END_REASON, name="engagement_end_reason", create_type=False)


def _grant_sql() -> str:
    grants = [f"GRANT {privileges} ON TABLE {table} TO bridge_app;" for table, privileges in APP_GRANTS.items()]
    grants += [f"GRANT {privileges} ON TABLE {t} TO bridge_app;" for t, privileges in APP_GRANTS_EARLIER_TABLES.items()]
    # REVOKE of a table privilege also revokes it on every column; the column grant follows.
    grants += [
        "REVOKE INSERT ON TABLE users FROM bridge_app;",
        f"GRANT INSERT ({USERS_INSERTABLE_COLUMNS}) ON TABLE users TO bridge_app;",
    ]
    grants += [
        f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;" for signature in (*INTERNAL_FUNCTIONS, *TRIGGER_FUNCTIONS)
    ]
    for signature, roles in FUNCTION_GRANTS.items():
        grants.append(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC;")
        grants.append(f"GRANT EXECUTE ON FUNCTION {signature} TO {', '.join(roles)};")
    return "\n".join(grants)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)
    _run_sql(CHECK_HELPERS_SQL)
    _alter_earlier_tables()
    _create_tables()
    _run_sql("INSERT INTO test_clock (singleton) VALUES (true);")  # disabled, offset 0: the owner enables it
    _run_sql(FUNCTIONS_SQL)
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(TRIGGERS_SQL)
    _run_sql(
        "\n".join(
            [
                *(
                    f"CREATE TRIGGER {t}_0_visible BEFORE INSERT ON {t}"
                    " FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();"
                    for t in TRACKER_TABLES
                ),
                *(
                    f"CREATE TRIGGER {t}_no_update_delete BEFORE UPDATE OR DELETE ON {t}"
                    " FOR EACH ROW EXECUTE FUNCTION block_mutation();"
                    for t in APPEND_ONLY_TABLES
                ),
                *(
                    f"CREATE TRIGGER {t}_no_truncate BEFORE TRUNCATE ON {t}"
                    " FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();"
                    for t in NO_TRUNCATE_TABLES
                ),
            ]
        )
    )
    _run_sql(BACKFILL_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    # This revision's policies and triggers on the revision 0002 table, and the canonical function (its argument is
    # engagement_events' row type), before the tables.
    _run_sql(
        "\n".join(
            [
                *(f"DROP POLICY {p.name} ON {p.table};" for p in POLICIES if p.table == "engagements"),
                "DROP TRIGGER engagements_members ON engagements;",
                "DROP TRIGGER engagements_genesis ON engagements;",
                "DROP TRIGGER engagements_guard ON engagements;",
                *(f"DROP FUNCTION {signature};" for signature in INTERNAL_FUNCTIONS),
            ]
        )
    )
    # Dropping a table drops its policies, triggers, indexes and grants. Referencing tables before referenced ones.
    for table in (
        "payment_records",
        "engagement_endorsements",
        "signatures",
        "milestones",
        "agreements",
        "engagement_events",
        "test_clock",
    ):
        op.drop_table(table)
    _run_sql("\n".join(f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS)))
    # REVOKE of a table privilege also revokes it on every column (the contact columns go with their columns below).
    _run_sql("REVOKE INSERT, UPDATE ON TABLE engagements FROM bridge_app;")
    op.drop_constraint(op.f("fk_engagements_contact_user_id_users"), "engagements", type_="foreignkey")
    for column in (
        "contact_by",
        "contact_channel",
        "contact_user_id",
        "lock_version",
        "ended_at",
        "stage_deadline_at",
        "stage_entered_at",
    ):
        op.drop_column("engagements", column)  # drops the CHECK constraints over it
    op.drop_constraint(op.f("ck_engagements_end_reason_matches_state"), "engagements", type_="check")
    op.create_check_constraint(  # revision 0002's, as it was
        op.f("ck_engagements_end_reason_matches_state"), "engagements", _end_reason_matches("state")
    )
    op.drop_column("users", "demo_account")
    _run_sql("REVOKE INSERT ON TABLE users FROM bridge_app; GRANT INSERT ON TABLE users TO bridge_app;")
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)


def _alter_earlier_tables() -> None:
    op.add_column("users", sa.Column("demo_account", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column(
        "engagements",
        sa.Column("stage_entered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column("engagements", sa.Column("stage_deadline_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("engagements", sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("engagements", sa.Column("lock_version", sa.Integer(), server_default="0", nullable=False))
    op.add_column("engagements", sa.Column("contact_user_id", sa.Uuid(), nullable=True))
    op.add_column("engagements", sa.Column("contact_channel", _enum("contact_channel"), nullable=True))
    op.add_column("engagements", sa.Column("contact_by", sa.Date(), nullable=True))
    op.create_foreign_key(
        op.f("fk_engagements_contact_user_id_users"), "engagements", "users", ["contact_user_id"], ["id"]
    )
    # Engagements that predate this revision (fixtures only): their stage was entered, and a terminal one ended, when
    # they were last changed. Before the triggers exist, so no guard runs.
    _run_sql(
        "UPDATE engagements SET stage_entered_at = updated_at,"
        f" ended_at = CASE WHEN state IN ({TERMINAL}) THEN updated_at END;"
    )
    # Revision 0002's end-reason CHECK let DECLINED or EXPIRED through without a reason (NULL IN (...) is NULL): the
    # NULL-safe version replaces it (the orchestrator's ruling, P1). Validated: an existing row without its reason
    # stops the upgrade.
    op.drop_constraint(op.f("ck_engagements_end_reason_matches_state"), "engagements", type_="check")
    op.create_check_constraint(
        op.f("ck_engagements_end_reason_matches_state"),
        "engagements",
        f"coalesce({_end_reason_matches('state')}, false)",
    )
    op.create_check_constraint(
        op.f("ck_engagements_ended_exactly_when_terminal"),
        "engagements",
        f"(ended_at IS NOT NULL) = (state IN ({TERMINAL}))",
    )
    op.create_check_constraint(
        op.f("ck_engagements_contact_complete"),
        "engagements",
        "(contact_user_id IS NULL) = (contact_channel IS NULL) AND (contact_channel IS NULL) = (contact_by IS NULL)",
    )


def _create_tables() -> None:
    op.create_table(
        "test_clock",
        sa.Column("singleton", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("clock_offset", sa.Interval(), server_default=sa.text("'00:00:00'::interval"), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "clock_offset >= interval '0' AND clock_offset <= interval '366 days'",
            name=op.f("ck_test_clock_clock_offset"),
        ),
        sa.CheckConstraint("singleton", name=op.f("ck_test_clock_singleton")),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], name=op.f("fk_test_clock_updated_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("singleton", name=op.f("pk_test_clock")),
    )
    op.create_table(
        "agreements",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("ip_terms", _enum("ip_terms"), nullable=True),
        sa.Column("exclusivity", sa.Text(), nullable=True),
        sa.Column("deemed_acceptance_days", sa.SmallInteger(), nullable=True),
        sa.Column("status", _enum("agreement_status"), server_default="draft", nullable=False),
        sa.Column("final_pdf_sha256", sa.LargeBinary(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "exclusivity IS NULL OR (btrim(exclusivity) <> '' AND length(exclusivity) <= 500)",
            name=op.f("ck_agreements_exclusivity"),
        ),
        sa.CheckConstraint(
            "status = 'draft' OR (ip_terms IS NOT NULL AND deemed_acceptance_days IS NOT NULL"
            " AND final_pdf_sha256 IS NOT NULL)",
            name=op.f("ck_agreements_final_is_complete"),
        ),
        sa.CheckConstraint(
            "deemed_acceptance_days BETWEEN 0 AND 90", name=op.f("ck_agreements_deemed_acceptance_days")
        ),
        sa.CheckConstraint(
            "final_pdf_sha256 IS NULL OR octet_length(final_pdf_sha256) = 32",
            name=op.f("ck_agreements_final_pdf_sha256"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_agreements_version_positive")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_agreements_created_by_users")),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_agreements_engagement_id_engagements")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agreements")),
        sa.UniqueConstraint("engagement_id", "version", name=op.f("uq_agreements_engagement_id_version")),
        sa.UniqueConstraint("id", "engagement_id", name=op.f("uq_agreements_id_engagement_id")),
    )
    op.create_index(
        "uq_agreements_signed_engagement",
        "agreements",
        ["engagement_id"],
        unique=True,
        postgresql_where=sa.text("status = 'signed'"),
    )
    op.create_table(
        "engagement_events",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_role", _enum("engagement_actor_role"), nullable=False),
        sa.Column("command", sa.String(length=40), nullable=False),
        sa.Column("from_state", _state(), nullable=True),
        sa.Column("to_state", _state(), nullable=False),
        sa.Column("end_reason", _end_reason(), nullable=True),
        sa.Column("stage_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(actor_role = 'system') = (actor_user_id IS NULL)", name=op.f("ck_engagement_events_actor_matches_role")
        ),
        sa.CheckConstraint(
            f"coalesce({_end_reason_matches('to_state')}, false)",
            name=op.f("ck_engagement_events_end_reason_matches_state"),
        ),
        sa.CheckConstraint("command ~ '^[a-z][a-z0-9_]{0,39}$'", name=op.f("ck_engagement_events_command_is_a_code")),
        sa.CheckConstraint(
            "app_event_payload_is_valid(payload)", name=op.f("ck_engagement_events_payload_holds_ids_and_codes")
        ),
        sa.CheckConstraint(
            "octet_length(prev_hash) = 32 AND octet_length(hash) = 32",
            name=op.f("ck_engagement_events_hashes_are_sha256"),
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_engagement_events_actor_user_id_users")),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_engagement_events_engagement_id_engagements")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_events")),
        sa.UniqueConstraint("engagement_id", "prev_hash", name=op.f("uq_engagement_events_engagement_id_prev_hash")),
        sa.UniqueConstraint("engagement_id", "seq", name=op.f("uq_engagement_events_engagement_id_seq")),
    )
    op.create_table(
        "signatures",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("document_kind", _enum("signature_document_kind"), nullable=False),
        sa.Column("document_ref", sa.Uuid(), nullable=False),
        sa.Column("document_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("signer_user_id", sa.Uuid(), nullable=False),
        sa.Column("party", _enum("engagement_party"), nullable=False),
        sa.Column("step_up_method", _enum("step_up_method"), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("octet_length(document_sha256) = 32", name=op.f("ck_signatures_document_sha256")),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_signatures_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(["signer_user_id"], ["users.id"], name=op.f("fk_signatures_signer_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signatures")),
        sa.UniqueConstraint(
            "engagement_id",
            "document_kind",
            "document_ref",
            "party",
            name=op.f("uq_signatures_engagement_id_document_kind_document_ref_party"),
        ),
    )
    op.create_table(
        "milestones",
        sa.Column("agreement_id", sa.Uuid(), nullable=False),
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.SmallInteger(), nullable=False),
        sa.Column("deliverable", sa.Text(), nullable=False),
        sa.Column("amount_kes_minor", sa.BigInteger(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("review_window_bd", sa.SmallInteger(), nullable=False),
        sa.Column("state", _enum("milestone_state"), server_default="PLANNED", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "btrim(deliverable) <> '' AND length(deliverable) <= 500", name=op.f("ck_milestones_deliverable")
        ),
        sa.CheckConstraint("amount_kes_minor > 0", name=op.f("ck_milestones_amount_positive")),
        sa.CheckConstraint("review_window_bd BETWEEN 1 AND 60", name=op.f("ck_milestones_review_window_bd")),
        sa.CheckConstraint("seq >= 1", name=op.f("ck_milestones_seq_positive")),
        sa.ForeignKeyConstraint(
            ["agreement_id", "engagement_id"],
            ["agreements.id", "agreements.engagement_id"],
            name="fk_milestones_agreement",
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_milestones_engagement_id_engagements")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_milestones")),
        sa.UniqueConstraint("agreement_id", "seq", name=op.f("uq_milestones_agreement_id_seq")),
        sa.UniqueConstraint("id", "engagement_id", name=op.f("uq_milestones_id_engagement_id")),
    )
    op.create_index(op.f("ix_milestones_engagement_id"), "milestones", ["engagement_id"], unique=False)
    op.create_table(
        "engagement_endorsements",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("stage", _state(), nullable=False),
        sa.Column("stage_round", sa.SmallInteger(), nullable=False),
        sa.Column("milestone_id", sa.Uuid(), nullable=True),
        sa.Column("party", _enum("engagement_party"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("role", _enum("engagement_actor_role"), nullable=False),
        sa.Column("method", _enum("endorsement_method"), nullable=False),
        sa.Column("endorsed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(method = 'auto') = (user_id IS NULL) AND (method = 'auto') = (role = 'system')",
            name=op.f("ck_engagement_endorsements_auto_names_nobody"),
        ),
        sa.CheckConstraint(
            "(party = 'developer' AND role IN ('developer', 'system'))"
            " OR (party = 'org' AND role IN ('owner', 'admin', 'reviewer', 'signatory', 'finance', 'system'))",
            name=op.f("ck_engagement_endorsements_role_matches_party"),
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_engagement_endorsements_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(
            ["milestone_id", "engagement_id"],
            ["milestones.id", "milestones.engagement_id"],
            name="fk_engagement_endorsements_milestone",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_engagement_endorsements_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_endorsements")),
    )
    op.create_index(
        "uq_engagement_endorsements_once",
        "engagement_endorsements",
        ["engagement_id", "stage", "stage_round", "party", "milestone_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_table(
        "payment_records",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("milestone_id", sa.Uuid(), nullable=True),
        sa.Column("amount_kes_minor", sa.BigInteger(), nullable=False),
        sa.Column("method", _enum("payment_method"), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_amount_kes_minor", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "reference IS NULL OR btrim(reference) <> ''", name=op.f("ck_payment_records_reference_not_blank")
        ),
        sa.CheckConstraint(
            "(confirmed_by IS NULL) = (confirmed_at IS NULL)"
            " AND (confirmed_at IS NULL) = (confirmed_amount_kes_minor IS NULL)",
            name=op.f("ck_payment_records_confirmation_complete"),
        ),
        sa.CheckConstraint("amount_kes_minor > 0", name=op.f("ck_payment_records_amount_positive")),
        sa.CheckConstraint(
            "confirmed_amount_kes_minor IS NULL OR confirmed_amount_kes_minor >= 0",
            name=op.f("ck_payment_records_confirmed_amount"),
        ),
        sa.ForeignKeyConstraint(["confirmed_by"], ["users.id"], name=op.f("fk_payment_records_confirmed_by_users")),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_payment_records_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(
            ["milestone_id", "engagement_id"],
            ["milestones.id", "milestones.engagement_id"],
            name="fk_payment_records_milestone",
        ),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], name=op.f("fk_payment_records_recorded_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payment_records")),
    )
    op.create_index(op.f("ix_payment_records_engagement_id"), "payment_records", ["engagement_id"], unique=False)
