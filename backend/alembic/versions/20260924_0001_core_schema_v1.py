"""Core schema v1: accounts, tenancy, reference data, profiles, consents, notifications, billing and the audit chain.

REQ-TEN-01 (tables, RLS helper functions, policies and grants), REQ-AUD-01 (hash-chained append-only
``audit_events`` and mutable ``event_details``), REQ-CON-01 (append-only ``consents`` by grants) and the Procrastinate
3.10.0 job schema (docs/spec/08 Jobs). Runs as ``bridge_owner``; ``bridge_app`` owns nothing and has no BYPASSRLS.

Row-Level Security is ENABLED (not FORCED) on every org, user and org_or_user table, so the owner bypasses it: the
SECURITY DEFINER helpers (``app_is_member``, ``app_create_organization``, ``audit_events_chain``) run as the owner and
read ``memberships``/``audit_events`` without recursing into their own policies.

Operating rules that follow from this revision:

- Policies key on ``app.user_id``. ``app.org_id`` only narrows what a member already sees; an org-only context (no
  user) sees nothing. Every job that touches tenant data must therefore bind the user id of the member it acts for
  (docs/spec/08: one tenant per job); jobs with no acting user can only append system audit events and details.
- Audit appends must run at READ COMMITTED. ``audit_events_chain()`` refuses REPEATABLE READ and SERIALIZABLE by
  design: their snapshot predates the per-chain lock, so the chain head it reads could be stale.
- Every function pins ``search_path = pg_catalog, public, pg_temp`` (pg_temp last, see FUNCTIONS_SQL), and
  ``infra/postgres/prepare_db.sql`` revokes TEMPORARY on the database from PUBLIC.
- This revision was edited in place during review, before its first merge. A database migrated with an earlier
  0001 (for example an existing dev volume) must be recreated (``docker compose --env-file infra/.env -f
  infra/docker-compose.dev.yml --profile full down -v``, then ``make dev``):
  ``alembic upgrade head`` sees 0001 as applied and never re-applies an edited revision. From the first merge on,
  0001 is frozen and every change is a new revision.

Revision ID: 0001
Revises:
Create Date: 2026-09-24
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROCRASTINATE_SQL = Path(__file__).parent / "sql" / "procrastinate_3.10.0_schema.sql"

# Enum types, frozen at this revision (the ORM enums in bridge.models.enums must match; a test compares them).
ENUMS: dict[str, tuple[str, ...]] = {
    "staff_role": ("admin", "moderator", "support"),
    "user_status": ("active", "suspended"),
    "auth_provider": ("github", "google"),
    "login_token_purpose": ("login", "verify_email"),
    "org_kind": (
        "company",
        "sme",
        "sacco_mfi",
        "university_tvet",
        "school",
        "national_govt",
        "county_govt",
        "ngo_pbo",
        "development_partner",
    ),
    "org_verification": ("unclaimed", "pending", "e1", "e2", "rejected"),
    "org_source": ("self_signup", "seed", "admin"),
    "org_role": ("owner", "admin", "reviewer", "signatory", "finance", "viewer"),
    "membership_status": ("active", "removed"),
    "dev_verification": ("d0", "d1", "d2", "d3"),
    "niche_interest": ("liked", "followed"),
    "region_kind": ("country", "county"),
    "consent_purpose": (
        "marketing",
        "reminders",
        "whatsapp",
        "profiling",
        "github_import",
        "tier2_llm_assistant",
        "tier2_llm_moderation",
    ),
    "audit_actor": ("user", "staff", "system"),
    "notification_channel": ("email", "whatsapp", "sms", "in_app"),
    "delivery_status": ("queued", "sent", "failed", "suppressed"),
    "suppression_reason": ("bounce", "complaint", "manual", "unsubscribe"),
    "plan_side": ("developer", "org"),
    "billing_interval": ("none", "month", "year"),
    "subscription_status": ("trialing", "active", "past_due", "downgraded", "cancelled"),
}

# Tables with Row-Level Security (tenancy org, user or org_or_user in the ORM metadata).
RLS_TABLES = (
    "organizations",
    "memberships",
    "invitations",
    "org_niches",
    "developer_profiles",
    "developer_niches",
    "consents",
    "notification_preferences",
    "in_app_notifications",
    "subscriptions",
    "notification_deliveries",
    "audit_events",
    "event_details",
)

# Table privileges of bridge_app (API and worker). Anything not listed is not granted. UPDATE is column-scoped where
# some columns are never the app's to change (users: staff_role, status, email; organizations: verification, slug,
# kind, source, public_entity, verified_domain, created_by; developer_profiles: verification_level, handle and the
# embedding columns, which verification and the embedding job own).
APP_GRANTS: dict[str, str] = {
    "users": (
        "SELECT, INSERT, UPDATE (email_verified_at, password_hash, display_name, locale, totp_secret_enc,"
        " totp_pending_enc, totp_enabled_at, totp_last_counter, totp_recovery_hashes, updated_at)"
    ),
    "sessions": "SELECT, INSERT, UPDATE, DELETE",
    "login_tokens": "SELECT, INSERT, UPDATE, DELETE",
    "login_attempts": "SELECT, INSERT, DELETE",
    "api_tokens": "SELECT, INSERT, UPDATE",
    "auth_identities": "SELECT, INSERT, DELETE",
    "email_suppressions": "SELECT, INSERT",
    "niches": "SELECT",
    "regions": "SELECT",
    "holidays": "SELECT",
    "plans": "SELECT",
    # INSERT only through app_create_organization()
    "organizations": "SELECT, UPDATE (legal_name, website, regions, registration_no, sector_id, country, updated_at)",
    "memberships": "SELECT, INSERT, UPDATE",  # members leave by status = 'removed', never DELETE
    "invitations": "SELECT, INSERT, UPDATE",
    "org_niches": "SELECT, INSERT, DELETE",
    # never verification_level, handle, profile_embedding, embed_model, embed_version
    "developer_profiles": "SELECT, INSERT, UPDATE (headline, bio, county_code, updated_at)",
    "developer_niches": "SELECT, INSERT, UPDATE, DELETE",
    "consents": "SELECT, INSERT",  # append-only (REQ-CON-01)
    "notification_preferences": "SELECT, INSERT, UPDATE, DELETE",
    "in_app_notifications": "SELECT, INSERT, UPDATE",
    "subscriptions": "SELECT, INSERT",  # changes go through the billing path (Phase 6)
    "notification_deliveries": "SELECT, INSERT, UPDATE",
    "audit_events": "SELECT, INSERT",  # append-only (REQ-AUD-01)
    "event_details": "SELECT, INSERT",  # UPDATE (erasure) arrives with REQ-SEC-02
}

AUDIT_READER_GRANTS = ("audit_events",)  # the chain verifier never needs event_details (personal data)


class Policy(NamedTuple):
    """One RLS policy for one command. Named ``<role>_<command>``; unique per table."""

    table: str
    command: str
    using: str | None = None
    check: str | None = None
    role: str = "bridge_app"

    def create_sql(self) -> str:
        # USING filters existing rows (SELECT, UPDATE, DELETE); WITH CHECK validates new rows (INSERT, UPDATE).
        shape = {"SELECT": (True, False), "INSERT": (False, True), "UPDATE": (True, True), "DELETE": (True, False)}
        if shape.get(self.command) != (self.using is not None, self.check is not None):
            raise ValueError(f"malformed policy: {self}")
        sql = f"CREATE POLICY {self.role}_{self.command.lower()} ON {self.table} AS PERMISSIVE FOR {self.command}"
        sql += f" TO {self.role}"
        if self.using is not None:
            sql += f" USING ({self.using})"
        if self.check is not None:
            sql += f" WITH CHECK ({self.check})"
        return sql + ";"


# Predicates. app_org_id() narrows reads to the organisation a request is scoped to (NULL = all of the user's orgs).
_ORG_MEMBER = "app_is_member(org_id) AND (app_org_id() IS NULL OR org_id = app_org_id())"
_ORG_ADMIN = "app_is_member(org_id, '{owner,admin}')"
# Protected roles (owner, signatory: control of the organisation and the power to sign) are granted, and memberships
# holding them changed, by owners only; admins manage everyone else.
_ORG_ADMIN_UNPROTECTED = (
    f"{_ORG_ADMIN} AND (NOT (roles && '{{owner,signatory}}'::org_role[]) OR app_is_member(org_id, '{{owner}}'))"
)
_SELF = "user_id = app_user_id()"
_USER_OR_ORG_MEMBER = (
    "user_id = app_user_id() OR (org_id IS NOT NULL AND app_is_member(org_id) "
    "AND (app_org_id() IS NULL OR org_id = app_org_id()))"
)
_USER_OR_ORG_ADMIN = "user_id = app_user_id() OR (org_id IS NOT NULL AND app_is_member(org_id, '{owner,admin}'))"
_AUDIT_VISIBLE = "actor_user_id = app_user_id() OR (org_id IS NOT NULL AND app_is_member(org_id, '{owner,admin}'))"
# No event may name another user as its actor: user events name the current user, system events name nobody, staff
# events name nobody or the current (staff) user.
_AUDIT_APPEND = (
    "(actor_user_id IS NULL OR actor_user_id = app_user_id())"
    " AND (actor_kind <> 'system' OR actor_user_id IS NULL)"
    " AND (actor_kind <> 'user' OR actor_user_id = app_user_id())"
)
_EVENT_VISIBLE = "EXISTS (SELECT 1 FROM audit_events e WHERE e.id = event_details.event_id)"


def _user_policies(table: str, commands: Sequence[str]) -> list[Policy]:
    policies = []
    for command in commands:
        using = None if command == "INSERT" else _SELF
        check = _SELF if command in ("INSERT", "UPDATE") else None
        policies.append(Policy(table, command, using, check))
    return policies


POLICIES: tuple[Policy, ...] = (
    # organizations: tenant column is id. No INSERT policy: app_create_organization() is the only way in.
    Policy("organizations", "SELECT", "app_is_member(id) AND (app_org_id() IS NULL OR id = app_org_id())"),
    Policy("organizations", "UPDATE", "app_is_member(id, '{owner,admin}')", "app_is_member(id, '{owner,admin}')"),
    # memberships: members see their organisation's roster; every user sees their own memberships.
    Policy("memberships", "SELECT", f"({_ORG_MEMBER}) OR user_id = app_user_id()"),
    Policy("memberships", "INSERT", check=_ORG_ADMIN_UNPROTECTED),
    Policy("memberships", "UPDATE", _ORG_ADMIN_UNPROTECTED, _ORG_ADMIN_UNPROTECTED),
    # invitations: owners and admins only; only owners invite owners or signatories.
    Policy("invitations", "SELECT", f"{_ORG_ADMIN} AND (app_org_id() IS NULL OR org_id = app_org_id())"),
    Policy("invitations", "INSERT", check=_ORG_ADMIN_UNPROTECTED),
    Policy("invitations", "UPDATE", _ORG_ADMIN, _ORG_ADMIN_UNPROTECTED),
    # org_niches
    Policy("org_niches", "SELECT", _ORG_MEMBER),
    Policy("org_niches", "INSERT", check=_ORG_ADMIN),
    Policy("org_niches", "DELETE", _ORG_ADMIN),
    # user tables: rows of the current user only.
    *_user_policies("developer_profiles", ("SELECT", "INSERT", "UPDATE")),
    *_user_policies("developer_niches", ("SELECT", "INSERT", "UPDATE", "DELETE")),
    *_user_policies("consents", ("SELECT", "INSERT")),
    *_user_policies("notification_preferences", ("SELECT", "INSERT", "UPDATE", "DELETE")),
    *_user_policies("in_app_notifications", ("SELECT", "INSERT", "UPDATE")),
    # org_or_user tables: the user's own rows, or rows of an organisation they belong to.
    Policy("subscriptions", "SELECT", _USER_OR_ORG_MEMBER),
    # Self-serve subscriptions only to a default (free) plan; paid plans go through the billing path (Phase 6).
    Policy(
        "subscriptions",
        "INSERT",
        check=f"({_USER_OR_ORG_ADMIN})"
        " AND EXISTS (SELECT 1 FROM plans p WHERE p.id = subscriptions.plan_id AND p.is_default)",
    ),
    Policy("notification_deliveries", "SELECT", _USER_OR_ORG_MEMBER),
    Policy("notification_deliveries", "INSERT", check=_USER_OR_ORG_ADMIN),
    Policy("notification_deliveries", "UPDATE", _USER_OR_ORG_ADMIN, _USER_OR_ORG_ADMIN),
    # audit chain: the app appends events that name no other user, and reads its own or its organisations' events;
    # the verifier reads the chain only (details hold personal data).
    Policy("audit_events", "SELECT", _AUDIT_VISIBLE),
    Policy("audit_events", "INSERT", check=_AUDIT_APPEND),
    Policy("audit_events", "SELECT", "true", role="audit_reader"),
    Policy("event_details", "SELECT", _EVENT_VISIBLE),
    Policy("event_details", "INSERT", check="app_event_accepts_details(event_id)"),
)

# ---------------------------------------------------------------------------------------------------------------------
# SQL functions. Every function pins search_path = pg_catalog, public, pg_temp: pg_temp must be listed, and last,
# because an unlisted pg_temp is searched FIRST for relations and types, so a caller could shadow uuid, text or bytea
# with a temporary domain whose CHECK then runs as the owner inside a SECURITY DEFINER function. EXECUTE is revoked
# from PUBLIC and granted explicitly. (prepare_db.sql also revokes TEMPORARY on the database from PUBLIC.)
# ---------------------------------------------------------------------------------------------------------------------

FUNCTIONS_SQL = r"""
CREATE FUNCTION uuid7() RETURNS uuid
    LANGUAGE sql VOLATILE
    SET search_path = pg_catalog, public, pg_temp
AS $$
    -- RFC 9562 UUIDv7: 48-bit Unix milliseconds, version 7, random tail (PostgreSQL 16 has no uuidv7()).
    SELECT encode(
        set_bit(
            set_bit(
                overlay(uuid_send(gen_random_uuid())
                        PLACING substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3)
                        FROM 1 FOR 6),
                52, 1),
            53, 1),
        'hex')::uuid
$$;

CREATE FUNCTION app_user_id() RETURNS uuid
    LANGUAGE sql STABLE SECURITY INVOKER
    SET search_path = pg_catalog, public, pg_temp
AS $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$;

CREATE FUNCTION app_org_id() RETURNS uuid
    LANGUAGE sql STABLE SECURITY INVOKER
    SET search_path = pg_catalog, public, pg_temp
AS $$ SELECT nullif(current_setting('app.org_id', true), '')::uuid $$;

-- True when the current user (app.user_id) has an active membership of p_org holding any of p_roles (any role when
-- p_roles is NULL). SECURITY DEFINER: runs as the owner, which bypasses RLS on memberships (ENABLED, not FORCED), so
-- policies that call it do not recurse.
CREATE FUNCTION app_is_member(p_org uuid, p_roles org_role[] DEFAULT NULL) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM public.memberships m
         WHERE m.org_id = p_org
           AND m.user_id = public.app_user_id()
           AND m.status = 'active'
           AND (p_roles IS NULL OR m.roles && p_roles)
    )
$$;

-- The only way for bridge_app to create an organisation (organizations has no INSERT grant or policy): inserts it as
-- pending self-signup created by app.user_id, and makes that user an active owner and admin.
CREATE FUNCTION app_create_organization(
    p_id uuid, p_kind org_kind, p_legal_name text, p_slug citext, p_country text DEFAULT 'KE'
) RETURNS uuid
    LANGUAGE plpgsql VOLATILE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_user uuid := public.app_user_id();
BEGIN
    IF v_user IS NULL THEN
        RAISE EXCEPTION 'app_create_organization: app.user_id is not set' USING ERRCODE = 'insufficient_privilege';
    END IF;
    INSERT INTO public.organizations (id, kind, legal_name, slug, country, verification, source, created_by)
    VALUES (p_id, p_kind, p_legal_name, p_slug, p_country, 'pending', 'self_signup', v_user);
    INSERT INTO public.memberships (id, org_id, user_id, roles, status)
    VALUES (public.uuid7(), p_id, v_user, '{owner,admin}', 'active');
    RETURN p_id;
END;
$$;

-- event_details INSERT check: details may be attached to an existing event that names no actor (system events) or
-- names the current user. SECURITY DEFINER so it sees the event whatever the caller's audit_events visibility.
CREATE FUNCTION app_event_accepts_details(p_event uuid) RETURNS boolean
    LANGUAGE sql STABLE SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM public.audit_events e
         WHERE e.id = p_event
           AND (e.actor_user_id IS NULL OR e.actor_user_id = public.app_user_id())
    )
$$;

REVOKE ALL ON FUNCTION uuid7() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_user_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_org_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_is_member(uuid, org_role[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_create_organization(uuid, org_kind, text, citext, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_event_accepts_details(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION uuid7() TO bridge_app;
GRANT EXECUTE ON FUNCTION app_user_id() TO bridge_app;
GRANT EXECUTE ON FUNCTION app_org_id() TO bridge_app;
GRANT EXECUTE ON FUNCTION app_is_member(uuid, org_role[]) TO bridge_app;
GRANT EXECUTE ON FUNCTION app_create_organization(uuid, org_kind, text, citext, text) TO bridge_app;
GRANT EXECUTE ON FUNCTION app_event_accepts_details(uuid) TO bridge_app;
"""

# The canonical string hashed into audit_events.event_hash (REQ-AUD-01). bridge.audit.chain recomputes it; any change
# here is a new chain format and needs a new revision plus a verifier version. Fields, joined with '|':
#   1  encode(prev_hash, 'hex')                       lower-case hex; 64 zeros for the first event of a chain
#   2  seq::text                                      decimal, 1-based per chain_id
#   3  id::text                                       lower-case hyphenated UUID
#   4  chain_id                                       as stored
#   5  (extract(epoch from occurred_at) * 1000000)::bigint::text   integer microseconds since the Unix epoch;
#                                                     occurred_at is clock_timestamp() read under the chain lock
#   6  actor_kind::text                               enum label
#   7  coalesce(actor_user_id::text, '')
#   8  coalesce(org_id::text, '')
#   9  action
#   10 coalesce(subject_type, '')
#   11 coalesce(subject_id::text, '')
#   12 payload::text                                  PostgreSQL's jsonb text form; verifiers must read payload::text
#                                                     from the database rather than re-serialise the JSON
# event_hash = sha256(convert_to(<canonical>, 'UTF8')). chain_id, action and subject_type may not contain '|' (the
# trigger rejects it) or be empty (CHECK constraints), so the split is unambiguous (payload, the only free-form field,
# is last). Other characters, such as the ':' of per-scope chain ids ("org:<uuid>", "user:<uuid>"), are fine.
AUDIT_SQL = r"""
CREATE FUNCTION audit_events_chain() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_last_seq bigint;
    v_last_hash bytea;
BEGIN
    -- Under REPEATABLE READ or SERIALIZABLE the snapshot predates the lock, so the head read below could be stale.
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'audit_events: appends must run at READ COMMITTED isolation, not %',
            upper(current_setting('transaction_isolation'))
            USING ERRCODE = 'invalid_transaction_state';
    END IF;
    IF NEW.id IS NULL OR NEW.chain_id IS NULL THEN
        RAISE EXCEPTION 'audit_events: id and chain_id are required' USING ERRCODE = 'not_null_violation';
    END IF;
    IF strpos(NEW.chain_id, '|') > 0 OR strpos(NEW.action, '|') > 0 OR strpos(coalesce(NEW.subject_type, ''), '|') > 0
    THEN
        RAISE EXCEPTION 'audit_events: chain_id, action and subject_type may not contain "|"'
            USING ERRCODE = 'check_violation';
    END IF;

    -- Serialise appends per chain until commit; the SELECT below then sees the previous head.
    PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || NEW.chain_id, 0));
    SELECT e.seq, e.event_hash INTO v_last_seq, v_last_hash
      FROM public.audit_events e
     WHERE e.chain_id = NEW.chain_id
     ORDER BY e.seq DESC
     LIMIT 1;

    IF v_last_seq IS NULL THEN
        NEW.seq := 1;
        NEW.prev_hash := decode(repeat('00', 32), 'hex');
    ELSE
        NEW.seq := v_last_seq + 1;
        NEW.prev_hash := v_last_hash;
    END IF;
    NEW.occurred_at := clock_timestamp();  -- taken under the lock, so occurred_at follows seq within a chain
    NEW.event_hash := sha256(convert_to(concat_ws('|',
        encode(NEW.prev_hash, 'hex'),
        NEW.seq::text,
        NEW.id::text,
        NEW.chain_id,
        ((extract(epoch FROM NEW.occurred_at) * 1000000)::bigint)::text,
        NEW.actor_kind::text,
        coalesce(NEW.actor_user_id::text, ''),
        coalesce(NEW.org_id::text, ''),
        NEW.action,
        coalesce(NEW.subject_type, ''),
        coalesce(NEW.subject_id::text, ''),
        NEW.payload::text
    ), 'UTF8'));
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION audit_events_chain() IS
    'REQ-AUD-01: sets seq, prev_hash, occurred_at and event_hash under a per-chain advisory lock. The canonical form '
    'hashed into event_hash is documented in Alembic revision 0001 (AUDIT_SQL) and recomputed by bridge.audit.chain.';

CREATE FUNCTION audit_block_mutation() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed: the audit log is append-only', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

REVOKE ALL ON FUNCTION audit_events_chain() FROM PUBLIC;
REVOKE ALL ON FUNCTION audit_block_mutation() FROM PUBLIC;

CREATE TRIGGER audit_events_chain
    BEFORE INSERT ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_chain();
CREATE TRIGGER audit_events_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_block_mutation();
CREATE TRIGGER audit_events_no_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_block_mutation();
-- event_details stays updatable (erasure overwrites personal data) but is never deleted.
CREATE TRIGGER event_details_no_delete
    BEFORE DELETE ON event_details
    FOR EACH ROW EXECUTE FUNCTION audit_block_mutation();
CREATE TRIGGER event_details_no_truncate
    BEFORE TRUNCATE ON event_details
    FOR EACH STATEMENT EXECUTE FUNCTION audit_block_mutation();
"""

# Procrastinate: bridge_app runs the worker and defers jobs.
PROCRASTINATE_GRANTS_SQL = r"""
DO $$
DECLARE
    r record;
BEGIN
    FOR r IN
        SELECT c.relname, c.relkind
          FROM pg_class c
         WHERE c.relnamespace = 'public'::regnamespace
           AND c.relname LIKE 'procrastinate\_%'
           AND c.relkind IN ('r', 'S')
    LOOP
        IF r.relkind = 'r' THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.%I TO bridge_app', r.relname);
        ELSE
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE public.%I TO bridge_app', r.relname);
        END IF;
    END LOOP;
    FOR r IN
        SELECT p.oid::regprocedure AS signature
          FROM pg_proc p
         WHERE p.pronamespace = 'public'::regnamespace
           AND p.proname LIKE 'procrastinate\_%'
    LOOP
        -- The vendored SQL does not pin search_path; pin it like every other function of this revision.
        EXECUTE format('ALTER FUNCTION %s SET search_path = pg_catalog, public, pg_temp', r.signature);
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', r.signature);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO bridge_app', r.signature);
    END LOOP;
END
$$;
"""

PROCRASTINATE_DROP_SQL = r"""
DO $$
DECLARE
    r record;
BEGIN
    -- Functions first: procrastinate_fetch_job_v2 returns the procrastinate_jobs row type; CASCADE removes only the
    -- triggers that call these functions.
    FOR r IN
        SELECT p.oid::regprocedure AS signature
          FROM pg_proc p
         WHERE p.pronamespace = 'public'::regnamespace
           AND p.proname LIKE 'procrastinate\_%'
    LOOP
        EXECUTE format('DROP FUNCTION %s CASCADE', r.signature);
    END LOOP;
END
$$;
DROP TABLE procrastinate_events, procrastinate_periodic_defers, procrastinate_jobs, procrastinate_workers;
DROP TYPE procrastinate_job_to_defer_v1;
DROP TYPE procrastinate_job_event_type;
DROP TYPE procrastinate_job_status;
"""


def _run_sql(script: str) -> None:
    """Run a SQL script verbatim on the migration's connection (same transaction).

    Goes to the DBAPI cursor without parameters, so neither SQLAlchemy (``:name`` binds) nor psycopg (``%``
    placeholders) rewrites it; several statements may be sent at once.
    """
    cursor = op.get_bind().connection.cursor()
    try:
        cursor.execute(script)
    finally:
        cursor.close()


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[name], name=name, create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=False)
    _create_tables()
    _run_sql(FUNCTIONS_SQL)
    _run_sql("\n".join(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" for table in RLS_TABLES))
    _run_sql("\n".join(policy.create_sql() for policy in POLICIES))
    _run_sql(AUDIT_SQL)
    grants = [f"GRANT {privileges} ON TABLE {table} TO bridge_app;" for table, privileges in APP_GRANTS.items()]
    grants += [f"GRANT SELECT ON TABLE {table} TO audit_reader;" for table in AUDIT_READER_GRANTS]
    _run_sql("\n".join(grants))
    # Procrastinate's schema, vendored verbatim from procrastinate 3.10.0 (procrastinate/sql/schema.sql).
    _run_sql(
        "SET LOCAL search_path = public;\n" + PROCRASTINATE_SQL.read_text(encoding="utf-8") + "\nRESET search_path;"
    )
    _run_sql(PROCRASTINATE_GRANTS_SQL)


def downgrade() -> None:
    _run_sql(PROCRASTINATE_DROP_SQL)
    # Dropping a table drops its policies, triggers and grants.
    for table in (
        "subscriptions",
        "org_niches",
        "notification_deliveries",
        "memberships",
        "invitations",
        "in_app_notifications",
        "sessions",
        "organizations",
        "notification_preferences",
        "login_tokens",
        "event_details",
        "developer_profiles",
        "developer_niches",
        "consents",
        "auth_identities",
        "api_tokens",
        "users",
        "regions",
        "plans",
        "niches",
        "login_attempts",
        "holidays",
        "email_suppressions",
        "audit_events",
    ):
        op.drop_table(table)
    _run_sql(
        """
        DROP FUNCTION audit_block_mutation();
        DROP FUNCTION audit_events_chain();
        DROP FUNCTION app_event_accepts_details(uuid);
        DROP FUNCTION app_create_organization(uuid, org_kind, text, citext, text);
        DROP FUNCTION app_is_member(uuid, org_role[]);
        DROP FUNCTION app_org_id();
        DROP FUNCTION app_user_id();
        DROP FUNCTION uuid7();
        """
    )
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=False)


def _create_tables() -> None:
    op.create_table(
        "audit_events",
        sa.Column("chain_id", sa.String(length=64), server_default="global", nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_kind", _enum("audit_actor"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=True),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(), nullable=False),
        sa.Column("event_hash", sa.LargeBinary(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("chain_id <> ''", name=op.f("ck_audit_events_chain_id_not_empty")),
        sa.CheckConstraint("action <> ''", name=op.f("ck_audit_events_action_not_empty")),
        sa.CheckConstraint(
            "subject_type IS NULL OR subject_type <> ''", name=op.f("ck_audit_events_subject_type_not_empty")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        sa.UniqueConstraint("chain_id", "prev_hash", name=op.f("uq_audit_events_chain_id_prev_hash")),
        sa.UniqueConstraint("chain_id", "seq", name=op.f("uq_audit_events_chain_id_seq")),
    )
    op.create_index(op.f("ix_audit_events_actor_user_id"), "audit_events", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_audit_events_org_id"), "audit_events", ["org_id"], unique=False)
    op.create_table(
        "email_suppressions",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("reason", _enum("suppression_reason"), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_suppressions")),
        sa.UniqueConstraint("email", name=op.f("uq_email_suppressions_email")),
    )
    op.create_table(
        "holidays",
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("holiday_on", sa.Date(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("provisional", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holidays")),
        sa.UniqueConstraint("country", "observed_on", "name", name=op.f("uq_holidays_country_observed_on_name")),
    )
    op.create_index(op.f("ix_holidays_observed_on"), "holidays", ["observed_on"], unique=False)
    op.create_table(
        "login_attempts",
        sa.Column("email_digest", sa.LargeBinary(), nullable=False),
        sa.Column("ip_digest", sa.LargeBinary(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
    )
    op.create_index(
        "ix_login_attempts_email_digest_created_at", "login_attempts", ["email_digest", "created_at"], unique=False
    )
    op.create_index(
        "ix_login_attempts_ip_digest_created_at", "login_attempts", ["ip_digest", "created_at"], unique=False
    )
    op.create_table(
        "niches",
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("isic_code", sa.String(length=8), nullable=True),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("name_sw", sa.String(length=120), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["niches.id"], name=op.f("fk_niches_parent_id_niches")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_niches")),
        sa.UniqueConstraint("slug", name=op.f("uq_niches_slug")),
    )
    op.create_table(
        "plans",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("side", _enum("plan_side"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("price_kes_minor", sa.BigInteger(), nullable=False),
        sa.Column("interval", _enum("billing_interval"), nullable=False),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("version", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("code", name=op.f("uq_plans_code")),
    )
    op.create_index("uq_plans_default_side", "plans", ["side"], unique=True, postgresql_where=sa.text("is_default"))
    op.create_table(
        "regions",
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("parent_code", sa.String(length=8), nullable=True),
        sa.Column("kind", _enum("region_kind"), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("county_code", sa.String(length=3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["parent_code"], ["regions.code"], name=op.f("fk_regions_parent_code_regions")),
        sa.PrimaryKeyConstraint("code", name=op.f("pk_regions")),
        sa.UniqueConstraint("county_code", name=op.f("uq_regions_county_code")),
    )
    op.create_table(
        "users",
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("locale", sa.String(length=8), server_default="en", nullable=False),
        sa.Column("staff_role", _enum("staff_role"), nullable=True),
        sa.Column("status", _enum("user_status"), server_default="active", nullable=False),
        sa.Column("totp_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("totp_pending_enc", sa.LargeBinary(), nullable=True),
        sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("totp_last_counter", sa.Integer(), nullable=True),
        sa.Column("totp_recovery_hashes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "api_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_api_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_index(op.f("ix_api_tokens_user_id"), "api_tokens", ["user_id"], unique=False)
    op.create_table(
        "auth_identities",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", _enum("auth_provider"), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_auth_identities_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_identities")),
        sa.UniqueConstraint("provider", "subject", name=op.f("uq_auth_identities_provider_subject")),
    )
    op.create_index(op.f("ix_auth_identities_user_id"), "auth_identities", ["user_id"], unique=False)
    op.create_table(
        "consents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", _enum("consent_purpose"), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("text_version", sa.String(length=32), nullable=False),
        sa.Column("text_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_consents_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_consents")),
    )
    op.create_index(op.f("ix_consents_user_id"), "consents", ["user_id"], unique=False)
    op.create_table(
        "developer_niches",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("niche_id", sa.Uuid(), nullable=False),
        sa.Column("kind", _enum("niche_interest"), nullable=False),
        sa.Column("weight", sa.Numeric(precision=4, scale=2), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], name=op.f("fk_developer_niches_niche_id_niches")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_developer_niches_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "niche_id", "kind", name=op.f("pk_developer_niches")),
    )
    op.create_table(
        "developer_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("handle", postgresql.CITEXT(), nullable=False),
        sa.Column("verification_level", _enum("dev_verification"), server_default="d0", nullable=False),
        sa.Column("headline", sa.String(length=160), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("country", sa.String(length=2), server_default="KE", nullable=False),
        sa.Column("county_code", sa.String(length=8), nullable=True),
        sa.Column("profile_embedding", Vector(1024), nullable=True),
        sa.Column("embed_model", sa.String(length=80), nullable=True),
        sa.Column("embed_version", sa.String(length=40), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["county_code"], ["regions.code"], name=op.f("fk_developer_profiles_county_code_regions")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_developer_profiles_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_developer_profiles")),
        sa.UniqueConstraint("handle", name=op.f("uq_developer_profiles_handle")),
    )
    op.create_table(
        "event_details",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["audit_events.id"], name=op.f("fk_event_details_event_id_audit_events")),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_event_details")),
    )
    op.create_table(
        "login_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("purpose", _enum("login_token_purpose"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_login_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_login_tokens_token_hash")),
    )
    op.create_index(op.f("ix_login_tokens_user_id"), "login_tokens", ["user_id"], unique=False)
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("channel", _enum("notification_channel"), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notification_preferences_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "kind", "channel", name=op.f("pk_notification_preferences")),
    )
    op.create_table(
        "organizations",
        sa.Column("kind", _enum("org_kind"), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("country", sa.String(length=2), server_default="KE", nullable=False),
        sa.Column("regions", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("registration_no", sa.String(length=64), nullable=True),
        sa.Column("website", sa.String(length=255), nullable=True),
        sa.Column("verified_domain", postgresql.CITEXT(), nullable=True),
        sa.Column("verification", _enum("org_verification"), server_default="pending", nullable=False),
        sa.Column("public_entity", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source", _enum("org_source"), nullable=False),
        sa.Column("sector_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_organizations_created_by_users")),
        sa.ForeignKeyConstraint(["sector_id"], ["niches.id"], name=op.f("fk_organizations_sector_id_niches")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mfa_pending", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_table(
        "in_app_notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=500), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_in_app_notifications_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_in_app_notifications_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_in_app_notifications")),
    )
    op.create_index(op.f("ix_in_app_notifications_user_id"), "in_app_notifications", ["user_id"], unique=False)
    op.create_table(
        "invitations",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("roles", postgresql.ARRAY(_enum("org_role")), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], name=op.f("fk_invitations_invited_by_users")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_invitations_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_invitations_token_hash")),
    )
    op.create_index(op.f("ix_invitations_org_id"), "invitations", ["org_id"], unique=False)
    op.create_table(
        "memberships",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("roles", postgresql.ARRAY(_enum("org_role")), nullable=False),
        sa.Column("status", _enum("membership_status"), server_default="active", nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_memberships_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("org_id", "user_id", name=op.f("uq_memberships_org_id_user_id")),
    )
    op.create_index(op.f("ix_memberships_org_id"), "memberships", ["org_id"], unique=False)
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False)
    op.create_table(
        "notification_deliveries",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("channel", _enum("notification_channel"), nullable=False),
        sa.Column("to_address", sa.String(length=320), nullable=False),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("local_date", sa.Date(), nullable=True),
        sa.Column("status", _enum("delivery_status"), server_default="queued", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_transient", sa.Boolean(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "user_id IS NOT NULL OR org_id IS NOT NULL", name=op.f("ck_notification_deliveries_has_recipient_scope")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_notification_deliveries_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_notification_deliveries_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_deliveries")),
        sa.UniqueConstraint("dedupe_key", name=op.f("uq_notification_deliveries_dedupe_key")),
    )
    op.create_index(op.f("ix_notification_deliveries_org_id"), "notification_deliveries", ["org_id"], unique=False)
    op.create_index(op.f("ix_notification_deliveries_user_id"), "notification_deliveries", ["user_id"], unique=False)
    op.create_table(
        "org_niches",
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("niche_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["niche_id"], ["niches.id"], name=op.f("fk_org_niches_niche_id_niches")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_org_niches_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("org_id", "niche_id", name=op.f("pk_org_niches")),
    )
    op.create_table(
        "subscriptions",
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("org_id", sa.Uuid(), nullable=True),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("status", _enum("subscription_status"), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("(user_id IS NULL) <> (org_id IS NULL)", name=op.f("ck_subscriptions_one_subject")),
        sa.ForeignKeyConstraint(
            ["org_id"], ["organizations.id"], name=op.f("fk_subscriptions_org_id_organizations"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name=op.f("fk_subscriptions_plan_id_plans")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_subscriptions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    live = sa.text("status IN ('trialing', 'active', 'past_due')")
    op.create_index("uq_subscriptions_live_org", "subscriptions", ["org_id"], unique=True, postgresql_where=live)
    op.create_index("uq_subscriptions_live_user", "subscriptions", ["user_id"], unique=True, postgresql_where=live)
