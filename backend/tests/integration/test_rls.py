"""AC-SEC-1/a and AC-SEC-1/b (REQ-TEN-01, REQ-REPO-01, REQ-AUTH-01): tenant isolation on every tenant table.

Generated from table metadata: every table whose tenancy is org, user, org_or_user or published is tested with the
two-tenant world (``world.TENANT_ROWS``), every staff table with the staff fixtures (``world.STAFF_ROWS``), and a
tenant table without a fixture fails the run. Tables read on the request path by another role than ``bridge_app``
(``info["db_role"]``: the Tier-2 tables) are read as that role, as the application does after ``as_role``.

- A member of org A reads 0 rows of org B, with and without an org context, and a forged org context does not help.
- PUBLISHED tables: A reads B's published, clear rows but none of B's drafts, held, hidden or candidate rows, and all
  of A's own; staff admin/moderator read everything.
- STAFF tables: a non-staff user reads 0 rows; staff read them.
- Developer A reads 0 of developer B's drafts, versions and Tier-2 rows; an organisation without a live grant reads 0
  ``proposal_confidential`` rows even as ``tier2_reader``, and removing any single condition of the database half of
  can_view_tier2 (``app_tier2_granted``) hides the row again.
- ``aggregate_worker`` reads 0 rows of every tenant table (no privilege at all) and reads ``signal_events``.
- A cross-tenant API access returns 404.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import bridge.models.all  # noqa: F401  # registers every table
from bridge.ids import uuid7
from bridge.models import Base, Tenancy
from bridge.models.base import RLS_TENANCIES
from tests.integration import world as w

TABLES = Base.metadata.tables
TENANT_KINDS = {Tenancy.ORG, Tenancy.USER, Tenancy.ORG_OR_USER, Tenancy.PUBLISHED}
TENANT_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") in TENANT_KINDS)
STAFF_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") == Tenancy.STAFF)
PUBLISHED_TABLES = sorted(t for t in TENANT_TABLES if TABLES[t].info["tenancy"] == Tenancy.PUBLISHED)
RLS_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") in RLS_TENANCIES)


def test_every_table_declares_its_tenancy() -> None:
    undeclared = [t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") not in set(Tenancy)]
    assert undeclared == []


def test_every_tenant_table_has_an_rls_fixture() -> None:
    assert sorted(w.TENANT_ROWS) == TENANT_TABLES
    assert sorted(w.STAFF_ROWS) == STAFF_TABLES
    assert sorted(TENANT_TABLES + STAFF_TABLES) == RLS_TABLES


@pytest.fixture(scope="module")
async def world(owner_engine: AsyncEngine) -> w.World:
    async with owner_engine.begin() as conn:
        return await w.build(conn, "rls")


@pytest.fixture(scope="module")
async def owners(owner_engine: AsyncEngine, world: w.World) -> dict[str, list[sa.Row[Any]]]:
    """Every fixture row of every tenant table with its owning org, user and public flag, read without RLS."""
    async with owner_engine.connect() as conn:
        return {table: list((await conn.execute(text(rows.owners))).all()) for table, rows in w.TENANT_ROWS.items()}


async def _as_tenant(
    conn: AsyncConnection, user_id: UUID | None, org_id: UUID | None, table: str | None = None
) -> None:
    """Scope the transaction to a user (and org) and, for a table read by another role, switch to that role."""
    await conn.execute(
        text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
        {"u": str(user_id) if user_id else "", "o": str(org_id) if org_id else ""},
    )
    role = TABLES[table].info.get("db_role") if table else None
    if role:
        await conn.execute(text(f"SET LOCAL ROLE {role}"))


async def _visible(conn: AsyncConnection, table: str, rows: w.Rows) -> set[str]:
    return set((await conn.execute(text(f"SELECT {rows.key} AS key FROM {table}"))).scalars())


def _owned_by(row: sa.Row[Any], tenant: w.Tenant) -> bool:
    return bool(row.org == tenant.org_id or row.usr == tenant.user_id)


@pytest.mark.parametrize("table", TENANT_TABLES)
@pytest.mark.parametrize("with_org_context", [True, False])
async def test_tenant_a_reads_only_its_own_and_public_rows_of_b(
    app_engine: AsyncEngine,
    world: w.World,
    owners: dict[str, list[sa.Row[Any]]],
    table: str,
    with_org_context: bool,
) -> None:
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, world.a.org_id if with_org_context else None, table)
        visible = await _visible(conn, table, w.TENANT_ROWS[table])
    b_rows = [r for r in owners[table] if _owned_by(r, world.b)]
    a_rows = [r for r in owners[table] if _owned_by(r, world.a)]
    assert b_rows, f"{table}: no fixture row of tenant B"
    assert a_rows, f"{table}: no fixture row of tenant A"
    leaked = [r.key for r in b_rows if not r.pub and r.key in visible]
    assert leaked == [], f"{table}: tenant A can read tenant B's private rows"
    hidden_public = [r.key for r in b_rows if r.pub and r.key not in visible]
    assert hidden_public == [], f"{table}: tenant A cannot read tenant B's published rows"
    hidden_own = [r.key for r in a_rows if r.key not in visible]
    assert hidden_own == [], f"{table}: tenant A cannot read its own rows (policy too strict)"
    if table in PUBLISHED_TABLES:  # both halves of the rule are exercised
        assert {r.pub for r in b_rows} == {True, False}, f"{table}: fixture needs public and private rows of B"


@pytest.mark.parametrize("table", RLS_TABLES)
async def test_no_tenant_context_reads_nothing(app_engine: AsyncEngine, world: w.World, table: str) -> None:
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, None, None, table)
        count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
    assert count == 0, f"{table}: rows visible without app.user_id"


async def test_org_context_cannot_be_forged_for_a_foreign_org(
    app_engine: AsyncEngine, world: w.World, owners: dict[str, list[sa.Row[Any]]]
) -> None:
    """Setting app.org_id to org B does not help user A: policies also require membership."""
    for table in TENANT_TABLES:
        async with app_engine.connect() as conn, conn.begin():
            await _as_tenant(conn, world.a.user_id, world.b.org_id, table)
            visible = await _visible(conn, table, w.TENANT_ROWS[table])
        leaked = [r.key for r in owners[table] if _owned_by(r, world.b) and not r.pub and r.key in visible]
        assert leaked == [], table


@pytest.mark.parametrize("table", STAFF_TABLES)
async def test_staff_tables_are_read_by_staff_only(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, world: w.World, table: str
) -> None:
    rows = w.STAFF_ROWS[table]
    async with owner_engine.connect() as conn:
        fixture = set((await conn.execute(text(rows.owners))).scalars())
    assert len(fixture) >= 2, f"{table}: no staff fixture rows"
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, world.a.org_id, table)
        assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0, "non-staff read a row"
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.staff_id, None, table)
        assert fixture <= await _visible(conn, table, rows), f"{table}: staff cannot read the queue"


@pytest.mark.parametrize("table", PUBLISHED_TABLES)
async def test_staff_read_every_published_table_row(
    app_engine: AsyncEngine, world: w.World, owners: dict[str, list[sa.Row[Any]]], table: str
) -> None:
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.staff_id, None, table)
        visible = await _visible(conn, table, w.TENANT_ROWS[table])
    fixture = {r.key for r in owners[table] if _owned_by(r, world.a) or _owned_by(r, world.b)}
    assert fixture <= visible


async def test_org_b_rows_cannot_be_updated_by_a(app_engine: AsyncEngine, world: w.World) -> None:
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, None)
        updated = await conn.execute(
            text("UPDATE organizations SET website = 'https://evil.example' WHERE id = :id"), {"id": world.b.org_id}
        )
        removed = await conn.execute(
            text("UPDATE memberships SET status = 'removed' WHERE org_id = :id"), {"id": world.b.org_id}
        )
        proposals = await conn.execute(
            text("UPDATE proposals SET title = 'Taken' WHERE owner_id = :id"), {"id": world.b.user_id}
        )
        versions = await conn.execute(
            text("UPDATE proposal_versions SET title = 'Taken' WHERE proposal_id = :id"), {"id": world.b.draft}
        )
        grants = await conn.execute(
            text("UPDATE disclosure_grants SET status = 'active' WHERE owner_id = :id"), {"id": world.b.user_id}
        )
        assert [r.rowcount for r in (updated, removed, proposals, versions, grants)] == [0] * 5
        await conn.rollback()


async def test_a_cannot_write_into_b_proposals(app_engine: AsyncEngine, world: w.World) -> None:
    """New rows must belong to the writer: a version, a problem link, a tag or a grant on B's proposal is refused."""
    statements = (
        (
            "INSERT INTO proposal_versions (id, proposal_id, version_no) VALUES (:id, :proposal, 99)",
            {"id": uuid7(), "proposal": world.b.draft},
        ),
        (
            "INSERT INTO tags (id, proposal_id, org_id, developer_id, status)"
            " VALUES (:id, :proposal, :org, :user, 'held_unclaimed')",
            {"id": uuid7(), "proposal": world.b.published, "org": world.a.org_id, "user": world.a.user_id},
        ),
        (
            "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source)"
            " VALUES (:id, :proposal, :org, :owner, 2, 'active', 'manual')",
            {"id": uuid7(), "proposal": world.b.published, "org": world.a.org_id, "owner": world.b.user_id},
        ),
    )
    for sql, params in statements:
        async with app_engine.connect() as conn, conn.begin():
            await _as_tenant(conn, world.a.user_id, world.a.org_id)
            with pytest.raises(ProgrammingError, match="row-level security"):
                await conn.execute(text(sql), params)


# --- AC-SEC-1/b: drafts, versions and Tier 2 ---------------------------------------------------------------------


async def test_developer_a_reads_none_of_developer_b_drafts_versions_or_tier2(
    app_engine: AsyncEngine, world: w.World
) -> None:
    b = world.b
    private = [b.draft, b.held, b.hidden]
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, None)
        proposals = (
            await conn.execute(text("SELECT id FROM proposals WHERE owner_id = :b"), {"b": b.user_id})
        ).scalars()
        assert set(proposals) == {b.published}  # none of the draft, held or hidden ones
        versions = await conn.execute(
            text("SELECT id FROM proposal_versions WHERE proposal_id = ANY (:ids)"), {"ids": [*private, b.published]}
        )
        assert set(versions.scalars()) == {b.published_version}
        await conn.execute(text("SET LOCAL ROLE tier2_reader"))
        tier2 = await conn.execute(
            text("SELECT count(*) FROM proposal_confidential WHERE owner_id = :b"), {"b": b.user_id}
        )
        assert tier2.scalar_one() == 0
        own = await conn.execute(
            text("SELECT count(*) FROM proposal_confidential WHERE owner_id = :a"), {"a": world.a.user_id}
        )
        assert own.scalar_one() == 4  # the owner reads all of their own Tier 2, drafts included


@asynccontextmanager
async def rolled_back(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()


async def _sql(conn: AsyncConnection, sql: str, **params: object) -> None:
    await conn.execute(text(sql), params)


# Each case breaks exactly one condition of app_tier2_granted(); "none" breaks nothing (the reviewer reads the row).
TIER2_CASES = (
    "none",
    "no_grant",
    "grant_requested",
    "grant_revoked",
    "org_not_e2",
    "org_suspended",
    "role_viewer",
    "membership_removed",
    "no_totp",
    "user_suspended",
    "no_master_enterprise_terms",
    "no_nda",
    "nda_for_another_proposal",
    "engagement_withdrawn",
    "engagement_declined",
    "engagement_terminated",
    "proposal_hidden",
    "proposal_held",
    "context_of_another_org",
)


async def _grant_scenario(conn: AsyncConnection, world: w.World, broken: str) -> tuple[UUID, UUID]:
    """As the owner: an E2 org G whose reviewer R may read B's published Tier 2, except for ``broken``."""
    b, tag = world.b, uuid7().hex[:12]
    reviewer = uuid7()
    await _sql(
        conn,
        "INSERT INTO users (id, email, display_name, status, totp_enabled_at) VALUES (:id, :email, 'Reviewer',"
        " CAST(:status AS user_status), :totp)",
        id=reviewer,
        email=f"reviewer-{tag}@example.test",
        status="suspended" if broken == "user_suspended" else "active",
        totp=None if broken == "no_totp" else datetime.now(UTC),
    )
    org = uuid7()
    await _sql(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, suspended_at)"
        " VALUES (:id, 'company', 'Granted Ltd', :slug, 'seed', CAST(:verification AS org_verification),"
        " CASE WHEN :suspended THEN now() END)",
        id=org,
        slug=f"granted-{tag}",
        verification="e1" if broken == "org_not_e2" else "e2",
        suspended=broken == "org_suspended",
    )
    await _sql(
        conn,
        "INSERT INTO memberships (id, org_id, user_id, roles, status) VALUES (:id, :org, :user,"
        " CAST(:roles AS org_role[]), CAST(:status AS membership_status))",
        id=uuid7(),
        org=org,
        user=reviewer,
        roles="{viewer}" if broken == "role_viewer" else "{reviewer}",
        status="removed" if broken == "membership_removed" else "active",
    )
    if broken != "no_master_enterprise_terms":
        await _sql(
            conn,
            "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
            " SELECT :id, :org, :user, id, sha256 FROM legal_templates WHERE id = :template",
            id=uuid7(),
            org=org,
            user=reviewer,
            template=world.met_template_id,
        )
    if broken != "no_nda":
        await _sql(
            conn,
            "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
            " logging_notice_version) SELECT :id, :user, :org, :proposal, id, sha256, 'v1' FROM nda_templates"
            " WHERE id = :template",
            id=uuid7(),
            user=reviewer,
            org=org,
            proposal=b.held if broken == "nda_for_another_proposal" else b.published,
            template=world.nda_template_id,
        )
    grants = [] if broken == "no_grant" else [b.published]
    if broken == "none":  # a live grant never opens a draft (Tier 0): the draft's row stays hidden
        grants.append(b.draft)
        await _sql(
            conn,
            "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
            " logging_notice_version) SELECT :id, :user, :org, :proposal, id, sha256, 'v1' FROM nda_templates"
            " WHERE id = :template",
            id=uuid7(),
            user=reviewer,
            org=org,
            proposal=b.draft,
            template=world.nda_template_id,
        )
    for proposal in grants:
        await _sql(
            conn,
            "INSERT INTO disclosure_grants (id, proposal_id, org_id, owner_id, tier, status, source, revoked_at)"
            " VALUES (:id, :proposal, :org, :owner, 2, CAST(:status AS grant_status), 'manual',"
            " CASE WHEN :revoked THEN now() END)",
            id=uuid7(),
            proposal=proposal,
            org=org,
            owner=b.user_id,
            status={"grant_requested": "requested", "grant_revoked": "revoked"}.get(broken, "active"),
            revoked=broken == "grant_revoked",
        )
    ended = {
        "engagement_withdrawn": "WITHDRAWN",
        "engagement_declined": "DECLINED",
        "engagement_terminated": "TERMINATED",
    }
    if broken in ended:
        await _sql(
            conn,
            "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state, end_reason)"
            " VALUES (:id, :proposal, :org, :dev, :version, 'tagged', CAST(:state AS engagement_state),"
            " CAST(:reason AS engagement_end_reason))",
            id=uuid7(),
            proposal=b.published,
            org=org,
            dev=b.user_id,
            version=b.published_version,
            state=ended[broken],
            reason="NOT_PRIORITY" if broken == "engagement_declined" else None,
        )
    if broken == "proposal_hidden":
        await _sql(conn, "UPDATE proposals SET status = 'hidden' WHERE id = :id", id=b.published)
    if broken == "proposal_held":
        await _sql(conn, "UPDATE proposals SET moderation_state = 'held' WHERE id = :id", id=b.published)
    context = org
    if broken == "context_of_another_org":  # the reviewer also belongs to org A and scopes the request to it
        await _sql(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, '{reviewer}')",
            id=uuid7(),
            org=world.a.org_id,
            user=reviewer,
        )
        context = world.a.org_id
    return reviewer, context


@pytest.mark.parametrize("broken", TIER2_CASES)
async def test_tier2_needs_every_condition_of_a_live_grant(
    owner_engine: AsyncEngine, world: w.World, broken: str
) -> None:
    """An organisation without a live grant reads 0 proposal_confidential rows even as tier2_reader (AC-SEC-1/b);
    with every condition met its reviewer reads the registered version's row (never a draft's)."""
    async with rolled_back(owner_engine) as conn:
        reviewer, context = await _grant_scenario(conn, world, broken)
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await _as_tenant(conn, reviewer, context, "proposal_confidential")
        assert (await conn.execute(text("SELECT current_user"))).scalar_one() == "tier2_reader"
        rows = await conn.execute(
            text("SELECT version_id FROM proposal_confidential WHERE owner_id = :b"), {"b": world.b.user_id}
        )
        expected = [world.b.published_version] if broken == "none" else []
        assert list(rows.scalars()) == expected


async def test_the_owner_reads_their_tier2_through_tier2_reader(app_engine: AsyncEngine, world: w.World) -> None:
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.b.user_id, None, "proposal_confidential")
        rows = await conn.execute(
            text("SELECT count(*) FROM proposal_confidential WHERE owner_id = :b"), {"b": world.b.user_id}
        )
        assert rows.scalar_one() == 4


# --- aggregate_worker ------------------------------------------------------------------------------------------------


async def test_aggregate_worker_reads_no_tenant_table(aggregate_engine: AsyncEngine) -> None:
    for table in RLS_TABLES:
        async with aggregate_engine.connect() as conn:
            with pytest.raises(ProgrammingError, match="permission denied"):
                await conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))


async def test_aggregate_worker_reads_signal_events_the_app_can_only_write(owner_engine: AsyncEngine) -> None:
    item = uuid7()
    async with rolled_back(owner_engine) as conn:
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await _sql(
            conn,
            "INSERT INTO signal_events (id, item_id, kind, actor_hash) VALUES (:id, :item, 'proposal.published', :h)",
            id=uuid7(),
            item=item,
            h=bytes(32),
        )
        savepoint = await conn.begin_nested()
        with pytest.raises(ProgrammingError, match="permission denied"):
            await conn.execute(text("SELECT 1 FROM signal_events"))
        await savepoint.rollback()
        await conn.execute(text("SET LOCAL ROLE aggregate_worker"))
        found = await conn.execute(text("SELECT kind FROM signal_events WHERE item_id = :item"), {"item": item})
        assert list(found.scalars()) == ["proposal.published"]


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
