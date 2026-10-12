"""Schema v11 (P27-M): team triage, prior-knowledge declarations, calendar feeds and the D3 references.

REQ-ENG-15 (D-68), REQ-PROV-06 (docs/spec/06 6.4 pt 5), REQ-ENG-13 (D-70) and REQ-DEV-04 (docs/spec/06 6.4 pt 8, D3).
Design: ``docs/platform/tasks/P27.md``, "The contract", tracks A (the feeds), C, D and E. Additive: one enum type
(``recommendation_stance``: pursue, pass, discuss); four new columns of ``developer_profiles`` with three CHECKs and
bridge_app's UPDATE of them; four new tables (``engagement_assignments``, ``engagement_recommendations``,
``prior_knowledge_declarations``, ``calendar_feeds``) with their policies, triggers and grants; eight new functions
(three granted to bridge_app, one internal, four trigger functions). Nothing of revisions 0001 to 0012 is changed or
dropped; the triggers reuse ``tracker_engagement_visible()`` (revision 0003) and ``block_mutation()`` (revision 0002),
the clocks ``app_clock_now()`` (revision 0003) and ``app_nairobi_today()`` (revision 0009), the policies
``app_is_member()`` (revision 0001) and ``app_is_staff()`` (revision 0002). The upgrade is additive; the downgrade is
destructive (see ``downgrade()``).

"A member" is an active membership of the row's organisation, narrowed by ``app.org_id`` when one is set (revision
0001's rule, as every organisation table); "a triage member" is one holding owner, admin, reviewer or signatory
(docs/spec/03: the reviewer "may Recommend internally without changing state"); "a declarer" one holding owner, admin
or signatory (the card's contract). Times written here are the shared clock's (``app_clock_now()``: the test clock's
offset applies where the owner enabled it).

- ``developer_profiles`` (revision 0001; USER, own-row policies): ``github_login`` (varchar 39; CHECK
  ``github_login_valid``: GitHub's rule, letters, digits and single hyphens, neither first nor last),
  ``kecobo_number`` and ``kipi_number`` (varchar 40; CHECKs ``kecobo_number_valid``, ``kipi_number_valid``: not blank,
  no control character) and ``ip_nudge_dismissed_at`` (timestamptz), all NULL by default. Self-reported and
  unverified: the certificate says so; ``/verify`` never shows them. bridge_app's UPDATE of the profile (column-scoped
  since revision 0001; the own row by 0001's policy) gains the four; its table-wide SELECT and INSERT (0001) cover
  them and revision 0012's INSERT policy is unchanged.
- ``engagement_assignments`` (ORG; bridge_app: SELECT, INSERT of ``id``, ``engagement_id``, ``org_id``,
  ``assignee_user_id``, ``assigned_by``, UPDATE of ``unassigned_at``): who at the organisation works an engagement. A
  member reads every row of their organisation's; a triage member assigns as themselves (``assigned_by``) on an
  engagement of the row's organisation and closes a live row; nobody else reads or writes (the developer, another
  organisation, staff: D-68). ``engagement_assignments_guard`` (every role, SECURITY DEFINER): the organisation is the
  engagement's and the assignee an active triage member of it (check_violation); a row's keys, people and time never
  change; it is closed once (``unassigned_at``, the shared clock whatever is sent) and never reopened
  (object_not_in_prerequisite_state). One live row per engagement: the partial unique index
  ``uq_engagement_assignments_live`` (a second live row is a unique violation, the API's 409 or retry);
  ``ix_engagement_assignments_assignee_live`` (org, assignee) serves "Assigned to me". Never deleted.
- ``engagement_recommendations`` (ORG; bridge_app: SELECT, INSERT of ``id``, ``engagement_id``, ``org_id``,
  ``member_user_id``, ``stance``, ``note``, UPDATE of ``stance`` and ``note``, DELETE): one per member and engagement
  (``uq_engagement_recommendations_engagement_id_member_user_id``; the API upserts). A member reads every row of
  their organisation's; a triage member writes their own row (``member_user_id`` the caller) on an engagement of the
  row's organisation; a member withdraws their own (DELETE, whatever their role now). ``note`` is plain text on one
  line, 1 to 200 characters, or NULL (CHECK ``note_valid``). ``engagement_recommendations_guard`` (every role,
  SECURITY DEFINER): the organisation is the engagement's and the member an active triage member of it; keys and
  ``created_at`` never change; ``updated_at`` is the shared clock on every update. Changes no engagement state.
- ``prior_knowledge_declarations`` (ORG_OR_USER through the engagement; bridge_app: SELECT, INSERT of ``id``,
  ``engagement_id``, ``org_id``, ``proposal_id``, ``version_id``, ``declared_by``, ``evidence_sha256``,
  ``evidence_title``, ``evidence_dated_on``): one per engagement (``uq_prior_knowledge_declarations_engagement_id``).
  Read by whoever reads the engagement (revisions 0002 and 0003's policies: its developer, the proposal's owner; the
  organisation's members; staff admin, for the evidence pack of docs/spec/06 6.12). Inserted by a declarer as
  themselves (``declared_by``), naming the engagement's organisation, proposal and version. Append-only for every
  role, the owner included: ``_no_update_delete`` and ``_no_truncate`` (``block_mutation()``). The evidence is its
  SHA-256 only (32 bytes, CHECK) with the organisation's own title (one line, 1 to 200 characters, CHECK) and its date;
  no file and no text of it is ever stored. On INSERT, ``_0_visible`` (``tracker_engagement_visible()``) refuses an
  engagement the caller does not read, then ``_1_window`` (``prior_knowledge_declarations_window()``, SECURITY
  INVOKER: ``current_user`` is the writer) refuses an organisation, proposal or version that is not the engagement's
  (check_violation, every role) and, for every writer but the table's owner (a seed or a backfill keeps what it sends;
  no definer function inserts here, a test scans for one), makes the window the database's: the organisation's first
  Tier-2 view and the closing day from ``app_prior_knowledge_window`` (object_not_in_prerequisite_state, "has not
  viewed", before any view; "window closed on <day>" once the Nairobi day on the shared clock is past it), the evidence
  dated no later than that day (check_violation), and ``first_tier2_view_at``, ``window_closes_on`` and
  ``declared_at`` set whatever was sent. CHECKs keep the three consistent for every writer (``window_after_first_view``,
  ``declared_within_window``, ``evidence_dated_by_declaration``). The engagement's state is not a condition here (the
  window is docs/spec/06's rule); the chain event the contract adds (``prior_knowledge_declared``) is refused by
  revision 0003 once the engagement has ended, so the API checks first.
- ``calendar_feeds`` (USER; bridge_app: SELECT, INSERT of ``id``, ``user_id``, ``org_id``, ``token_hash``, UPDATE of
  ``revoked_at``): D-70's capability URLs, the token stored only as its SHA-256 (32 bytes, CHECK; unique). The user's
  own rows only; a feed for an organisation only by a member of it. One live feed per user (``org_id`` NULL,
  ``uq_calendar_feeds_live_personal``) and per user and organisation (``uq_calendar_feeds_live_org``). ``calendar_
  feeds_guard`` (every role): keys, token and creation time never change; a revoked feed never changes again;
  ``revoked_at`` is the shared clock whatever is sent. ``last_fetched_at`` only ``app_calendar_feed_touch`` stamps.
  Not deleted by the app (the cascade from ``users`` removes a user's).

Functions (pinned search_path; EXECUTE revoked from PUBLIC; granted to bridge_app where listed in
``FUNCTION_GRANTS``):

- ``app_prior_knowledge_window(engagement)`` -> (first_tier2_view_at, window_closes_on), SECURITY DEFINER: one row for
  a reader of the engagement (its developer, a member of its organisation narrowed by ``app.org_id``, staff admin: the
  engagements' SELECT policies restated), both NULL before the organisation's first Tier-2 view; no row for anyone
  else. The first view is the earliest ``document_views`` row of the engagement's organisation and proposal (by any
  member: revision 0002's policy shows a member only their own rows, hence the definer); the window closes at the end
  of the 10th Kenyan business day after that view's Nairobi day. The API's ``prior_knowledge`` facts and the
  ``_1_window`` trigger both read it: one rule.
- ``app_calendar_feed_lookup(token_hash)`` -> (feed_id, user_id, org_id), SECURITY DEFINER: the live feed with that
  hash whose user is active and, for an organisation feed, still an active member of it (a feed never outlives the
  membership it was made under); no row otherwise (an unknown, revoked or wrong-length hash included). Answers any
  session: the hash is the capability.
- ``app_calendar_feed_touch(feed)`` -> boolean, SECURITY DEFINER: stamps ``last_fetched_at`` (the shared clock) on
  the live feed; for a session bound to a user, only their own; false otherwise.
- Internal (no EXECUTE grant; called as the owner): ``kenyan_business_days_after(start, n)``: the n-th business day
  after ``start`` (Monday to Friday, not an observed holiday of ``holidays`` with country ``KE``; ``start`` never
  counted), ``bridge.engagements.calendar.add_business_days`` for n >= 1 on the holidays the app loads.
- Trigger functions: ``engagement_assignments_guard()`` and ``engagement_recommendations_guard()`` (SECURITY DEFINER:
  they read the engagement and the membership whatever the caller's visibility), ``prior_knowledge_declarations_
  window()`` and ``calendar_feeds_guard()`` (SECURITY INVOKER).

Operating rules for the code that uses this schema:

- Org-side reads of assignments and recommendations bind the member and their organisation (``app.org_id``); a
  developer-side response never joins these tables (D-68: no ``team`` key at all). A recommendation's note is free
  text a member typed: keep it out of event payloads, logs, audit details, emails and notices.
- Assign: in one transaction, ``UPDATE engagement_assignments SET unassigned_at = now() WHERE engagement_id = :e AND
  unassigned_at IS NULL`` (the database sets the time), then INSERT the new row (``assigned_by`` the caller) leaving
  ``assigned_at`` out. Map check_violation from ``engagement_assignments_guard`` to 422 (an assignee who is not a
  triage member), a row-level security refusal to 403 (the caller is not a triage member) and
  ``uq_engagement_assignments_live`` to 409 (a concurrent assignment).
- Recommend: ``INSERT ... ON CONFLICT (engagement_id, member_user_id) DO UPDATE SET stance = EXCLUDED.stance, note =
  EXCLUDED.note`` as the member, sending NULL for no note; withdraw with ``DELETE ... WHERE engagement_id = :e AND
  member_user_id = :me``.
- Declare: read ``app_prior_knowledge_window(:e)`` for the 403s (``no_tier2_access_yet`` while the first view is NULL,
  ``declaration_window_closed`` once ``app_nairobi_today()`` is past the closing day) and the 409 (a row exists),
  then INSERT as the declarer with the engagement's ``org_id``, ``proposal_id`` and ``version_id``, leaving the three
  database columns out (read them back), and append the engagement event ``prior_knowledge_declared`` (payload: ids
  and the hex hash only) and the audit row in the same transaction. SQLSTATE 55000 from ``_1_window`` is the race of
  the window closing (403); the unique violation on ``engagement_id`` the race of two declarations (409).
- Feeds: create or rotate in one transaction (``UPDATE calendar_feeds SET revoked_at = now() WHERE user_id = :me AND
  org_id IS NOT DISTINCT FROM :org AND revoked_at IS NULL``, then INSERT the new hash); revoke with the same UPDATE.
  The unauthenticated read: ``SELECT * FROM app_calendar_feed_lookup(sha256(:token))`` (no row: 404), bind that user
  (and organisation), read the deadlines under their RLS, then ``SELECT app_calendar_feed_touch(:feed)``.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = (
    "engagement_assignments",
    "engagement_recommendations",
    "prior_knowledge_declarations",
    "calendar_feeds",
)
RLS_TABLES = NEW_TABLES
STANCES = ("pursue", "pass", "discuss")
PROFILE_COLUMNS = ("github_login", "kecobo_number", "kipi_number", "ip_nudge_dismissed_at")

# Table privileges of bridge_app on this revision's tables; anything not listed is not granted. Column-scoped where the
# database owns a column (times, the window) or a column is written later (a close, a revocation).
APP_GRANTS: dict[str, str] = {
    "engagement_assignments": (
        "SELECT, INSERT (id, engagement_id, org_id, assignee_user_id, assigned_by), UPDATE (unassigned_at)"
    ),
    "engagement_recommendations": (
        "SELECT, INSERT (id, engagement_id, org_id, member_user_id, stance, note), UPDATE (stance, note), DELETE"
    ),
    "prior_knowledge_declarations": (
        "SELECT, INSERT (id, engagement_id, org_id, proposal_id, version_id, declared_by, evidence_sha256,"
        " evidence_title, evidence_dated_on)"
    ),
    "calendar_feeds": "SELECT, INSERT (id, user_id, org_id, token_hash), UPDATE (revoked_at)",
}
# revision 0001's developer_profiles grant gains the D3 references and the nudge's dismissal (own row: 0001's policy)
PROFILE_GRANT = f"GRANT UPDATE ({', '.join(PROFILE_COLUMNS)}) ON TABLE developer_profiles TO bridge_app;"
APPEND_ONLY_TABLES = ("prior_knowledge_declarations",)

# CHECK expressions, verbatim from the ORM models (bridge.engagements.models, bridge.profiles.models).
GITHUB_LOGIN_VALID = "github_login IS NULL OR github_login ~ '^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$'"


def _reference_valid(column: str) -> str:
    return f"{column} IS NULL OR ({column} ~ '[^[:space:]]' AND {column} !~ '[[:cntrl:]]')"


def _one_line(column: str, max_chars: int) -> str:
    return f"{column} ~ '[^[:space:]]' AND char_length({column}) <= {max_chars} AND {column} !~ '[[:cntrl:]]'"


def _nairobi_day(column: str) -> str:
    return f"({column} AT TIME ZONE 'Africa/Nairobi')::date"


PROFILE_CHECKS = (
    ("github_login_valid", GITHUB_LOGIN_VALID),
    ("kecobo_number_valid", _reference_valid("kecobo_number")),
    ("kipi_number_valid", _reference_valid("kipi_number")),
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


# Predicates. The organisation tables follow revision 0001's member rule (narrowed by app.org_id); a writer names the
# engagement's organisation, read under the writer's own RLS (the engagements' policies).
_IN_ORG = "(app_org_id() IS NULL OR org_id = app_org_id())"
_MEMBER = f"app_is_member(org_id) AND {_IN_ORG}"
_TRIAGE = f"app_is_member(org_id, '{{owner,admin,reviewer,signatory}}') AND {_IN_ORG}"
_DECLARER = f"app_is_member(org_id, '{{owner,admin,signatory}}') AND {_IN_ORG}"
_OWN_FEED = "user_id = app_user_id()"


def _of_engagement(table: str, extra: str = "") -> str:
    """The row's engagement is one the caller reads and is of the row's organisation (and meets ``extra``)."""
    return (
        f"EXISTS (SELECT 1 FROM engagements e WHERE e.id = {table}.engagement_id AND e.org_id = {table}.org_id{extra})"
    )


_OWN_RECOMMENDATION = f"member_user_id = app_user_id() AND {_TRIAGE}"
DECLARATION_INSERT = f"declared_by = app_user_id() AND {_DECLARER} AND " + _of_engagement(
    "prior_knowledge_declarations",
    " AND e.proposal_id = prior_knowledge_declarations.proposal_id"
    " AND e.version_id = prior_knowledge_declarations.version_id",
)

POLICIES: tuple[Policy, ...] = (
    # --- engagement_assignments: members read; a triage member assigns as themselves and closes a live row ---
    Policy("engagement_assignments", "SELECT", _MEMBER),
    Policy(
        "engagement_assignments",
        "INSERT",
        check=f"assigned_by = app_user_id() AND {_TRIAGE} AND " + _of_engagement("engagement_assignments"),
    ),
    Policy("engagement_assignments", "UPDATE", f"unassigned_at IS NULL AND {_TRIAGE}", _TRIAGE),
    # --- engagement_recommendations: members read; a triage member writes their own; a member withdraws their own ---
    Policy("engagement_recommendations", "SELECT", _MEMBER),
    Policy(
        "engagement_recommendations",
        "INSERT",
        check=f"{_OWN_RECOMMENDATION} AND " + _of_engagement("engagement_recommendations"),
    ),
    Policy("engagement_recommendations", "UPDATE", _OWN_RECOMMENDATION, _OWN_RECOMMENDATION),
    Policy("engagement_recommendations", "DELETE", f"member_user_id = app_user_id() AND {_MEMBER}"),
    # --- prior_knowledge_declarations: the engagement's readers read; a declarer declares (append-only) ---
    Policy(
        "prior_knowledge_declarations",
        "SELECT",
        "EXISTS (SELECT 1 FROM engagements e WHERE e.id = prior_knowledge_declarations.engagement_id)",
    ),
    Policy("prior_knowledge_declarations", "INSERT", check=DECLARATION_INSERT),
    # --- calendar_feeds: the user's own; an organisation's feed only for a member of it ---
    Policy("calendar_feeds", "SELECT", _OWN_FEED),
    Policy("calendar_feeds", "INSERT", check=f"{_OWN_FEED} AND (org_id IS NULL OR ({_MEMBER}))"),
    Policy("calendar_feeds", "UPDATE", _OWN_FEED, _OWN_FEED),
)

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0012: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS; internal and trigger functions to nobody).
# SECURITY DEFINER functions run as bridge_owner, which bypasses RLS (ENABLED, not FORCED).
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- The p_n-th Kenyan business day after p_start (p_start itself never counted): Monday to Friday and not the observed
-- day of a holiday of the holidays table with country KE, the rows bridge.engagements.service.load_holidays reads, so
-- it is bridge.engagements.calendar.add_business_days for p_n >= 1. Internal (no EXECUTE grant).
CREATE FUNCTION kenyan_business_days_after(p_start date, p_n integer) RETURNS date
    LANGUAGE plpgsql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_day date := p_start;
    v_counted integer := 0;
BEGIN
    IF p_start IS NULL OR p_n IS NULL OR p_n < 1 THEN
        RAISE EXCEPTION 'kenyan_business_days_after: a start date and a count of 1 or more'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    WHILE v_counted < p_n LOOP
        v_day := v_day + 1;
        IF extract(isodow FROM v_day) < 6
           AND NOT EXISTS (SELECT 1 FROM public.holidays h WHERE h.country = 'KE' AND h.observed_on = v_day) THEN
            v_counted := v_counted + 1;
        END IF;
    END LOOP;
    RETURN v_day;
END;
$$;

-- The prior-knowledge window of p_engagement (REQ-PROV-06; docs/spec/06 6.4 pt 5): the organisation's first Tier-2
-- view of the engagement's proposal (the earliest document_views row of that organisation and proposal, by any of its
-- members) and the Nairobi day the window closes, the 10th Kenyan business day after that view's Nairobi day (it
-- closes at the end of that day). One row for a reader of the engagement (its developer; a member of its
-- organisation, narrowed by app.org_id; staff admin: the engagements' SELECT policies of revisions 0002 and 0003), both
-- NULL before any view; no row for anyone else. SECURITY DEFINER: a member reads only their own document_views rows
-- (revision 0002), the window needs every member's.
CREATE FUNCTION app_prior_knowledge_window(p_engagement uuid)
    RETURNS TABLE (first_tier2_view_at timestamptz, window_closes_on date)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT f.first_view,
           CASE WHEN f.first_view IS NOT NULL
                THEN public.kenyan_business_days_after((f.first_view AT TIME ZONE 'Africa/Nairobi')::date, 10) END
      FROM public.engagements e
     CROSS JOIN LATERAL (SELECT min(v.started_at) AS first_view FROM public.document_views v
                          WHERE v.org_id = e.org_id AND v.proposal_id = e.proposal_id) f
     WHERE e.id = p_engagement
       AND (e.developer_id = public.app_user_id()
            OR (public.app_is_member(e.org_id) AND (public.app_org_id() IS NULL OR e.org_id = public.app_org_id()))
            OR public.app_is_staff('{admin}'))
$$;

-- The live calendar feed whose token hashes to p_token_hash (REQ-ENG-13, D-70: GET /api/calendar/{token}.ics is
-- unauthenticated; the token is the capability): its id, user and organisation, while the user is active and, for an
-- organisation's feed, still an active member of it (a feed never outlives the membership it was made under); no row
-- for anything else. The API then binds that user (and organisation) and reads the deadlines under their RLS. Answers
-- any session: the hash is the capability, so a caller learns nothing it could not read with the token.
CREATE FUNCTION app_calendar_feed_lookup(p_token_hash bytea)
    RETURNS TABLE (feed_id uuid, user_id uuid, org_id uuid)
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT f.id, f.user_id, f.org_id
      FROM public.calendar_feeds f
      JOIN public.users u ON u.id = f.user_id
     WHERE f.token_hash = p_token_hash AND f.revoked_at IS NULL AND u.status = 'active'
       AND (f.org_id IS NULL
            OR EXISTS (SELECT 1 FROM public.memberships m
                        WHERE m.org_id = f.org_id AND m.user_id = f.user_id AND m.status = 'active'))
$$;

-- Stamps last_fetched_at (the shared clock) on the live feed p_feed, after a read through app_calendar_feed_lookup: for
-- a session bound to a user only that user's own feed, for an unbound one any live feed. Returns whether it stamped
-- (false for an unknown, revoked or another user's feed). bridge_app holds no UPDATE of last_fetched_at.
CREATE FUNCTION app_calendar_feed_touch(p_feed uuid) RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    UPDATE public.calendar_feeds f
       SET last_fetched_at = public.app_clock_now()
     WHERE f.id = p_feed AND f.revoked_at IS NULL
       AND (public.app_user_id() IS NULL OR f.user_id = public.app_user_id());
    RETURN FOUND;
END;
$$;

-- engagement_assignments, BEFORE INSERT OR UPDATE (on INSERT after engagement_assignments_0_visible), every role: a new
-- assignment names the engagement's organisation and an assignee who is an active owner, admin, reviewer or signatory
-- of it (check_violation); an assignment's keys, people and time never change (check_violation); it is closed once,
-- unassigned_at the shared clock whatever is sent, and never reopened (object_not_in_prerequisite_state). SECURITY
-- DEFINER: reads the engagement and the assignee's membership whatever the caller's visibility.
CREATE FUNCTION engagement_assignments_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (SELECT 1 FROM public.engagements e WHERE e.id = NEW.engagement_id AND e.org_id = NEW.org_id) THEN
            RAISE EXCEPTION 'engagement_assignments: the organisation is the engagement''s'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.memberships m
             WHERE m.org_id = NEW.org_id AND m.user_id = NEW.assignee_user_id AND m.status = 'active'
               AND m.roles && CAST('{owner,admin,reviewer,signatory}' AS public.org_role[])) THEN
            RAISE EXCEPTION 'engagement_assignments: the assignee must be an active owner, admin, reviewer or signatory'
                ' of the organisation' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.id, NEW.engagement_id, NEW.org_id, NEW.assignee_user_id, NEW.assigned_by, NEW.assigned_at)
       IS DISTINCT FROM (OLD.id, OLD.engagement_id, OLD.org_id, OLD.assignee_user_id, OLD.assigned_by, OLD.assigned_at)
    THEN
        RAISE EXCEPTION 'engagement_assignments: an assignment''s engagement, organisation, assignee, assigner and time'
            ' never change' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.unassigned_at IS NOT NULL THEN
        RAISE EXCEPTION 'engagement_assignments: a closed assignment stays closed'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF NEW.unassigned_at IS NOT NULL THEN
        NEW.unassigned_at := public.app_clock_now();
    END IF;
    RETURN NEW;
END;
$$;

-- engagement_recommendations, BEFORE INSERT OR UPDATE (on INSERT after engagement_recommendations_0_visible), every
-- role: a new recommendation names the engagement's organisation and a member who is an active owner, admin, reviewer
-- or signatory of it (check_violation); its keys, member and creation time never change (check_violation), and
-- updated_at is the shared clock on every update. SECURITY DEFINER: reads the engagement and the membership whatever
-- the caller's visibility.
CREATE FUNCTION engagement_recommendations_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (SELECT 1 FROM public.engagements e WHERE e.id = NEW.engagement_id AND e.org_id = NEW.org_id) THEN
            RAISE EXCEPTION 'engagement_recommendations: the organisation is the engagement''s'
                USING ERRCODE = 'check_violation';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.memberships m
             WHERE m.org_id = NEW.org_id AND m.user_id = NEW.member_user_id AND m.status = 'active'
               AND m.roles && CAST('{owner,admin,reviewer,signatory}' AS public.org_role[])) THEN
            RAISE EXCEPTION 'engagement_recommendations: the member must be an active owner, admin, reviewer or'
                ' signatory of the organisation' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.id, NEW.engagement_id, NEW.org_id, NEW.member_user_id, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.engagement_id, OLD.org_id, OLD.member_user_id, OLD.created_at) THEN
        RAISE EXCEPTION 'engagement_recommendations: a recommendation''s engagement, organisation, member and creation'
            ' time never change' USING ERRCODE = 'check_violation';
    END IF;
    NEW.updated_at := public.app_clock_now();
    RETURN NEW;
END;
$$;

-- prior_knowledge_declarations, BEFORE INSERT after prior_knowledge_declarations_0_visible (the engagement is the
-- caller's): the organisation, proposal and version are the engagement's, for every writer (check_violation). Then, for
-- every writer but the table's owner (a seed or a backfill keeps what it sends), the window is the database's
-- (REQ-PROV-06): the first Tier-2 view and the closing day from app_prior_knowledge_window, refused before any view
-- and once the Nairobi day on the shared clock is past the closing day (object_not_in_prerequisite_state), evidence
-- dated after that day refused (check_violation), and first_tier2_view_at, window_closes_on and declared_at set
-- whatever was sent. SECURITY INVOKER: current_user is the writer (as consents_created_now() of revision 0012) and the
-- engagement is read under the writer's RLS; app_prior_knowledge_window is bridge_app's to execute.
CREATE FUNCTION prior_knowledge_declarations_window() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_org uuid;
    v_proposal uuid;
    v_version uuid;
    v_first timestamptz;
    v_closes date;
    v_today date;
BEGIN
    SELECT e.org_id, e.proposal_id, e.version_id INTO v_org, v_proposal, v_version
      FROM public.engagements e WHERE e.id = NEW.engagement_id;
    IF (NEW.org_id, NEW.proposal_id, NEW.version_id) IS DISTINCT FROM (v_org, v_proposal, v_version) THEN
        RAISE EXCEPTION 'prior_knowledge_declarations: the organisation, proposal and version are the engagement''s'
            USING ERRCODE = 'check_violation';
    END IF;
    IF current_user = (SELECT pg_catalog.pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c WHERE c.oid = TG_RELID)
    THEN
        RETURN NEW;
    END IF;
    SELECT w.first_tier2_view_at, w.window_closes_on INTO v_first, v_closes
      FROM public.app_prior_knowledge_window(NEW.engagement_id) w;
    IF v_first IS NULL THEN
        RAISE EXCEPTION 'prior_knowledge_declarations: the organisation has not viewed the proposal''s Tier 2 yet'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    v_today := public.app_nairobi_today();
    IF v_today > v_closes THEN
        RAISE EXCEPTION 'prior_knowledge_declarations: the declaration window closed on %', v_closes
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF NEW.evidence_dated_on > v_today THEN
        RAISE EXCEPTION 'prior_knowledge_declarations: the evidence is dated after today'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.first_tier2_view_at := v_first;
    NEW.window_closes_on := v_closes;
    NEW.declared_at := public.app_clock_now();
    RETURN NEW;
END;
$$;

-- calendar_feeds, BEFORE UPDATE, every role: a feed's keys, user, organisation, token and creation time never change
-- (check_violation); a revoked feed never changes again (object_not_in_prerequisite_state); revoked_at is the shared
-- clock whatever is sent. last_fetched_at moves only through app_calendar_feed_touch (bridge_app holds no UPDATE of
-- it).
CREATE FUNCTION calendar_feeds_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.id, NEW.user_id, NEW.org_id, NEW.token_hash, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.user_id, OLD.org_id, OLD.token_hash, OLD.created_at) THEN
        RAISE EXCEPTION 'calendar_feeds: a feed''s user, organisation, token and creation time never change'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'calendar_feeds: a revoked feed never changes'
            USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    IF NEW.revoked_at IS NOT NULL THEN
        NEW.revoked_at := public.app_clock_now();
    END IF;
    RETURN NEW;
END;
$$;
"""

# EXECUTE grants (EXECUTE revoked from PUBLIC first): a trigger runs the functions it calls with the caller's
# privileges, so prior_knowledge_declarations_window() needs app_prior_knowledge_window granted.
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_prior_knowledge_window(uuid)": ("bridge_app",),  # the API's prior_knowledge facts and the window trigger
    "app_calendar_feed_lookup(bytea)": ("bridge_app",),  # the unauthenticated feed read
    "app_calendar_feed_touch(uuid)": ("bridge_app",),  # the feed read, after the lookup
}
INTERNAL_FUNCTIONS = ("kenyan_business_days_after(date, integer)",)
TRIGGER_FUNCTIONS = (
    "engagement_assignments_guard()",
    "engagement_recommendations_guard()",
    "prior_knowledge_declarations_window()",
    "calendar_feeds_guard()",
)

# Triggers of one timing and event fire in name order: <table>_0_visible (revision 0003's tracker_engagement_visible())
# first on INSERT, so the definer triggers after it read and report nothing about an engagement the caller cannot see.
TRIGGERS_SQL = r"""
CREATE TRIGGER engagement_assignments_0_visible
    BEFORE INSERT ON engagement_assignments
    FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();
CREATE TRIGGER engagement_assignments_guard
    BEFORE INSERT OR UPDATE ON engagement_assignments
    FOR EACH ROW EXECUTE FUNCTION engagement_assignments_guard();
CREATE TRIGGER engagement_recommendations_0_visible
    BEFORE INSERT ON engagement_recommendations
    FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();
CREATE TRIGGER engagement_recommendations_guard
    BEFORE INSERT OR UPDATE ON engagement_recommendations
    FOR EACH ROW EXECUTE FUNCTION engagement_recommendations_guard();
CREATE TRIGGER prior_knowledge_declarations_0_visible
    BEFORE INSERT ON prior_knowledge_declarations
    FOR EACH ROW EXECUTE FUNCTION tracker_engagement_visible();
CREATE TRIGGER prior_knowledge_declarations_1_window
    BEFORE INSERT ON prior_knowledge_declarations
    FOR EACH ROW EXECUTE FUNCTION prior_knowledge_declarations_window();
CREATE TRIGGER prior_knowledge_declarations_no_update_delete
    BEFORE UPDATE OR DELETE ON prior_knowledge_declarations
    FOR EACH ROW EXECUTE FUNCTION block_mutation();
CREATE TRIGGER prior_knowledge_declarations_no_truncate
    BEFORE TRUNCATE ON prior_knowledge_declarations
    FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();
CREATE TRIGGER calendar_feeds_guard
    BEFORE UPDATE ON calendar_feeds
    FOR EACH ROW EXECUTE FUNCTION calendar_feeds_guard();
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
    postgresql.ENUM(*STANCES, name="recommendation_stance").create(op.get_bind(), checkfirst=False)
    _add_profile_columns()
    _create_tables()
    _run_sql(FUNCTIONS_SQL)  # after the tables: app_calendar_feed_lookup's body reads calendar_feeds
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    """Destructive: drops the organisations' assignments and internal recommendations, every prior-knowledge
    declaration (append-only evidence the owner was shown and the evidence pack lists), every calendar feed (their URLs
    stop working) and every developer's self-reported D3 references and nudge dismissal. Under the CLAUDE.md stop rule
    a downgrade of a database holding any of them is a destructive migration: back the database up and get the human's
    decision first. The downgrade refuses while any of the tables has rows or any profile holds one of the four
    columns, unless it is run with ``-x allow_p27_loss=true`` (``alembic -x allow_p27_loss=true downgrade 0012``)."""
    allowed = context.get_x_argument(as_dictionary=True).get("allow_p27_loss") == "true"
    bind = op.get_bind()
    holding = [
        table for table in NEW_TABLES if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")).scalar()
    ]
    held_profile = " OR ".join(f"{column} IS NOT NULL" for column in PROFILE_COLUMNS)
    if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM developer_profiles WHERE {held_profile})")).scalar():
        holding.append("developer_profiles (D3 references or nudge dismissals)")
    if holding and not allowed:
        raise RuntimeError(
            f"revision 0013 downgrade: {', '.join(holding)} hold the organisations' assignments and recommendations,"
            " prior-knowledge declarations, calendar feeds or developers' D3 references; back the database up, get the"
            " human's decision (CLAUDE.md: destructive migration), then run with -x allow_p27_loss=true"
        )
    # Dropping a table drops its policies, triggers, indexes and grants (tracker_engagement_visible(), block_mutation(),
    # app_clock_now(), app_nairobi_today(), app_is_member() and app_is_staff() are earlier revisions' and stay).
    # Dropping a column drops its grant.
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    _run_sql(
        "\n".join(
            f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *FUNCTION_GRANTS, *INTERNAL_FUNCTIONS)
        )
    )
    for name, _expression in reversed(PROFILE_CHECKS):
        op.drop_constraint(op.f(f"ck_developer_profiles_{name}"), "developer_profiles", type_="check")
    for column in reversed(PROFILE_COLUMNS):
        op.drop_column("developer_profiles", column)
    postgresql.ENUM(name="recommendation_stance").drop(bind, checkfirst=False)


def _add_profile_columns() -> None:
    op.add_column("developer_profiles", sa.Column("github_login", sa.String(length=39), nullable=True))
    op.add_column("developer_profiles", sa.Column("kecobo_number", sa.String(length=40), nullable=True))
    op.add_column("developer_profiles", sa.Column("kipi_number", sa.String(length=40), nullable=True))
    op.add_column("developer_profiles", sa.Column("ip_nudge_dismissed_at", sa.DateTime(timezone=True), nullable=True))
    for name, expression in PROFILE_CHECKS:
        op.create_check_constraint(op.f(f"ck_developer_profiles_{name}"), "developer_profiles", expression)


def _create_tables() -> None:
    op.create_table(
        "engagement_assignments",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by", sa.Uuid(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("unassigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "unassigned_at IS NULL OR unassigned_at >= assigned_at",
            name=op.f("ck_engagement_assignments_unassigned_after_assigned"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["users.id"], name=op.f("fk_engagement_assignments_assigned_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"], ["users.id"], name=op.f("fk_engagement_assignments_assignee_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_engagement_assignments_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_engagement_assignments_org_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_assignments")),
    )
    op.create_index(
        "uq_engagement_assignments_live",
        "engagement_assignments",
        ["engagement_id"],
        unique=True,
        postgresql_where=sa.text("unassigned_at IS NULL"),
    )
    op.create_index(
        "ix_engagement_assignments_assignee_live",
        "engagement_assignments",
        ["org_id", "assignee_user_id"],
        unique=False,
        postgresql_where=sa.text("unassigned_at IS NULL"),
    )
    op.create_table(
        "engagement_recommendations",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("member_user_id", sa.Uuid(), nullable=False),
        sa.Column("stance", postgresql.ENUM(*STANCES, name="recommendation_stance", create_type=False), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"note IS NULL OR ({_one_line('note', 200)})", name=op.f("ck_engagement_recommendations_note_valid")
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"], ["engagements.id"], name=op.f("fk_engagement_recommendations_engagement_id_engagements")
        ),
        sa.ForeignKeyConstraint(
            ["member_user_id"], ["users.id"], name=op.f("fk_engagement_recommendations_member_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_engagement_recommendations_org_id_organizations")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_engagement_recommendations")),
        sa.UniqueConstraint(
            "engagement_id",
            "member_user_id",
            name=op.f("uq_engagement_recommendations_engagement_id_member_user_id"),
        ),
    )
    op.create_table(
        "prior_knowledge_declarations",
        sa.Column("engagement_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("declared_by", sa.Uuid(), nullable=False),
        sa.Column("evidence_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("evidence_title", sa.Text(), nullable=False),
        sa.Column("evidence_dated_on", sa.Date(), nullable=False),
        sa.Column("first_tier2_view_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_closes_on", sa.Date(), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            f"declared_at >= first_tier2_view_at AND {_nairobi_day('declared_at')} <= window_closes_on",
            name=op.f("ck_prior_knowledge_declarations_declared_within_window"),
        ),
        sa.CheckConstraint(
            f"evidence_dated_on <= {_nairobi_day('declared_at')}",
            name=op.f("ck_prior_knowledge_declarations_evidence_dated_by_declaration"),
        ),
        sa.CheckConstraint(
            _one_line("evidence_title", 200), name=op.f("ck_prior_knowledge_declarations_evidence_title_valid")
        ),
        sa.CheckConstraint(
            f"window_closes_on > {_nairobi_day('first_tier2_view_at')}",
            name=op.f("ck_prior_knowledge_declarations_window_after_first_view"),
        ),
        sa.CheckConstraint(
            "octet_length(evidence_sha256) = 32", name=op.f("ck_prior_knowledge_declarations_evidence_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["declared_by"], ["users.id"], name=op.f("fk_prior_knowledge_declarations_declared_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["engagement_id"],
            ["engagements.id"],
            name=op.f("fk_prior_knowledge_declarations_engagement_id_engagements"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_prior_knowledge_declarations_org_id_organizations")
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_prior_knowledge_declarations_version",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposals.id"], name=op.f("fk_prior_knowledge_declarations_proposal_id_proposals")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prior_knowledge_declarations")),
        sa.UniqueConstraint("engagement_id", name=op.f("uq_prior_knowledge_declarations_engagement_id")),
    )
    op.create_table(
        "calendar_feeds",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("octet_length(token_hash) = 32", name=op.f("ck_calendar_feeds_token_hash_sha256")),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at", name=op.f("ck_calendar_feeds_revoked_after_created")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_calendar_feeds_org_id_organizations")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_calendar_feeds_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_feeds")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_calendar_feeds_token_hash")),
    )
    op.create_index(
        "uq_calendar_feeds_live_personal",
        "calendar_feeds",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("org_id IS NULL AND revoked_at IS NULL"),
    )
    op.create_index(
        "uq_calendar_feeds_live_org",
        "calendar_feeds",
        ["user_id", "org_id"],
        unique=True,
        postgresql_where=sa.text("org_id IS NOT NULL AND revoked_at IS NULL"),
    )
