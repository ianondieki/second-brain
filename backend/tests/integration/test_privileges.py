"""AC-REPO-3, privileges half (REQ-REPO-01; docs/spec/06 6.1), the Tier-2 role memberships, ``bridge.db.as_role`` and
the privileged changes that run only through SECURITY DEFINER functions (revision 0002).

- ``has_table_privilege`` over every role of the cluster: exactly tier2_reader, provenance_worker,
  tier2_embed_worker, tier2_moderation and dsr_exporter hold SELECT on ``proposal_confidential`` (bridge_app holds no
  privilege at all), and only tier2_moderation on ``proposal_confidential_embeddings``. Superusers and the owner hold
  every privilege by definition and are left out; no other role may hold ``pg_read_all_data``.
- bridge_app is a member of each Tier-2 role WITH INHERIT FALSE, SET TRUE (PostgreSQL 16) and of nothing else, so a
  session logged in as bridge_app (``SET SESSION AUTHORIZATION`` here) can switch to a Tier-2 role and to no other.
- Each definer function checks its caller in SQL: staff decisions need the staff role (and TOTP), the OTPs are compared
  against the stored hash, holds only go up, and approvals set verification and create the membership.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, async_sessionmaker, create_async_engine

from bridge.db import TIER2_ROLES, as_role, bind_tenant
from bridge.ids import uuid7
from tests.integration import world as w

PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
OTHER_ROLES = ("bridge_owner", "aggregate_worker", "audit_reader")
# Held on the table or on any of its columns (column grants count).
HOLDS = (
    "CASE WHEN p.name IN ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES')"
    " THEN has_any_column_privilege(r.oid, CAST(:table AS regclass), p.name)"
    " ELSE has_table_privilege(r.oid, CAST(:table AS regclass), p.name) END"
)


async def roles_holding(engine: AsyncEngine, table: str, privilege: str) -> set[str]:
    """Roles of the cluster holding ``privilege`` on ``table``, except superusers, the owner and predefined roles."""
    async with engine.connect() as conn:
        found = await conn.execute(
            text(
                "SELECT r.rolname FROM pg_roles r CROSS JOIN (SELECT CAST(:privilege AS text) AS name) p"
                " WHERE NOT r.rolsuper AND r.rolname <> 'bridge_owner' AND r.rolname NOT LIKE 'pg\\_%' AND " + HOLDS
            ),
            {"table": f"public.{table}", "privilege": privilege},
        )
        return set(found.scalars())


async def test_exactly_the_tier2_role_set_reads_proposal_confidential(owner_engine: AsyncEngine) -> None:
    expected = {"tier2_reader", "provenance_worker", "tier2_embed_worker", "tier2_moderation", "dsr_exporter"}
    assert expected == TIER2_ROLES
    assert await roles_holding(owner_engine, "proposal_confidential", "SELECT") == TIER2_ROLES


async def test_only_tier2_moderation_reads_full_text_embeddings(owner_engine: AsyncEngine) -> None:
    assert await roles_holding(owner_engine, "proposal_confidential_embeddings", "SELECT") == {"tier2_moderation"}


@pytest.mark.parametrize("table", ["proposal_confidential", "proposal_confidential_embeddings"])
@pytest.mark.parametrize("privilege", PRIVILEGES)
async def test_bridge_app_holds_no_privilege_on_tier2_tables(
    owner_engine: AsyncEngine, table: str, privilege: str
) -> None:
    assert "bridge_app" not in await roles_holding(owner_engine, table, privilege)


async def test_no_role_reads_or_writes_all_data(owner_engine: AsyncEngine) -> None:
    """pg_read_all_data would bypass the grants (not RLS); no Bridge role may hold it."""
    async with owner_engine.connect() as conn:
        holders = await conn.execute(
            text(
                "SELECT r.rolname FROM pg_roles r WHERE NOT r.rolsuper AND r.rolname NOT LIKE 'pg\\_%'"
                " AND (pg_has_role(r.oid, 'pg_read_all_data', 'USAGE')"
                " OR pg_has_role(r.oid, 'pg_write_all_data', 'USAGE'))"
            )
        )
        assert list(holders.scalars()) == []


async def test_bridge_app_membership_is_set_only_for_the_tier2_roles(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT g.rolname AS role, m.rolname AS member, a.inherit_option, a.set_option, a.admin_option"
                    " FROM pg_auth_members a JOIN pg_roles g ON g.oid = a.roleid JOIN pg_roles m ON m.oid = a.member"
                    " WHERE m.rolname = 'bridge_app' OR g.rolname = ANY (:roles)"
                ),
                {"roles": sorted(TIER2_ROLES)},
            )
        ).all()
    assert {(r.role, r.member, r.inherit_option, r.set_option, r.admin_option) for r in rows} == {
        (role, "bridge_app", False, True, False) for role in TIER2_ROLES
    }


async def test_tier2_roles_cannot_log_in_or_bypass_rls(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT rolname, rolcanlogin, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles"
                    " WHERE rolname = ANY (:roles)"
                ),
                {"roles": sorted(TIER2_ROLES)},
            )
        ).all()
    assert {r.rolname for r in rows} == TIER2_ROLES
    assert not any(r.rolcanlogin or r.rolsuper or r.rolbypassrls or r.rolcreaterole or r.rolcreatedb for r in rows)


# --- Switching roles as a real bridge_app session ---------------------------------------------------------------


def bridge_app_session_engine(url: URL) -> AsyncEngine:
    """An engine whose session user is bridge_app (SET SESSION AUTHORIZATION), so SET ROLE is checked against
    bridge_app's memberships exactly as in production (the harness's other engines keep a superuser session)."""
    engine = create_async_engine(url, poolclass=sa.pool.NullPool)

    @sa.event.listens_for(engine.sync_engine, "connect")
    def _authorize(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET SESSION AUTHORIZATION bridge_app")
        cursor.close()
        dbapi_connection.commit()

    return engine


@pytest.fixture(scope="module")
async def app_session_engine(database_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = bridge_app_session_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.mark.parametrize("role", sorted(TIER2_ROLES))
async def test_bridge_app_can_switch_to_each_tier2_role(app_session_engine: AsyncEngine, role: str) -> None:
    async with app_session_engine.connect() as conn, conn.begin():
        assert (await conn.execute(text("SELECT session_user"))).scalar_one() == "bridge_app"
        await conn.execute(text("SELECT set_config('role', :role, true)"), {"role": role})
        assert (await conn.execute(text("SELECT current_user"))).scalar_one() == role


@pytest.mark.parametrize("role", OTHER_ROLES)
async def test_bridge_app_cannot_switch_to_any_other_role(app_session_engine: AsyncEngine, role: str) -> None:
    async with app_session_engine.connect() as conn, conn.begin():
        with pytest.raises(DBAPIError, match="permission denied to set role"):
            await conn.execute(text("SELECT set_config('role', :role, true)"), {"role": role})


class Developer(NamedTuple):
    user_id: UUID
    published_version: UUID
    draft_version: UUID


@pytest.fixture(scope="module")
async def developer(owner_engine: AsyncEngine) -> Developer:
    """A developer with one draft and one registered proposal (committed: the as_role session reads them)."""
    tag = uuid4().hex[:10]
    async with owner_engine.begin() as conn:
        niche = uuid7()
        await conn.execute(
            text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, 'Priv niche')"),
            {"id": niche, "slug": f"priv-{tag}"},
        )
        user = await w.add_user(conn, f"dev-{tag}@example.test", "Developer")
        problem = await w.add_problem(conn, user, niche)
        _, published_version = await w.add_proposal(conn, user, niche, problem)
        _, draft_version = await w.add_proposal(conn, user, niche, problem, registered=False)
    return Developer(user, published_version, draft_version)


async def test_as_role_switches_to_a_tier2_role_and_back(app_session_engine: AsyncEngine, developer: Developer) -> None:
    factory = async_sessionmaker(app_session_engine, expire_on_commit=False)
    count_mine = text("SELECT count(*) FROM proposal_confidential WHERE owner_id = :u")
    async with factory() as session:
        await bind_tenant(session, user_id=developer.user_id)
        with pytest.raises(ProgrammingError, match="permission denied"):  # bridge_app itself: no privilege at all
            await session.execute(count_mine, {"u": developer.user_id})
        await session.rollback()

        async with as_role(session, "tier2_reader"):
            assert (await session.execute(text("SELECT current_user"))).scalar_one() == "tier2_reader"
            assert (await session.execute(count_mine, {"u": developer.user_id})).scalar_one() == 2
            with pytest.raises(RuntimeError, match="do not nest"):
                async with as_role(session, "dsr_exporter"):
                    pass
        assert (await session.execute(text("SELECT current_user"))).scalar_one() == "bridge_app"
        # Back as bridge_app, the audit write works in the same transaction (tier2_reader has no grant on it).
        await session.execute(
            text(
                "INSERT INTO audit_events (id, chain_id, actor_kind, actor_user_id, action)"
                " VALUES (:id, :c, 'user', :u, 'tier2.viewed')"
            ),
            {"id": uuid7(), "c": f"test:{uuid4().hex}", "u": developer.user_id},
        )
        await session.rollback()

        with pytest.raises(ValueError, match="not a Tier-2 role"):
            async with as_role(session, "bridge_owner"):
                pass
        with pytest.raises(LookupError):
            async with as_role(session, "provenance_worker"):
                raise LookupError("the block failed")
        assert (await session.execute(text("SELECT current_user"))).scalar_one() == "bridge_app"
        await session.rollback()


async def test_as_role_rolls_back_when_the_block_breaks_the_transaction(
    app_session_engine: AsyncEngine, developer: Developer
) -> None:
    factory = async_sessionmaker(app_session_engine, expire_on_commit=False)
    async with factory() as session:
        await bind_tenant(session, user_id=developer.user_id)
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with as_role(session, "dsr_exporter"):
                await session.execute(text("SELECT 1 FROM users"))  # dsr_exporter has no grant on users
        assert not session.in_transaction()
        assert (await session.execute(text("SELECT current_user"))).scalar_one() == "bridge_app"


# --- SECURITY DEFINER functions (privileged changes checked in SQL) ------------------------------------------------


@asynccontextmanager
async def as_app(owner_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """One rolled-back transaction: fixtures are written as the owner, then the connection acts as bridge_app."""
    async with owner_engine.connect() as conn:
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()


async def run(conn: AsyncConnection, sql: str, **params: object) -> Any:
    """Execute ``sql``; the first column of the first row when it returns rows."""
    result = await conn.execute(text(sql), params)
    return result.scalar() if result.returns_rows else None


async def act(conn: AsyncConnection, user_id: UUID | None, org_id: UUID | None = None) -> None:
    """Switch the connection to bridge_app acting for ``user_id`` (and ``org_id``)."""
    await conn.execute(text("SET LOCAL ROLE bridge_app"))
    await conn.execute(
        text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
        {"u": str(user_id) if user_id else "", "o": str(org_id) if org_id else ""},
    )


async def as_owner(conn: AsyncConnection) -> None:
    await conn.execute(text("SET LOCAL ROLE bridge_owner"))


async def expect(conn: AsyncConnection, sql: str, match: str, **params: object) -> None:
    savepoint = await conn.begin_nested()
    with pytest.raises(DBAPIError, match=match):
        await conn.execute(text(sql), params)
    await savepoint.rollback()


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.test"


async def add_org(
    conn: AsyncConnection, *, verification: str = "unclaimed", source: str = "seed", **columns: Any
) -> UUID:
    org_id = uuid7()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, official_domains)"
            " VALUES (:id, 'company', 'Listed Ltd', :slug, CAST(:source AS org_source),"
            " CAST(:verification AS org_verification), CAST(:domains AS citext[]))"
        ),
        {
            "id": org_id,
            "slug": f"org-{org_id.hex}",
            "source": source,
            "verification": verification,
            "domains": columns.get("official_domains", "{}"),
        },
    )
    return org_id


@pytest.fixture
def otp() -> tuple[bytes, bytes]:
    """(right, wrong) OTP hashes."""
    return hashlib.sha256(b"123456").digest(), hashlib.sha256(b"654321").digest()


async def test_app_is_staff_needs_an_active_staff_user_with_totp(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("admin"), "Admin", staff_role="admin")
        moderator = await w.add_user(conn, _email("mod"), "Moderator", staff_role="moderator")
        no_totp = await w.add_user(conn, _email("nototp"), "No TOTP", staff_role="admin")
        await run(conn, "UPDATE users SET totp_enabled_at = NULL WHERE id = :id", id=no_totp)
        suspended = await w.add_user(conn, _email("susp"), "Suspended", staff_role="admin")
        await run(conn, "UPDATE users SET status = 'suspended' WHERE id = :id", id=suspended)
        developer = await w.add_user(conn, _email("dev"), "Developer")
        check = "SELECT app_is_staff(), app_is_staff('{admin}'), app_is_staff('{moderator}')"
        expected = {
            admin: (True, True, False),
            moderator: (True, False, True),
            no_totp: (False, False, False),
            suspended: (False, False, False),
            developer: (False, False, False),
            None: (False, False, False),
        }
        for user, answer in expected.items():
            await act(conn, user)
            assert tuple((await conn.execute(text(check))).one()) == answer, user


async def test_phone_otp_is_compared_in_sql_and_raises_d0_to_d1(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    right, wrong = otp
    async with as_app(owner_engine) as conn:
        user = await w.add_user(conn, _email("phone"), "Phone")
        other = await w.add_user(conn, _email("other"), "Other")
        await run(conn, "INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)", u=user, h=f"h{user.hex}")
        await act(conn, user)
        code = uuid7()
        await run(
            conn,
            "INSERT INTO phone_verifications (id, user_id, phone_e164, otp_hash, expires_at)"
            " VALUES (:id, :u, '+254712345678', :h, now() + interval '10 minutes')",
            id=code,
            u=user,
            h=right,
        )
        await expect(conn, "UPDATE phone_verifications SET verified_at = now()", "permission denied")
        await expect(conn, "UPDATE developer_profiles SET verification_level = 'd1'", "permission denied")
        confirm = "SELECT app_confirm_phone_otp(:id, :h)"
        assert await run(conn, confirm, id=code, h=wrong) is False
        assert (
            await run(conn, "SELECT verification_level::text FROM developer_profiles WHERE user_id = :u", u=user)
            == "d0"
        )
        assert await run(conn, confirm, id=code, h=right) is True
        assert (
            await run(conn, "SELECT verification_level::text FROM developer_profiles WHERE user_id = :u", u=user)
            == "d1"
        )
        assert await run(conn, "SELECT attempts FROM phone_verifications WHERE id = :id", id=code) == 2
        assert await run(conn, confirm, id=code, h=right) is False  # a code confirms once
        await act(conn, other)
        await expect(conn, confirm, "no such code for the current user", id=code, h=right)
        # Five wrong attempts lock a code, even against the right one afterwards.
        await act(conn, user)
        locked = uuid7()
        await run(
            conn,
            "INSERT INTO phone_verifications (id, user_id, phone_e164, otp_hash, expires_at)"
            " VALUES (:id, :u, '+254712345678', :h, now() + interval '10 minutes')",
            id=locked,
            u=user,
            h=right,
        )
        for _ in range(5):
            assert await run(conn, confirm, id=locked, h=wrong) is False
        assert await run(conn, confirm, id=locked, h=right) is False


async def test_kyc_decisions_are_staff_admin_only_and_raise_d1_to_d2(owner_engine: AsyncEngine) -> None:
    decide = (
        "SELECT app_decide_kyc(:id, :approve, 'ref-1', 'Jane Wanjiru', 'national_id', '1234', CAST(:adult AS boolean))"
    )
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("kyc-admin"), "Admin", staff_role="admin")
        moderator = await w.add_user(conn, _email("kyc-mod"), "Moderator", staff_role="moderator")
        subject = await w.add_user(conn, _email("kyc-dev"), "Jane")
        await run(
            conn,
            "INSERT INTO developer_profiles (user_id, handle, verification_level) VALUES (:u, :h, 'd1')",
            u=subject,
            h=f"h{subject.hex}",
        )
        await act(conn, subject)
        review = uuid7()
        await run(conn, "INSERT INTO kyc_reviews (id, user_id) VALUES (:id, :u)", id=review, u=subject)
        await expect(
            conn,
            "INSERT INTO kyc_reviews (id, user_id, status) VALUES (:id, :u, 'approved')",
            "row-level security",
            id=uuid7(),
            u=subject,
        )
        await expect(conn, decide, "staff admin only", id=review, approve=True, adult=True)
        await act(conn, moderator)
        await expect(conn, decide, "staff admin only", id=review, approve=True, adult=True)
        await act(conn, admin)
        await expect(conn, decide, "an adult", id=review, approve=True, adult=False)
        await run(conn, decide, id=review, approve=True, adult=True)
        row = (
            await conn.execute(
                text(
                    "SELECT status::text, verified_legal_name, decided_by, purge_due_at - decided_at AS window"
                    " FROM kyc_reviews WHERE id = :id"
                ),
                {"id": review},
            )
        ).one()
        assert (row.status, row.verified_legal_name, row.decided_by, row.window) == (
            "approved",
            "Jane Wanjiru",
            admin,
            timedelta(hours=72),
        )
        await act(conn, subject)  # the subject reads their own profile: now D2
        assert (
            await run(conn, "SELECT verification_level::text FROM developer_profiles WHERE user_id = :u", u=subject)
            == "d2"
        )
        await act(conn, admin)
        await expect(conn, decide, "already decided", id=review, approve=True, adult=True)
        # The purge job sees the review only once it is due, and marks it purged once.
        assert await run(conn, "SELECT count(*) FROM app_kyc_purge_due() AS r(id) WHERE r.id = :id", id=review) == 0
        await as_owner(conn)
        await run(conn, "UPDATE kyc_reviews SET purge_due_at = now() - interval '1 minute' WHERE id = :id", id=review)
        await act(conn, None)
        assert await run(conn, "SELECT count(*) FROM app_kyc_purge_due() AS r(id) WHERE r.id = :id", id=review) == 1
        assert await run(conn, "SELECT app_mark_kyc_images_purged(:id)", id=review) is True
        assert await run(conn, "SELECT app_mark_kyc_images_purged(:id)", id=review) is False


async def test_moderation_state_changes_only_through_staff_and_holds_only_go_up(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        niche = uuid7()
        await run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Mod')", id=niche, s=f"m-{niche.hex}")
        owner = await w.add_user(conn, _email("owner"), "Owner")
        stranger = await w.add_user(conn, _email("stranger"), "Stranger")
        moderator = await w.add_user(conn, _email("moderator"), "Moderator", staff_role="moderator")
        problem = await w.add_problem(conn, owner, niche)
        proposal, _ = await w.add_proposal(conn, owner, niche, problem)
        state = "SELECT moderation_state::text FROM proposals WHERE id = :id"
        await act(conn, owner)
        await expect(conn, "UPDATE proposals SET moderation_state = 'held'", "permission denied")
        await expect(conn, "SELECT app_moderate_proposal(:id, 'clear')", "staff admin or moderator only", id=proposal)
        await run(conn, "SELECT app_hold_proposal(:id)", id=proposal)
        assert await run(conn, state, id=proposal) == "held"
        await act(conn, stranger)
        await expect(conn, "SELECT app_hold_proposal(:id)", "owner or staff only", id=proposal)
        await expect(conn, "SELECT app_hold_problem(:id)", "owner or staff only", id=problem)
        await act(conn, moderator)
        await run(conn, "SELECT app_moderate_proposal(:id, 'clear')", id=proposal)
        assert await run(conn, state, id=proposal) == "clear"
        await run(conn, "SELECT app_moderate_problem(:id, 'rejected', 'rejected')", id=problem)
        row = (
            await conn.execute(
                text(
                    "SELECT moderation_state::text AS m, status::text AS s, moderator_id FROM problems WHERE id = :id"
                ),
                {"id": problem},
            )
        ).one()
        assert tuple(row) == ("rejected", "rejected", moderator)
        # A moderator never decides on their own content.
        await as_owner(conn)
        mine, _ = await w.add_proposal(conn, moderator, niche, problem)
        await act(conn, moderator)
        await expect(conn, "SELECT app_moderate_proposal(:id, 'clear')", "moderator's own", id=mine)


async def _claim(conn: AsyncConnection, org: UUID, claimant: UUID, domain: str, level: str, otp_hash: bytes) -> UUID:
    claim = uuid7()
    await run(
        conn,
        "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status, otp_hash,"
        " otp_expires_at) VALUES (:id, :org, :u, :d, :e, CAST(:level AS claim_level), 'otp_sent', :h,"
        " now() + interval '10 minutes')",
        id=claim,
        org=org,
        u=claimant,
        d=domain,
        e=f"partnerships@{domain}",
        level=level,
        h=otp_hash,
    )
    return claim


async def _held_tag(conn: AsyncConnection, org: UUID, status: str) -> UUID:
    """As the owner: a developer's proposal tagged to ``org`` with ``status``; returns the tag id."""
    await as_owner(conn)
    niche = uuid7()
    await run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Tag')", id=niche, s=f"t-{niche.hex}")
    developer = await w.add_user(conn, _email("tagger"), "Tagger")
    problem = await w.add_problem(conn, developer, niche)
    proposal, _ = await w.add_proposal(conn, developer, niche, problem)
    tag = uuid7()
    await run(
        conn,
        "INSERT INTO tags (id, proposal_id, org_id, developer_id, status)"
        " VALUES (:id, :p, :org, :dev, CAST(:status AS tag_status))",
        id=tag,
        p=proposal,
        org=org,
        dev=developer,
        status=status,
    )
    return tag


async def test_e1_claims_approve_automatically_only_on_an_official_domain(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    right, wrong = otp
    async with as_app(owner_engine) as conn:
        official = await add_org(conn, official_domains="{telco-a.example.test}")
        lookalike = await add_org(conn, official_domains="{telco-b.example.test}")
        verified = await add_org(conn, verification="e2")
        tag = await _held_tag(conn, official, "held_unclaimed")
        claimant = await w.add_user(conn, _email("claimant"), "Claimant")
        await act(conn, claimant)
        claim = await _claim(conn, official, claimant, "telco-a.example.test", "e1", right)
        approve = "SELECT app_approve_claim_e1(:id)::text"
        await expect(
            conn, "UPDATE org_claims SET otp_verified_at = now() WHERE id = :id", "permission denied", id=claim
        )
        await expect(conn, "UPDATE org_claims SET status = 'approved' WHERE id = :id", "row-level security", id=claim)
        await expect(conn, "UPDATE organizations SET verification = 'e1'", "permission denied")
        await expect(conn, approve, "must both be verified", id=claim)
        assert await run(conn, "SELECT app_confirm_claim_otp(:id, :h)", id=claim, h=wrong) is False
        assert await run(conn, "SELECT app_confirm_claim_otp(:id, :h)", id=claim, h=right) is True
        await expect(conn, approve, "must both be verified", id=claim)  # the DNS TXT record is still missing
        await run(
            conn, "UPDATE org_claims SET dns_verified_at = now(), status = 'dns_pending' WHERE id = :id", id=claim
        )
        assert await run(conn, approve, id=claim) == "approved"
        org = (
            await conn.execute(
                text("SELECT verification::text AS v, verified_domain::text AS d FROM organizations WHERE id = :id"),
                {"id": official},
            )
        ).one()
        assert tuple(org) == ("e1", "telco-a.example.test")
        assert await run(conn, "SELECT app_is_member(:id, '{owner,admin}')", id=official) is True
        await as_owner(conn)
        assert await run(conn, "SELECT status::text FROM tags WHERE id = :id", id=tag) == "held_pending_verification"

        # A lookalike domain waits for manual review and the listing stays unclaimed (AC-DIR-7).
        await act(conn, claimant)
        other = await _claim(conn, lookalike, claimant, "telco-b-ke.example.test", "e1", right)
        assert await run(conn, "SELECT app_confirm_claim_otp(:id, :h)", id=other, h=right) is True
        await run(conn, "UPDATE org_claims SET dns_verified_at = now() WHERE id = :id", id=other)
        assert await run(conn, approve, id=other) == "pending_review"
        assert (
            await run(conn, "SELECT verification::text FROM organizations WHERE id = :id", id=lookalike) == "unclaimed"
        )
        # A claim on an E2 organisation becomes a dispute, never a transfer (AC-DIR-2).
        dispute = await _claim(conn, verified, claimant, "verified.example.test", "e1", right)
        assert await run(conn, "SELECT app_confirm_claim_otp(:id, :h)", id=dispute, h=right) is True
        await run(conn, "UPDATE org_claims SET dns_verified_at = now() WHERE id = :id", id=dispute)
        assert await run(conn, approve, id=dispute) == "disputed"
        assert await run(conn, "SELECT app_is_member(:id)", id=verified) is False


async def test_e2_approval_is_staff_admin_only_needs_the_terms_and_delivers_held_tags(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    right, _ = otp
    decide = "SELECT app_decide_claim(:id, true, 'documents checked')"
    async with as_app(owner_engine) as conn:
        org = await add_org(conn, verification="e1")
        tag = await _held_tag(conn, org, "held_pending_verification")
        admin = await w.add_user(conn, _email("claims-admin"), "Admin", staff_role="admin")
        moderator = await w.add_user(conn, _email("claims-mod"), "Moderator", staff_role="moderator")
        claimant = await w.add_user(conn, _email("signatory"), "Signatory")
        met, _ = await w.add_templates(conn, uuid4().hex[:8])
        await act(conn, claimant)
        claim = await _claim(conn, org, claimant, "signatory.example.test", "e2", right)
        await run(conn, "UPDATE org_claims SET status = 'pending_review' WHERE id = :id", id=claim)
        await act(conn, moderator)
        await expect(conn, decide, "staff admin only", id=claim)
        await act(conn, admin)
        await expect(conn, decide, "Master Enterprise Terms", id=claim)
        # The claimant of an open E2 claim may accept the terms before being a member.
        await act(conn, claimant)
        await run(
            conn,
            "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
            " SELECT :id, :org, :u, id, sha256 FROM legal_templates WHERE id = :t",
            id=uuid7(),
            org=org,
            u=claimant,
            t=met,
        )
        await act(conn, admin)
        await run(conn, decide, id=claim)
        await as_owner(conn)
        row = (
            await conn.execute(
                text(
                    "SELECT verification::text AS v, e2_verified_at IS NOT NULL AS dated, reverify_due_on"
                    " FROM organizations WHERE id = :id"
                ),
                {"id": org},
            )
        ).one()
        assert (row.v, row.dated) == ("e2", True)
        assert row.reverify_due_on > datetime.now(UTC).date() + timedelta(days=364)
        assert await run(conn, "SELECT status::text FROM tags WHERE id = :id", id=tag) == "delivered"
        assert await run(conn, "SELECT status::text FROM org_claims WHERE id = :id", id=claim) == "approved"
        await act(conn, claimant)
        assert await run(conn, "SELECT app_is_member(:id, '{owner}')", id=org) is True
        await act(conn, admin)
        await expect(conn, decide, "not open", id=claim)


async def test_delisting_and_opt_out_and_the_held_tag_count(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        e0 = await add_org(conn)
        e1 = await add_org(conn, verification="e1")
        held = await _held_tag(conn, e0, "held_unclaimed")
        await _held_tag(conn, e1, "held_pending_verification")
        await _held_tag(conn, e1, "held_pending_verification")
        admin = await w.add_user(conn, _email("delist-admin"), "Admin", staff_role="admin")
        member = await w.add_user(conn, _email("e1-member"), "Member")
        await run(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{viewer}')",
            id=uuid7(),
            org=e1,
            u=member,
        )
        invitation = uuid7()
        await run(
            conn,
            "INSERT INTO directory_invitations (id, org_id, to_address) VALUES (:id, :org, 'info@e0.example.test')",
            id=invitation,
            org=e0,
        )
        await act(conn, member)
        assert await run(conn, "SELECT app_held_tag_count(:id)", id=e1) == 2
        assert await run(conn, "SELECT app_held_tag_count(:id)", id=e0) == 0  # not a member: nothing
        assert await run(conn, "SELECT count(*) FROM tags WHERE org_id = :id", id=e1) == 0  # held tags stay unseen
        await expect(conn, "SELECT app_delist_org(:id)", "staff admin only", id=e0)
        await act(conn, admin)
        await expect(conn, "SELECT app_delist_org(:id)", "only an unclaimed", id=e1)
        await run(conn, "SELECT app_delist_org(:id)", id=e0)
        await act(conn, member)
        assert await run(conn, "SELECT count(*) FROM organizations WHERE id = :id", id=e0) == 0  # no longer listed
        await act(conn, None)
        await run(conn, "SELECT app_opt_out_org_invitations(:id)", id=invitation)
        await as_owner(conn)
        assert await run(conn, "SELECT status::text FROM tags WHERE id = :id", id=held) == "released"
        opted = "SELECT invitations_opted_out_at IS NOT NULL FROM organizations WHERE id = :id"
        assert await run(conn, opted, id=e0) is True


async def test_llm_spend_is_a_platform_total(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        user = await w.add_user(conn, _email("llm"), "LLM")
        since = await run(conn, "SELECT now() - interval '1 second'")
        before = await run(conn, "SELECT app_llm_spend_usd(:t)", t=since)
        await run(
            conn,
            "INSERT INTO llm_calls (id, user_id, task, model, status, cost_usd) VALUES (:id, :u, 't', 'm', 'ok', 1.25)",
            id=uuid7(),
            u=user,
        )
        await act(conn, None)  # another tenant's (or no tenant's) request still sees the total, never the rows
        assert await run(conn, "SELECT count(*) FROM llm_calls WHERE user_id = :u", u=user) == 0
        assert await run(conn, "SELECT app_llm_spend_usd(:t)", t=since) - before == Decimal("1.25")
