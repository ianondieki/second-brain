"""Revision 0001 (REQ-TEN-01, REQ-AUD-01, REQ-CON-01; docs/spec/08 Migrations and Tenancy).

Migration round trip and drift, table classification, RLS coverage generated from the ORM metadata, grants and role
attributes, the RLS helper functions, the append-only hash-chained audit log and the Procrastinate schema.
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
from tests.integration.conftest import BACKEND, create_database, drop_database, role_engine, run_alembic

TABLES = Base.metadata.tables
TENANT_KINDS = {Tenancy.ORG, Tenancy.USER, Tenancy.ORG_OR_USER}
ROLES = ("bridge_owner", "bridge_app", "aggregate_worker", "audit_reader")
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")

# The grant matrix of bridge_app (task card T1.4 and review). Every other privilege on every ORM table must be absent.
# UPDATE on users and organizations is column-scoped (APP_COLUMN_UPDATES).
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
    "organizations": {"legal_name", "website", "regions", "registration_no", "sector_id", "country", "updated_at"},
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
}

# (signature, SECURITY DEFINER?) of the helper functions bridge_app may execute.
APP_FUNCTIONS = (
    ("uuid7()", False),
    ("app_user_id()", False),
    ("app_org_id()", False),
    ("app_is_member(uuid, org_role[])", True),
    ("app_create_organization(uuid, org_kind, text, citext, text)", True),
    ("app_event_accepts_details(uuid)", True),
)
TRIGGER_FUNCTIONS = (("audit_events_chain()", True), ("audit_block_mutation()", False))
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
    return sorted(name for name, table in TABLES.items() if tenancy(table) in TENANT_KINDS)


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


def test_upgrade_downgrade_upgrade_without_drift(scratch_url: URL) -> None:
    run_alembic(scratch_url, lambda config: command.upgrade(config, "head"))
    run_alembic(scratch_url, command.check)  # raises AutogenerateDiffsDetected on drift from the ORM
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
    if tenancy(TABLES[table]) in TENANT_KINDS:
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
async def test_every_command_granted_to_the_app_has_a_policy(owner_engine: AsyncEngine, table: str) -> None:
    holds = "SELECT " + HOLDS_PRIVILEGE.format(r="'bridge_app'", t="CAST(:t AS text)", p="CAST(:p AS text)")
    for privilege in (S, I, U, D):
        if await scalar(owner_engine, holds, t=table, p=privilege):
            policies = await scalar(
                owner_engine,
                "SELECT count(*) FROM pg_policies WHERE schemaname = 'public' AND tablename = :t"
                " AND cmd IN (:p, 'ALL') AND 'bridge_app' = ANY (roles)",
                t=table,
                p=privilege,
            )
            assert policies >= 1, f"bridge_app may {privilege} {table} but no policy covers it"


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
    assert not {"staff_role", "status", "email"} & updatable["users"]
    assert not {"verification", "slug", "kind", "source", "public_entity"} & updatable["organizations"]


async def test_bridge_app_cannot_update_protected_columns(app_engine: AsyncEngine) -> None:
    user_id = uuid7()
    async with rolled_back(app_engine, user_id) as conn:
        await add_user(conn, user_id)
        await conn.execute(sa.text("UPDATE users SET display_name = 'Renamed' WHERE id = :id"), {"id": user_id})
        for column, value in (("staff_role", "'admin'"), ("status", "'suspended'"), ("email", "'x@example.test'")):
            await expect_error(
                conn, f"UPDATE users SET {column} = {value} WHERE id = :id", "permission denied", {"id": user_id}
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


async def test_aggregate_worker_has_no_privilege_on_any_table(owner_engine: AsyncEngine) -> None:
    assert await privileges_of(owner_engine, "aggregate_worker") == {}


async def test_audit_reader_reads_only_the_audit_chain(owner_engine: AsyncEngine) -> None:
    assert await privileges_of(owner_engine, "audit_reader") == {"audit_events": {S}}


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


@pytest.mark.parametrize("role", ["bridge_app", "aggregate_worker", "audit_reader"])
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


@pytest.mark.parametrize(("signature", "definer"), APP_FUNCTIONS + TRIGGER_FUNCTIONS)
async def test_helper_functions_are_locked_down(owner_engine: AsyncEngine, signature: str, definer: bool) -> None:
    (row,) = await rows(
        owner_engine,
        "SELECT prosecdef, proconfig, pg_get_userbyid(proowner) AS owner FROM pg_proc"
        " WHERE oid = to_regprocedure(:sig)",
        sig=signature,
    )
    assert row.prosecdef is definer
    assert row.owner == "bridge_owner"
    assert row.proconfig == [PINNED_SEARCH_PATH]
    callers = {"bridge_app"} if (signature, definer) in APP_FUNCTIONS else set()
    for role in ("public", "bridge_app", "aggregate_worker", "audit_reader"):
        allowed = await scalar(
            owner_engine, "SELECT has_function_privilege(:r, :sig, 'EXECUTE')", r=role, sig=signature
        )
        assert allowed is (role in callers), f"{role} EXECUTE {signature}"


async def test_every_function_pins_search_path_with_pg_temp_last(owner_engine: AsyncEngine) -> None:
    """Every function of the revision (helpers, triggers, Procrastinate's), not only the listed helpers."""
    found = await rows(
        owner_engine,
        "SELECT p.oid::regprocedure::text AS signature, p.proconfig FROM pg_proc p"
        " WHERE p.pronamespace = 'public'::regnamespace AND NOT EXISTS (SELECT 1 FROM pg_depend d"
        " WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')",
    )
    assert len(found) > len(APP_FUNCTIONS) + len(TRIGGER_FUNCTIONS)  # includes procrastinate_*
    unpinned = sorted(row.signature for row in found if row.proconfig != [PINNED_SEARCH_PATH])
    assert unpinned == []


@pytest.mark.parametrize("role", ["bridge_app", "aggregate_worker", "audit_reader"])
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
            sa.text("SELECT user_id, roles::text[] AS roles, status::text AS status FROM memberships WHERE org_id = :org"),
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
