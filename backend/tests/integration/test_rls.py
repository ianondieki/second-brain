"""AC-SEC-1/a and AC-SEC-1/b (REQ-TEN-01, REQ-REPO-01, REQ-AUTH-01): tenant isolation on every tenant table.

Generated from table metadata: every table whose tenancy is org, user, org_or_user or published is tested with the
two-tenant world (``world.TENANT_ROWS``), every staff table with the staff fixtures (``world.STAFF_ROWS``), and a
tenant table without a fixture fails the run. Tables read on the request path by another role than ``bridge_app``
(``info["db_role"]``: the Tier-2 tables) are read as that role, as the application does after ``as_role``.

- A member of org A reads 0 rows of org B, with and without an org context, and a forged org context does not help.
- PUBLISHED tables: A reads B's published, clear rows but none of B's drafts, held, hidden or candidate rows, and all
  of A's own; staff admin/moderator read everything.
- STAFF tables: a non-staff user reads 0 rows; staff read them.
- EVIDENCE (``provenance_records``): readable without a signed-in user (``/verify``); provenance_worker bound to A
  reads and writes only records of A's versions.
- Developer A reads 0 of developer B's drafts, versions and Tier-2 rows; an organisation without a live grant reads 0
  ``proposal_confidential`` rows even as ``tier2_reader``, and removing any single condition of the database half of
  can_view_tier2 (``app_tier2_granted``) hides the row again; a draft version of a granted proposal stays hidden.
- Every Tier-2 role bound to developer A reads and updates 0 of B's Tier-2 rows and writes none of B's embeddings;
  tier2_moderation reads nothing without a staff context.
- ``aggregate_worker`` reads 0 rows of every tenant table (no privilege at all) and reads ``signal_events``.
- Engagement notes (revision 0006, REQ-ENG-10): both parties and staff admin read them, nobody else does; only the
  actor of the engagement's latest event writes its one note, of the kind its transition is; nothing is ever updated
  or deleted. In-app notifications (REQ-NOT-03): a user marks only their own read and changes nothing else. Problem
  Briefs (REQ-DIR-05): a draft Brief awaiting review is unreadable to developers; approval publishes it; a closed
  public Brief stays readable.
- The expiry job's list (revision 0007, ``app_engagements_due_for_expiry``): only a session with no user bound reads
  it, and it learns only developer and engagement ids, of the engagements the clock may act on.
- CURATED tables (revision 0009, the quiz's sets and questions, ``world.CURATED_ROWS``): staff admin reads every row,
  a developer the approved ones, an account without a developer profile none.
- A cross-tenant API access returns 404.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, NamedTuple
from uuid import UUID
from zoneinfo import ZoneInfo

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
from tests.integration.engagements import tracker as t

TABLES = Base.metadata.tables
TENANT_KINDS = {Tenancy.ORG, Tenancy.USER, Tenancy.ORG_OR_USER, Tenancy.PUBLISHED}
TENANT_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") in TENANT_KINDS)
STAFF_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") == Tenancy.STAFF)
EVIDENCE_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") == Tenancy.EVIDENCE)
PUBLISHED_TABLES = sorted(t for t in TENANT_TABLES if TABLES[t].info["tenancy"] == Tenancy.PUBLISHED)
CURATED_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") == Tenancy.CURATED)
RLS_TABLES = sorted(t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") in RLS_TENANCIES)


def test_every_table_declares_its_tenancy() -> None:
    undeclared = [t.name for t in Base.metadata.sorted_tables if t.info.get("tenancy") not in set(Tenancy)]
    assert undeclared == []


def test_every_tenant_table_has_an_rls_fixture() -> None:
    assert sorted(w.TENANT_ROWS) == TENANT_TABLES
    assert sorted(w.STAFF_ROWS) == STAFF_TABLES
    assert sorted(w.CURATED_ROWS) == CURATED_TABLES
    assert EVIDENCE_TABLES == ["provenance_records"]  # a new EVIDENCE table needs its own writer test below
    assert sorted(TENANT_TABLES + STAFF_TABLES + EVIDENCE_TABLES + CURATED_TABLES) == RLS_TABLES


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


@pytest.mark.parametrize("table", sorted(set(RLS_TABLES) - set(EVIDENCE_TABLES)))  # evidence is public (/verify)
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


@pytest.mark.parametrize("table", CURATED_TABLES)
async def test_curated_tables_are_read_by_staff_admin_and_by_developers_once_approved(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, world: w.World, table: str
) -> None:
    """Revision 0009 (REQ-DEV-01): staff admin reads every fixture row; a developer (tenant A, who also owns an
    organisation) reads the approved set's rows and none of the rejected one's; a signed-in account without a developer
    profile (an organisation-only account) reads no row at all."""
    rows = w.CURATED_ROWS[table]
    async with owner_engine.connect() as conn:
        fixture = {row.key: row.pub for row in (await conn.execute(text(rows.owners))).all()}
    assert set(fixture.values()) == {True, False}, f"{table}: fixture needs approved and unapproved rows"
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.staff_id, None, table)
        assert set(fixture) <= await _visible(conn, table, rows), f"{table}: staff admin cannot read the queue"
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, world.a.org_id, table)
        visible = await _visible(conn, table, rows)
    assert {key for key, pub in fixture.items() if pub} <= visible, f"{table}: a developer cannot read approved rows"
    assert not {key for key, pub in fixture.items() if not pub} & visible, f"{table}: a developer reads a rejected row"
    async with rolled_back(owner_engine) as conn:
        org_only = await _add_user(conn, f"org-only-{uuid7().hex}@example.test")
        await _add_member(conn, world.a.org_id, org_only, "{viewer}")
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await _as_tenant(conn, org_only, world.a.org_id, table)
        assert (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0


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
        bands = await conn.execute(  # B's originality buckets, published proposal included (readable, not A's)
            text("DELETE FROM proposal_lsh_bands WHERE proposal_id = ANY (:ids)"),
            {"ids": [world.b.published, world.b.draft]},
        )
        assert [r.rowcount for r in (updated, removed, proposals, versions, grants, bands)] == [0] * 6
        await conn.rollback()


async def test_a_cannot_write_into_b_proposals(app_engine: AsyncEngine, world: w.World) -> None:
    """New rows must belong to the writer: a version, a tag, a grant or an originality bucket of B's proposal is
    refused."""
    statements = (
        (
            "INSERT INTO proposal_lsh_bands (proposal_id, band, bucket) VALUES (:proposal, 99, 1)",
            {"proposal": world.b.published},
        ),
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
    "email_unverified",
    "no_totp",
    "user_suspended",
    "no_master_enterprise_terms",
    "met_by_a_non_signatory",
    "met_by_an_unapproved_claimant",
    "met_superseded",
    "no_nda",
    "nda_for_another_proposal",
    "nda_superseded",
    "engagement_withdrawn",
    "engagement_declined",
    "engagement_terminated",
    "proposal_hidden",
    "proposal_held",
    "context_of_another_org",
)
TIER2_READABLE = frozenset({"none", "met_by_the_approved_claimant"})


async def _add_user(
    conn: AsyncConnection, email: str, *, status: str = "active", totp: bool = True, email_verified: bool = True
) -> UUID:
    user, now = uuid7(), datetime.now(UTC)
    await _sql(
        conn,
        "INSERT INTO users (id, email, display_name, status, totp_enabled_at, email_verified_at) VALUES (:id, :email,"
        " 'Member', CAST(:status AS user_status), :totp, :verified)",
        id=user,
        email=email,
        status=status,
        totp=now if totp else None,
        verified=now if email_verified else None,
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


async def _add_evaluation_nda(conn: AsyncConnection, tag: str) -> UUID:
    """A new, so current, version of the Evaluation NDA (its legal body and its nda_templates row)."""
    legal, template = uuid7(), uuid7()
    await _sql(
        conn,
        "INSERT INTO legal_templates (id, kind, version, body, sha256) VALUES (:id, 'evaluation_nda', :version, :body,"
        " sha256(convert_to(:body, 'UTF8')))",
        id=legal,
        version=f"n-{tag}-{legal.hex[-6:]}",
        body=f"[[LEGAL-PLACEHOLDER:nda-{legal.hex}]]\n",
    )
    await _sql(
        conn,
        "INSERT INTO nda_templates (id, kind, version, legal_template_id, sha256)"
        " SELECT :id, 'evaluation', :version, id, sha256 FROM legal_templates WHERE id = :legal",
        id=template,
        version=f"n-{tag}-{template.hex[-6:]}",
        legal=legal,
    )
    return template


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
        " summary) VALUES (:id, :proposal, 2, 'Next version', :niche, 'idea', 'pilot', 'A problem', 'What it does')",
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
        email_verified=broken != "email_unverified",
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
    nda = await _add_evaluation_nda(conn, tag)  # the current Evaluation NDA
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
            template=nda,
        )
    if broken == "nda_superseded":  # a new NDA version needs a new acceptance
        await _add_evaluation_nda(conn, tag)
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
            template=nda,
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


VIEW_INSERT = (
    "INSERT INTO document_views (id, proposal_id, version_id, owner_id, viewer_user_id, org_id, render_kind,"
    " fingerprint_seed, started_at, nda_acceptance_id) VALUES (:id, :p, :v, :owner, :viewer, :org, 'html', :seed,"
    " now() - interval '30 days', :nda)"
)
# As the owner: the reviewer's acceptance of the Evaluation NDA for B's published proposal under G, copied for another
# user or organisation.
COPY_NDA = (
    "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
    " logging_notice_version) SELECT :id, :user, :org, proposal_id, nda_template_id, template_sha256,"
    " logging_notice_version FROM nda_acceptances WHERE user_id = :reviewer AND org_id = :g AND proposal_id = :p"
)


@pytest.mark.parametrize("broken", ["none", "no_grant", "no_nda"])
async def test_only_a_granted_viewer_logs_a_view_under_the_granting_org(
    owner_engine: AsyncEngine, world: w.World, broken: str
) -> None:
    """A Tier-2 view is logged only by a viewer the grant lets read that registered version (app_tier2_granted), under
    the organisation holding the grant: a member without it cannot plant views in the owner's "Who has seen this", nor
    log a granted view under another organisation of theirs or on a draft; the start time is the database's. The NDA
    acceptance a view names is the viewer's own, for that proposal, under that organisation (round 5): not a
    colleague's, not one for another proposal, not one under another organisation of the viewer's."""
    b = world.b
    async with rolled_back(owner_engine) as conn:
        scenario = await _grant_scenario(conn, world, broken)
        await _add_member(conn, world.a.org_id, scenario.reviewer, "{reviewer}")  # also a reviewer of org A
        ndas: dict[str, UUID] = {}
        if broken == "none":
            colleague = await _add_user(conn, f"colleague-{uuid7().hex[-12:]}@example.test")
            await _add_member(conn, scenario.context, colleague, "{reviewer}")
            source = {"reviewer": scenario.reviewer, "g": scenario.context, "p": b.published}
            copies = (("colleague", colleague, scenario.context), ("another_org", scenario.reviewer, world.a.org_id))
            for name, user, org in copies:
                ndas[name] = uuid7()
                await _sql(conn, COPY_NDA, id=ndas[name], user=user, org=org, **source)
            own = await conn.execute(  # the scenario's: for B's published proposal and for B's draft proposal
                text("SELECT proposal_id, id FROM nda_acceptances WHERE user_id = :u AND org_id = :g"),
                {"u": scenario.reviewer, "g": scenario.context},
            )
            accepted = dict(own.tuples().all())
            ndas["own"], ndas["another_proposal"] = accepted[b.published], accepted[b.draft]
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await _as_tenant(conn, scenario.reviewer, None)
        view = {"p": b.published, "owner": b.user_id, "viewer": scenario.reviewer, "seed": bytes(16), "nda": None}
        registered = view | {"v": b.published_version}
        await _refused_by_rls(conn, VIEW_INSERT, id=uuid7(), org=world.a.org_id, **registered)
        await _refused_by_rls(conn, VIEW_INSERT, id=uuid7(), org=scenario.context, **view, v=scenario.draft_version)
        if broken != "none":
            await _refused_by_rls(conn, VIEW_INSERT, id=uuid7(), org=scenario.context, **registered)
            return
        for name in ("colleague", "another_proposal", "another_org"):
            await _refused_by_rls(
                conn, VIEW_INSERT, id=uuid7(), org=scenario.context, **(registered | {"nda": ndas[name]})
            )
        logged = uuid7()
        await _sql(conn, VIEW_INSERT, id=logged, org=scenario.context, **(registered | {"nda": ndas["own"]}))
        started = await conn.execute(
            text("SELECT started_at = now() FROM document_views WHERE id = :id"), {"id": logged}
        )
        assert started.scalar_one() is True  # the backdated start was replaced


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


# --- EVIDENCE: provenance_records ---------------------------------------------------------------------------------

RECORD_INSERT = (
    "INSERT INTO provenance_records (id, version_id, cert_id, content_hash) VALUES (:id, :version, :cert, :hash)"
)


async def test_registration_records_are_public_and_written_only_for_the_bound_owner(
    owner_engine: AsyncEngine, world: w.World
) -> None:
    """/verify reads every record without a signed-in user. The registration job (provenance_worker) bound to
    developer A reads, inserts and updates only records of A's versions: none of B's, and none of A's draft (only a
    registered version is evidence)."""
    a, b = world.a, world.b
    b_record = uuid7()
    async with rolled_back(owner_engine) as conn:
        certs = await conn.execute(
            text("SELECT id, cert_id FROM proposal_versions WHERE id = ANY (:ids)"),
            {"ids": [a.published_version, b.published_version]},
        )
        cert = {row.id: row.cert_id for row in certs.all()}  # a record carries its version's cert_id
        await _sql(
            conn,
            RECORD_INSERT,
            id=b_record,
            version=b.published_version,
            cert=cert[b.published_version],
            hash=bytes(32),
        )
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await _as_tenant(conn, None, None)
        public = await conn.execute(text("SELECT id FROM provenance_records WHERE id = :id"), {"id": b_record})
        assert list(public.scalars()) == [b_record]  # anonymous /verify
        await _as_tenant(conn, a.user_id, None)
        await conn.execute(text("SET LOCAL ROLE provenance_worker"))
        for version in (b.published_version, a.draft_version):
            await _refused_by_rls(
                conn, RECORD_INSERT, id=uuid7(), version=version, cert=uuid7().hex[:16], hash=bytes(32)
            )
        a_record = uuid7()
        await _sql(
            conn,
            RECORD_INSERT,
            id=a_record,
            version=a.published_version,
            cert=cert[a.published_version],
            hash=bytes(32),
        )
        seen = await conn.execute(text("SELECT id FROM provenance_records"))
        assert list(seen.scalars()) == [a_record]
        touched = await conn.execute(text("UPDATE provenance_records SET tsa_url = 'https://tsa.example.test'"))
        assert touched.rowcount == 1  # no WHERE: the UPDATE policy alone admits A's record only
        targeted = await conn.execute(
            text("UPDATE provenance_records SET tsa_url = 'https://tsa.example.test' WHERE id = :id"), {"id": b_record}
        )
        assert targeted.rowcount == 0


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


# --- revision 0006: the side states' notes and marking in-app notifications read -----------------------------------

NOTE = (
    "INSERT INTO engagement_notes (id, engagement_id, event_seq, kind, body, resume_at, created_by)"
    " VALUES (:id, :e, :seq, :kind, :body, :resume_at, :by)"
)
COUNT_NOTES = "SELECT count(*) FROM engagement_notes WHERE engagement_id = :e"
RESUME_AT = date(2027, 1, 29)


def _note(
    engagement: UUID, seq: int, kind: str, by: UUID, *, resume_at: date | None = None, body: str = "Which counties?"
) -> dict[str, object]:
    return {"id": uuid7(), "e": engagement, "seq": seq, "kind": kind, "body": body, "resume_at": resume_at, "by": by}


async def test_engagement_notes_are_written_by_the_events_actor_and_read_by_both_parties(
    owner_engine: AsyncEngine,
) -> None:
    """Given an engagement and its two parties, When the organisation requests information, the developer answers
    and either side pauses and resumes, Then each note is written only by its event's actor, as themselves, while the
    event is the latest, with the kind of its transition, once; both parties and staff admin read the notes, a
    stranger reads none; and no role updates, deletes or truncates them."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.act(conn, p.developer)
        engagement = await t.engage(conn, p)
        await t.act(conn, p.owner, p.org)  # seq 2: the organisation asks
        await t.append(conn, engagement, p.owner, "owner", "request_info", "SUBMITTED", "INFO_REQUESTED")
        await t.run(conn, NOTE, **_note(engagement, 2, "info_request", p.owner))
        rls, hidden = "row-level security", "no engagement of the caller's with that id"
        stale = "only while its event is the engagement's latest"  # engagement_notes_1_latest_event
        for actor, org, params, refusal in (
            (p.owner, p.org, _note(engagement, 2, "info_request", p.signatory), rls),  # as someone else
            (p.owner, p.org, _note(engagement, 2, "hold", p.owner, resume_at=RESUME_AT), rls),  # not the kind's
            (p.owner, p.org, _note(engagement, 2, "info_answer", p.owner), rls),
            (p.signatory, p.org, _note(engagement, 2, "info_request", p.signatory), rls),  # not the event's actor
            (p.developer, None, _note(engagement, 2, "info_answer", p.developer), rls),
            (p.staff, None, _note(engagement, 2, "info_request", p.staff), rls),
            (p.outsider, None, _note(engagement, 2, "info_request", p.outsider), hidden),
            (p.other_member, p.other_org, _note(engagement, 2, "info_request", p.other_member), hidden),
            (p.owner, p.org, _note(engagement, 2, "info_request", p.owner), "duplicate key"),  # one note per event
            (p.owner, p.org, _note(engagement, 1, "info_request", p.owner), stale),  # the genesis takes none
        ):
            await t.act(conn, actor, org)
            await t.expect(conn, NOTE, refusal, **params)
        await t.act(conn, p.developer)  # seq 3: the developer answers
        await t.append(conn, engagement, p.developer, "developer", "answer_info", "INFO_REQUESTED", "SUBMITTED")
        for params, constraint in (
            (_note(engagement, 3, "info_answer", p.developer, body="  "), "ck_engagement_notes_body_length"),
            (_note(engagement, 3, "info_answer", p.developer, body="x" * 2001), "ck_engagement_notes_body_length"),
            (
                _note(engagement, 3, "info_answer", p.developer, resume_at=RESUME_AT),
                "ck_engagement_notes_resume_at_only_for_hold",
            ),
        ):
            await t.expect(conn, NOTE, constraint, **params)
        await t.run(conn, NOTE, **_note(engagement, 3, "info_answer", p.developer, body="Nairobi and Kisumu."))
        await t.append(conn, engagement, p.developer, "developer", "pause", "SUBMITTED", "ON_HOLD")  # seq 4
        await t.expect(
            conn, NOTE, "ck_engagement_notes_resume_at_only_for_hold", **_note(engagement, 4, "hold", p.developer)
        )
        await t.append(conn, engagement, p.developer, "developer", "resume", "ON_HOLD", "SUBMITTED")  # seq 5
        late = _note(engagement, 4, "hold", p.developer, resume_at=RESUME_AT)
        await t.expect(conn, NOTE, stale, **late)  # its event is no longer the latest
        await t.run(conn, NOTE, **_note(engagement, 5, "resume", p.developer, body="Budget approved early."))
        await t.act(conn, p.owner, p.org)  # seq 6: the organisation pauses, its event written inside a savepoint
        async with conn.begin_nested():  # (and after the rolled-back savepoints above): still this transaction's
            await t.append(conn, engagement, p.owner, "owner", "pause", "SUBMITTED", "ON_HOLD")
        await t.run(conn, NOTE, **_note(engagement, 6, "hold", p.owner, resume_at=RESUME_AT, body="Board meets."))
        await t.act(conn, p.developer)  # seq 7: the job resumes it, bound to the developer; a system event takes none
        await t.append(conn, engagement, None, "system", "resume", "ON_HOLD", "SUBMITTED")
        await t.expect(conn, NOTE, rls, **_note(engagement, 7, "resume", p.developer))
        for reader, org, seen in (
            (p.developer, None, 4),
            (p.viewer, p.org, 4),
            (p.staff, None, 4),
            (p.owner, p.other_org, 0),  # a forged organisation context
            (p.outsider, None, 0),
            (p.other_member, p.other_org, 0),
            (None, None, 0),
        ):
            await t.act(conn, reader, org)
            assert await t.run(conn, COUNT_NOTES, e=engagement) == seen, reader
        await t.act(conn, p.developer)
        for sql in (
            "UPDATE engagement_notes SET body = 'Edited' WHERE engagement_id = :e",
            "UPDATE engagement_notes SET resume_at = NULL WHERE engagement_id = :e",
            REDACT + " WHERE engagement_id = :e",  # D-54: the app cannot redact
            "DELETE FROM engagement_notes WHERE engagement_id = :e",
            "TRUNCATE engagement_notes",
        ):
            await t.expect(conn, sql, "permission denied", e=engagement, by=p.staff)
        await t.as_owner(conn)  # the triggers hold for every role
        for sql, refusal in (
            ("UPDATE engagement_notes SET body = 'Edited' WHERE engagement_id = :e", "only by its redaction"),
            ("DELETE FROM engagement_notes WHERE engagement_id = :e", "append-only"),
            ("TRUNCATE engagement_notes", "append-only"),
        ):
            await t.expect(conn, sql, refusal, e=engagement)
        assert await t.run(conn, COUNT_NOTES, e=engagement) == 4


REDACT = "UPDATE engagement_notes SET body = '[redacted]', redacted_at = now(), redacted_by = :by"


async def test_a_note_is_redacted_once_by_the_owner_and_never_otherwise_changed(owner_engine: AsyncEngine) -> None:
    """D-54 (default (a)): the owner, or a SECURITY DEFINER function it owns, redacts a note's body once, setting the
    marker with redacted_at and redacted_by in one statement; any other change, a second redaction and a redaction
    that touches another column are refused; the app holds no UPDATE on notes at all (tested above)."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.act(conn, p.developer)
        engagement = await t.engage(conn, p)
        await t.act(conn, p.owner, p.org)
        await t.append(conn, engagement, p.owner, "owner", "request_info", "SUBMITTED", "INFO_REQUESTED")
        faked = _note(engagement, 2, "info_request", p.owner, body="[redacted]")  # a party cannot fake a redaction
        await t.expect(conn, NOTE, "ck_engagement_notes_redaction_complete", **faked)
        await t.run(conn, NOTE, **_note(engagement, 2, "info_request", p.owner, body="Call me on +254 700 000 000"))
        await t.as_owner(conn)
        guard, where = "only by its redaction", " WHERE engagement_id = :e"
        for sql in (
            "UPDATE engagement_notes SET body = '[redacted]'" + where,  # without who and when
            "UPDATE engagement_notes SET redacted_at = now(), redacted_by = :by" + where,  # without the marker
            REDACT + ", kind = 'info_answer'" + where,  # and something else
            REDACT + ", created_by = :by" + where,
        ):
            await t.expect(conn, sql, guard, e=engagement, by=p.staff)
        assert await t.rowcount(conn, REDACT + where, e=engagement, by=p.staff) == 1
        redacted = "SELECT body, redacted_by FROM engagement_notes WHERE engagement_id = :e"
        assert tuple((await conn.execute(text(redacted), {"e": engagement})).one()) == ("[redacted]", p.staff)
        for sql in (REDACT + where, "UPDATE engagement_notes SET body = 'Restored'" + where):  # once, for good
            await t.expect(conn, sql, guard, e=engagement, by=p.staff)


async def test_a_user_marks_only_their_own_notifications_read(app_engine: AsyncEngine, world: w.World) -> None:
    """REQ-NOT-03 (P19-C): bridge_app updates read_at only (revision 0006), and only on the user's own rows."""
    async with app_engine.connect() as conn, conn.begin():
        await _as_tenant(conn, world.a.user_id, None)
        own = sa.text("SELECT count(*) FROM in_app_notifications WHERE user_id = :u AND read_at IS NULL")
        unread = (await conn.execute(own, {"u": world.a.user_id})).scalar_one()
        assert unread >= 1
        marked = await conn.execute(text("UPDATE in_app_notifications SET read_at = now() WHERE read_at IS NULL"))
        assert marked.rowcount == unread
        assert (await conn.execute(own, {"u": world.a.user_id})).scalar_one() == 0
        foreign = await conn.execute(
            text("UPDATE in_app_notifications SET read_at = now() WHERE user_id = :b"), {"b": world.b.user_id}
        )
        assert foreign.rowcount == 0
        for assignment in (
            "title = 'Changed'",
            "body = 'Changed'",
            "link = '/elsewhere'",
            "kind = 'changed'",
            "user_id = user_id",
            "org_id = NULL",
            "created_at = now()",
        ):
            savepoint = await conn.begin_nested()
            with pytest.raises(ProgrammingError, match="permission denied"):
                await conn.execute(text(f"UPDATE in_app_notifications SET {assignment}"))
            await savepoint.rollback()
        await conn.rollback()


BRIEF = (
    "INSERT INTO problem_briefs (problem_id, org_id, visibility, budget_band, deadline, status)"
    " VALUES (:p, :org, 'public', 'band_b', :deadline, CAST(:status AS brief_status))"
)
BRIEF_STATUS = "SELECT CAST(status AS text) FROM problem_briefs WHERE problem_id = :p"
MODERATE = "SELECT app_moderate_problem(:p, CAST(:state AS moderation_state), CAST(:status AS problem_status))"
BRIEF_AND_PROBLEM_READ = (
    "SELECT (SELECT count(*) FROM problem_briefs WHERE problem_id = :p) + (SELECT count(*) FROM problems WHERE id = :p)"
)


async def test_a_brief_is_published_by_moderation_and_stays_readable_once_closed(owner_engine: AsyncEngine) -> None:
    """REQ-DIR-05 (P19-B; revision 0006). Given an E2 organisation's reviewer posting public Briefs as drafts with their
    problems awaiting review, Then a developer reads none, and the organisation can neither publish nor close one ahead
    of moderation; When staff approve, Then a listed E2 organisation's Brief is published and read, while an E1 or a
    delisted organisation's stays a draft nobody else reads (whoever tries to publish it); When staff reject a
    published Brief's problem, Then the Brief returns to draft and is read by nobody else. Only moderation publishes:
    an organisation that returns its Brief to draft cannot republish it. A closed Brief is terminal for every role,
    stays read and closed after a later approval, and is read by nobody else once its problem is rejected."""
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        niche, e1_org, delisted_org = uuid7(), uuid7(), uuid7()
        await t.run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Briefs')", id=niche, s=niche.hex)
        for org, verification, delisted in ((e1_org, "e1", False), (delisted_org, "e2", True)):
            await t.run(
                conn,
                "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, delisted_at)"
                " VALUES (:id, 'company', 'Brief Ltd', :slug, 'seed', CAST(:verification AS org_verification),"
                " CASE WHEN :delisted THEN now() END)",
                id=org,
                slug=f"brief-{org.hex}",
                verification=verification,
                delisted=delisted,
            )
        await t.member(conn, e1_org, p.outsider, "{reviewer}")
        await t.member(conn, delisted_org, p.viewer, "{reviewer}")
        brief, second, early = [
            await w.add_problem(conn, p.reviewer, niche, org_id=p.org, status="pending_review") for _ in range(3)
        ]
        e1_brief = await w.add_problem(conn, p.outsider, niche, org_id=e1_org, status="pending_review")
        delisted_brief = await w.add_problem(conn, p.viewer, niche, org_id=delisted_org, status="pending_review")
        deadline = date(2027, 3, 31)
        await t.act(conn, p.reviewer, p.org)
        for problem in (brief, second):
            await t.run(conn, BRIEF, p=problem, org=p.org, deadline=deadline, status="draft")
        ahead = "a Brief is published only once its problem is published and clear, for a listed E2 organisation"
        moderation_only, terminal = "only moderation publishes a Brief", "a closed Brief stays closed"
        publish, close, unpublish = (
            f"UPDATE problem_briefs SET status = '{status}' WHERE problem_id = :p"
            for status in ("published", "closed", "draft")
        )
        await t.expect(conn, BRIEF, moderation_only, p=early, org=p.org, deadline=deadline, status="published")
        await t.expect(conn, publish, moderation_only, p=brief)
        closing = "only a published Brief is closed"
        await t.expect(conn, close, closing, p=brief)
        await t.expect(conn, BRIEF, closing, p=early, org=p.org, deadline=deadline, status="closed")
        for actor, org, problem in ((p.outsider, e1_org, e1_brief), (p.viewer, delisted_org, delisted_brief)):
            await t.act(conn, actor, org)
            await t.run(conn, BRIEF, p=problem, org=org, deadline=deadline, status="draft")
        everyone = (brief, second, e1_brief, delisted_brief)
        await t.act(conn, p.developer)
        for problem in everyone:
            assert await t.run(conn, BRIEF_AND_PROBLEM_READ, p=problem) == 0, "a Brief awaiting review is read"
        await t.act(conn, p.staff)
        for problem in everyone:
            await t.run(conn, MODERATE, p=problem, state="clear", status="published")
        statuses = {problem: await t.run(conn, BRIEF_STATUS, p=problem) for problem in everyone}
        assert statuses == {brief: "published", second: "published", e1_brief: "draft", delisted_brief: "draft"}
        await t.run(conn, MODERATE, p=second, state="rejected", status="rejected")
        assert await t.run(conn, BRIEF_STATUS, p=second) == "draft"  # a published Brief returns to draft
        await t.act(conn, p.developer)
        reads = {problem: await t.run(conn, BRIEF_AND_PROBLEM_READ, p=problem) for problem in everyone}
        assert reads == {brief: 2, second: 0, e1_brief: 0, delisted_brief: 0}
        # The policy's helper tells a developer nothing the policy hides: e1_brief's problem is approved and clear,
        # but its Brief is a draft.
        public = {
            problem: await t.run(conn, "SELECT app_brief_problem_is_public(:p)", p=problem) for problem in everyone
        }
        assert public == {brief: True, second: False, e1_brief: False, delisted_brief: False}
        await t.act(conn, p.outsider, e1_org)  # the policies' E2 guard on 'published'
        await t.expect(conn, publish, "row-level security", p=e1_brief)
        await t.as_owner(conn)  # and the status guard's, for every role
        for problem in (e1_brief, delisted_brief):
            await t.expect(conn, publish, ahead, p=problem)
        await t.act(conn, p.reviewer, p.org)  # the published -> draft -> published route is not the organisation's
        assert await t.rowcount(conn, unpublish, p=brief) == 1
        await t.expect(conn, publish, moderation_only, p=brief)
        await t.act(conn, p.staff)
        await t.run(conn, MODERATE, p=brief, state="clear", status="published")  # moderation publishes it again
        assert await t.run(conn, BRIEF_STATUS, p=brief) == "published"
        await t.act(conn, p.reviewer, p.org)
        assert await t.rowcount(conn, close, p=brief) == 1
        for sql in (publish, unpublish):
            await t.expect(conn, sql, terminal, p=brief)
        await t.as_owner(conn)  # closed is terminal for every role
        await t.expect(conn, publish, terminal, p=brief)
        await t.act(conn, p.developer)
        assert await t.run(conn, BRIEF_AND_PROBLEM_READ, p=brief) == 2  # the problem page and the links stay
        await t.act(conn, p.staff)
        await t.run(conn, MODERATE, p=brief, state="clear", status="published")  # say, clearing a later hold
        await t.run(conn, MODERATE, p=brief, state="rejected", status="rejected")
        assert await t.run(conn, BRIEF_STATUS, p=brief) == "closed"  # closed stays closed whatever moderation decides
        await t.act(conn, p.developer)
        assert await t.run(conn, BRIEF_AND_PROBLEM_READ, p=brief) == 0  # but is read only while its problem is public


# --- revision 0007: the engagements the expiry job may act on --------------------------------------------------------

DUE = "SELECT developer_id, engagement_id FROM app_engagements_due_for_expiry(:now)"
NAIROBI = ZoneInfo("Africa/Nairobi")
ENTERED = "SELECT stage_entered_at FROM engagements WHERE id = :id"


async def _due(conn: AsyncConnection, now: datetime, *engagements: UUID) -> set[tuple[UUID, UUID]]:
    """The (developer, engagement) pairs of ``engagements`` the job's list holds at ``now`` (the database is shared)."""
    result = await conn.execute(text(DUE), {"now": now})
    assert list(result.keys()) == ["developer_id", "engagement_id"]  # ids only
    return {(row.developer_id, row.engagement_id) for row in result if row.engagement_id in engagements}


async def test_only_the_expiry_job_lists_the_engagements_due_and_learns_only_ids(owner_engine: AsyncEngine) -> None:
    """Given a submitted engagement and one on hold, When the expiry job (no user bound) asks for the engagements the
    clock may act on, Then it gets each one's developer and id once its stage deadline (without one, its stage entry)
    has come, a hold from 00:00 Africa/Nairobi on its resume date, and an engagement that ended never; a session bound
    to a developer, a member or staff is refused, and so is a missing time."""
    tick = timedelta(microseconds=1)
    resume_day = datetime(2027, 1, 29, tzinfo=NAIROBI)  # 00:00 EAT on the resume date
    async with t.as_app(owner_engine) as conn:
        p = await t.parties(conn)
        await t.act(conn, p.developer)
        submitted = await t.engage(conn, p)  # a fixture: no stage deadline
        entered = await t.run(conn, ENTERED, id=submitted)
        await t.tag(conn, p.proposal, p.other_org, p.developer)
        held = await t.engage(conn, replace(p, org=p.other_org))
        until = resume_day.replace(hour=23, minute=59, second=59)  # a hold's deadline: the end of its resume date
        await t.append(conn, held, p.developer, "developer", "pause", "SUBMITTED", "ON_HOLD", deadline=until)
        assert await t.run(conn, ENTERED, id=held) < resume_day

        await t.act(conn, None)  # the job's session
        assert await _due(conn, entered - tick, submitted) == set()  # without a deadline: listed from its entry
        assert await _due(conn, entered, submitted) == {(p.developer, submitted)}
        await t.act(conn, p.developer)  # a deadline ten days out (a same-state event renews it)
        deadline = entered + timedelta(days=10)
        await t.append(conn, submitted, None, "system", "remind", "SUBMITTED", "SUBMITTED", deadline=deadline)
        await t.act(conn, None)
        assert await _due(conn, deadline - tick, submitted) == set()
        assert await _due(conn, deadline, submitted) == {(p.developer, submitted)}
        assert await _due(conn, resume_day - tick, held) == set()
        assert await _due(conn, resume_day, held) == {(p.developer, held)}  # not only once its deadline has passed

        await t.act(conn, p.developer)  # the job expires the submitted one: an ended engagement is never listed
        await t.append(conn, submitted, None, "system", "expire", "SUBMITTED", "EXPIRED", reason="NO_REVIEW")
        await t.act(conn, None)
        later = resume_day + timedelta(days=365)
        assert await _due(conn, later, submitted, held) == {(p.developer, held)}

        for caller, org in ((p.developer, None), (p.owner, p.org), (p.signatory, None), (p.staff, None)):
            await t.act(conn, caller, org)
            await t.expect(conn, DUE, "the engagements.expire job only, with no user bound", now=later)
        await t.act(conn, None)
        await t.expect(conn, DUE, "name the time", now=None)


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
