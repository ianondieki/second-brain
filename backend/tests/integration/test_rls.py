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

from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, NamedTuple
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


# Each case breaks exactly one condition of app_tier2_granted(), except the TIER2_READABLE ones: "none" breaks nothing
# and "met_by_the_approved_claimant" meets the terms condition the other way (the reviewer reads the row).
TIER2_CASES = (
    "none",
    "met_by_the_approved_claimant",
    "no_grant",
    "grant_requested",
    "grant_revoked",
    "org_not_e2",
    "org_suspended",
    "role_viewer",
    "membership_removed",
    "off_domain_member",
    "no_totp",
    "user_suspended",
    "no_master_enterprise_terms",
    "met_by_a_non_signatory",
    "met_by_an_unapproved_claimant",
    "met_superseded",
    "no_nda",
    "nda_for_another_proposal",
    "engagement_withdrawn",
    "engagement_declined",
    "engagement_terminated",
    "proposal_hidden",
    "proposal_held",
    "context_of_another_org",
)
TIER2_READABLE = frozenset({"none", "met_by_the_approved_claimant"})


async def _add_user(conn: AsyncConnection, email: str, *, status: str = "active", totp: bool = True) -> UUID:
    user = uuid7()
    await _sql(
        conn,
        "INSERT INTO users (id, email, display_name, status, totp_enabled_at) VALUES (:id, :email, 'Member',"
        " CAST(:status AS user_status), :totp)",
        id=user,
        email=email,
        status=status,
        totp=datetime.now(UTC) if totp else None,
    )
    return user


async def _add_member(conn: AsyncConnection, org: UUID, user: UUID, roles: str, status: str = "active") -> None:
    await _sql(
        conn,
        "INSERT INTO memberships (id, org_id, user_id, roles, status) VALUES (:id, :org, :user,"
        " CAST(:roles AS org_role[]), CAST(:status AS membership_status))",
        id=uuid7(),
        org=org,
        user=user,
        roles=roles,
        status=status,
    )


async def _add_master_terms(conn: AsyncConnection, tag: str) -> UUID:
    """A new, so current, version of the Master Enterprise Terms."""
    template = uuid7()
    await _sql(
        conn,
        "INSERT INTO legal_templates (id, kind, version, body, sha256) VALUES (:id, 'master_enterprise_terms',"
        " :version, :body, sha256(convert_to(:body, 'UTF8')))",
        id=template,
        version=f"g-{tag}-{template.hex[-6:]}",
        body=f"[[LEGAL-PLACEHOLDER:met-{template.hex}]]\n",
    )
    return template


async def _accept_master_terms(conn: AsyncConnection, org: UUID, broken: str, tag: str) -> None:
    """As the owner: G's current Master Enterprise Terms, accepted by a signatory of G unless ``broken`` says
    otherwise (nobody; an outsider (and the reviewer); the approved or a still-pending E2 claimant, an owner and admin
    but no signatory; or a version superseded since)."""
    terms = await _add_master_terms(conn, tag)
    if broken == "no_master_enterprise_terms":
        return
    acceptor = await _add_user(conn, f"acceptor-{tag}@example.test")
    if broken in ("met_by_the_approved_claimant", "met_by_an_unapproved_claimant"):
        await _add_member(conn, org, acceptor, "{owner,admin}")  # what approval makes the claimant; no signatory
        await _sql(
            conn,
            "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status)"
            " VALUES (:id, :org, :user, :domain, :email, 'e2', CAST(:status AS claim_status))",
            id=uuid7(),
            org=org,
            user=acceptor,
            domain=f"granted-{tag}.example.test",
            email=f"acceptor-{tag}@granted-{tag}.example.test",
            status="approved" if broken == "met_by_the_approved_claimant" else "pending_review",
        )
    elif broken != "met_by_a_non_signatory":
        await _add_member(conn, org, acceptor, "{signatory}")
    await _sql(
        conn,
        "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
        " SELECT :id, :org, :user, id, sha256 FROM legal_templates WHERE id = :template",
        id=uuid7(),
        org=org,
        user=acceptor,
        template=terms,
    )
    if broken == "met_superseded":
        await _add_master_terms(conn, tag)


class GrantScenario(NamedTuple):
    reviewer: UUID
    context: UUID  # the organisation the reviewer's request is scoped to (app.org_id)
    draft_version: UUID  # the next version of B's published proposal, still a draft (Tier 0)


async def _grant_scenario(conn: AsyncConnection, world: w.World, broken: str) -> GrantScenario:
    """As the owner: an E2 org G with a verified domain whose reviewer R (an address at that domain) may read B's
    published Tier 2, except for ``broken``. B's published proposal also has a draft next version with its own Tier-2
    row, which no grant ever opens (drafts are Tier 0: owner only)."""
    b, tag = world.b, uuid7().hex[:12]
    draft_version = uuid7()
    await _sql(
        conn,
        "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, maturity, ask, problem_statement,"
        " summary, owner_handle) VALUES (:id, :proposal, 2, 'Next version', :niche, 'idea', 'pilot', 'A problem',"
        " 'What it does', 'rls-handle')",
        id=draft_version,
        proposal=b.published,
        niche=world.niche_id,
    )
    await _sql(
        conn,
        "INSERT INTO proposal_confidential (version_id, proposal_id, owner_id, ciphertext, nonce, wrapped_dek,"
        " kms_key_id) VALUES (:version, :proposal, :owner, '\\x04', '\\x05', '\\x06', 'local:test')",
        version=draft_version,
        proposal=b.published,
        owner=b.user_id,
    )
    await _sql(
        conn, "UPDATE proposals SET draft_version_id = :version WHERE id = :id", version=draft_version, id=b.published
    )
    domain = f"granted-{tag}.example.test"  # G's verified domain
    reviewer = await _add_user(
        conn,
        f"reviewer-{tag}@{'elsewhere.example.test' if broken == 'off_domain_member' else domain}",
        status="suspended" if broken == "user_suspended" else "active",
        totp=broken != "no_totp",
    )
    org = uuid7()
    await _sql(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, verified_domain, suspended_at)"
        " VALUES (:id, 'company', 'Granted Ltd', :slug, 'seed', CAST(:verification AS org_verification), :domain,"
        " CASE WHEN :suspended THEN now() END)",
        id=org,
        slug=f"granted-{tag}",
        domain=domain,
        verification="e1" if broken == "org_not_e2" else "e2",
        suspended=broken == "org_suspended",
    )
    await _add_member(
        conn,
        org,
        reviewer,
        "{viewer}" if broken == "role_viewer" else "{reviewer}",
        "removed" if broken == "membership_removed" else "active",
    )
    await _accept_master_terms(conn, org, broken, tag)
    if broken == "met_by_a_non_signatory":  # the reviewer accepts too, next to the outsider
        await _sql(
            conn,
            "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
            " SELECT :id, :org, :user, legal_template_id, template_sha256 FROM legal_acceptances WHERE org_id = :org",
            id=uuid7(),
            org=org,
            user=reviewer,
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
    if broken == "none":  # nor does a live grant open a draft proposal: its row stays hidden
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
    return GrantScenario(reviewer, context, draft_version)


@pytest.mark.parametrize("broken", TIER2_CASES)
async def test_tier2_needs_every_condition_of_a_live_grant(
    owner_engine: AsyncEngine, world: w.World, broken: str
) -> None:
    """An organisation without a live grant reads 0 proposal_confidential rows even as tier2_reader (AC-SEC-1/b);
    with every condition met its reviewer reads the registered version's row, never a draft's: neither the draft
    version (Tier 0) nor its Tier-2 row."""
    async with rolled_back(owner_engine) as conn:
        scenario = await _grant_scenario(conn, world, broken)
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await _as_tenant(conn, scenario.reviewer, scenario.context)
        draft = await conn.execute(
            text("SELECT count(*) FROM proposal_versions WHERE id = :id"), {"id": scenario.draft_version}
        )
        assert draft.scalar_one() == 0
        await _as_tenant(conn, scenario.reviewer, scenario.context, "proposal_confidential")
        assert (await conn.execute(text("SELECT current_user"))).scalar_one() == "tier2_reader"
        rows = await conn.execute(
            text("SELECT version_id FROM proposal_confidential WHERE owner_id = :b"), {"b": world.b.user_id}
        )
        expected = [world.b.published_version] if broken in TIER2_READABLE else []
        assert list(rows.scalars()) == expected


async def test_the_owner_reads_their_tier2_through_tier2_reader(app_engine: AsyncEngine, world: w.World) -> None:
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.b.user_id, None, "proposal_confidential")
        rows = await conn.execute(
            text("SELECT count(*) FROM proposal_confidential WHERE owner_id = :b"), {"b": world.b.user_id}
        )
        assert rows.scalar_one() == 4


# --- every Tier-2 role, bound to one developer --------------------------------------------------------------------

# docs/spec/06 6.1. Jobs bind the user they act for (app.user_id: one tenant per job).
TIER2_ROLES = ("dsr_exporter", "provenance_worker", "tier2_embed_worker", "tier2_moderation", "tier2_reader")
TIER2_INSERT = (
    "INSERT INTO proposal_confidential (version_id, proposal_id, owner_id, ciphertext, nonce, wrapped_dek, kms_key_id)"
    " VALUES (:version, :proposal, :owner, '\\x01', '\\x02', '\\x03', 'local:test')"
)
EMBEDDING_INSERT = (
    "INSERT INTO proposal_confidential_embeddings (version_id, embed_model, embed_version, full_embedding)"
    f" VALUES (:version, 'rls-role-test', '1', {w.VECTOR_1024})"
)


async def _tier2_owners(conn: AsyncConnection) -> Counter[UUID]:
    return Counter((await conn.execute(text("SELECT owner_id FROM proposal_confidential"))).scalars())


async def _refused_by_rls(conn: AsyncConnection, sql: str, **params: object) -> None:
    savepoint = await conn.begin_nested()
    with pytest.raises(ProgrammingError, match="row-level security"):
        await conn.execute(text(sql), params)
    await savepoint.rollback()


async def _next_draft_version(conn: AsyncConnection, proposal: UUID) -> UUID:
    """As the owner: a second, draft version of ``proposal`` without a Tier-2 row yet."""
    version = uuid7()
    await _sql(
        conn, "INSERT INTO proposal_versions (id, proposal_id, version_no) VALUES (:id, :p, 2)", id=version, p=proposal
    )
    return version


@pytest.mark.parametrize("role", TIER2_ROLES)
async def test_every_tier2_role_bound_to_developer_a_reads_and_writes_none_of_b(
    owner_engine: AsyncEngine, world: w.World, role: str
) -> None:
    """Each role of the Tier-2 set, bound to developer A, reads and updates 0 of developer B's proposal_confidential
    rows and writes none of B's full-text embeddings, while the roles that act for an owner do read and write A's own
    rows (so no policy is merely closed). tier2_moderation reads nothing without a staff context, A's rows included,
    and everything with one. The UPDATE without WHERE touches exactly the rows the UPDATE policy admits (no SELECT
    policy applies to it), so an UPDATE policy opened to ``true`` fails the count."""
    a, b = world.a, world.b
    async with rolled_back(owner_engine) as conn:
        a_next, b_next = await _next_draft_version(conn, a.draft), await _next_draft_version(conn, b.draft)
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await _as_tenant(conn, a.user_id, None)
        await conn.execute(text(f"SET LOCAL ROLE {role}"))
        assert (await conn.execute(text("SELECT current_user"))).scalar_one() == role
        seen = await _tier2_owners(conn)
        if role == "tier2_moderation":
            assert seen == Counter(), "tier2_moderation read Tier 2 without a staff context"
        else:
            assert seen[b.user_id] == 0, f"{role} bound to A read B's Tier 2"
            assert seen[a.user_id] == 4, f"{role} bound to A cannot read A's own Tier 2"
        if role in ("tier2_reader", "provenance_worker"):
            touched = await conn.execute(text("UPDATE proposal_confidential SET updated_at = now()"))
            assert touched.rowcount == 4, f"{role} bound to A updated rows that are not A's"
            for version in (b.draft_version, b.published_version):
                targeted = await conn.execute(
                    text("UPDATE proposal_confidential SET updated_at = now() WHERE version_id = :v"), {"v": version}
                )
                assert targeted.rowcount == 0
        if role == "tier2_reader":
            await _refused_by_rls(conn, TIER2_INSERT, version=b_next, proposal=b.draft, owner=b.user_id)
            await _sql(conn, TIER2_INSERT, version=a_next, proposal=a.draft, owner=a.user_id)
        if role == "tier2_embed_worker":
            await _refused_by_rls(conn, EMBEDDING_INSERT, version=b.published_version)
            await _sql(conn, EMBEDDING_INSERT, version=a.published_version)
        if role == "tier2_moderation":
            embeddings = text("SELECT version_id FROM proposal_confidential_embeddings")
            assert list((await conn.execute(embeddings)).scalars()) == []
            await conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(world.staff_id)})
            seen = await _tier2_owners(conn)
            assert (seen[a.user_id], seen[b.user_id]) == (4, 4)
            assert {a.published_version, b.published_version} <= set((await conn.execute(embeddings)).scalars())


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
