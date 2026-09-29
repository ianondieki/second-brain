"""Schema v4 (prototype M2): scouts, research runs, trend aggregates and fake payments (P10, P11, P12, P14).

REQ-SCOUT-01 and REQ-SCOUT-02 (``scout_agents``, ``agent_runs``, ``agent_matches``, ``app_scouts_due``), REQ-RES-01
(``research_runs``, ``app_create_research_candidate``, the AC-RES-1 publication backstop on ``problems``), REQ-TREND-01
(``app_trend_aggregates``), REQ-BIL-08 and the REQ-BIL-04 interface (``payments``, ``app_settle_payment``,
``app_activate_paid_subscription``, ``payments_guard``). Design: ``docs/platform/prototype-m2-plan.md`` §2 and the
"Revision 0005" section of ``docs/platform/tasks/REQ-SCOUT-01.md``. Additive: 5 new tables, 5 new enum types, three new
columns on ``problems`` and ``problem_sources``, one trigger on ``problems``, and bridge_app's INSERT on ``problems``
and ``problem_sources`` narrowed to every column but the new ones (the table-wide grants are restored on downgrade).
Nothing of revisions 0001 to 0004 is changed or dropped. D-43: the scout has no database role of its own in the
prototype (the worker is bridge_app; the scout code never reads Tier 2, enforced by P10's import-lint and prompt tests).

Who writes what (RLS; bridge_app; ``app.org_id`` narrows every organisation predicate when set):

- ``scout_agents`` (ORG): members read; the organisation's owner or admin inserts (as ``created_by``), updates the
  form, pause and cursor columns (column grant) and deletes (runs and matches go with the scout: ON DELETE CASCADE).
  Niches 1 to 5 distinct ids, counties at most 47 codes, include and exclude keywords at most 20 of at most 60
  characters, maturity at most 4, ``min_fit`` 0 to 100 (default 60), language ``en`` or ``sw``, recipients at most 20
  distinct ids, each an active reviewer of the organisation when the list is written (``scout_agents_recipients``,
  AFTER, after RLS; the digest re-checks at send time).
- On ``agent_runs`` and ``agent_matches`` the first BEFORE INSERT trigger (``<table>_0_visible``,
  ``scout_row_visible()``, SECURITY INVOKER) refuses a row naming a scout the caller cannot see under that
  organisation, with one message, before any unique or foreign key check could tell another organisation that the
  scout exists or what it matched.
- ``agent_runs`` (ORG): members read; an acting member (owner, admin, signatory or reviewer: a job binds the
  ``act_as_user_id`` that ``app_scouts_due`` names) inserts a running run and updates its status, counts and error code;
  no DELETE. ``error_code`` is a code, never free text; a failed run carries one, no other does.
- ``agent_matches`` (ORG only): members read; an acting member inserts a match for the current registered version of a
  published, clear proposal (read under the caller's own RLS), with no feedback and no digest time; UPDATE of the
  feedback columns (the caller's own ``feedback_by``) and ``digest_sent_at`` only. UNIQUE (scout_id, proposal_id): a
  proposal is matched once per scout across runs (AC-SCOUT-6).
- ``research_runs`` (STAFF): staff admin only (read, insert as ``started_by``, update); CHECK searches <= 25 and
  fetches <= 40 (AC-RES-3). Candidates come only from ``app_create_research_candidate``.
- ``payments`` (ORG_OR_USER): the user, or the organisation's owner, admin or finance member, reads; inserts a pending
  payment (as ``initiated_by``) for an active, non-default plan of the subject's side at exactly its price; no UPDATE
  or DELETE grant. Provider ``fake`` only (CHECK); ``provider_ref`` platform-generated and unique; no phone column.
  Status and subscription change only through the two definers below; ``payments_guard`` (every role, the owner too)
  refuses DELETE and TRUNCATE, keeps the subject, plan, amount, provider and reference, settles once
  (pending -> succeeded | failed | cancelled, ``settled_at`` from ``app_clock_now()``) and links a succeeded payment to
  one subscription once. A payment starts pending, unsettled and unlinked, for every role.
- ``problems``: ``research_run_id`` (only on ``research_agent`` rows) and ``named_orgs`` (at most 10) and
  ``problem_sources.excerpt_ref``: written only by ``app_create_research_candidate``; bridge_app neither inserts nor
  updates them (column grants). ``problems_research_guard`` (every role): a ``research_agent`` problem reaches
  ``published`` only with one official source or two distinct publishers among sources that carry a quote and a date
  (AC-RES-1), and, when it names organisations, an official source (docs/spec/06 6.5).

SECURITY DEFINER functions (pinned search_path, EXECUTE revoked from PUBLIC and granted to bridge_app only):

- ``app_scouts_due(p_now, p_trigger, p_proposal)`` -> (scout_id, org_id, act_as_user_id): the scouts.scan job only
  (refused while a user is bound). Unpaused scouts of the trigger's frequency of E1 or E2 organisations that are not
  suspended; ``act_as_user_id`` is the scout's creator while an active owner or admin, else the organisation's earliest
  active owner or admin (no such member: the scout is not due). daily and weekly: none already run (running or
  completed, not failed) in the same Africa/Nairobi day or ISO week as ``p_now``; on_new: only for a published, clear
  proposal the scout has not matched yet. Nothing else is returned.
- ``app_create_research_candidate(run, title, statement, affected_group, county, confidence, named_orgs, sources)``:
  staff admin only, on the caller's own running run; a title of 1 to 90 characters and a statement of at most 120
  words; confidence 0.40 to 1; 1 to 10 sources, each an object of string values with an https URL, a published date
  (YYYY-MM-DD), a retrieval time and a quote (optional publisher, source type of the 6.5 tiers, excerpt ref; nothing
  else); a card naming organisations needs an official source. Inserts the candidate (``created_by`` NULL, so the same
  admin may approve it through ``app_moderate_problem``) and its sources in one call, niche and country from the run.
- ``app_settle_payment(payment, status, failure_code)``: the payment's subject only (one refusal, the same for a
  payment that does not exist); pending -> succeeded, failed or cancelled once; repeating the same outcome is a no-op
  (false); another outcome is refused.
- ``app_activate_paid_subscription(payment)``: the subject only; a succeeded payment whose plan is of the subject's
  side at the paid amount; serialised per subject; cancels the subject's live subscription and inserts the new one
  from ``app_clock_now()`` (a month or a year, per the plan's interval), linking the payment; a linked payment returns
  its subscription (idempotent).
- ``app_trend_aggregates(p_since, p_now)``: signal_events in [p_since, p_now) (at most 400 days) per item, kind and
  Africa/Nairobi day: ``events`` counts each actor once per item and day (actor-less signals once per day); ``actors``
  is the item and kind's distinct actors over the window; ``orgs`` its distinct organisations only when there are 3 or
  more, else NULL. It never returns an actor hash, an organisation hash or an organisation id.

Owner of ``app_trend_aggregates``: ``bridge_owner``, not ``aggregate_worker`` (docs/spec/08 reads aggregates under
that role). ``ALTER FUNCTION ... OWNER TO aggregate_worker`` needs the migration role to be able to ``SET ROLE``
``aggregate_worker`` and ``aggregate_worker`` to hold CREATE on schema ``public``: ``roles.sql`` gives ``bridge_owner``
no membership in it and ``prepare_db.sql`` lets nobody but the owner create in ``public``; granting either would give a
runtime role an owned object (``test_runtime_roles_own_nothing``) and a login path to CREATE. bridge_app cannot switch
to ``aggregate_worker`` either (it is a member of the Tier-2 roles only). So the definer runs as the owner, reads
``signal_events`` only, and returns counts only; the query is the whole of its privilege.

Operating rules for the code that uses this schema:

- The scan job calls ``app_scouts_due`` with no user bound, then binds each ``act_as_user_id`` with the scout's
  organisation (``bind_tenant``) for its run: runs, matches and the cursor are written under that binding.
- Leave ``agent_runs.started_at`` out (``app_clock_now()``, so due-ness follows the test clock).
- Research runs bind the staff admin who started them; create candidates only through ``app_create_research_candidate``.
- Payments: insert pending at the plan's price, query the provider, then ``app_settle_payment`` and
  ``app_activate_paid_subscription`` (refresh the ORM rows afterwards: the functions changed them). The database cannot
  tell a paid checkout from a claimed one: the provider query is the application's (docs/spec/05).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types created by this revision, frozen here (the ORM enums in bridge.models.enums must match; a test compares).
ENUMS: dict[str, tuple[str, ...]] = {
    "scout_frequency": ("daily", "weekly", "on_new"),
    "agent_run_status": ("running", "completed", "failed"),
    "match_feedback": ("relevant", "not_relevant"),
    "research_run_status": ("running", "completed", "stopped", "failed"),
    "payment_status": ("pending", "succeeded", "failed", "cancelled"),
}
# Revision 0002's enum used by this revision's tables (not created or dropped here).
PROPOSAL_MATURITY = ("idea", "prototype", "mvp", "live")

RLS_TABLES = ("scout_agents", "agent_runs", "agent_matches", "research_runs", "payments")

# Table privileges of bridge_app on this revision's tables; anything not listed is not granted. UPDATE is column-scoped
# wherever some columns are never the app's (keys, owners, creators, start times).
APP_GRANTS: dict[str, str] = {
    "scout_agents": (
        "SELECT, INSERT, DELETE, UPDATE (niches, counties, include_keywords, exclude_keywords, maturity, budget_band,"
        " min_fit, frequency, language, recipients, paused_at, cursor_at, cursor_proposal_id, updated_at)"
    ),
    # started_at is the database's clock (its default, app_clock_now()): never inserted or updated by the app, so a
    # run is never forward- or back-dated.
    "agent_runs": (
        "SELECT, INSERT (id, scout_id, org_id, trigger, status, finished_at, window_start, window_end, scanned_count,"
        " matched_count, error_code), UPDATE (status, finished_at, scanned_count, matched_count, error_code)"
    ),
    "agent_matches": "SELECT, INSERT, UPDATE (feedback, feedback_reason, feedback_by, feedback_at, digest_sent_at)",
    "research_runs": (
        "SELECT, INSERT, UPDATE (status, finished_at, searches, fetches, input_tokens, candidates, discarded, cost_usd,"
        " stop_reason, demo_fallback, updated_at)"
    ),
    "payments": "SELECT, INSERT",  # status and subscription change only through the definer functions
}
# The new problems and problem_sources columns are app_create_research_candidate()'s: bridge_app's table-wide INSERT of
# revision 0002 becomes an INSERT of every other column (restored to the table-wide grant on downgrade).
PROBLEMS_INSERTABLE_COLUMNS = (
    "id, source, niche_id, country, county_code, title, statement, affected_group, status, created_by, org_id,"
    " ai_generated, confidence, cluster_id, moderator_id, moderation_state, embedding, embed_model, embed_version,"
    " published_at, updated_at, created_at"
)
PROBLEM_SOURCES_INSERTABLE_COLUMNS = (
    "id, problem_id, url, publisher, source_type, published_date, retrieved_at, quote, created_at"
)

# CHECK expressions, verbatim from the ORM models.
CODE = "'^[a-z][a-z0-9_]{0,39}$'"  # an error, stop, failure or feedback code: never free text


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


# Predicates. app_org_id() narrows every organisation predicate to the organisation a request is scoped to.
_NARROWED = "(app_org_id() IS NULL OR org_id = app_org_id())"
_ORG_MEMBER = f"app_is_member(org_id) AND {_NARROWED}"
# Who configures an organisation's scouts (docs/spec/06 6.8: an org admin): its owner or admin.
_SCOUT_ADMIN = f"app_is_member(org_id, '{{owner,admin}}') AND {_NARROWED}"
# Who acts for a scout (a run, a match, feedback): members who act on proposals; never a viewer or finance.
_SCOUT_ACTOR = f"app_is_member(org_id, '{{owner,admin,signatory,reviewer}}') AND {_NARROWED}"
_STAFF_ADMIN = "app_is_staff('{admin}')"
# A payment's subject: the user themselves, or the organisation's owner, admin or finance member.
_PAYMENT_SUBJECT = (
    "(user_id = app_user_id() AND org_id IS NULL) OR (user_id IS NULL AND org_id IS NOT NULL"
    f" AND app_is_member(org_id, '{{owner,admin,finance}}') AND {_NARROWED})"
)
# A new payment is pending, for an active, non-default (paid) plan of the subject's side, at exactly its price.
PAYMENT_INSERT = (
    f"({_PAYMENT_SUBJECT}) AND initiated_by = app_user_id() AND status = 'pending' AND settled_at IS NULL"
    " AND subscription_id IS NULL AND failure_code IS NULL"
    " AND EXISTS (SELECT 1 FROM plans p WHERE p.id = payments.plan_id AND p.active AND NOT p.is_default"
    " AND p.price_kes_minor = payments.amount_kes_minor"
    " AND p.side = CASE WHEN payments.org_id IS NULL THEN CAST('developer' AS plan_side)"
    " ELSE CAST('org' AS plan_side) END)"
)
# A match names the current registered version of a published, clear proposal (read under the caller's RLS), and
# carries no feedback and no digest time yet.
MATCH_INSERT = (
    f"{_SCOUT_ACTOR} AND digest_sent_at IS NULL AND feedback IS NULL AND feedback_reason IS NULL"
    " AND feedback_by IS NULL AND feedback_at IS NULL"
    " AND EXISTS (SELECT 1 FROM proposals p WHERE p.id = agent_matches.proposal_id"
    " AND p.current_version_id = agent_matches.version_id AND p.status = 'published' AND p.moderation_state = 'clear')"
)

POLICIES: tuple[Policy, ...] = (
    # --- scout_agents (ORG): members read; the owner or admin configures ---
    Policy("scout_agents", "SELECT", _ORG_MEMBER),
    Policy("scout_agents", "INSERT", check=f"{_SCOUT_ADMIN} AND created_by = app_user_id()"),
    Policy("scout_agents", "UPDATE", _SCOUT_ADMIN, _SCOUT_ADMIN),
    Policy("scout_agents", "DELETE", _SCOUT_ADMIN),
    # --- agent_runs (ORG): an acting member starts and finishes a run; never deleted by the app ---
    Policy("agent_runs", "SELECT", _ORG_MEMBER),
    Policy(
        "agent_runs",
        "INSERT",
        check=f"{_SCOUT_ACTOR} AND status = 'running' AND finished_at IS NULL AND error_code IS NULL",
    ),
    Policy("agent_runs", "UPDATE", _SCOUT_ACTOR, _SCOUT_ACTOR),
    # --- agent_matches (ORG only): matches of published proposals; feedback as oneself ---
    Policy("agent_matches", "SELECT", _ORG_MEMBER),
    Policy("agent_matches", "INSERT", check=MATCH_INSERT),
    # Whose feedback it is needs OLD: agent_matches_feedback_guard (a CHECK here on feedback_by would also stop every
    # other member, the digest job included, from updating a match someone judged).
    Policy("agent_matches", "UPDATE", _SCOUT_ACTOR, _SCOUT_ACTOR),
    # --- research_runs (STAFF): staff admin only ---
    Policy("research_runs", "SELECT", _STAFF_ADMIN),
    Policy(
        "research_runs",
        "INSERT",
        check=f"{_STAFF_ADMIN} AND started_by = app_user_id() AND status = 'running' AND finished_at IS NULL"
        " AND stop_reason IS NULL",
    ),
    Policy("research_runs", "UPDATE", _STAFF_ADMIN, _STAFF_ADMIN),
    # --- payments (ORG_OR_USER): the subject reads and starts a pending payment; nothing else is the app's ---
    Policy("payments", "SELECT", _PAYMENT_SUBJECT),
    Policy("payments", "INSERT", check=PAYMENT_INSERT),
)

# CHECK helpers, created before the tables (EXECUTE bridge_app: a CHECK runs its functions with the writer's
# privileges). Both are total: never NULL, so a CHECK never passes on an unknown.
CHECK_HELPERS_SQL = r"""
-- A set of ids: p_min to p_max distinct, non-NULL ids in a one-dimensional array (a scout's niches and recipients).
CREATE FUNCTION app_uuid_set_is_valid(p_ids uuid[], p_min integer, p_max integer) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT p_ids IS NOT NULL AND coalesce(array_ndims(p_ids), 1) = 1
       AND cardinality(p_ids) BETWEEN p_min AND p_max
       AND array_position(p_ids, NULL) IS NULL
       AND cardinality(p_ids) = (SELECT count(DISTINCT t.id) FROM unnest(p_ids) AS t(id))
$$;

-- A set of short texts: at most p_max distinct items in a one-dimensional array, each non-blank and at most p_len
-- characters (a scout's keywords and counties, a research card's named organisations).
CREATE FUNCTION app_text_set_is_valid(p_items text[], p_max integer, p_len integer) RETURNS boolean
    LANGUAGE sql IMMUTABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT p_items IS NOT NULL AND coalesce(array_ndims(p_items), 1) = 1
       AND cardinality(p_items) <= p_max
       AND NOT EXISTS (
           SELECT 1 FROM unnest(p_items) AS t(item)
            WHERE t.item IS NULL OR btrim(t.item) = '' OR length(t.item) > p_len)
       AND cardinality(p_items) = (SELECT count(DISTINCT t.item) FROM unnest(p_items) AS t(item))
$$;
"""

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. As in 0001 to 0004: every function pins search_path = pg_catalog, public, pg_temp (pg_temp last),
# EXECUTE is revoked from PUBLIC and granted explicitly (FUNCTION_GRANTS). SECURITY DEFINER functions run as
# bridge_owner, which bypasses RLS (ENABLED, not FORCED), and check their caller in SQL before changing anything.
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
-- The scouts due for a scan (docs/spec/06 6.8; REQ-SCOUT-02). Called by the scouts.scan job with no user bound (a
-- signed-in request learns nothing about other organisations' scouts), it returns only ids: the scout, its
-- organisation and the member the run acts for. Unpaused scouts of p_trigger's frequency, of E1 or E2 organisations
-- that are not suspended (pending organisations configure and preview only; REQ-SCOUT-07). The acting member is the
-- scout's creator while an active owner or admin of the organisation, else its earliest active owner or admin (both
-- active users); a scout whose organisation has none is not due. daily and weekly: not already run (running or
-- completed; a failed run may be retried) in the same Africa/Nairobi day or ISO week as p_now (the test clock's time),
-- so a repeated call finds nothing new. on_new: p_proposal is required and published and clear, and scouts that
-- already matched it are left out (AC-SCOUT-6).
CREATE FUNCTION app_scouts_due(p_now timestamptz, p_trigger scout_frequency, p_proposal uuid DEFAULT NULL)
    RETURNS TABLE (scout_id uuid, org_id uuid, act_as_user_id uuid)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF public.app_user_id() IS NOT NULL THEN
        RAISE EXCEPTION 'app_scouts_due: the scouts.scan job only, with no user bound'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_now IS NULL OR p_trigger IS NULL OR (p_trigger = 'on_new') <> (p_proposal IS NOT NULL) THEN
        RAISE EXCEPTION 'app_scouts_due: name the time and the trigger, and a proposal for (and only for) on_new'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    SELECT s.id, s.org_id, a.user_id
      FROM public.scout_agents s
      JOIN public.organizations o ON o.id = s.org_id
     CROSS JOIN LATERAL (
            SELECT m.user_id
              FROM public.memberships m
              JOIN public.users u ON u.id = m.user_id
             WHERE m.org_id = s.org_id AND m.status = 'active' AND u.status = 'active'
               AND m.roles && '{owner,admin}'::public.org_role[]
             ORDER BY m.user_id = s.created_by DESC, m.created_at, m.id
             LIMIT 1) a
     WHERE s.frequency = p_trigger
       AND s.paused_at IS NULL
       AND o.verification IN ('e1', 'e2')
       AND o.suspended_at IS NULL
       AND CASE WHEN p_trigger = 'on_new' THEN
                EXISTS (SELECT 1 FROM public.proposals p
                         WHERE p.id = p_proposal AND p.status = 'published' AND p.moderation_state = 'clear')
                AND NOT EXISTS (SELECT 1 FROM public.agent_matches am
                                 WHERE am.scout_id = s.id AND am.proposal_id = p_proposal)
           ELSE NOT EXISTS (
                SELECT 1 FROM public.agent_runs r
                 WHERE r.scout_id = s.id AND r.trigger = p_trigger AND r.status <> 'failed'
                   AND date_trunc(CASE WHEN p_trigger = 'daily' THEN 'day' ELSE 'week' END,
                                  r.started_at AT TIME ZONE 'Africa/Nairobi')
                     = date_trunc(CASE WHEN p_trigger = 'daily' THEN 'day' ELSE 'week' END,
                                  p_now AT TIME ZONE 'Africa/Nairobi'))
           END
     ORDER BY s.id;
END;
$$;

-- One source of a research candidate (docs/spec/06 6.5 evidence[]): an object whose values are strings, with an https
-- URL on an ASCII host (letters, digits, dots and hyphens, an optional port; no user info, no whitespace), a published
-- date (YYYY-MM-DD, a real date), a retrieval time from the published date up to now (app_clock_now()), and a
-- non-blank quote of at most 2000 characters; optionally a publisher (non-blank, at most 200), a source type of the
-- 6.5 quality tiers and an excerpt ref (the saved excerpt's id); no other key; no control character (U+0001-U+001F,
-- U+007F) in the URL, the quote or the publisher. Every malformed date or time (any data exception: a bad format, an
-- out-of-range field, a time zone) is the same false. Internal: only app_create_research_candidate() calls it, as the
-- owner. VOLATILE: it reads the clock.
CREATE FUNCTION app_research_source_is_valid(p_source jsonb) RETURNS boolean
    LANGUAGE plpgsql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_date date;
    v_retrieved timestamptz;
BEGIN
    IF p_source IS NULL OR jsonb_typeof(p_source) <> 'object' THEN
        RETURN false;
    END IF;
    IF EXISTS (SELECT 1 FROM jsonb_each(p_source) AS kv(key, value)
                WHERE kv.key NOT IN ('url', 'publisher', 'source_type', 'published_date', 'retrieved_at', 'quote',
                                     'excerpt_ref')
                   OR jsonb_typeof(kv.value) <> 'string') THEN
        RETURN false;
    END IF;
    IF NOT coalesce(p_source->>'url' ~ '^https://[A-Za-z0-9.-]+(:[0-9]+)?(/[^[:space:]]*)?$'
                    AND length(p_source->>'url') <= 1000, false)
       OR coalesce(p_source->>'url' ~ '[\x01-\x1f\x7f]' OR p_source->>'quote' ~ '[\x01-\x1f\x7f]'
                   OR p_source->>'publisher' ~ '[\x01-\x1f\x7f]', false)
       OR NOT coalesce(btrim(p_source->>'quote') <> '' AND length(p_source->>'quote') <= 2000, false)
       OR NOT coalesce(p_source->>'published_date' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$', false)
       OR NOT coalesce(p_source->>'retrieved_at' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}([T ][^[:space:]].*)?$', false)
       OR (p_source ? 'publisher'
           AND NOT (btrim(p_source->>'publisher') <> '' AND length(p_source->>'publisher') <= 200))
       OR (p_source ? 'source_type'
           AND p_source->>'source_type' NOT IN ('official', 'filing', 'news', 'ngo', 'blog', 'social'))
       OR (p_source ? 'excerpt_ref' AND p_source->>'excerpt_ref' !~ '^[A-Za-z0-9_.:-]{1,32}$') THEN
        RETURN false;
    END IF;
    BEGIN
        v_date := CAST(p_source->>'published_date' AS date);
        v_retrieved := CAST(p_source->>'retrieved_at' AS timestamptz);
    EXCEPTION WHEN data_exception THEN
        RETURN false;
    END;
    RETURN v_date IS NOT NULL AND v_retrieved IS NOT NULL
       AND (v_retrieved AT TIME ZONE 'Africa/Nairobi')::date >= v_date
       AND v_retrieved <= public.app_clock_now();
END;
$$;

-- The only way a research card enters the database (REQ-RES-01; docs/spec/06 6.5): staff admin only, on the
-- caller's own running run (read FOR SHARE, so a run finishing meanwhile takes no further candidate). The card is a
-- candidate (never public: 0002's policies), ai_generated, with the run's niche and country and, for a county run,
-- its county; created_by is NULL, so the same staff admin may approve it through app_moderate_problem(). A title of
-- 1 to 90 characters, a statement of at most 120 words and 1500 characters, an affected group of at most 200
-- characters, no control character (U+0001-U+001F, U+007F) in any of them or in a named organisation, confidence
-- 0.40 to 1 (below 0.40 is discarded), 1 to 10 valid sources (app_research_source_is_valid), and an official source
-- when the card names organisations. The card and its sources are written in one call: a refused source leaves
-- nothing behind. Returns the card's id.
CREATE FUNCTION app_create_research_candidate(
    p_run uuid, p_title text, p_statement text, p_affected_group text, p_county_code text, p_confidence numeric,
    p_named_orgs text[], p_sources jsonb
) RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_run public.research_runs%ROWTYPE;
    v_problem uuid := public.uuid7();
    v_valid boolean;
BEGIN
    IF NOT public.app_is_staff('{admin}') THEN
        RAISE EXCEPTION 'app_create_research_candidate: staff admin only' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO v_run FROM public.research_runs r WHERE r.id = p_run FOR SHARE;
    IF v_run.id IS NULL OR v_run.started_by IS DISTINCT FROM public.app_user_id() OR v_run.status <> 'running' THEN
        RAISE EXCEPTION 'app_create_research_candidate: no running research run of the caller''s with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_confidence IS NULL OR p_confidence < 0.40 OR p_confidence > 1 THEN
        RAISE EXCEPTION 'app_create_research_candidate: confidence is 0.40 to 1 (a card below 0.40 is discarded)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF p_title IS NULL OR btrim(p_title) = '' OR length(btrim(p_title)) > 90 OR p_title ~ '[\x01-\x1f\x7f]'
       OR p_statement IS NULL OR btrim(p_statement) = '' OR length(p_statement) > 1500
       OR p_statement ~ '[\x01-\x1f\x7f]'
       OR cardinality(regexp_split_to_array(btrim(p_statement), '\s+')) > 120 THEN
        RAISE EXCEPTION 'app_create_research_candidate: a title of 1 to 90 characters and a statement of 1 to 120 words'
            ' (at most 1500 characters), without control characters' USING ERRCODE = 'check_violation';
    END IF;
    IF length(p_affected_group) > 200 OR p_affected_group ~ '[\x01-\x1f\x7f]'
       OR EXISTS (SELECT 1 FROM unnest(p_named_orgs) AS n(name) WHERE n.name ~ '[\x01-\x1f\x7f]') THEN
        RAISE EXCEPTION 'app_create_research_candidate: an affected group of at most 200 characters and named'
            ' organisations without control characters' USING ERRCODE = 'check_violation';
    END IF;
    IF v_run.county_code IS NOT NULL AND p_county_code IS NOT NULL AND p_county_code <> v_run.county_code THEN
        RAISE EXCEPTION 'app_create_research_candidate: a county run''s card is of its county'
            USING ERRCODE = 'check_violation';
    END IF;
    IF p_sources IS NULL OR jsonb_typeof(p_sources) <> 'array' THEN
        v_valid := false;
    ELSE
        v_valid := jsonb_array_length(p_sources) BETWEEN 1 AND 10 AND NOT EXISTS (
            SELECT 1 FROM jsonb_array_elements(p_sources) AS t(source)
             WHERE NOT public.app_research_source_is_valid(t.source));
    END IF;
    IF NOT v_valid THEN
        RAISE EXCEPTION 'app_create_research_candidate: 1 to 10 sources, each with an https URL, a published date, a'
            ' retrieval time and a quote' USING ERRCODE = 'check_violation';
    END IF;
    IF cardinality(coalesce(p_named_orgs, '{}')) > 0 AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_sources) AS t(source) WHERE t.source->>'source_type' = 'official'
    ) THEN
        RAISE EXCEPTION 'app_create_research_candidate: a card naming an organisation needs an official source'
            USING ERRCODE = 'check_violation';
    END IF;
    INSERT INTO public.problems (id, source, niche_id, country, county_code, title, statement, affected_group, status,
                                 created_by, org_id, ai_generated, confidence, moderation_state, research_run_id,
                                 named_orgs)
    VALUES (v_problem, 'research_agent', v_run.niche_id, v_run.country, coalesce(p_county_code, v_run.county_code),
            btrim(p_title), btrim(p_statement), nullif(btrim(p_affected_group), ''), 'candidate', NULL, NULL, true,
            p_confidence, 'clear', p_run, coalesce(p_named_orgs, '{}'));
    INSERT INTO public.problem_sources (id, problem_id, url, publisher, source_type, published_date, retrieved_at,
                                       quote, excerpt_ref)
    SELECT public.uuid7(), v_problem, t.source->>'url', btrim(t.source->>'publisher'), t.source->>'source_type',
           CAST(t.source->>'published_date' AS date), CAST(t.source->>'retrieved_at' AS timestamptz),
           t.source->>'quote', t.source->>'excerpt_ref'
      FROM jsonb_array_elements(p_sources) WITH ORDINALITY AS t(source, n)
     ORDER BY t.n;
    RETURN v_problem;
END;
$$;

-- True when the current user is the subject (p_user_id, p_org_id: exactly one set) of a payment: the user themselves,
-- or an active owner, admin or finance member of the organisation (narrowed by app.org_id), as the payments SELECT
-- policy. NULL-safe: false without app.user_id or without a subject. Internal: the payment definers call it as the
-- owner.
CREATE FUNCTION app_is_payment_subject(p_user_id uuid, p_org_id uuid) RETURNS boolean
    LANGUAGE sql STABLE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT coalesce(
        public.app_user_id() IS NOT NULL
        AND ((p_user_id = public.app_user_id() AND p_org_id IS NULL)
             OR (p_user_id IS NULL AND p_org_id IS NOT NULL
                 AND public.app_is_member(p_org_id, '{owner,admin,finance}')
                 AND (public.app_org_id() IS NULL OR p_org_id = public.app_org_id()))),
        false)
$$;

-- Settles a pending payment once (docs/spec/05; REQ-BIL-04 interface): the payment's subject only (one refusal, the
-- same for a payment that does not exist, before any lock), to succeeded, failed or cancelled; a failure code (a code,
-- never free text) only for failed or cancelled. Repeating the recorded outcome changes nothing and returns false (a
-- repeated query or callback); another outcome is refused. settled_at is the database's (payments_guard). Whether the
-- provider really took the money is the caller's to check before calling (the provider query): the database cannot.
-- So it fails closed for real money: a payment of any provider but the fake one is never settled as succeeded here,
-- by its subject; the revision that widens the provider CHECK must add the platform path (REQ-BIL-04:
-- webhook_events, the provider's verification, the amount and currency check) on purpose.
CREATE FUNCTION app_settle_payment(p_payment uuid, p_status payment_status, p_failure_code text DEFAULT NULL)
    RETURNS boolean
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_payment public.payments%ROWTYPE;
BEGIN
    SELECT * INTO v_payment FROM public.payments p WHERE p.id = p_payment;
    IF v_payment.id IS NULL OR NOT public.app_is_payment_subject(v_payment.user_id, v_payment.org_id) THEN
        RAISE EXCEPTION 'app_settle_payment: no payment of the caller''s with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF p_status IS NULL OR p_status = 'pending' THEN
        RAISE EXCEPTION 'app_settle_payment: a payment settles as succeeded, failed or cancelled'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_failure_code IS NOT NULL AND (p_status = 'succeeded' OR p_failure_code !~ '^[a-z][a-z0-9_]{0,39}$') THEN
        RAISE EXCEPTION 'app_settle_payment: a failure code (a code) only for a failed or cancelled payment'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_status = 'succeeded' AND v_payment.provider IS DISTINCT FROM 'fake' THEN
        RAISE EXCEPTION 'app_settle_payment: only the platform settles a real provider''s payment as succeeded'
            ' (REQ-BIL-04)' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT * INTO v_payment FROM public.payments p WHERE p.id = p_payment FOR UPDATE;
    IF v_payment.status <> 'pending' THEN
        IF v_payment.status = p_status AND v_payment.failure_code IS NOT DISTINCT FROM p_failure_code THEN
            RETURN false;
        END IF;
        RAISE EXCEPTION 'app_settle_payment: the payment was already settled as %', v_payment.status
            USING ERRCODE = 'check_violation';
    END IF;
    UPDATE public.payments p SET status = p_status, failure_code = p_failure_code, updated_at = now()
     WHERE p.id = p_payment;
    RETURN true;
END;
$$;

-- Activates the plan a succeeded payment paid for (REQ-BIL-08): the payment's subject only (the same one refusal),
-- only a succeeded payment whose plan is of the subject's side. The price is not re-checked: the plan and the amount
-- were matched when the payment was inserted (INSERT policy) and never change (payments_guard), so a later price
-- change in plans.yaml never strands a payment that succeeded. Activations of one subject are
-- serialised (advisory lock), then the payment's row is locked: a payment already linked returns its subscription
-- (idempotent: a repeated query or callback activates nothing twice, AC-SUB-2). Otherwise the subject's live
-- subscription (trialing, active or past_due) is cancelled and the new one inserted active from app_clock_now() for a
-- month or a year (the plan's interval; none: open-ended), and the payment linked to it. Returns the subscription id.
CREATE FUNCTION app_activate_paid_subscription(p_payment uuid) RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_payment public.payments%ROWTYPE;
    v_plan public.plans%ROWTYPE;
    v_side public.plan_side;
    v_now timestamptz;
    v_subscription uuid;
BEGIN
    SELECT * INTO v_payment FROM public.payments p WHERE p.id = p_payment;
    IF v_payment.id IS NULL OR NOT public.app_is_payment_subject(v_payment.user_id, v_payment.org_id) THEN
        RAISE EXCEPTION 'app_activate_paid_subscription: no payment of the caller''s with that id'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    PERFORM pg_advisory_xact_lock(
        hashtextextended('subscription:' || coalesce(v_payment.org_id, v_payment.user_id)::text, 0));
    SELECT * INTO v_payment FROM public.payments p WHERE p.id = p_payment FOR UPDATE;
    IF v_payment.subscription_id IS NOT NULL THEN
        RETURN v_payment.subscription_id;
    END IF;
    IF v_payment.status <> 'succeeded' THEN
        RAISE EXCEPTION 'app_activate_paid_subscription: the payment has not succeeded (it is %)', v_payment.status
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT * INTO v_plan FROM public.plans pl WHERE pl.id = v_payment.plan_id;
    v_side := CASE WHEN v_payment.org_id IS NULL THEN 'developer' ELSE 'org' END;
    IF v_plan.side IS DISTINCT FROM v_side THEN
        RAISE EXCEPTION 'app_activate_paid_subscription: the payment''s plan is not of its subject''s side'
            USING ERRCODE = 'check_violation';
    END IF;
    v_now := public.app_clock_now();
    UPDATE public.subscriptions s SET status = 'cancelled', updated_at = now()
     WHERE s.status IN ('trialing', 'active', 'past_due')
       AND ((v_payment.org_id IS NULL AND s.user_id = v_payment.user_id)
            OR (v_payment.org_id IS NOT NULL AND s.org_id = v_payment.org_id));
    v_subscription := public.uuid7();
    INSERT INTO public.subscriptions (id, user_id, org_id, plan_id, status, current_period_start, current_period_end)
    VALUES (v_subscription, v_payment.user_id, v_payment.org_id, v_payment.plan_id, 'active', v_now,
            CASE v_plan.interval WHEN 'month' THEN v_now + interval '1 month'
                                 WHEN 'year' THEN v_now + interval '1 year' END);
    UPDATE public.payments p SET subscription_id = v_subscription, updated_at = now() WHERE p.id = p_payment;
    RETURN v_subscription;
END;
$$;

-- Cross-organisation trend aggregates (REQ-TREND-01; docs/spec/06 6.6, docs/spec/08 Tenancy): signal_events in
-- [p_since, p_now), at most 400 days, per item, kind and Africa/Nairobi day, of the listed kinds only
-- (proposal_published, proposal_version_published, scout_match, org_interest: adding a kind is a revision), whose item
-- is a published proposal clear of moderation holds, and only for an item and kind with at least 3 distinct actors in
-- the window (fewer: no row at all, so no count ever describes one or two accounts). events counts each actor once
-- per item and day (signals without an actor once per day: 1 event/account/item/day); actors is the item and kind's
-- distinct actors over the window; orgs its distinct organisations only when there are 3 or more (else NULL). No
-- actor hash, organisation hash or organisation id is ever returned. Owned by bridge_owner (the revision's docstring
-- and D-46 say why not aggregate_worker); it reads signal_events and the proposals' visibility, nothing else.
CREATE FUNCTION app_trend_aggregates(p_since timestamptz, p_now timestamptz)
    RETURNS TABLE (item_id uuid, kind varchar, day date, events integer, actors integer, orgs integer)
    LANGUAGE plpgsql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF p_since IS NULL OR p_now IS NULL OR p_since > p_now OR p_now - p_since > interval '400 days' THEN
        RAISE EXCEPTION 'app_trend_aggregates: a window [since, now) of at most 400 days'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    RETURN QUERY
    WITH signals AS (
        SELECT s.item_id AS s_item, s.kind AS s_kind, (s.ts AT TIME ZONE 'Africa/Nairobi')::date AS s_day,
               s.actor_hash AS s_actor, s.org_hash AS s_org
          FROM public.signal_events s
         WHERE s.ts >= p_since AND s.ts < p_now
           AND s.kind = ANY ('{proposal_published,proposal_version_published,scout_match,org_interest}'::text[])
           AND EXISTS (SELECT 1 FROM public.proposals p
                        WHERE p.id = s.item_id AND p.status = 'published' AND p.moderation_state = 'clear')
    ), per_day AS (
        SELECT g.s_item, g.s_kind, g.s_day, count(DISTINCT coalesce(g.s_actor, '\x'::bytea)) AS d_events
          FROM signals g
         GROUP BY g.s_item, g.s_kind, g.s_day
    ), per_item AS (
        SELECT g.s_item, g.s_kind, count(DISTINCT g.s_actor) AS i_actors, count(DISTINCT g.s_org) AS i_orgs
          FROM signals g
         GROUP BY g.s_item, g.s_kind
        HAVING count(DISTINCT g.s_actor) >= 3
    )
    SELECT d.s_item, d.s_kind, d.s_day, d.d_events::integer, i.i_actors::integer,
           CASE WHEN i.i_orgs >= 3 THEN i.i_orgs::integer END
      FROM per_day d
      JOIN per_item i ON i.s_item = d.s_item AND i.s_kind = d.s_kind
     ORDER BY d.s_item, d.s_kind, d.s_day;
END;
$$;
"""

# Trigger functions. None is executable by any runtime role.
TRIGGERS_SQL = r"""
-- A payment (docs/spec/05), for every role, the owner included: starts pending, unsettled and unlinked; is never
-- deleted (nor truncated: payments_no_truncate); its subject, plan, amount, provider, reference and initiator never
-- change; it settles once, pending -> succeeded, failed or cancelled, at the database's time (app_clock_now()), and
-- the settlement (time, failure code) never changes afterwards; a succeeded payment is linked to one subscription once.
CREATE FUNCTION payments_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'payments: a payment is never deleted' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'pending' OR NEW.settled_at IS NOT NULL OR NEW.subscription_id IS NOT NULL
           OR NEW.failure_code IS NOT NULL THEN
            RAISE EXCEPTION 'payments: a payment starts pending, unsettled and unlinked'
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.id, NEW.user_id, NEW.org_id, NEW.plan_id, NEW.amount_kes_minor, NEW.provider, NEW.provider_ref,
        NEW.initiated_by, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.user_id, OLD.org_id, OLD.plan_id, OLD.amount_kes_minor, OLD.provider,
                         OLD.provider_ref, OLD.initiated_by, OLD.created_at) THEN
        RAISE EXCEPTION 'payments: the subject, plan, amount, provider and reference of a payment never change'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status THEN
        IF OLD.status <> 'pending' THEN
            RAISE EXCEPTION 'payments: a payment is settled once (it is %)', OLD.status
                USING ERRCODE = 'check_violation';
        END IF;
        NEW.settled_at := public.app_clock_now();
    ELSIF (NEW.settled_at, NEW.failure_code) IS DISTINCT FROM (OLD.settled_at, OLD.failure_code) THEN
        RAISE EXCEPTION 'payments: a settlement never changes' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.subscription_id IS DISTINCT FROM OLD.subscription_id
       AND (OLD.subscription_id IS NOT NULL OR NEW.status <> 'succeeded') THEN
        RAISE EXCEPTION 'payments: a succeeded payment is linked to its subscription once'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- The AC-RES-1 backstop, for every role: a research_agent problem reaches published (inserted as published, or moved
-- there from another status) only with one official source or two distinct publishers (case- and space-insensitive)
-- among its sources that carry a quote and a published date; and when it names organisations, with an official
-- source (docs/spec/06 6.5). The quotes themselves are verified in code. SECURITY DEFINER: reads the sources whatever
-- the caller's visibility.
CREATE FUNCTION problems_research_guard() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_official boolean;
    v_publishers bigint;
BEGIN
    IF NEW.source <> 'research_agent' OR NEW.status <> 'published' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF OLD.status = 'published' THEN
            RETURN NEW;
        END IF;
    END IF;
    SELECT coalesce(bool_or(s.source_type = 'official'), false),
           count(DISTINCT lower(btrim(s.publisher))) FILTER (WHERE btrim(s.publisher) <> '')
      INTO v_official, v_publishers
      FROM public.problem_sources s
     WHERE s.problem_id = NEW.id AND s.quote IS NOT NULL AND btrim(s.quote) <> '' AND s.published_date IS NOT NULL;
    IF NOT (v_official OR v_publishers >= 2) THEN
        RAISE EXCEPTION 'problems: a research card is published with one official source or two independent'
            ' publishers (AC-RES-1)' USING ERRCODE = 'check_violation';
    END IF;
    IF cardinality(NEW.named_orgs) > 0 AND NOT v_official THEN
        RAISE EXCEPTION 'problems: a research card naming an organisation is published with an official source'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- A scout's digest recipients (docs/spec/06 6.8: Reviewer-role members; AC-SCOUT-7) are, when the list is written,
-- active members of the scout's organisation holding reviewer. The digest re-checks at send time (a member may leave
-- afterwards) and adds the verified-domain condition. AFTER, so it runs once RLS let the owner or admin write the
-- row. SECURITY DEFINER: reads memberships.
CREATE FUNCTION scout_agents_recipients() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (TG_OP = 'INSERT' OR NEW.recipients IS DISTINCT FROM OLD.recipients) AND EXISTS (
        SELECT 1 FROM unnest(NEW.recipients) AS r(user_id)
         WHERE NOT EXISTS (
               SELECT 1 FROM public.memberships m
                WHERE m.org_id = NEW.org_id AND m.user_id = r.user_id AND m.status = 'active'
                  AND m.roles && '{reviewer}'::public.org_role[]))
    THEN
        RAISE EXCEPTION 'scout_agents: every recipient is an active reviewer of the organisation'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

-- Runs first on agent_runs and agent_matches (its trigger, <table>_0_visible, sorts before any other BEFORE INSERT
-- trigger, and triggers fire in name order): the new row names a scout of the named organisation that the caller can
-- see (a member of it), else one refusal, the same as for a scout that does not exist. So no unique or foreign key
-- error tells another organisation that a scout exists or what it matched. SECURITY INVOKER: the caller's RLS
-- decides; the owner sees every scout.
CREATE FUNCTION scout_row_visible() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF NEW.scout_id IS NULL OR NEW.org_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM public.scout_agents s WHERE s.id = NEW.scout_id AND s.org_id = NEW.org_id
    ) THEN
        RAISE EXCEPTION 'no scout of the caller''s with that id' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

-- A match's feedback is its author's (docs/spec/06 6.8 feedback loop), for every role: a feedback is given as oneself,
-- and once given only the member who gave it changes or clears it; anyone else who may update the match (an acting
-- member, the digest job) still writes digest_sent_at. SECURITY INVOKER: reads nothing.
CREATE FUNCTION agent_matches_feedback_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.feedback, NEW.feedback_reason, NEW.feedback_by, NEW.feedback_at)
       IS DISTINCT FROM (OLD.feedback, OLD.feedback_reason, OLD.feedback_by, OLD.feedback_at) THEN
        IF OLD.feedback_by IS NOT NULL AND OLD.feedback_by IS DISTINCT FROM public.app_user_id() THEN
            RAISE EXCEPTION 'agent_matches: only the member who gave a feedback changes or clears it'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        IF NEW.feedback_by IS NOT NULL AND NEW.feedback_by IS DISTINCT FROM public.app_user_id() THEN
            RAISE EXCEPTION 'agent_matches: a feedback is given as oneself' USING ERRCODE = 'insufficient_privilege';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

-- A research run's lifecycle, for every role: its niche, region, starter and start never change; only the staff
-- admin who started it changes its status (and with it its finish and stop reason); a finished run (completed,
-- stopped or failed) never changes again: never back to running, nor its counts, cost or flags. SECURITY INVOKER:
-- reads nothing.
CREATE FUNCTION research_runs_guard() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    IF (NEW.id, NEW.niche_id, NEW.country, NEW.county_code, NEW.started_by, NEW.created_at)
       IS DISTINCT FROM (OLD.id, OLD.niche_id, OLD.country, OLD.county_code, OLD.started_by, OLD.created_at) THEN
        RAISE EXCEPTION 'research_runs: the niche, region, starter and start of a run never change'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.status <> 'running'
       AND (NEW.status, NEW.finished_at, NEW.searches, NEW.fetches, NEW.input_tokens, NEW.candidates, NEW.discarded,
            NEW.cost_usd, NEW.stop_reason, NEW.demo_fallback)
           IS DISTINCT FROM (OLD.status, OLD.finished_at, OLD.searches, OLD.fetches, OLD.input_tokens, OLD.candidates,
                             OLD.discarded, OLD.cost_usd, OLD.stop_reason, OLD.demo_fallback) THEN
        RAISE EXCEPTION 'research_runs: a finished run never changes (it is %)', OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status AND OLD.started_by IS DISTINCT FROM public.app_user_id() THEN
        RAISE EXCEPTION 'research_runs: only the staff admin who started a run changes its status'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER agent_matches_feedback_guard
    BEFORE UPDATE ON agent_matches
    FOR EACH ROW EXECUTE FUNCTION agent_matches_feedback_guard();
CREATE TRIGGER research_runs_guard
    BEFORE UPDATE ON research_runs
    FOR EACH ROW EXECUTE FUNCTION research_runs_guard();
CREATE TRIGGER agent_runs_0_visible
    BEFORE INSERT ON agent_runs
    FOR EACH ROW EXECUTE FUNCTION scout_row_visible();
CREATE TRIGGER agent_matches_0_visible
    BEFORE INSERT ON agent_matches
    FOR EACH ROW EXECUTE FUNCTION scout_row_visible();
CREATE TRIGGER payments_guard
    BEFORE INSERT OR UPDATE OR DELETE ON payments
    FOR EACH ROW EXECUTE FUNCTION payments_guard();
CREATE TRIGGER payments_no_truncate
    BEFORE TRUNCATE ON payments
    FOR EACH STATEMENT EXECUTE FUNCTION block_mutation();
CREATE TRIGGER problems_research_guard
    BEFORE INSERT OR UPDATE ON problems
    FOR EACH ROW EXECUTE FUNCTION problems_research_guard();
CREATE TRIGGER scout_agents_recipients
    AFTER INSERT OR UPDATE ON scout_agents
    FOR EACH ROW EXECUTE FUNCTION scout_agents_recipients();
"""

# EXECUTE grants (every function of this revision has EXECUTE revoked from PUBLIC first).
FUNCTION_GRANTS: dict[str, tuple[str, ...]] = {
    "app_uuid_set_is_valid(uuid[], integer, integer)": ("bridge_app",),  # scout_agents CHECKs
    "app_text_set_is_valid(text[], integer, integer)": ("bridge_app",),  # scout_agents and problems CHECKs
    "app_scouts_due(timestamp with time zone, scout_frequency, uuid)": ("bridge_app",),  # the scouts.scan job
    "app_create_research_candidate(uuid, text, text, text, text, numeric, text[], jsonb)": ("bridge_app",),
    "app_settle_payment(uuid, payment_status, text)": ("bridge_app",),
    "app_activate_paid_subscription(uuid)": ("bridge_app",),
    "app_trend_aggregates(timestamp with time zone, timestamp with time zone)": ("bridge_app",),
}
# Called only inside this revision's definer functions, as the owner: no EXECUTE for any role.
INTERNAL_FUNCTIONS = ("app_research_source_is_valid(jsonb)", "app_is_payment_subject(uuid, uuid)")
TRIGGER_FUNCTIONS = (
    "scout_row_visible()",
    "agent_matches_feedback_guard()",
    "research_runs_guard()",
    "payments_guard()",
    "problems_research_guard()",
    "scout_agents_recipients()",
)


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction); see revision 0001."""
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def _grant_sql() -> str:
    grants = [f"GRANT {privileges} ON TABLE {table} TO bridge_app;" for table, privileges in APP_GRANTS.items()]
    # REVOKE of a table privilege also revokes it on every column; the column grant follows.
    grants += [
        "REVOKE INSERT ON TABLE problems FROM bridge_app;",
        f"GRANT INSERT ({PROBLEMS_INSERTABLE_COLUMNS}) ON TABLE problems TO bridge_app;",
        "REVOKE INSERT ON TABLE problem_sources FROM bridge_app;",
        f"GRANT INSERT ({PROBLEM_SOURCES_INSERTABLE_COLUMNS}) ON TABLE problem_sources TO bridge_app;",
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
    _create_tables()
    _alter_earlier_tables()
    _run_sql(FUNCTIONS_SQL)
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(TRIGGERS_SQL)
    _run_sql(_grant_sql())


def downgrade() -> None:
    # The trigger and the columns of this revision on revision 0002 tables first (a column drop takes its CHECKs,
    # foreign key and index with it), then bridge_app's table-wide INSERT as it was.
    _run_sql("DROP TRIGGER problems_research_guard ON problems;")
    op.drop_column("problems", "named_orgs")
    op.drop_column("problems", "research_run_id")
    op.drop_column("problem_sources", "excerpt_ref")
    _run_sql(
        "REVOKE INSERT ON TABLE problems FROM bridge_app; GRANT INSERT ON TABLE problems TO bridge_app;"
        " REVOKE INSERT ON TABLE problem_sources FROM bridge_app; GRANT INSERT ON TABLE problem_sources TO bridge_app;"
    )
    # Dropping a table drops its policies, triggers, indexes and grants. Referencing tables before referenced ones.
    for table in ("agent_matches", "agent_runs", "scout_agents", "payments", "research_runs"):
        op.drop_table(table)
    _run_sql(
        "\n".join(
            f"DROP FUNCTION {signature};" for signature in (*TRIGGER_FUNCTIONS, *INTERNAL_FUNCTIONS, *FUNCTION_GRANTS)
        )
    )
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)


def _alter_earlier_tables() -> None:
    op.add_column("problems", sa.Column("research_run_id", sa.Uuid(), nullable=True))
    op.add_column("problems", sa.Column("named_orgs", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False))
    op.create_foreign_key(
        op.f("fk_problems_research_run_id_research_runs"), "problems", "research_runs", ["research_run_id"], ["id"]
    )
    op.create_index(op.f("ix_problems_research_run_id"), "problems", ["research_run_id"], unique=False)
    op.create_check_constraint(
        op.f("ck_problems_named_orgs_valid"), "problems", "app_text_set_is_valid(named_orgs, 10, 200)"
    )
    op.create_check_constraint(
        op.f("ck_problems_research_run_only_for_research"),
        "problems",
        "research_run_id IS NULL OR source = 'research_agent'",
    )
    op.add_column("problem_sources", sa.Column("excerpt_ref", sa.String(length=32), nullable=True))
    op.create_check_constraint(
        op.f("ck_problem_sources_excerpt_ref_format"),
        "problem_sources",
        "excerpt_ref IS NULL OR excerpt_ref ~ '^[A-Za-z0-9_.:-]{1,32}$'",
    )


def _create_tables() -> None:
    op.create_table(
        "research_runs",
        sa.Column("niche_id", sa.Uuid(), nullable=False),
        sa.Column("country", sa.String(length=2), server_default="KE", nullable=False),
        sa.Column("county_code", sa.String(length=8), nullable=True),
        sa.Column("status", _enum("research_run_status"), server_default="running", nullable=False),
        sa.Column("started_by", sa.Uuid(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("searches", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fetches", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("candidates", sa.Integer(), server_default="0", nullable=False),
        sa.Column("discarded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), server_default="0", nullable=False),
        sa.Column("stop_reason", sa.String(length=40), nullable=True),
        sa.Column("demo_fallback", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "searches BETWEEN 0 AND 25 AND fetches BETWEEN 0 AND 40", name=op.f("ck_research_runs_run_caps")
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND candidates >= 0 AND discarded >= 0",
            name=op.f("ck_research_runs_counts_not_negative"),
        ),
        sa.CheckConstraint("cost_usd BETWEEN 0 AND 100", name=op.f("ck_research_runs_cost_usd_range")),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name=op.f("ck_research_runs_finished_unless_running")
        ),
        sa.CheckConstraint(
            f"(status IN ('stopped', 'failed')) = (stop_reason IS NOT NULL)"
            f" AND (stop_reason IS NULL OR stop_reason ~ {CODE})",
            name=op.f("ck_research_runs_stop_reason_is_a_code"),
        ),
        sa.ForeignKeyConstraint(["county_code"], ["regions.code"], name=op.f("fk_research_runs_county_code_regions")),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], name=op.f("fk_research_runs_niche_id_niches")),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"], name=op.f("fk_research_runs_started_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_research_runs")),
    )
    op.create_index(op.f("ix_research_runs_started_by"), "research_runs", ["started_by"], unique=False)
    op.create_table(
        "scout_agents",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("niches", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("counties", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("include_keywords", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("exclude_keywords", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "maturity",
            postgresql.ARRAY(postgresql.ENUM(*PROPOSAL_MATURITY, name="proposal_maturity", create_type=False)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("budget_band", sa.String(length=32), nullable=True),
        sa.Column("min_fit", sa.SmallInteger(), server_default="60", nullable=False),
        sa.Column("frequency", _enum("scout_frequency"), server_default="weekly", nullable=False),
        sa.Column("language", sa.String(length=2), server_default="en", nullable=False),
        sa.Column("recipients", postgresql.ARRAY(sa.Uuid()), server_default="{}", nullable=False),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cursor_proposal_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("app_uuid_set_is_valid(niches, 1, 5)", name=op.f("ck_scout_agents_niches_valid")),
        sa.CheckConstraint("app_uuid_set_is_valid(recipients, 0, 20)", name=op.f("ck_scout_agents_recipients_valid")),
        sa.CheckConstraint("app_text_set_is_valid(counties, 47, 8)", name=op.f("ck_scout_agents_counties_valid")),
        sa.CheckConstraint(
            "app_text_set_is_valid(include_keywords, 20, 60)", name=op.f("ck_scout_agents_include_keywords_valid")
        ),
        sa.CheckConstraint(
            "app_text_set_is_valid(exclude_keywords, 20, 60)", name=op.f("ck_scout_agents_exclude_keywords_valid")
        ),
        sa.CheckConstraint(
            "cardinality(maturity) <= 4 AND array_position(maturity, NULL) IS NULL",
            name=op.f("ck_scout_agents_maturity_valid"),
        ),
        sa.CheckConstraint(
            "budget_band IS NULL OR budget_band ~ '^[a-z0-9_-]{1,32}$'", name=op.f("ck_scout_agents_budget_band_code")
        ),
        sa.CheckConstraint("min_fit BETWEEN 0 AND 100", name=op.f("ck_scout_agents_min_fit_range")),
        sa.CheckConstraint("language IN ('en', 'sw')", name=op.f("ck_scout_agents_language_known")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_scout_agents_created_by_users")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_scout_agents_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scout_agents")),
        sa.UniqueConstraint("id", "org_id", name=op.f("uq_scout_agents_id_org_id")),
    )
    op.create_index(op.f("ix_scout_agents_org_id"), "scout_agents", ["org_id"], unique=False)
    op.create_table(
        "agent_runs",
        sa.Column("scout_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("trigger", _enum("scout_frequency"), nullable=False),
        sa.Column("status", _enum("agent_run_status"), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("app_clock_now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scanned_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("scanned_count >= 0 AND matched_count >= 0", name=op.f("ck_agent_runs_counts_not_negative")),
        sa.CheckConstraint(
            "window_start IS NULL OR window_start <= window_end", name=op.f("ck_agent_runs_window_in_order")
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)", name=op.f("ck_agent_runs_finished_unless_running")
        ),
        sa.CheckConstraint(
            f"(status = 'failed') = (error_code IS NOT NULL) AND (error_code IS NULL OR error_code ~ {CODE})",
            name=op.f("ck_agent_runs_error_code_when_failed"),
        ),
        sa.ForeignKeyConstraint(
            ["scout_id", "org_id"],
            ["scout_agents.id", "scout_agents.org_id"],
            name="fk_agent_runs_scout",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index(op.f("ix_agent_runs_org_id"), "agent_runs", ["org_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_scout_id"), "agent_runs", ["scout_id"], unique=False)
    op.create_table(
        "agent_matches",
        sa.Column("scout_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("niche_id", sa.Uuid(), nullable=True),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("rule_breakdown", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("rationale_demo_fallback", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("injection_suspected", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("digest_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback", _enum("match_feedback"), nullable=True),
        sa.Column("feedback_reason", sa.String(length=40), nullable=True),
        sa.Column("feedback_by", sa.Uuid(), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name=op.f("ck_agent_matches_score_range")),
        sa.CheckConstraint(
            "jsonb_typeof(rule_breakdown) = 'object' AND octet_length(rule_breakdown::text) <= 4096",
            name=op.f("ck_agent_matches_rule_breakdown_object"),
        ),
        sa.CheckConstraint(
            "rationale IS NULL OR (btrim(rationale) <> '' AND length(rationale) <= 600)",
            name=op.f("ck_agent_matches_rationale_length"),
        ),
        sa.CheckConstraint(
            "(feedback IS NULL) = (feedback_by IS NULL) AND (feedback IS NULL) = (feedback_at IS NULL)"
            f" AND (feedback_reason IS NULL OR (feedback IS NOT NULL AND feedback_reason ~ {CODE}))",
            name=op.f("ck_agent_matches_feedback_complete"),
        ),
        sa.ForeignKeyConstraint(["feedback_by"], ["users.id"], name=op.f("fk_agent_matches_feedback_by_users")),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], name=op.f("fk_agent_matches_niche_id_niches")),
        sa.ForeignKeyConstraint(
            ["proposal_id", "version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_agent_matches_version",
        ),
        sa.ForeignKeyConstraint(
            ["scout_id", "org_id"],
            ["scout_agents.id", "scout_agents.org_id"],
            name="fk_agent_matches_scout",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_matches")),
        sa.UniqueConstraint("scout_id", "proposal_id", name=op.f("uq_agent_matches_scout_id_proposal_id")),
    )
    op.create_index(op.f("ix_agent_matches_org_id"), "agent_matches", ["org_id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("amount_kes_minor", sa.BigInteger(), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_ref", sa.String(length=64), nullable=False),
        sa.Column("status", _enum("payment_status"), server_default="pending", nullable=False),
        sa.Column("initiated_by", sa.Uuid(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("failure_code", sa.String(length=40), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(user_id IS NULL) <> (org_id IS NULL)", name=op.f("ck_payments_one_subject")),
        sa.CheckConstraint("amount_kes_minor > 0", name=op.f("ck_payments_amount_positive")),
        sa.CheckConstraint("provider IN ('fake')", name=op.f("ck_payments_provider_known")),
        sa.CheckConstraint("provider_ref ~ '^[A-Za-z0-9_-]{16,64}$'", name=op.f("ck_payments_provider_ref_format")),
        sa.CheckConstraint(
            "(status = 'pending') = (settled_at IS NULL)", name=op.f("ck_payments_settled_unless_pending")
        ),
        sa.CheckConstraint(
            f"failure_code IS NULL OR (status IN ('failed', 'cancelled') AND failure_code ~ {CODE})",
            name=op.f("ck_payments_failure_code_when_failed"),
        ),
        sa.CheckConstraint(
            "subscription_id IS NULL OR status = 'succeeded'", name=op.f("ck_payments_linked_only_when_succeeded")
        ),
        sa.ForeignKeyConstraint(["initiated_by"], ["users.id"], name=op.f("fk_payments_initiated_by_users")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], name=op.f("fk_payments_org_id_organizations")),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name=op.f("fk_payments_plan_id_plans")),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["subscriptions.id"], name=op.f("fk_payments_subscription_id_subscriptions")
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_payments_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("provider_ref", name=op.f("uq_payments_provider_ref")),
        sa.UniqueConstraint("subscription_id", name=op.f("uq_payments_subscription_id")),
    )
    op.create_index(op.f("ix_payments_org_id"), "payments", ["org_id"], unique=False)
    op.create_index(op.f("ix_payments_user_id"), "payments", ["user_id"], unique=False)
