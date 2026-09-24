"""AC-SEC-1/a (REQ-TEN-01, REQ-AUTH-01): tenant isolation on every org- or user-scoped table that exists in Phase 1.

Generated from table metadata: every table whose ``tenancy`` is org, user or org_or_user is tested, and a tenant
table without a fixture in ``world.TENANT_ROWS`` fails the run. A member of org A reads 0 rows of org B (with and
without an org context), and a cross-tenant API access returns 404. The full AC-SEC-1 (Tier 2, drafts,
aggregate_worker over signal_events) is re-run at the Phase 2 exit.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import bridge.models.all  # noqa: F401  # registers every table
from bridge.models import Base, Tenancy
from tests.integration import world as w

TENANT_KINDS = {Tenancy.ORG, Tenancy.USER, Tenancy.ORG_OR_USER}
TENANT_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") in TENANT_KINDS)


def test_every_table_declares_its_tenancy() -> None:
    undeclared = [t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") not in set(Tenancy)]
    assert undeclared == []


def test_every_tenant_table_has_an_rls_fixture() -> None:
    assert sorted(w.TENANT_ROWS) == TENANT_TABLES


@pytest.fixture(scope="module")
async def world(owner_engine: AsyncEngine) -> w.World:
    async with owner_engine.begin() as conn:
        return await w.build(conn, "rls")


async def _as_tenant(conn: AsyncConnection, user_id: UUID, org_id: UUID | None) -> None:
    await conn.execute(
        text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
        {"u": str(user_id), "o": str(org_id) if org_id else ""},
    )


@pytest.mark.parametrize("table", TENANT_TABLES)
@pytest.mark.parametrize("with_org_context", [True, False])
async def test_member_of_org_a_reads_no_row_of_org_b(
    app_engine: AsyncEngine, world: w.World, table: str, with_org_context: bool
) -> None:
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, world.a.org_id if with_org_context else None)
        rows = (await conn.execute(text(w.TENANT_ROWS[table]))).all()
    leaked = [r for r in rows if r.org == world.b.org_id or r.usr == world.b.user_id]
    assert leaked == [], f"{table}: tenant A can read tenant B's rows"
    own = [r for r in rows if r.org == world.a.org_id or r.usr == world.a.user_id]
    assert own, f"{table}: tenant A cannot read its own rows (policy too strict or fixture missing)"


@pytest.mark.parametrize("table", TENANT_TABLES)
async def test_no_tenant_context_reads_nothing(app_engine: AsyncEngine, world: w.World, table: str) -> None:
    async with app_engine.connect() as conn, conn.begin():
        rows = (await conn.execute(text(w.TENANT_ROWS[table]))).all()
    assert rows == [], f"{table}: rows visible without app.user_id"


async def test_org_context_cannot_be_forged_for_a_foreign_org(app_engine: AsyncEngine, world: w.World) -> None:
    """Setting app.org_id to org B does not help user A: policies also require membership."""
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, world.b.org_id)
        for table in TENANT_TABLES:
            rows = (await conn.execute(text(w.TENANT_ROWS[table]))).all()
            assert [r for r in rows if r.org == world.b.org_id or r.usr == world.b.user_id] == [], table


async def test_org_b_rows_cannot_be_updated_or_deleted_by_a(app_engine: AsyncEngine, world: w.World) -> None:
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, None)
        updated = await conn.execute(
            text("UPDATE organizations SET website = 'https://evil.example' WHERE id = :id"), {"id": world.b.org_id}
        )
        deleted = await conn.execute(text("DELETE FROM memberships WHERE org_id = :id"), {"id": world.b.org_id})
        assert (updated.rowcount, deleted.rowcount) == (0, 0)
        await conn.rollback()


async def test_aggregate_worker_reads_no_tenant_table(aggregate_engine: AsyncEngine) -> None:
    for table in TENANT_TABLES:
        async with aggregate_engine.connect() as conn:
            with pytest.raises(ProgrammingError, match="permission denied"):
                await conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))


# ---------------------------------------------------------------- cross-tenant API access returns 404


@pytest.fixture(scope="module")
async def client(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    from tests.integration.api import make_client

    async with make_client(app_engine) as c:
        yield c


async def test_cross_tenant_api_access_is_404(
    client: httpx.AsyncClient, app_engine: AsyncEngine, world: w.World
) -> None:
    from tests.integration.api import sign_in_as

    await sign_in_as(client, app_engine, world.a.user_id, mfa_verified=True)
    await _enable_totp_marker(app_engine, world)
    own = await client.get(f"/api/orgs/{world.a.org_id}")
    foreign = await client.get(f"/api/orgs/{world.b.org_id}")
    foreign_members = await client.get(f"/api/orgs/{world.b.org_id}/members")
    assert own.status_code == 200, own.text
    assert foreign.status_code == 404
    assert foreign_members.status_code == 404
    assert foreign.json()["detail"]["code"] == "not_found"


async def _enable_totp_marker(app_engine: AsyncEngine, world: w.World) -> None:
    """Owners must have TOTP; mark user A as enrolled so the org route checks tenancy, not MFA."""
    async with app_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET totp_enabled_at = now() WHERE id = :id"), {"id": world.a.user_id})
