"""Revisions 0001 and 0002 (REQ-TEN-01, REQ-AUD-01, REQ-CON-01, REQ-REPO-01, REQ-PROV-01; docs/spec/08 Migrations and
Tenancy; AC-IP-2).

Migration round trip and drift (0002 leaves 0001 exactly as it found it), table classification, RLS coverage
generated from the ORM metadata, the grant matrix of every role, role attributes, the helper and SECURITY DEFINER
functions, the append-only hash-chained audit log, the evidence triggers of schema v2, the listed-organisations
policy and the Procrastinate schema.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from itertools import pairwise
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from procrastinate.schema import SchemaManager
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import bridge.models.all  # noqa: F401  # registers every table
from bridge.ids import uuid7
from bridge.models import Base, Tenancy
from bridge.models.base import RLS_TENANCIES
from tests.integration import world as w
from tests.integration.conftest import BACKEND, create_database, drop_database, role_engine, run_alembic

TABLES = Base.metadata.tables
TIER2_ROLES = ("tier2_reader", "provenance_worker", "tier2_embed_worker", "tier2_moderation", "dsr_exporter")
RUNTIME_ROLES = ("bridge_app", "aggregate_worker", "audit_reader", *TIER2_ROLES)
ROLES = ("bridge_owner", *RUNTIME_ROLES)
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

# The grant matrix of bridge_app (task cards T1.4 and T2.1, and review). Every other privilege on every ORM table
# must be absent. UPDATE is column-scoped where some columns are never the app's to change (APP_COLUMN_UPDATES).
S, I, U, D = "SELECT", "INSERT", "UPDATE", "DELETE"  # noqa: E741
APP_COLUMN_UPDATES: dict[str, set[str]] = {
    "users": {
        "email_verified_at",
        "password_hash",
        "display_name",
        "locale",
        "totp_secret_enc",
        "totp_pending_enc",
        "totp_enabled_at",
        "totp_last_counter",
        "totp_recovery_hashes",
        "updated_at",
    },
    "organizations": {
        "legal_name",
        "website",
        "regions",
        "registration_no",
        "sector_id",
        "country",
        "updated_at",
        "county_code",  # revision 0002
    },
    "developer_profiles": {"headline", "bio", "county_code", "updated_at"},
    # revision 0002: never moderation_state, owners, keys or decisions
    "problems": {
        "title",
        "statement",
        "affected_group",
        "niche_id",
        "country",
        "county_code",
        "embedding",
        "embed_model",
        "embed_version",
        "updated_at",
    },
    "problem_briefs": {"visibility", "budget_band", "deadline", "status", "updated_at"},
    "proposals": {
        "status",
        "current_version_id",
        "draft_version_id",
        "title",
        "niche_id",
        "country",
        "county_code",
        "maturity",
        "ask",
        "problem_statement",
        "impact_claims",
        "summary",
        "teaser_embedding",
        "embed_model",
        "embed_version",
        "tier2_policy",
        "raw_download_enabled",
        "published_at",
        "hidden_at",
        "updated_at",
    },
    "proposal_versions": {
        "status",
        "title",
        "niche_id",
        "country",
        "county_code",
        "maturity",
        "ask",
        "problem_statement",
        "impact_claims",
        "summary",
        "owner_handle",
        "prev_version_hash",
        "content_hash",
        "cert_id",
        "manifest_version",
        "registered_at",
        "updated_at",
    },
    "proposal_attachments": {"sha256", "size_bytes", "av_status", "rerendered", "updated_at"},
    "tags": {"status", "updated_at"},
    "disclosure_grants": {
        "status",
        "counts_as_unlock",
        "billing_month",
        "granted_by",
        "granted_at",
        "revoked_at",
        "revoked_by",
        "updated_at",
    },
    "document_views": {"duration_bucket"},
    "moderation_cases": {"status", "reasons", "assigned_to", "decided_by", "decided_at", "updated_at"},
    "org_claims": {
        "otp_hash",
        "otp_expires_at",
        "otp_attempts",
        "dns_token",
        "dns_verified_at",
        "registration_no",
        "cr12_date",
        "kra_pin",
        "sector_register",
        "public_entity_requested",
        "document_keys",
        "status",
        "updated_at",
    },
    "directory_invitations": {"status", "reason", "approved_by", "sent_at", "updated_at"},
}
APP_GRANTS: dict[str, set[str]] = {
    "users": {S, I, U},
    "sessions": {S, I, U, D},
    "login_tokens": {S, I, U, D},
    "login_attempts": {S, I, D},
    "api_tokens": {S, I, U},
    "auth_identities": {S, I, D},
    "email_suppressions": {S, I},
    "niches": {S},
    "regions": {S},
    "holidays": {S},
    "plans": {S},
    "organizations": {S, U},
    "memberships": {S, I, U},
    "invitations": {S, I, U},
    "org_niches": {S, I, D},
    "developer_profiles": {S, I, U},
    "developer_niches": {S, I, U, D},
    "consents": {S, I},
    "notification_preferences": {S, I, U, D},
    "in_app_notifications": {S, I, U},
    "subscriptions": {S, I},
    "notification_deliveries": {S, I, U},
    "audit_events": {S, I},
    "event_details": {S, I},
    # revision 0002
    "legal_templates": {S},
    "nda_templates": {S},
    "provenance_keys": {S},
    "problems": {S, I, U},
    "problem_sources": {S, I, D},
    "problem_briefs": {S, I, U},
    "brief_invitations": {S, I, D},
    "proposals": {S, I, U, D},
    "proposal_versions": {S, I, U, D},
    "proposal_problems": {S, I, D},
    "proposal_confidential": set(),  # docs/spec/06 6.1: no privilege at all; the Tier-2 roles only
    "proposal_confidential_embeddings": set(),
    "proposal_attachments": {S, I, U, D},
    "proposal_lsh_bands": {S, I, D},
    "originality_checks": {S, I},
    "provenance_records": {S},
    "chain_anchors": set(),
    "transparency_roots": {S},
    "attestations": {S, I},
    "tags": {S, I, U},
    "engagements": {S},
    "disclosure_grants": {S, I, U},
    "nda_acceptances": {S, I},
    "legal_acceptances": {S, I},
    "document_views": {S, I, U},
    "signal_events": {I},
    "moderation_cases": {S, I, U},
    "org_claims": {S, I, U},
    "directory_invitations": {S, I, U},
    "phone_verifications": {S, I},
    "kyc_reviews": {S, I},
    "llm_calls": {S, I},
}
# Every other runtime role: its whole matrix (table -> privileges) and its column-scoped UPDATEs.
ROLE_GRANTS: dict[str, dict[str, set[str]]] = {
    "aggregate_worker": {"signal_events": {S}},
    "audit_reader": {"audit_events": {S}, "chain_anchors": {S}},
    "tier2_reader": {"proposal_confidential": {S, I, U}},
    "provenance_worker": {
        "proposal_confidential": {S, U},
        "provenance_records": {S, I, U},
        "provenance_keys": {S},
        "chain_anchors": {I},
        "transparency_roots": {I},
    },
    "tier2_embed_worker": {"proposal_confidential": {S}, "proposal_confidential_embeddings": {I}},
    "tier2_moderation": {"proposal_confidential": {S}, "proposal_confidential_embeddings": {S}},
    "dsr_exporter": {"proposal_confidential": {S}},
}
ROLE_COLUMN_UPDATES: dict[str, dict[str, set[str]]] = {
    "tier2_reader": {"proposal_confidential": {"ciphertext", "nonce", "wrapped_dek", "kms_key_id", "updated_at"}},
    "provenance_worker": {
        "proposal_confidential": {"manifest_ciphertext", "manifest_nonce", "updated_at"},
        "provenance_records": {
            "signature",
            "key_id",
            "status",
            "tsa_token",
            "tsa_time",
            "tsa_serial",
            "tsa_url",
            "ots_proof",
            "evidence_s3_key",
        },
    },
}

# signature -> (SECURITY DEFINER?, roles that may EXECUTE it). Trigger functions: nobody.
FUNCTIONS: dict[str, tuple[bool, set[str]]] = {
    "uuid7()": (False, {"bridge_app"}),
    "app_user_id()": (False, {"bridge_app", *TIER2_ROLES}),
    "app_org_id()": (False, {"bridge_app"}),
    "app_is_member(uuid, org_role[])": (True, {"bridge_app"}),
    "app_create_organization(uuid, org_kind, text, citext, text)": (True, {"bridge_app"}),
    "app_event_accepts_details(uuid)": (True, {"bridge_app"}),
    "audit_events_chain()": (True, set()),
    "audit_block_mutation()": (False, set()),
    # revision 0002
    "app_is_staff(staff_role[])": (True, {"bridge_app", "tier2_moderation"}),
    "app_tier2_granted(uuid, uuid)": (True, {"bridge_app", "tier2_reader"}),
    "app_held_tag_count(uuid)": (True, {"bridge_app"}),
    "app_confirm_phone_otp(uuid, bytea)": (True, {"bridge_app"}),
    "app_decide_kyc(uuid, boolean, text, text, text, text, boolean)": (True, {"bridge_app"}),
    "app_kyc_purge_due()": (True, {"bridge_app"}),
    "app_mark_kyc_images_purged(uuid)": (True, {"bridge_app"}),
    "app_moderate_proposal(uuid, moderation_state)": (True, {"bridge_app"}),
    "app_moderate_problem(uuid, moderation_state, problem_status)": (True, {"bridge_app"}),
    "app_hold_proposal(uuid)": (True, {"bridge_app"}),
    "app_hold_problem(uuid)": (True, {"bridge_app"}),
    "app_confirm_claim_otp(uuid, bytea)": (True, {"bridge_app"}),
    "app_approve_claim_e1(uuid)": (True, {"bridge_app"}),
    "app_decide_claim(uuid, boolean, text)": (True, {"bridge_app"}),
    "app_delist_org(uuid)": (True, {"bridge_app"}),
    "app_opt_out_org_invitations(uuid)": (True, {"bridge_app"}),
    "app_llm_spend_usd(timestamp with time zone)": (True, {"bridge_app"}),
    "app_audit_chain_heads()": (True, {"provenance_worker"}),
    "block_mutation()": (False, set()),
    "proposal_versions_guard()": (True, set()),
    "proposal_confidential_guard()": (True, set()),
    "provenance_records_guard()": (False, set()),
}
PINNED_SEARCH_PATH = "search_path=pg_catalog, public, pg_temp"

# Temporary objects an attacker would plant (one statement each: psycopg sends parameterised queries singly).
SHADOWING_ATTACK = (
    "CREATE FUNCTION pg_temp.trap(v anyelement) RETURNS boolean LANGUAGE plpgsql AS"
    " $$ BEGIN RAISE EXCEPTION USING MESSAGE = concat('hijacked as ', current_user); END $$",
    "CREATE DOMAIN pg_temp.text AS pg_catalog.text CHECK (pg_temp.trap(VALUE))",
    "CREATE DOMAIN pg_temp.uuid AS pg_catalog.uuid CHECK (pg_temp.trap(VALUE))",
    "CREATE DOMAIN pg_temp.bytea AS pg_catalog.bytea CHECK (pg_temp.trap(VALUE))",
)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ZERO_HASH = bytes(32)

INSERT_EVENT = sa.text(
    "INSERT INTO audit_events (id, chain_id, actor_kind, actor_user_id, org_id, action, subject_type, subject_id,"
    " payload, seq, prev_hash, event_hash)"
    " VALUES (:id, :chain, CAST(:actor_kind AS audit_actor), :actor, :org, :action, :subject_type, :subject_id,"
    " CAST(:payload AS jsonb),"
    " 999, '\\x00'::bytea, '\\x00'::bytea)"  # seq and hashes sent by a client are overwritten by the trigger
)
SELECT_CHAIN = sa.text(
    "SELECT id, chain_id, seq, occurred_at, actor_kind::text AS actor_kind, actor_user_id, org_id, action,"
    " subject_type, subject_id, payload::text AS payload_text, prev_hash, event_hash"
    " FROM audit_events WHERE chain_id = :chain ORDER BY seq"
)


def tenancy(table: sa.Table) -> Tenancy:
    return Tenancy(table.info["tenancy"])


def tenant_tables() -> list[str]:
    return sorted(name for name, table in TABLES.items() if tenancy(table) in RLS_TENANCIES)


def event_params(chain: str, actor: UUID | None, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid7(),
        "chain": chain,
        "actor_kind": "user",
        "actor": actor,
        "org": None,
        "action": "test.event",
        "subject_type": "test",
        "subject_id": uuid7(),
        "payload": json.dumps({"n": 1, "note": "pipes | inside the payload are fine"}),
    }
    params.update(overrides)
    return params


def canonical(row: sa.Row[Any]) -> bytes:
    """The canonical form hashed by audit_events_chain() (documented in revision 0001)."""

    def text(value: object) -> str:
        return "" if value is None else str(value)

    fields = [
        row.prev_hash.hex(),
        str(row.seq),
        str(row.id),
        row.chain_id,
        str((row.occurred_at - EPOCH) // timedelta(microseconds=1)),
        row.actor_kind,
        text(row.actor_user_id),
        text(row.org_id),
        row.action,
        text(row.subject_type),
        text(row.subject_id),
        row.payload_text,
    ]
    return "|".join(fields).encode("utf-8")


def assert_linked_chain(rows: list[sa.Row[Any]]) -> None:
    assert [row.seq for row in rows] == list(range(1, len(rows) + 1))
    assert rows[0].prev_hash == ZERO_HASH
    for previous, row in pairwise(rows):
        assert row.prev_hash == previous.event_hash
        assert row.occurred_at >= previous.occurred_at  # clock_timestamp() under the lock follows seq
    for row in rows:
        assert len(row.event_hash) == 32
        assert row.event_hash == hashlib.sha256(canonical(row)).digest()


@asynccontextmanager
async def rolled_back(engine: AsyncEngine, user_id: UUID | None = None) -> AsyncIterator[AsyncConnection]:
    """A connection inside a transaction that is always rolled back (the session database is shared)."""
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            if user_id is not None:
                await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})
            yield conn
        finally:
            await transaction.rollback()


async def expect_error(conn: AsyncConnection, sql: str, match: str, params: dict[str, Any] | None = None) -> None:
    """Run ``sql`` in a savepoint, assert it fails with ``match``, and leave the outer transaction usable."""
    savepoint = await conn.begin_nested()
    with pytest.raises(sa.exc.DBAPIError, match=match):
        await conn.execute(sa.text(sql), params or {})
    await savepoint.rollback()


async def scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(sa.text(sql), params)).scalar_one()


async def rows(engine: AsyncEngine, sql: str, **params: Any) -> list[sa.Row[Any]]:
    async with engine.connect() as conn:
        return list((await conn.execute(sa.text(sql), params)).all())


# --- Migration round trip ----------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scratch_url(admin_url: URL) -> Iterator[URL]:
    """A database of its own for the round trip and for tests that must commit (audit rows are undeletable)."""
    name = f"bridge_mig_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        yield url
    finally:
        drop_database(admin_url, name)


def leftover_objects(url: URL) -> list[str]:
    """Objects in schema public that are neither Alembic's version table nor extension members."""
    queries = {
        "relation": "SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'public'::regnamespace"
        " AND c.relname NOT LIKE 'alembic_version%' AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')",
        "type": "SELECT t.typname FROM pg_type t WHERE t.typnamespace = 'public'::regnamespace"
        " AND t.typtype IN ('e', 'c', 'd') AND (t.typrelid = 0 OR t.typtype = 'c')"
        " AND t.typname NOT LIKE 'alembic_version%' AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')",
        "function": "SELECT p.proname FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace"
        " AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')",
        "policy": "SELECT policyname FROM pg_policies WHERE schemaname = 'public'",
    }
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            return [f"{kind} {name}" for kind, sql in queries.items() for (name,) in conn.execute(sa.text(sql))]
    finally:
        engine.dispose()


# The shape of schema public that a revision may change: columns, constraints, indexes, RLS and policies, functions,
# triggers, enum labels and every ACL (tables, columns, functions). Extension members are left out.
_NOT_EXTENSION = (
    "NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = '{catalog}'::regclass AND d.objid = {oid}"
    " AND d.deptype = 'e')"
)
SNAPSHOT: dict[str, str] = {
    "columns": "SELECT c.relname || '.' || a.attname || ' ' || format_type(a.atttypid, a.atttypmod)"
    " || CASE WHEN a.attnotnull THEN ' not null' ELSE '' END"
    " || coalesce(' default ' || pg_get_expr(d.adbin, d.adrelid), '')"
    " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
    " LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum"
    " WHERE c.relnamespace = 'public'::regnamespace AND a.attnum > 0 AND NOT a.attisdropped"
    " AND " + _NOT_EXTENSION.format(catalog="pg_class", oid="c.oid"),
    "constraints": "SELECT conrelid::regclass::text || ' ' || conname || ' ' || pg_get_constraintdef(oid)"
    " FROM pg_constraint WHERE connamespace = 'public'::regnamespace AND conrelid <> 0",
    "indexes": "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public'",
    "rls": "SELECT relname || ' ' || relrowsecurity || ' ' || relforcerowsecurity FROM pg_class"
    " WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'",
    "policies": "SELECT tablename || ' ' || policyname || ' ' || cmd || ' ' || roles::text || ' '"
    " || coalesce(qual, '') || ' ' || coalesce(with_check, '') FROM pg_policies WHERE schemaname = 'public'",
    "functions": "SELECT p.oid::regprocedure::text || ' ' || p.prosecdef || ' ' || coalesce(p.proconfig::text, '')"
    " || ' ' || md5(pg_get_functiondef(p.oid)) FROM pg_proc p WHERE p.pronamespace = 'public'::regnamespace"
    " AND p.prokind = 'f' AND " + _NOT_EXTENSION.format(catalog="pg_proc", oid="p.oid"),
    "triggers": "SELECT tgrelid::regclass::text || ' ' || tgname || ' ' || tgfoid::regprocedure::text || ' ' || tgtype"
    " FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
    " WHERE NOT t.tgisinternal AND c.relnamespace = 'public'::regnamespace",
    "enums": "SELECT t.typname || ' ' || string_agg(e.enumlabel, ',' ORDER BY e.enumsortorder) FROM pg_type t"
    " JOIN pg_enum e ON e.enumtypid = t.oid WHERE t.typnamespace = 'public'::regnamespace GROUP BY t.typname",
    "table_acl": "SELECT c.relname || ' ' || a.grantee::regrole::text || ' ' || a.privilege_type FROM pg_class c"
    " CROSS JOIN LATERAL aclexplode(c.relacl) a WHERE c.relnamespace = 'public'::regnamespace",
    "column_acl": "SELECT c.relname || '.' || t.attname || ' ' || a.grantee::regrole::text || ' ' || a.privilege_type"
    " FROM pg_attribute t JOIN pg_class c ON c.oid = t.attrelid CROSS JOIN LATERAL aclexplode(t.attacl) a"
    " WHERE c.relnamespace = 'public'::regnamespace AND NOT t.attisdropped",
    "function_acl": "SELECT p.oid::regprocedure::text || ' ' || a.grantee::regrole::text || ' ' || a.privilege_type"
    " FROM pg_proc p CROSS JOIN LATERAL aclexplode(p.proacl) a WHERE p.pronamespace = 'public'::regnamespace"
    " AND " + _NOT_EXTENSION.format(catalog="pg_proc", oid="p.oid"),
}


def schema_snapshot(url: URL) -> dict[str, list[str]]:
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            return {kind: sorted(conn.execute(sa.text(sql)).scalars()) for kind, sql in SNAPSHOT.items()}
    finally:
        engine.dispose()


def test_upgrade_downgrade_upgrade_without_drift(scratch_url: URL) -> None:
    run_alembic(scratch_url, lambda config: command.upgrade(config, "0001"))
    at_0001 = schema_snapshot(scratch_url)
    run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
    run_alembic(scratch_url, command.check)  # raises AutogenerateDiffsDetected on drift from the ORM
    run_alembic(scratch_url, lambda config: command.downgrade(config, "0001"))
    after = schema_snapshot(scratch_url)
    for kind in SNAPSHOT:  # 0002 leaves every object of 0001 exactly as it found it
        assert after[kind] == at_0001[kind], kind
    run_alembic(scratch_url, lambda config: command.downgrade(config, "base"))
    assert leftover_objects(scratch_url) == []
    run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
    run_alembic(scratch_url, command.check)


def test_concurrent_appends_to_one_chain_are_serialised(scratch_url: URL) -> None:
    """A second writer waits on the chain's advisory lock and links to the first writer's committed event."""
    run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
    chain = f"test:{uuid4().hex}"
    engine = sa.create_engine(scratch_url, poolclass=sa.pool.NullPool)
    errors: list[BaseException] = []
    pid: list[int] = []

    def second_writer() -> None:
        try:
            with engine.begin() as conn:  # commits on exit
                conn.exec_driver_sql("SET LOCAL ROLE bridge_app")
                pid.append(conn.execute(sa.text("SELECT pg_backend_pid()")).scalar_one())
                conn.execute(INSERT_EVENT, event_params(chain, None, actor_kind="system"))
        except BaseException as exc:  # reported by the main thread
            errors.append(exc)

    blocked = sa.text("SELECT count(*) FROM pg_locks WHERE pid = :pid AND locktype = 'advisory' AND NOT granted")
    try:
        with engine.begin() as first:  # holds the chain lock until it commits on exit
            first.exec_driver_sql("SET LOCAL ROLE bridge_app")
            first.execute(INSERT_EVENT, event_params(chain, None, actor_kind="system"))
            thread = threading.Thread(target=second_writer)
            thread.start()
            deadline = time.monotonic() + 60
            waiting = False
            while not waiting and time.monotonic() < deadline and thread.is_alive():
                time.sleep(0.1)
                if pid:
                    waiting = bool(first.execute(blocked, {"pid": pid[0]}).scalar_one())
            assert waiting, "the second writer did not wait on the chain's advisory lock"
        thread.join(timeout=60)
        assert not thread.is_alive()
        assert not errors, errors
        with engine.connect() as conn:
            assert_linked_chain(list(conn.execute(SELECT_CHAIN, {"chain": chain}).all()))
    finally:
        engine.dispose()


# --- Harness ------------------------------------------------------------------------------------------------------


async def test_role_engines_keep_their_role_across_transactions(
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    aggregate_engine: AsyncEngine,
    audit_reader_engine: AsyncEngine,
) -> None:
    """A rolled-back transaction must not undo an engine's SET ROLE (else tests would run as the superuser)."""
    engines = {
        "bridge_app": app_engine,
        "bridge_owner": owner_engine,
        "aggregate_worker": aggregate_engine,
        "audit_reader": audit_reader_engine,
    }
    current_user = sa.text("SELECT current_user")
    for role, engine in engines.items():
        for _ in range(3):
            async with rolled_back(engine) as conn:
                assert (await conn.execute(current_user)).scalar_one() == role
        async with engine.connect() as conn:
            assert (await conn.execute(current_user)).scalar_one() == role
            await conn.commit()
            assert (await conn.execute(current_user)).scalar_one() == role


# --- Classification and RLS coverage (generated from the ORM metadata) --------------------------------------------


async def test_every_table_is_declared_with_a_tenancy(owner_engine: AsyncEngine) -> None:
    found = await rows(
        owner_engine,
        "SELECT relname FROM pg_class WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')",
    )
    names = {row.relname for row in found}
    undeclared = {n for n in names if n != "alembic_version" and not n.startswith("procrastinate_")} - set(TABLES)
    assert undeclared == set(), f"tables without an ORM model and tenancy: {sorted(undeclared)}"
    assert set(TABLES) <= names
    for table in TABLES.values():
        assert "tenancy" in table.info, f"{table.name} declares no tenancy"
        tenancy(table)  # a valid Tenancy value


@pytest.mark.parametrize("table", sorted(TABLES))
async def test_rls_follows_the_declared_tenancy(owner_engine: AsyncEngine, table: str) -> None:
    (row,) = await rows(
        owner_engine,
        "SELECT c.relrowsecurity, c.relforcerowsecurity, (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)"
        " AS policies FROM pg_class c WHERE c.oid = to_regclass(:t)",
        t=f"public.{table}",
    )
    if tenancy(TABLES[table]) in RLS_TENANCIES:
        assert row.relrowsecurity, f"{table}: RLS is not enabled"
        assert not row.relforcerowsecurity, f"{table}: RLS must be ENABLED, not FORCED (owner helpers bypass it)"
        assert row.policies >= 1, f"{table}: no policy"
    else:
        assert not row.relrowsecurity, f"{table}: global/system tables have no RLS"
        assert row.policies == 0


# Held on the table or on any of its columns (column-scoped UPDATE grants count). DELETE, TRUNCATE and TRIGGER exist
# only at table level.
HOLDS_PRIVILEGE = (
    "CASE WHEN {p} IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')"
    " THEN has_any_column_privilege({r}, 'public.' || {t}, {p})"
    " ELSE has_table_privilege({r}, 'public.' || {t}, {p}) END"
)


@pytest.mark.parametrize("table", tenant_tables())
async def test_every_command_granted_on_an_rls_table_has_a_policy(owner_engine: AsyncEngine, table: str) -> None:
    """For every runtime role (bridge_app and the Tier-2 roles alike): a granted command without a policy for that
    role would silently match no row, so the grant and the policy must come together."""
    found = await rows(
        owner_engine,
        "SELECT r.name AS role, p.name AS privilege, (SELECT count(*) FROM pg_policies pol"
        " WHERE pol.schemaname = 'public' AND pol.tablename = CAST(:t AS name) AND pol.cmd IN (p.name, 'ALL')"
        " AND CAST(r.name AS name) = ANY (pol.roles)) AS policies"
        " FROM unnest(CAST(:roles AS text[])) AS r(name) CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(name)"
        " WHERE " + HOLDS_PRIVILEGE.format(r="CAST(r.name AS name)", t="CAST(:t AS text)", p="p.name"),
        t=table,
        roles=list(RUNTIME_ROLES),
        privileges=[S, I, U, D],
    )
    uncovered = sorted(f"{row.role} may {row.privilege}" for row in found if row.policies == 0)
    assert uncovered == [], f"{table}: no policy covers {uncovered}"


@pytest.mark.parametrize("table", tenant_tables())
async def test_no_policy_is_granted_to_a_role_without_the_privilege(owner_engine: AsyncEngine, table: str) -> None:
    """The reverse: every policy names a runtime role that holds its command (no stale or misnamed policy)."""
    found = await rows(
        owner_engine,
        "SELECT pol.policyname, pol.cmd, CAST(r.role AS text) AS role, "
        + HOLDS_PRIVILEGE.format(r="r.role", t="CAST(:t AS text)", p="pol.cmd")
        + " AS held FROM pg_policies pol CROSS JOIN LATERAL unnest(pol.roles) AS r(role)"
        " WHERE pol.schemaname = 'public' AND pol.tablename = CAST(:t AS name)",
        t=table,
    )
    assert found, f"{table}: no policy"
    for policy in found:
        assert policy.role in RUNTIME_ROLES, f"{table}.{policy.policyname} is for {policy.role}"
        assert policy.held, f"{table}.{policy.policyname}: {policy.role} does not hold {policy.cmd}"


# --- Grants and roles ---------------------------------------------------------------------------------------------


async def privileges_of(engine: AsyncEngine, role: str) -> dict[str, set[str]]:
    found = await rows(
        engine,
        "SELECT t.name AS table_name, p.name AS privilege"
        " FROM unnest(CAST(:tables AS text[])) AS t(name) CROSS JOIN unnest(CAST(:privileges AS text[])) AS p(name)"
        " WHERE " + HOLDS_PRIVILEGE.format(r="CAST(:role AS name)", t="t.name", p="p.name"),
        tables=sorted(TABLES),
        privileges=list(PRIVILEGES),
        role=role,
    )
    held: dict[str, set[str]] = {}
    for row in found:
        held.setdefault(row.table_name, set()).add(row.privilege)
    return held


async def test_bridge_app_grants_are_exactly_the_matrix(owner_engine: AsyncEngine) -> None:
    assert set(APP_GRANTS) == set(TABLES), "every ORM table needs a row in the grant matrix"
    expected = {table: privileges for table, privileges in APP_GRANTS.items() if privileges}
    assert await privileges_of(owner_engine, "bridge_app") == expected


async def test_bridge_app_updates_only_the_allowed_columns(owner_engine: AsyncEngine) -> None:
    columns = [(name, column.name) for name, table in TABLES.items() for column in table.columns]
    found = await rows(
        owner_engine,
        "SELECT x.t AS table_name, x.c AS column_name"
        " FROM unnest(CAST(:tables AS text[]), CAST(:columns AS text[])) AS x(t, c)"
        " WHERE has_column_privilege('bridge_app', 'public.' || x.t, x.c, 'UPDATE')",
        tables=[table for table, _ in columns],
        columns=[column for _, column in columns],
    )
    updatable: dict[str, set[str]] = {}
    for row in found:
        updatable.setdefault(row.table_name, set()).add(row.column_name)
    expected = {
        name: APP_COLUMN_UPDATES.get(name, {column.name for column in table.columns})
        for name, table in TABLES.items()
        if U in APP_GRANTS[name]
    }
    assert updatable == expected
    for table in APP_COLUMN_UPDATES:  # column-scoped only, never the whole table
        assert await scalar(owner_engine, "SELECT has_table_privilege('bridge_app', :t, 'UPDATE')", t=table) is False
    assert not {"staff_role", "status", "email", "subject_salt"} & updatable["users"]
    org_protected = {"verification", "slug", "kind", "source", "public_entity", "verified_domain", "official_domains"}
    org_protected |= {"delisted_at", "invitations_opted_out_at", "e2_verified_at", "reverify_due_on", "suspended_at"}
    assert not org_protected & updatable["organizations"]
    assert not {"moderation_state", "owner_id"} & (updatable["proposals"] | updatable["problems"])
    assert (
        not {"otp_verified_at", "claimant_user_id", "reviewed_by", "decided_at", "level", "domain"}
        & (updatable["org_claims"])
    )
    profile_protected = {"verification_level", "handle", "profile_embedding", "embed_model", "embed_version"}
    assert not profile_protected & updatable["developer_profiles"]


async def test_bridge_app_cannot_update_protected_columns(app_engine: AsyncEngine) -> None:
    user_id = uuid7()
    async with rolled_back(app_engine, user_id) as conn:
        await add_user(conn, user_id)
        await conn.execute(sa.text("UPDATE users SET display_name = 'Renamed' WHERE id = :id"), {"id": user_id})
        for column, value in (("staff_role", "'admin'"), ("status", "'suspended'"), ("email", "'x@example.test'")):
            await expect_error(
                conn, f"UPDATE users SET {column} = {value} WHERE id = :id", "permission denied", {"id": user_id}
            )
        await conn.execute(
            sa.text("INSERT INTO developer_profiles (user_id, handle) VALUES (:id, :handle)"),
            {"id": user_id, "handle": f"dev-{uuid4().hex[:12]}"},
        )
        by_user = {"id": user_id}
        await conn.execute(sa.text("UPDATE developer_profiles SET headline = 'Builder' WHERE user_id = :id"), by_user)
        for assignment in (
            "verification_level = 'd2'",
            "handle = 'taken'",
            "embed_model = 'x'",
            "embed_version = 'x'",
            "profile_embedding = NULL",
        ):
            await expect_error(
                conn, f"UPDATE developer_profiles SET {assignment} WHERE user_id = :id", "permission denied", by_user
            )
        await expect_error(conn, "UPDATE organizations SET verification = 'e2'", "permission denied")
        await expect_error(conn, "DELETE FROM memberships", "permission denied")
        await expect_error(conn, "UPDATE subscriptions SET status = 'active'", "permission denied")


async def test_append_only_tables_deny_update_delete_truncate_to_the_app(owner_engine: AsyncEngine) -> None:
    for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
        assert not await scalar(
            owner_engine, "SELECT has_table_privilege('bridge_app', 'audit_events', :p)", p=privilege
        )
    for privilege in ("UPDATE", "DELETE"):
        assert not await scalar(owner_engine, "SELECT has_table_privilege('bridge_app', 'consents', :p)", p=privilege)


@pytest.mark.parametrize("role", sorted(ROLE_GRANTS))
async def test_other_runtime_roles_hold_exactly_their_matrix(owner_engine: AsyncEngine, role: str) -> None:
    """aggregate_worker reads only signal_events; audit_reader only the chain and its anchors; each Tier-2 role only
    what docs/spec/06 6.1 gives it. UPDATE is column-scoped wherever ROLE_COLUMN_UPDATES says so."""
    assert set(ROLE_GRANTS) | {"bridge_app"} == set(RUNTIME_ROLES)
    assert await privileges_of(owner_engine, role) == ROLE_GRANTS[role]
    for table, columns in ROLE_COLUMN_UPDATES.get(role, {}).items():
        found = await rows(
            owner_engine,
            "SELECT c.name FROM unnest(CAST(:columns AS text[])) AS c(name)"
            " WHERE has_column_privilege(CAST(:role AS name), 'public.' || CAST(:t AS text), c.name, 'UPDATE')",
            columns=[column.name for column in TABLES[table].columns],
            role=role,
            t=table,
        )
        assert {row.name for row in found} == columns, f"{role} UPDATE on {table}"
        whole = "SELECT has_table_privilege(CAST(:role AS name), CAST(:t AS text), 'UPDATE')"
        assert await scalar(owner_engine, whole, role=role, t=table) is False


async def test_roles_are_neither_superuser_nor_bypassrls(owner_engine: AsyncEngine) -> None:
    found = await rows(
        owner_engine,
        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = ANY (:roles)",
        roles=list(ROLES),
    )
    assert {row.rolname for row in found} == set(ROLES)
    for row in found:
        assert not row.rolsuper, row.rolname
        assert not row.rolbypassrls, row.rolname


@pytest.mark.parametrize("role", RUNTIME_ROLES)
async def test_runtime_roles_own_nothing(owner_engine: AsyncEngine, role: str) -> None:
    owned = await scalar(
        owner_engine,
        "SELECT (SELECT count(*) FROM pg_class WHERE relowner = r.oid)"
        " + (SELECT count(*) FROM pg_proc WHERE proowner = r.oid)"
        " + (SELECT count(*) FROM pg_type WHERE typowner = r.oid)"
        " + (SELECT count(*) FROM pg_namespace WHERE nspowner = r.oid)"
        " FROM pg_roles r WHERE r.rolname = :role",
        role=role,
    )
    assert owned == 0


async def test_every_table_is_owned_by_bridge_owner(owner_engine: AsyncEngine) -> None:
    owners = await rows(
        owner_engine,
        "SELECT DISTINCT pg_get_userbyid(relowner) AS owner FROM pg_class"
        " WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p', 'S', 'v', 'm')",
    )
    assert {row.owner for row in owners} == {"bridge_owner"}


@pytest.mark.parametrize("signature", sorted(FUNCTIONS))
async def test_helper_functions_are_locked_down(owner_engine: AsyncEngine, signature: str) -> None:
    definer, callers = FUNCTIONS[signature]
    (row,) = await rows(
        owner_engine,
        "SELECT prosecdef, proconfig, pg_get_userbyid(proowner) AS owner FROM pg_proc"
        " WHERE oid = to_regprocedure(:sig)",
        sig=signature,
    )
    assert row.prosecdef is definer
    assert row.owner == "bridge_owner"
    assert row.proconfig == [PINNED_SEARCH_PATH]
    allowed = await rows(
        owner_engine,
        "SELECT r.name FROM unnest(CAST(:roles AS text[])) AS r(name)"
        " WHERE has_function_privilege(r.name, CAST(:sig AS text), 'EXECUTE')",
        roles=["public", *RUNTIME_ROLES],
        sig=signature,
    )
    assert {row.name for row in allowed} == callers, f"EXECUTE {signature}"


async def test_every_function_pins_search_path_with_pg_temp_last(owner_engine: AsyncEngine) -> None:
    """Every function of the revision (helpers, triggers, Procrastinate's), not only the listed helpers."""
    found = await rows(
        owner_engine,
        "SELECT p.oid::regprocedure::text AS signature, p.proconfig FROM pg_proc p"
        " WHERE p.pronamespace = 'public'::regnamespace AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')",
    )
    assert len(found) > len(FUNCTIONS)  # includes procrastinate_*
    unpinned = sorted(row.signature for row in found if row.proconfig != [PINNED_SEARCH_PATH])
    assert unpinned == []


@pytest.mark.parametrize("role", RUNTIME_ROLES)
async def test_runtime_roles_cannot_create_temporary_objects(owner_engine: AsyncEngine, role: str) -> None:
    privilege = "SELECT has_database_privilege(:r, current_database(), 'TEMPORARY')"
    assert await scalar(owner_engine, privilege, r=role) is False


async def test_pg_temp_shadowing_cannot_hijack_definer_functions(database_url: URL) -> None:
    """The attack the pinned search_path stops. bridge_app shadows uuid, text and bytea with temporary domains whose
    CHECK raises with current_user. With pg_temp unlisted it is searched first for types, so SECURITY DEFINER code
    (``v_user uuid`` in app_create_organization, ``bytea`` and ``::text`` in the audit trigger) resolved the domains
    and ran the CHECK as bridge_owner. TEMPORARY is granted inside the rolled-back transaction to show the pinned path
    holds on its own; a fresh backend makes sure no plan compiled before the domains existed hides a regression."""
    engine = role_engine(database_url, "bridge_owner", poolclass=sa.pool.NullPool)
    user_id, org_id = uuid7(), uuid7()
    try:
        async with rolled_back(engine) as conn:
            await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
            await expect_error(conn, "CREATE TEMP TABLE t (x int)", "permission denied to create temporary tables")
            await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))  # owns the database; the grant is rolled back
            database = (await conn.execute(sa.text("SELECT current_database()"))).scalar_one()
            await conn.execute(sa.text(f'GRANT TEMPORARY ON DATABASE "{database}" TO bridge_app'))
            await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
            await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})
            await conn.execute(
                sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Victim')"),
                {"id": user_id, "email": f"{uuid4().hex}@example.test"},
            )
            for statement in SHADOWING_ATTACK:
                await conn.execute(sa.text(statement))
            # The trap is live: SQL without a pinned path resolves the temporary domain and runs its CHECK.
            await expect_error(conn, "SELECT CAST('x' AS text)", "hijacked as bridge_app")
            # Pinned functions never resolve it (before the fix each of these raised "hijacked as bridge_owner").
            await conn.execute(
                sa.text("SELECT app_create_organization(:id, 'company', 'Victim Ltd', CAST(:slug AS citext))"),
                {"id": org_id, "slug": f"victim-{uuid4().hex}"},
            )
            member = sa.text("SELECT app_is_member(:id, '{owner}')")
            assert (await conn.execute(member, {"id": org_id})).scalar_one() is True
            await conn.execute(sa.text("SELECT uuid7(), app_user_id(), app_org_id()"))
            event_id = uuid7()
            await conn.execute(
                sa.text("INSERT INTO audit_events (id, chain_id, actor_kind, action) VALUES (:id, :c, 'system', 'x')"),
                {"id": event_id, "c": f"test:{uuid4().hex}"},
            )
            await conn.execute(sa.text("INSERT INTO event_details (event_id) VALUES (:id)"), {"id": event_id})
    finally:
        await engine.dispose()


ADD_PLAN = (
    'INSERT INTO plans (id, code, side, name, price_kes_minor, "interval", limits, is_default)'
    " VALUES (:id, :code, 'developer', 'Test plan', :price, 'month', '{}'::jsonb, :is_default)"
)


def plan_params(price: int, is_default: bool) -> dict[str, Any]:
    return {"id": uuid7(), "code": f"test-{uuid4().hex[:12]}", "price": price, "is_default": is_default}


async def test_self_serve_subscriptions_only_to_the_default_plan(owner_engine: AsyncEngine) -> None:
    user_id = uuid7()
    subscribe = (
        "INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start)"
        " VALUES (:id, :user, :plan, 'active', now())"
    )
    async with rolled_back(owner_engine) as conn:
        await add_user(conn, user_id)
        existing = "SELECT id FROM plans WHERE side = 'developer' AND is_default"
        default_id = (await conn.execute(sa.text(existing))).scalar_one_or_none()
        if default_id is None:  # the seed may already have one (config/plans.yaml `default: true`)
            default = plan_params(0, is_default=True)
            await conn.execute(sa.text(ADD_PLAN), default)
            default_id = default["id"]
        paid = plan_params(150_000, is_default=False)
        await conn.execute(sa.text(ADD_PLAN), paid)
        await expect_error(conn, ADD_PLAN, "uq_plans_default_side", plan_params(0, is_default=True))  # one per side

        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        await act_as(conn, user_id)
        await expect_error(conn, subscribe, "row-level security", {"id": uuid7(), "user": user_id, "plan": paid["id"]})
        await conn.execute(sa.text(subscribe), {"id": uuid7(), "user": user_id, "plan": default_id})
        mine = sa.text("SELECT plan_id FROM subscriptions WHERE user_id = :user")
        assert (await conn.execute(mine, {"user": user_id})).scalars().all() == [default_id]


async def test_deleting_a_user_removes_their_user_only_deliveries(owner_engine: AsyncEngine) -> None:
    """ON DELETE CASCADE: SET NULL would violate has_recipient_scope and block the deletion (erasure, REQ-SEC-02)."""
    user_id = uuid7()
    async with rolled_back(owner_engine) as conn:
        await add_user(conn, user_id)
        await conn.execute(
            sa.text(
                "INSERT INTO notification_deliveries (id, user_id, kind, channel, to_address)"
                " VALUES (:id, :user, 'em7', 'email', 'x@example.test')"
            ),
            {"id": uuid7(), "user": user_id},
        )
        await conn.execute(sa.text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        left = sa.text("SELECT count(*) FROM notification_deliveries WHERE user_id = :id")
        assert (await conn.execute(left, {"id": user_id})).scalar_one() == 0


async def test_enum_types_match_the_orm(owner_engine: AsyncEngine) -> None:
    declared: dict[str, list[str]] = {}
    for table in TABLES.values():
        for column in table.columns:
            column_type = column.type
            if isinstance(column_type, postgresql.ARRAY):
                column_type = column_type.item_type
            if isinstance(column_type, sa.Enum) and column_type.name:
                declared[column_type.name] = list(column_type.enums)
    found = await rows(
        owner_engine,
        "SELECT t.typname, array_agg(e.enumlabel::text ORDER BY e.enumsortorder) AS labels"
        " FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid"
        " WHERE t.typnamespace = 'public'::regnamespace AND t.typname NOT LIKE 'procrastinate%' GROUP BY t.typname",
    )
    assert {row.typname: list(row.labels) for row in found} == declared


# --- RLS helpers --------------------------------------------------------------------------------------------------


async def test_app_create_organization_makes_the_caller_owner(app_engine: AsyncEngine) -> None:
    org_id = uuid7()
    create = "SELECT app_create_organization(:id, 'company', 'Acme Ltd', CAST(:slug AS citext))"
    async with rolled_back(app_engine) as conn:
        await expect_error(conn, create, "app.user_id is not set", {"id": org_id, "slug": f"acme-{uuid4().hex}"})

    user_id = uuid7()
    async with rolled_back(app_engine, user_id) as conn:
        await conn.execute(
            sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Test Owner')"),
            {"id": user_id, "email": f"{uuid4().hex}@example.test"},
        )
        created = (await conn.execute(sa.text(create), {"id": org_id, "slug": f"acme-{uuid4().hex}"})).scalar_one()
        assert created == org_id
        org = (
            await conn.execute(
                sa.text("SELECT verification::text, source::text, created_by FROM organizations WHERE id = :id"),
                {"id": org_id},
            )
        ).one()
        assert tuple(org) == ("pending", "self_signup", user_id)
        membership = (
            await conn.execute(
                sa.text("SELECT roles::text[] AS roles, status::text AS status FROM memberships WHERE org_id = :id"),
                {"id": org_id},
            )
        ).one()
        assert (membership.roles, membership.status) == (["owner", "admin"], "active")
        member = sa.text("SELECT app_is_member(:id), app_is_member(:id, '{owner}'), app_is_member(:id, '{signatory}')")
        assert tuple((await conn.execute(member, {"id": org_id})).one()) == (True, True, False)
        await expect_error(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source) VALUES (:id, 'sme', 'X', :slug, 'seed')",
            "permission denied",
            {"id": uuid7(), "slug": f"x-{uuid4().hex}"},
        )
        # Another user in the same transaction: not a member, and RLS hides the organisation and its roster.
        await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(uuid7())})
        assert (await conn.execute(member, {"id": org_id})).one()[0] is False
        for table, column in (("organizations", "id"), ("memberships", "org_id")):
            visible = sa.text(f"SELECT count(*) FROM {table} WHERE {column} = :id")
            assert (await conn.execute(visible, {"id": org_id})).scalar_one() == 0


async def act_as(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user_id)})


async def add_user(conn: AsyncConnection, user_id: UUID) -> None:
    await conn.execute(
        sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Test User')"),
        {"id": user_id, "email": f"{uuid4().hex}@example.test"},
    )


ADD_MEMBER = (
    "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, CAST(:roles AS org_role[]))"
)
INVITE = (
    "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at)"
    " VALUES (:id, :org, :email, CAST(:roles AS org_role[]), :token, app_user_id(), now() + interval '7 days')"
)


def member_params(org_id: UUID, user_id: UUID, roles: str) -> dict[str, Any]:
    return {"id": uuid7(), "org": org_id, "user": user_id, "roles": roles}


def invite_params(org_id: UUID, roles: str) -> dict[str, Any]:
    return {
        "id": uuid7(),
        "org": org_id,
        "email": f"{uuid4().hex}@example.test",
        "roles": roles,
        "token": uuid4().bytes,
    }


async def test_admins_cannot_grant_or_touch_protected_roles(app_engine: AsyncEngine) -> None:
    """Protected roles are owner and signatory. An admin who is not an owner cannot grant them (to themselves or
    anyone), invite with them, or change a membership that holds them; an owner can do all of it."""
    owner, admin, member, newcomer = uuid7(), uuid7(), uuid7(), uuid7()
    org_id = uuid7()
    rls = "row-level security"
    async with rolled_back(app_engine, owner) as conn:
        for user_id in (owner, admin, member, newcomer):
            await add_user(conn, user_id)
        await conn.execute(
            sa.text("SELECT app_create_organization(:id, 'sme', 'Roles Ltd', CAST(:slug AS citext))"),
            {"id": org_id, "slug": f"roles-{uuid4().hex}"},
        )
        await conn.execute(sa.text(ADD_MEMBER), member_params(org_id, admin, "{admin}"))

        await act_as(conn, admin)
        await conn.execute(sa.text(ADD_MEMBER), member_params(org_id, member, "{viewer}"))  # admins manage others
        invitation = invite_params(org_id, "{reviewer}")
        await conn.execute(sa.text(INVITE), invitation)
        own_roles = "UPDATE memberships SET roles = CAST(:roles AS org_role[]) WHERE org_id = :org AND user_id = :user"
        for protected in ("{owner,admin}", "{admin,signatory}"):  # no self-assignment of owner or signatory
            await expect_error(conn, own_roles, rls, {"roles": protected, "org": org_id, "user": admin})
        for protected in ("{owner}", "{viewer,signatory}"):
            await expect_error(conn, own_roles, rls, {"roles": protected, "org": org_id, "user": member})
            await expect_error(conn, ADD_MEMBER, rls, member_params(org_id, newcomer, protected))
            await expect_error(conn, INVITE, rls, invite_params(org_id, protected))
            await expect_error(
                conn,
                "UPDATE invitations SET roles = CAST(:roles AS org_role[]) WHERE id = :id",
                rls,
                {"roles": protected, "id": invitation["id"]},
            )
        # The owner's membership is invisible to the admin's UPDATE: no demotion, no removal.
        remove = "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :user"
        assert (await conn.execute(sa.text(remove), {"org": org_id, "user": owner})).rowcount == 0

        await act_as(conn, owner)
        grant = await conn.execute(sa.text(own_roles), {"roles": "{viewer,signatory}", "org": org_id, "user": member})
        assert grant.rowcount == 1
        await conn.execute(sa.text(ADD_MEMBER), member_params(org_id, newcomer, "{owner}"))
        await conn.execute(sa.text(INVITE), invite_params(org_id, "{owner}"))
        await conn.execute(sa.text(INVITE), invite_params(org_id, "{signatory}"))

        await act_as(conn, admin)  # a signatory's membership is now out of the admin's reach too
        assert (await conn.execute(sa.text(remove), {"org": org_id, "user": member})).rowcount == 0

        await act_as(conn, owner)
        promote = await conn.execute(sa.text(own_roles), {"roles": "{owner,admin}", "org": org_id, "user": admin})
        assert promote.rowcount == 1
        roles = await conn.execute(
            sa.text(
                "SELECT user_id, roles::text[] AS roles, status::text AS status FROM memberships WHERE org_id = :org"
            ),
            {"org": org_id},
        )
        assert {row.user_id: (row.roles, row.status) for row in roles} == {
            owner: (["owner", "admin"], "active"),
            admin: (["owner", "admin"], "active"),
            member: (["viewer", "signatory"], "active"),
            newcomer: (["owner"], "active"),
        }


# --- Audit chain (REQ-AUD-01) -------------------------------------------------------------------------------------


async def test_trigger_chains_seq_prev_hash_and_event_hash(app_engine: AsyncEngine) -> None:
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    async with rolled_back(app_engine, actor) as conn:
        for n in range(3):
            payload = json.dumps({"n": n, "amount_kes_minor": 150_000, "note": "a|b"})
            await conn.execute(INSERT_EVENT, event_params(chain, actor, payload=payload, subject_type=None))
        chained = list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all())
    assert len(chained) == 3
    assert_linked_chain(chained)


async def test_multi_row_insert_is_chained_in_order(app_engine: AsyncEngine) -> None:
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    first, second = event_params(chain, actor, action="test.first"), event_params(chain, actor, action="test.second")
    values = "(:id{n}, :chain, 'user', :actor, NULL, :action{n}, 'test', :subject_id{n}, '{{}}'::jsonb, 0, '', '')"
    sql = (
        "INSERT INTO audit_events (id, chain_id, actor_kind, actor_user_id, org_id, action, subject_type, subject_id,"
        f" payload, seq, prev_hash, event_hash) VALUES {values.format(n=1)}, {values.format(n=2)}"
    )
    params = {"chain": chain, "actor": actor}
    for n, event in ((1, first), (2, second)):
        params |= {f"id{n}": event["id"], f"action{n}": event["action"], f"subject_id{n}": event["subject_id"]}
    async with rolled_back(app_engine, actor) as conn:
        await conn.execute(sa.text(sql), params)
        chained = list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all())
    assert [row.action for row in chained] == ["test.first", "test.second"]
    assert_linked_chain(chained)


async def test_separator_in_chain_fields_is_rejected(app_engine: AsyncEngine) -> None:
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    async with rolled_back(app_engine, actor) as conn:
        for field in ("chain", "action", "subject_type"):
            params = event_params(chain, actor) | {field: "evil|field"}
            savepoint = await conn.begin_nested()
            with pytest.raises(sa.exc.DBAPIError, match="may not contain"):
                await conn.execute(INSERT_EVENT, params)
            await savepoint.rollback()


async def test_empty_chain_fields_are_rejected_and_scoped_chain_ids_accepted(app_engine: AsyncEngine) -> None:
    actor = uuid7()
    async with rolled_back(app_engine, actor) as conn:
        for overrides in ({"chain": ""}, {"action": ""}, {"subject_type": ""}):
            params = event_params(f"test:{uuid4().hex}", actor) | overrides
            savepoint = await conn.begin_nested()
            with pytest.raises(sa.exc.DBAPIError, match="violates check constraint"):
                await conn.execute(INSERT_EVENT, params)
            await savepoint.rollback()
        for chain in (f"org:{uuid7()}", f"user:{uuid7()}"):  # the app's per-scope chain ids
            await conn.execute(INSERT_EVENT, event_params(chain, actor))
            await conn.execute(INSERT_EVENT, event_params(chain, actor))
            assert_linked_chain(list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all()))


async def test_appends_outside_read_committed_are_refused(app_engine: AsyncEngine) -> None:
    """Under REPEATABLE READ the head read after the lock could be stale, so the trigger refuses by design."""
    for level in ("REPEATABLE READ", "SERIALIZABLE"):
        async with rolled_back(app_engine) as conn:
            await conn.execute(sa.text(f"SET TRANSACTION ISOLATION LEVEL {level}"))
            with pytest.raises(sa.exc.DBAPIError, match=f"must run at READ COMMITTED isolation, not {level}"):
                await conn.execute(INSERT_EVENT, event_params(f"test:{uuid4().hex}", None, actor_kind="system"))


async def test_app_cannot_update_delete_or_truncate_audit_events(app_engine: AsyncEngine) -> None:
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    async with rolled_back(app_engine, actor) as conn:
        await conn.execute(INSERT_EVENT, event_params(chain, actor))
        chain_filter = {"chain": chain}
        await expect_error(
            conn, "UPDATE audit_events SET action = 'x' WHERE chain_id = :chain", "permission denied", chain_filter
        )
        await expect_error(conn, "DELETE FROM audit_events WHERE chain_id = :chain", "permission denied", chain_filter)
        await expect_error(conn, "TRUNCATE audit_events", "permission denied")
        await expect_error(conn, "DELETE FROM event_details", "permission denied")
        await expect_error(conn, "UPDATE consents SET granted = true", "permission denied")
        await expect_error(conn, "DELETE FROM consents", "permission denied")


async def test_triggers_block_update_delete_truncate_even_for_the_owner(owner_engine: AsyncEngine) -> None:
    chain = f"test:{uuid4().hex}"
    params = event_params(chain, None)
    async with rolled_back(owner_engine) as conn:
        await conn.execute(INSERT_EVENT, params)
        await conn.execute(
            sa.text('INSERT INTO event_details (event_id, details) VALUES (:id, \'{"email": "a@example.test"}\')'),
            {"id": params["id"]},
        )
        by_id = {"id": params["id"]}
        await expect_error(conn, "UPDATE audit_events SET action = 'x' WHERE id = :id", "append-only", by_id)
        await expect_error(conn, "DELETE FROM audit_events WHERE id = :id", "append-only", by_id)
        # TRUNCATE audit_events alone stops at the event_details foreign key before any trigger runs; with both tables
        # listed, the audit_events trigger fires first and names its own table.
        await expect_error(
            conn, "TRUNCATE audit_events, event_details", "TRUNCATE on audit_events is not allowed: the audit log"
        )
        await expect_error(conn, "DELETE FROM event_details WHERE event_id = :id", "append-only", by_id)
        await expect_error(conn, "TRUNCATE event_details", "append-only")
        # event_details stays updatable by the owner: erasure overwrites personal data without touching the chain.
        await conn.execute(sa.text("UPDATE event_details SET details = '{}' WHERE event_id = :id"), by_id)
        assert_linked_chain(list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all()))


# pg_trigger.tgtype bits (src/include/catalog/pg_trigger.h).
ROW, BEFORE, ON_INSERT, ON_DELETE, ON_UPDATE, ON_TRUNCATE = 1, 2, 4, 8, 16, 32
AUDIT_TRIGGERS = {
    ("audit_events", "audit_events_chain"): ("audit_events_chain", ROW | BEFORE | ON_INSERT),
    ("audit_events", "audit_events_no_update_delete"): ("audit_block_mutation", ROW | BEFORE | ON_DELETE | ON_UPDATE),
    ("audit_events", "audit_events_no_truncate"): ("audit_block_mutation", BEFORE | ON_TRUNCATE),
    ("event_details", "event_details_no_delete"): ("audit_block_mutation", ROW | BEFORE | ON_DELETE),
    ("event_details", "event_details_no_truncate"): ("audit_block_mutation", BEFORE | ON_TRUNCATE),
}


async def test_audit_triggers_are_installed_and_enabled(owner_engine: AsyncEngine) -> None:
    """Each table's own triggers, checked in the catalog (a statement can only show the first one that fires)."""
    found = await rows(
        owner_engine,
        "SELECT tgrelid::regclass::text AS table_name, tgname, tgfoid::regproc::text AS function, tgtype, tgenabled"
        " FROM pg_trigger WHERE NOT tgisinternal"
        " AND tgrelid IN ('public.audit_events'::regclass, 'public.event_details'::regclass)",
    )
    assert {(row.table_name, row.tgname): (row.function, row.tgtype) for row in found} == AUDIT_TRIGGERS
    assert {row.tgenabled for row in found} == {"O"}  # enabled for ordinary sessions, not disabled or replica-only


async def test_audit_visibility_for_the_app_and_the_reader(owner_engine: AsyncEngine) -> None:
    """One transaction, switching roles with SET LOCAL ROLE (the harness session user is a superuser)."""
    actor, chain = uuid7(), f"test:{uuid4().hex}"
    count = sa.text("SELECT count(*) FROM audit_events WHERE chain_id = :chain")
    details = "INSERT INTO event_details (event_id) VALUES (:id)"
    own, other = event_params(chain, actor), event_params(chain, uuid7())
    async with rolled_back(owner_engine) as conn:
        await conn.execute(INSERT_EVENT, own)
        await conn.execute(INSERT_EVENT, other)

        await conn.execute(sa.text("SET LOCAL ROLE audit_reader"))
        assert (await conn.execute(count, {"chain": chain})).scalar_one() == 2  # the verifier reads every event
        await expect_error(conn, "SELECT count(*) FROM event_details", "permission denied")  # but no personal data
        await expect_error(conn, details, "permission denied", {"id": own["id"]})

        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        assert (await conn.execute(count, {"chain": chain})).scalar_one() == 0  # no tenant context: nothing
        await conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(actor)})
        assert (await conn.execute(count, {"chain": chain})).scalar_one() == 1  # only the actor's own event
        await conn.execute(sa.text(details), {"id": own["id"]})
        await expect_error(conn, details, "row-level security", {"id": other["id"]})  # another user's event
        visible_details = sa.text("SELECT event_id FROM event_details WHERE event_id IN (:own, :other)")
        found = (await conn.execute(visible_details, {"own": own["id"], "other": other["id"]})).scalars().all()
        assert found == [own["id"]]  # reading them follows the event's visibility

        # An organisation's owners and admins see its events, whoever the actor was.
        org_id = uuid7()
        await conn.execute(
            sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Test Admin')"),
            {"id": actor, "email": f"{uuid4().hex}@example.test"},
        )
        await conn.execute(
            sa.text("SELECT app_create_organization(:id, 'sme', 'Org Ltd', CAST(:slug AS citext))"),
            {"id": org_id, "slug": f"org-{uuid4().hex}"},
        )
        await conn.execute(INSERT_EVENT, event_params(chain, None, actor_kind="system", org=org_id))
        assert (await conn.execute(count, {"chain": chain})).scalar_one() == 2


async def test_system_event_and_details_need_no_user(app_engine: AsyncEngine) -> None:
    """A job without app.user_id appends a system event and its details in one transaction."""
    chain = f"test:{uuid4().hex}"
    event = event_params(chain, None, actor_kind="system")
    async with rolled_back(app_engine) as conn:
        await conn.execute(INSERT_EVENT, event)
        await conn.execute(
            sa.text('INSERT INTO event_details (event_id, details) VALUES (:id, \'{"note": "nightly job"}\')'),
            {"id": event["id"]},
        )
        # Written, but not readable without a user who may see it.
        visible = sa.text("SELECT count(*) FROM event_details WHERE event_id = :id")
        assert (await conn.execute(visible, {"id": event["id"]})).scalar_one() == 0


async def test_details_attach_only_to_own_or_actorless_events(owner_engine: AsyncEngine) -> None:
    """app_event_accepts_details(): user A cannot attach details to user B's event (or to a missing event), but can
    to A's own events and to events that name no actor."""
    user_a, user_b, chain = uuid7(), uuid7(), f"test:{uuid4().hex}"
    b_event, a_event = event_params(chain, user_b), event_params(chain, user_a)
    system_event = event_params(chain, None, actor_kind="system")
    details = "INSERT INTO event_details (event_id) VALUES (:id)"
    async with rolled_back(owner_engine) as conn:
        await conn.execute(INSERT_EVENT, b_event)  # written by B's own request earlier
        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        await act_as(conn, user_a)
        await conn.execute(INSERT_EVENT, a_event)
        await conn.execute(INSERT_EVENT, system_event)
        await expect_error(conn, details, "row-level security", {"id": b_event["id"]})
        await expect_error(conn, details, "row-level security", {"id": uuid7()})
        await conn.execute(sa.text(details), {"id": a_event["id"]})
        await conn.execute(sa.text(details), {"id": system_event["id"]})


async def test_events_cannot_name_another_user_as_actor(app_engine: AsyncEngine) -> None:
    """User events name the current user; system events name nobody; staff events name nobody or the current user.
    No kind of event may name another user."""
    actor, other, chain = uuid7(), uuid7(), f"test:{uuid4().hex}"
    refused = [("user", other), ("user", None), ("staff", other), ("system", other), ("system", actor)]
    accepted = [("user", actor), ("staff", actor), ("staff", None), ("system", None)]
    async with rolled_back(app_engine, actor) as conn:
        for kind, named in refused:
            savepoint = await conn.begin_nested()
            with pytest.raises(sa.exc.DBAPIError, match="row-level security"):
                await conn.execute(INSERT_EVENT, event_params(chain, named, actor_kind=kind))
            await savepoint.rollback()
        for kind, named in accepted:
            await conn.execute(INSERT_EVENT, event_params(chain, named, actor_kind=kind))
        await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))  # read the whole chain back
        chained = list((await conn.execute(SELECT_CHAIN, {"chain": chain})).all())
    assert [(row.actor_kind, row.actor_user_id) for row in chained] == accepted
    assert_linked_chain(chained)


# --- Schema v2 (revision 0002): protected columns, evidence triggers (AC-IP-2), the directory policy ----------------


async def test_schema_v2_protected_columns_and_tables_are_not_the_apps(app_engine: AsyncEngine) -> None:
    """What only definer functions, workers, staff or the owner may change: bridge_app is refused by its grants."""
    user_id = uuid7()
    async with rolled_back(app_engine, user_id) as conn:
        await add_user(conn, user_id)
        salt = sa.text("SELECT octet_length(subject_salt) FROM users WHERE id = :id")
        assert (await conn.execute(salt, {"id": user_id})).scalar_one() == 32  # set by the database per user
        for sql in (
            "UPDATE users SET subject_salt = '\\x00'",
            "UPDATE organizations SET verified_domain = 'x.example'",
            "UPDATE organizations SET official_domains = '{}'",
            "UPDATE organizations SET delisted_at = now()",
            "UPDATE organizations SET suspended_at = now()",
            "UPDATE organizations SET e2_verified_at = now()",
            "UPDATE proposals SET moderation_state = 'clear'",
            "UPDATE proposals SET owner_id = owner_id",
            "UPDATE problems SET moderation_state = 'clear'",
            "UPDATE problems SET status = 'published'",
            "UPDATE org_claims SET otp_verified_at = now()",
            "UPDATE org_claims SET reviewed_by = NULL",
            "UPDATE kyc_reviews SET status = 'approved'",
            "UPDATE phone_verifications SET verified_at = now()",
            "UPDATE engagements SET state = 'CLOSED'",
            "UPDATE provenance_records SET status = 'timestamped'",
            "UPDATE attestations SET created_it = true",
            "DELETE FROM nda_acceptances",
            "INSERT INTO provenance_keys (key_id, public_key) VALUES ('k', '\\x00')",
            "SELECT 1 FROM proposal_confidential",
            "SELECT 1 FROM proposal_confidential_embeddings",
            "SELECT 1 FROM signal_events",
            "SELECT 1 FROM chain_anchors",
        ):
            await expect_error(conn, sql, "permission denied")


async def _registered_proposal(conn: AsyncConnection) -> tuple[UUID, UUID, UUID, UUID]:
    """As the owner: (owner, niche, proposal, registered version) of a fresh developer."""
    niche = uuid7()
    await conn.execute(
        sa.text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, 'Evidence')"),
        {"id": niche, "slug": f"evidence-{niche.hex}"},
    )
    owner = await w.add_user(conn, f"{uuid4().hex}@example.test", "Owner")
    problem = await w.add_problem(conn, owner, niche)
    proposal, version = await w.add_proposal(conn, owner, niche, problem)
    return owner, niche, proposal, version


async def test_registered_versions_refuse_update_and_delete(owner_engine: AsyncEngine) -> None:
    """AC-IP-2 (manifest half): the trigger holds for every role, the owner included; only the empty registration
    hashes may be filled, once. Drafts stay editable, and a version is inserted as a draft and registered only with a
    linked problem."""
    h1, h2 = hashlib.sha256(b"manifest-1").digest(), hashlib.sha256(b"manifest-2").digest()
    async with rolled_back(owner_engine) as conn:
        owner, niche, proposal, version = await _registered_proposal(conn)
        by_id = {"id": version}
        for assignment in (
            "title = 'Edited'",
            "summary = 'Edited'",
            "status = 'draft'",
            "cert_id = 'another'",
            "registered_at = now() - interval '1 day'",  # now() itself is the value it was registered with
            "owner_handle = 'someone-else'",
        ):
            await expect_error(conn, f"UPDATE proposal_versions SET {assignment} WHERE id = :id", "immutable", by_id)
        await expect_error(conn, "DELETE FROM proposal_versions WHERE id = :id", "never deleted", by_id)
        await expect_error(conn, "DELETE FROM proposals WHERE id = :id", "never deleted", {"id": proposal})
        fill = "UPDATE proposal_versions SET content_hash = :h, manifest_version = 'm1' WHERE id = :id"
        await conn.execute(sa.text(fill), {"id": version, "h": h1})
        await expect_error(conn, fill, "immutable", {"id": version, "h": h2})
        await expect_error(conn, "UPDATE proposal_versions SET content_hash = NULL WHERE id = :id", "immutable", by_id)
        await expect_error(conn, "TRUNCATE proposal_versions CASCADE", "append-only evidence")

        problem = await w.add_problem(conn, owner, niche)
        draft, draft_version = await w.add_proposal(conn, owner, niche, problem, registered=False)
        await conn.execute(
            sa.text("UPDATE proposal_versions SET title = 'Draft edit' WHERE id = :id"), {"id": draft_version}
        )
        second = uuid7()
        await conn.execute(
            sa.text(
                "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, maturity, ask,"
                " problem_statement, summary, owner_handle)"
                " VALUES (:id, :p, 2, 'T', :n, 'idea', 'pilot', 'P', 'S', 'h')"
            ),
            {"id": second, "p": draft, "n": niche},
        )
        await expect_error(
            conn,
            "UPDATE proposal_versions SET status = 'registered', cert_id = :c, registered_at = now() WHERE id = :id",
            "at least one linked problem",
            {"id": second, "c": uuid4().hex[:16]},
        )
        await expect_error(
            conn,
            "INSERT INTO proposal_versions (id, proposal_id, version_no, status) VALUES (:id, :p, 3, 'registered')",
            "inserted as a draft",
            {"id": uuid7(), "p": draft},
        )
        await conn.execute(sa.text("DELETE FROM proposal_versions WHERE id = :id"), {"id": second})  # drafts may go


async def test_tier2_of_a_registered_version_is_frozen_except_the_manifest(owner_engine: AsyncEngine) -> None:
    async with rolled_back(owner_engine) as conn:
        owner, niche, _proposal, version = await _registered_proposal(conn)
        by_id = {"id": version}
        await expect_error(
            conn, "UPDATE proposal_confidential SET ciphertext = '\\x09' WHERE version_id = :id", "immutable", by_id
        )
        await expect_error(conn, "DELETE FROM proposal_confidential WHERE version_id = :id", "never deleted", by_id)
        await expect_error(
            conn,
            "UPDATE proposal_confidential SET manifest_ciphertext = '\\x0a' WHERE version_id = :id",
            "manifest_pair",
            by_id,
        )
        fill = "UPDATE proposal_confidential SET manifest_ciphertext = :m, manifest_nonce = :n WHERE version_id = :id"
        await conn.execute(sa.text(fill), {"id": version, "m": b"\x0a", "n": b"\x0b"})
        await expect_error(conn, fill, "immutable", {"id": version, "m": b"\x0c", "n": b"\x0d"})
        # A draft's Tier 2 stays editable; Tier 2 always belongs to the version's owner and proposal.
        problem = await w.add_problem(conn, owner, niche)
        _draft, draft_version = await w.add_proposal(conn, owner, niche, problem, registered=False)
        await conn.execute(
            sa.text("UPDATE proposal_confidential SET ciphertext = '\\x09' WHERE version_id = :id"),
            {"id": draft_version},
        )
        stranger = await w.add_user(conn, f"{uuid4().hex}@example.test", "Stranger")
        await expect_error(
            conn,
            "UPDATE proposal_confidential SET owner_id = :u WHERE version_id = :id",
            "never change",
            {"id": draft_version, "u": stranger},
        )


async def test_provenance_records_only_fill_empty_columns_and_move_forward(owner_engine: AsyncEngine) -> None:
    async with rolled_back(owner_engine) as conn:
        _owner, _niche, _proposal, version = await _registered_proposal(conn)
        key_id, record = f"test-{uuid4().hex[:8]}", uuid7()
        await conn.execute(
            sa.text("INSERT INTO provenance_keys (key_id, public_key) VALUES (:k, :pk)"), {"k": key_id, "pk": bytes(32)}
        )
        await conn.execute(
            sa.text("INSERT INTO provenance_records (id, version_id, cert_id, content_hash) VALUES (:id, :v, :c, :h)"),
            {"id": record, "v": version, "c": uuid4().hex[:16], "h": ZERO_HASH},
        )
        by_id = {"id": record}
        sign = "UPDATE provenance_records SET signature = '\\x01', key_id = :k, status = 'signed' WHERE id = :id"
        await conn.execute(sa.text(sign), {"id": record, "k": key_id})
        refused = "only empty signature"
        await expect_error(conn, "UPDATE provenance_records SET status = 'hashed' WHERE id = :id", refused, by_id)
        await conn.execute(sa.text("SET LOCAL ROLE provenance_worker"))  # the worker that fills the TSA columns
        await conn.execute(
            sa.text(
                "UPDATE provenance_records SET tsa_token = '\\x02', tsa_time = now(), tsa_serial = '42',"
                " tsa_url = 'https://tsa.example.test', status = 'timestamped' WHERE id = :id"
            ),
            by_id,
        )
        await expect_error(
            conn, "UPDATE provenance_records SET content_hash = '\\x00' WHERE id = :id", "permission denied", by_id
        )
        await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))
        for assignment in ("tsa_token = '\\x03'", "signature = '\\x04'", "content_hash = '\\x05'", "cert_id = 'x'"):
            await expect_error(conn, f"UPDATE provenance_records SET {assignment} WHERE id = :id", refused, by_id)
        await expect_error(conn, "DELETE FROM provenance_records WHERE id = :id", "never deleted", by_id)
        await expect_error(conn, "TRUNCATE provenance_records", "append-only evidence")


async def test_append_only_evidence_refuses_update_and_delete_even_for_the_owner(owner_engine: AsyncEngine) -> None:
    async with rolled_back(owner_engine) as conn:
        owner, _niche, _proposal, version = await _registered_proposal(conn)
        await conn.execute(
            sa.text(
                "INSERT INTO attestations (id, user_id, version_id, created_it, not_owned_by_employer_or_client,"
                " no_third_party_confidential, text_version, text_sha256)"
                " VALUES (:id, :u, :v, true, true, true, 'v1', :h)"
            ),
            {"id": uuid7(), "u": owner, "v": version, "h": ZERO_HASH},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO chain_anchors (id, chain_id, seq, event_hash, tsa_token, tsa_time, tsa_serial)"
                " VALUES (:id, 'global', 1, :h, '\\x01', now(), '1')"
            ),
            {"id": uuid7(), "h": ZERO_HASH},
        )
        for table in ("attestations", "chain_anchors"):
            await expect_error(conn, f"UPDATE {table} SET id = id", "append-only evidence")
            await expect_error(conn, f"DELETE FROM {table}", "append-only evidence")


# pg_trigger.tgtype bits: see AUDIT_TRIGGERS.
V2_APPEND_ONLY = ("attestations", "nda_acceptances", "legal_acceptances", "chain_anchors", "transparency_roots")
V2_TRIGGERS = {
    ("proposal_versions", "proposal_versions_guard"): (
        "proposal_versions_guard",
        ROW | BEFORE | ON_INSERT | ON_DELETE | ON_UPDATE,
    ),
    ("proposal_confidential", "proposal_confidential_guard"): (
        "proposal_confidential_guard",
        ROW | BEFORE | ON_INSERT | ON_DELETE | ON_UPDATE,
    ),
    ("provenance_records", "provenance_records_guard"): (
        "provenance_records_guard",
        ROW | BEFORE | ON_DELETE | ON_UPDATE,
    ),
    **{(t, f"{t}_no_update_delete"): ("block_mutation", ROW | BEFORE | ON_DELETE | ON_UPDATE) for t in V2_APPEND_ONLY},
    **{
        (t, f"{t}_no_truncate"): ("block_mutation", BEFORE | ON_TRUNCATE)
        for t in (*V2_APPEND_ONLY, "proposal_versions", "proposal_confidential", "provenance_records")
    },
}


async def test_every_trigger_is_installed_and_enabled(owner_engine: AsyncEngine) -> None:
    """The complete set of triggers on Bridge tables (Procrastinate's own are left to its schema)."""
    found = await rows(
        owner_engine,
        "SELECT c.relname AS table_name, t.tgname, t.tgfoid::regproc::text AS function, t.tgtype, t.tgenabled"
        " FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid WHERE NOT t.tgisinternal"
        " AND c.relnamespace = 'public'::regnamespace AND c.relname NOT LIKE 'procrastinate%'",
    )
    assert {(row.table_name, row.tgname): (row.function, row.tgtype) for row in found} == AUDIT_TRIGGERS | V2_TRIGGERS
    assert {row.tgenabled for row in found} == {"O"}


async def test_listed_organisations_are_readable_by_every_signed_in_user(owner_engine: AsyncEngine) -> None:
    """The directory: unclaimed, E1 and E2 organisations that are not delisted, and their niches, are readable by
    every signed-in user; pending self-signup organisations of others, rejected and delisted ones are not."""
    async with rolled_back(owner_engine) as conn:
        viewer, creator = uuid7(), uuid7()
        await add_user(conn, viewer)
        await add_user(conn, creator)
        niche = uuid7()
        await conn.execute(
            sa.text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, 'Directory')"),
            {"id": niche, "slug": f"dir-{niche.hex}"},
        )
        orgs: dict[str, UUID] = {}
        for name, verification, source, delisted in (
            ("unclaimed", "unclaimed", "seed", False),
            ("e1", "e1", "seed", False),
            ("e2", "e2", "self_signup", False),
            ("pending", "pending", "self_signup", False),
            ("rejected", "rejected", "self_signup", False),
            ("delisted", "unclaimed", "seed", True),
        ):
            orgs[name] = uuid7()
            await conn.execute(
                sa.text(
                    "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, created_by,"
                    " delisted_at) VALUES (:id, 'company', :name, :slug, CAST(:source AS org_source),"
                    " CAST(:verification AS org_verification), :creator, CASE WHEN :delisted THEN now() END)"
                ),
                {
                    "id": orgs[name],
                    "name": name,
                    "slug": f"{name}-{uuid4().hex}",
                    "source": source,
                    "verification": verification,
                    "creator": creator,
                    "delisted": delisted,
                },
            )
            await conn.execute(
                sa.text("INSERT INTO org_niches (org_id, niche_id) VALUES (:org, :niche)"),
                {"org": orgs[name], "niche": niche},
            )
        listed = {orgs["unclaimed"], orgs["e1"], orgs["e2"]}
        ids = {"ids": list(orgs.values())}
        visible_orgs = sa.text("SELECT id FROM organizations WHERE id = ANY (:ids)")
        visible_niches = sa.text("SELECT org_id FROM org_niches WHERE org_id = ANY (:ids)")
        await conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        assert set((await conn.execute(visible_orgs, ids)).scalars()) == set()  # not signed in: nothing
        await act_as(conn, viewer)
        assert set((await conn.execute(visible_orgs, ids)).scalars()) == listed
        assert set((await conn.execute(visible_niches, ids)).scalars()) == listed
        edit = sa.text("UPDATE organizations SET website = 'https://evil.example' WHERE id = ANY (:ids)")
        assert (await conn.execute(edit, ids)).rowcount == 0  # readable is not writable


# --- Procrastinate ------------------------------------------------------------------------------------------------


def test_vendored_procrastinate_schema_matches_the_installed_package() -> None:
    assert version("procrastinate") == "3.10.0", "procrastinate changed: add a revision with its migrations"
    vendored = (BACKEND / "alembic" / "versions" / "sql" / "procrastinate_3.10.0_schema.sql").read_text("utf-8")
    assert vendored.replace("\r\n", "\n") == SchemaManager.get_schema().replace("\r\n", "\n")


async def test_app_can_defer_fetch_and_finish_a_job(app_engine: AsyncEngine) -> None:
    async with rolled_back(app_engine) as conn:
        deferred = (
            await conn.execute(
                sa.text(
                    "SELECT procrastinate_defer_jobs_v1(ARRAY[ROW('bridge_test', 'bridge.test', 0, NULL, NULL,"
                    " '{}'::jsonb, NULL)::procrastinate_job_to_defer_v1])"
                )
            )
        ).scalar_one()
        worker = (await conn.execute(sa.text("SELECT worker_id FROM procrastinate_register_worker_v1()"))).scalar_one()
        fetched = (
            await conn.execute(
                sa.text("SELECT id FROM procrastinate_fetch_job_v2(ARRAY['bridge_test']::varchar[], :w)"),
                {"w": worker},
            )
        ).scalar_one()
        assert fetched == deferred[0]
        await conn.execute(sa.text("SELECT procrastinate_finish_job_v1(:j, 'succeeded', false)"), {"j": fetched})
        status = sa.text("SELECT status::text FROM procrastinate_jobs WHERE id = :j")
        assert (await conn.execute(status, {"j": fetched})).scalar_one() == "succeeded"
