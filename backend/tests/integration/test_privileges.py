"""AC-REPO-3, privileges half (REQ-REPO-01; docs/spec/06 6.1), the Tier-2 role memberships, ``bridge.db.as_role`` and
the privileged changes that run only through SECURITY DEFINER functions (revision 0002).

- ``has_table_privilege`` over every role of the cluster: exactly tier2_reader, provenance_worker,
  tier2_embed_worker, tier2_moderation and dsr_exporter hold SELECT on ``proposal_confidential`` (bridge_app holds no
  privilege at all), and only tier2_moderation on ``proposal_confidential_embeddings``. Superusers and the owner hold
  every privilege by definition and are left out; no other role may hold ``pg_read_all_data``.
- bridge_app is a member of each Tier-2 role WITH INHERIT FALSE, SET TRUE (PostgreSQL 16) and of nothing else, so a
  session logged in as bridge_app (``SET SESSION AUTHORIZATION`` here) can switch to a Tier-2 role and to no other.
- Each definer function checks its caller in SQL: staff decisions need the staff role (and TOTP), the OTPs are compared
  against the stored hash (D1 only from D0; codes expire by the database clock), holds only go up, approvals need the
  domain proven and set verification and create the membership, and only the verified E2 claimant or a member records
  the Master Enterprise Terms (the current version by the claimant for E2 approval).
- Registration: the database sets ``registered_at``; only ``provenance_worker`` bound to the owner fills the hashes.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import URL, CursorResult
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql.elements import TextClause

from bridge.db import TIER2_ROLES, as_role, bind_tenant
from bridge.ids import uuid7
from bridge.models.enums import VersionStatus
from bridge.proposals.models import ProposalVersion
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


async def rowcount(session: AsyncSession, statement: TextClause, params: dict[str, Any] | None = None) -> int:
    """Rows an UPDATE or DELETE matched, as a session reports it."""
    result = cast(CursorResult[Any], await session.execute(statement, params or {}))
    return result.rowcount


async def test_the_database_times_a_registration_and_only_the_bound_worker_fills_its_hashes(
    app_session_engine: AsyncEngine, developer: Developer
) -> None:
    """The app registers a version (status, cert_id) but never chooses registered_at: the trigger sets it and the ORM
    reads it back on the same flush. Only provenance_worker, bound to the owner, fills the registration hashes; the
    app role holds no UPDATE on them, and a worker bound to another user matches no row."""
    factory = async_sessionmaker(app_session_engine, expire_on_commit=False)
    digest = hashlib.sha256(b"manifest").digest()
    fill = text(
        "UPDATE proposal_versions SET content_hash = :h, prev_version_hash = :h, manifest_version = '1' WHERE id = :id"
    )
    async with factory() as session:
        await bind_tenant(session, user_id=developer.user_id)
        version = await session.get(ProposalVersion, developer.draft_version)
        assert version is not None
        version.status = VersionStatus.REGISTERED
        version.cert_id = uuid4().hex[:16]
        await session.flush()
        stamped = (
            await session.execute(
                text("SELECT registered_at, now() AS now FROM proposal_versions WHERE id = :id"), {"id": version.id}
            )
        ).one()
        assert version.registered_at == stamped.registered_at == stamped.now
        for column in ("content_hash = :h", "registered_at = now()"):
            with pytest.raises(ProgrammingError, match="permission denied"):
                async with session.begin_nested():
                    await session.execute(
                        text(f"UPDATE proposal_versions SET {column} WHERE id = :id"), {"id": version.id, "h": digest}
                    )
        await bind_tenant(session, user_id=uuid7())  # a job bound to another user sees and touches no version
        async with as_role(session, "provenance_worker"):
            assert (await session.execute(text("SELECT count(*) FROM proposal_versions"))).scalar_one() == 0
            touch_all = text("UPDATE proposal_versions SET updated_at = now()")  # no WHERE: the UPDATE policy alone
            assert await rowcount(session, touch_all) == 0
            assert await rowcount(session, fill, {"id": version.id, "h": digest}) == 0
        await bind_tenant(session, user_id=developer.user_id)
        async with as_role(session, "provenance_worker"):
            assert await rowcount(session, fill, {"id": version.id, "h": digest}) == 1
        filled = await session.execute(
            text("SELECT content_hash, manifest_version FROM proposal_versions WHERE id = :id"), {"id": version.id}
        )
        assert tuple(filled.one()) == (digest, "1")
        await session.rollback()


SUBJECT_DIGEST = "SELECT app_subject_digest(:u, uuid_send(:u))"
DIGEST_REFUSED = "only the current user's own digest"


async def test_subject_digests_are_bound_to_the_caller(
    owner_engine: AsyncEngine, app_session_engine: AsyncEngine, developer: Developer
) -> None:
    """A subject digest is a stable pseudonym of its user, so bridge_app computes only the current user's own
    (app.user_id); staff (any staff role) and the registration job (provenance_worker) compute any user's. Inside the
    SECURITY DEFINER function current_user is its owner and session_user the login role, so the job is recognised by
    the role it switched to (the ``role`` setting, which only a membership-checked SET ROLE changes): proven here on a
    session logged in as bridge_app, exactly as in production, and under the harness's SET ROLE."""
    async with owner_engine.begin() as conn:  # committed: the bridge_app session below reads them
        other = await w.add_user(conn, _email("digest-other"), "Other")
        staff = await w.add_user(conn, _email("digest-support"), "Support", staff_role="support")
        salted = "SELECT sha256(subject_salt || uuid_send(id)) FROM users WHERE id = :u"
        expected = {user: await run(conn, salted, u=user) for user in (developer.user_id, other)}

    async with as_app(owner_engine) as conn:
        await act(conn, developer.user_id)
        assert await run(conn, SUBJECT_DIGEST, u=developer.user_id) == expected[developer.user_id]
        await expect(conn, SUBJECT_DIGEST, DIGEST_REFUSED, u=other)
        await act(conn, None)  # no app.user_id: nobody's digest (the NULL-safe check)
        await expect(conn, SUBJECT_DIGEST, DIGEST_REFUSED, u=developer.user_id)
        await act(conn, staff)
        assert await run(conn, SUBJECT_DIGEST, u=other) == expected[other]
        await act(conn, developer.user_id)
        await conn.execute(text("SET LOCAL ROLE provenance_worker"))
        assert await run(conn, SUBJECT_DIGEST, u=other) == expected[other]
        assert await run(conn, SUBJECT_DIGEST, u=uuid7()) is None  # an unknown user

    factory = async_sessionmaker(app_session_engine, expire_on_commit=False)
    digest = text(SUBJECT_DIGEST)
    async with factory() as session:
        await bind_tenant(session, user_id=developer.user_id)
        assert (await session.execute(text("SELECT session_user"))).scalar_one() == "bridge_app"
        assert (await session.execute(digest, {"u": developer.user_id})).scalar_one() == expected[developer.user_id]
        with pytest.raises(DBAPIError, match=DIGEST_REFUSED):
            async with session.begin_nested():
                await session.execute(digest, {"u": other})
        async with as_role(session, "provenance_worker"):
            assert (await session.execute(digest, {"u": other})).scalar_one() == expected[other]
        with pytest.raises(DBAPIError, match=DIGEST_REFUSED):  # back as bridge_app: bound again
            async with session.begin_nested():
                await session.execute(digest, {"u": other})
        await session.rollback()


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


PHONE_CODE = (
    "INSERT INTO phone_verifications (id, user_id, phone_e164, otp_hash, expires_at)"
    " VALUES (:id, :u, :phone, :h, now() + interval '10 minutes')"
)


async def _phone_code(conn: AsyncConnection, user: UUID, otp_hash: bytes, phone: str = "+254712345678") -> UUID:
    code = uuid7()
    await run(conn, PHONE_CODE, id=code, u=user, phone=phone, h=otp_hash)
    return code


async def test_phone_otp_is_compared_in_sql_and_raises_d0_to_d1(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    right, wrong = otp
    level = "SELECT verification_level::text FROM developer_profiles WHERE user_id = :u"
    attempts = "SELECT attempts, verified_at IS NOT NULL AS verified FROM phone_verifications WHERE id = :id"
    async with as_app(owner_engine) as conn:
        user = await w.add_user(conn, _email("phone"), "Phone")
        other = await w.add_user(conn, _email("other"), "Other")
        locked_user = await w.add_user(conn, _email("locked"), "Locked")
        no_profile = await w.add_user(conn, _email("no-profile"), "No profile")
        for developer in (user, locked_user):
            await run(
                conn,
                "INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)",
                u=developer,
                h=f"h{developer.hex}",
            )
        await act(conn, user)
        code = await _phone_code(conn, user, right)
        second = await _phone_code(conn, user, right, phone="+254722000000")  # another number, still open
        await expect(conn, "UPDATE phone_verifications SET verified_at = now()", "permission denied")
        await expect(conn, "UPDATE developer_profiles SET verification_level = 'd1'", "permission denied")
        confirm = "SELECT app_confirm_phone_otp(:id, :h)"
        assert await run(conn, confirm, id=code, h=wrong) is False
        assert await run(conn, level, u=user) == "d0"
        assert await run(conn, confirm, id=code, h=right) is True
        assert await run(conn, level, u=user) == "d1"
        assert tuple((await conn.execute(text(attempts), {"id": code})).one()) == (2, True)
        assert await run(conn, confirm, id=code, h=right) is False  # a code confirms once
        # Once D1, a second open code never verifies too; the attempt is still counted.
        assert await run(conn, confirm, id=second, h=right) is False
        assert tuple((await conn.execute(text(attempts), {"id": second})).one()) == (1, False)
        await act(conn, other)
        await expect(conn, confirm, "no such code for the current user", id=code, h=right)
        # Five wrong attempts lock a code, even against the right one afterwards.
        await act(conn, locked_user)
        locked = await _phone_code(conn, locked_user, right)
        for _ in range(5):
            assert await run(conn, confirm, id=locked, h=wrong) is False
        assert await run(conn, confirm, id=locked, h=right) is False
        assert await run(conn, level, u=locked_user) == "d0"
        # Without a developer profile there is nothing to raise: no code verifies.
        await act(conn, no_profile)
        orphan = await _phone_code(conn, no_profile, right)
        assert await run(conn, confirm, id=orphan, h=right) is False
        assert tuple((await conn.execute(text(attempts), {"id": orphan})).one()) == (1, False)


async def test_a_phone_code_expires_ten_minutes_after_it_is_stored(owner_engine: AsyncEngine) -> None:
    """The database sets expires_at (trigger): a later expiry sent by the application, or none, gives now() + 10 min,
    for every role."""
    ttl = "SELECT expires_at - now() FROM phone_verifications WHERE id = :id"
    async with as_app(owner_engine) as conn:
        user = await w.add_user(conn, _email("expiry"), "Expiry")
        await act(conn, user)
        codes = [uuid7() for _ in range(3)]
        insert = (
            "INSERT INTO phone_verifications (id, user_id, phone_e164, otp_hash{col})"
            " VALUES (:id, :u, '+254712345678', :h{val})"
        )
        await run(
            conn, insert.format(col=", expires_at", val=", now() + interval '1 day'"), id=codes[0], u=user, h=bytes(32)
        )
        await run(conn, insert.format(col="", val=""), id=codes[1], u=user, h=bytes(32))
        await as_owner(conn)
        await run(
            conn, insert.format(col=", expires_at", val=", now() + interval '1 year'"), id=codes[2], u=user, h=bytes(32)
        )
        for code in codes:
            assert await run(conn, ttl, id=code) == timedelta(minutes=10)


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
        for caller in (stranger, None):  # None: no app.user_id at all (the NULL-safe checks)
            await act(conn, caller)
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


# What the app's DNS-check code calls once it has resolved the claim's TXT record (the lookup itself is app-side).
MARK_DNS = "SELECT app_mark_claim_dns_verified(:id)"


async def _claim(conn: AsyncConnection, org: UUID, claimant: UUID, domain: str, level: str, otp_hash: bytes) -> UUID:
    claim = uuid7()
    await run(
        conn,
        "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status, otp_hash,"
        " otp_expires_at, dns_token) VALUES (:id, :org, :u, :d, :e, CAST(:level AS claim_level), 'otp_sent', :h,"
        " now() + interval '10 minutes', :token)",
        id=claim,
        token=f"bridge-verify-{claim.hex}",
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
        assert await run(conn, MARK_DNS, id=claim) is True
        await run(conn, "UPDATE org_claims SET status = 'dns_pending' WHERE id = :id", id=claim)
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
        assert await run(conn, MARK_DNS, id=other) is True
        assert await run(conn, approve, id=other) == "pending_review"
        assert (
            await run(conn, "SELECT verification::text FROM organizations WHERE id = :id", id=lookalike) == "unclaimed"
        )
        # A claim on an E2 organisation becomes a dispute, never a transfer (AC-DIR-2).
        dispute = await _claim(conn, verified, claimant, "verified.example.test", "e1", right)
        assert await run(conn, "SELECT app_confirm_claim_otp(:id, :h)", id=dispute, h=right) is True
        assert await run(conn, MARK_DNS, id=dispute) is True
        assert await run(conn, approve, id=dispute) == "disputed"
        assert await run(conn, "SELECT app_is_member(:id)", id=verified) is False


async def test_claim_otp_attempts_never_reset_and_reissues_are_capped(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    """The app cannot touch the OTP columns. app_reissue_claim_otp() replaces the code but keeps the cumulative
    attempt count (budget: 5 attempts per code issued); after 5 reissues the claim goes to manual review. A new claim
    cannot reset the limits: one open claim per claimant and organisation, one new claim per 24 hours."""
    right, wrong = otp
    fresh = hashlib.sha256(b"111111").digest()
    confirm = "SELECT app_confirm_claim_otp(:id, :h)"
    reissue = "SELECT app_reissue_claim_otp(:id, :h, now() + interval '10 minutes')"
    counters = "SELECT otp_attempts, otp_reissues, status::text AS status FROM org_claims WHERE id = :id"
    async with as_app(owner_engine) as conn:
        org = await add_org(conn, official_domains="{capped.example.test}")
        other_org = await add_org(conn)
        claimant = await w.add_user(conn, _email("otp-claimant"), "Claimant")
        stranger = await w.add_user(conn, _email("otp-stranger"), "Stranger")
        await act(conn, claimant)
        claim = await _claim(conn, org, claimant, "capped.example.test", "e1", right)
        for column in ("otp_attempts = 0", "otp_reissues = 0", "otp_hash = NULL", "otp_expires_at = now()"):
            await expect(conn, f"UPDATE org_claims SET {column} WHERE id = :id", "permission denied", id=claim)

        for _ in range(5):
            assert await run(conn, confirm, id=claim, h=wrong) is False
        assert await run(conn, confirm, id=claim, h=right) is False  # the first code's 5 attempts are spent
        assert await run(conn, reissue, id=claim, h=fresh) is True
        assert tuple((await conn.execute(text(counters), {"id": claim})).one()) == (5, 1, "otp_sent")  # kept
        assert await run(conn, confirm, id=claim, h=right) is False  # the old code is gone
        assert await run(conn, confirm, id=claim, h=fresh) is True
        assert tuple((await conn.execute(text(counters), {"id": claim})).one()) == (7, 1, "otp_sent")
        await expect(conn, reissue, "not waiting for an email code", id=claim, h=fresh)  # already verified

        capped = await _claim(conn, other_org, claimant, "other.example.test", "e1", right)
        for expiry in ("now() + interval '2 hours'", "now() - interval '1 minute'"):
            await expect(
                conn,
                f"SELECT app_reissue_claim_otp(:id, :h, {expiry})",
                "an expiry within the next hour",
                id=capped,
                h=fresh,
            )
        await expect(conn, reissue, "32-byte code digest", id=capped, h=b"short")
        for _ in range(5):
            assert await run(conn, reissue, id=capped, h=fresh) is True
        assert await run(conn, reissue, id=capped, h=fresh) is False  # the sixth: no code, manual review instead
        assert tuple((await conn.execute(text(counters), {"id": capped})).one()) == (0, 5, "pending_review")
        await act(conn, stranger)
        await expect(conn, reissue, "no such claim for the current user", id=capped, h=fresh)

        await act(conn, claimant)
        await run(conn, "UPDATE org_claims SET status = 'withdrawn' WHERE id = :id", id=capped)
        await expect(
            conn,
            "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status)"
            " VALUES (:id, :org, :u, 'other.example.test', 'info@other.example.test', 'e1', 'otp_sent')",
            "one claim per claimant and organisation per 24 hours",
            id=uuid7(),
            org=other_org,
            u=claimant,
        )
        # After the cooldown a new claim is possible, but never a second open one.
        await as_owner(conn)
        await run(
            conn,
            "UPDATE org_claims SET created_at = now() - interval '2 days', status = 'pending_review' WHERE id = :id",
            id=capped,
        )
        await act(conn, claimant)
        again = uuid7()
        new_claim = (
            "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status)"
            " VALUES (:id, :org, :u, 'other.example.test', 'info@other.example.test', 'e1', 'otp_sent')"
        )
        await expect(conn, new_claim, "uq_org_claims_open_claimant_org", id=again, org=other_org, u=claimant)
        await run(conn, "UPDATE org_claims SET status = 'withdrawn' WHERE id = :id", id=capped)
        await run(conn, new_claim, id=again, org=other_org, u=claimant)


async def test_dns_verification_is_marked_only_through_the_function_and_the_token_is_write_once(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    """bridge_app cannot set dns_verified_at or change dns_token (the token is written with the claim):
    app_mark_claim_dns_verified() marks the claimant's own open claim with a token once the app has resolved the TXT
    record. Once set, the token and the verification time never change, for any role."""
    right, _ = otp
    async with as_app(owner_engine) as conn:
        org, tokenless_org, withdrawn_org = await add_org(conn), await add_org(conn), await add_org(conn)
        claimant = await w.add_user(conn, _email("dns-claimant"), "Claimant")
        stranger = await w.add_user(conn, _email("dns-stranger"), "Stranger")
        await act(conn, claimant)
        claim = await _claim(conn, org, claimant, "dns.example.test", "e1", right)
        for column in ("dns_verified_at = now()", "dns_token = 'mine'", "dns_verified_at = NULL"):
            await expect(conn, f"UPDATE org_claims SET {column} WHERE id = :id", "permission denied", id=claim)
        await act(conn, stranger)
        await expect(conn, MARK_DNS, "no such claim for the current user", id=claim)
        await act(conn, claimant)
        assert await run(conn, MARK_DNS, id=claim) is True
        assert await run(conn, MARK_DNS, id=claim) is False  # already verified: nothing changes
        tokenless = uuid7()
        await run(
            conn,
            "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status)"
            " VALUES (:id, :org, :u, 'dns.example.test', 'info@dns.example.test', 'e1', 'otp_sent')",
            id=tokenless,
            org=tokenless_org,
            u=claimant,
        )
        await expect(conn, MARK_DNS, "no DNS token", id=tokenless)
        withdrawn = await _claim(conn, withdrawn_org, claimant, "dns.example.test", "e1", right)
        await run(conn, "UPDATE org_claims SET status = 'withdrawn' WHERE id = :id", id=withdrawn)
        await expect(conn, MARK_DNS, "not open", id=withdrawn)
        await as_owner(conn)  # the trigger holds for every role
        later = "dns_verified_at = now() + interval '1 minute'"  # now() is the transaction's: the marked time
        for column in ("dns_token = 'other'", "dns_token = NULL", later, "dns_verified_at = NULL"):
            await expect(conn, f"UPDATE org_claims SET {column} WHERE id = :id", "write-once", id=claim)
        await run(conn, "UPDATE org_claims SET dns_token = 'late' WHERE id = :id", id=tokenless)  # a first write


MET_ACCEPTANCE = (
    "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
    " SELECT :id, :org, :u, id, sha256 FROM legal_templates WHERE id = :t"
)


async def add_legal_template(conn: AsyncConnection, kind: str) -> UUID:
    """As the owner: a new (so current) placeholder version of a legal template kind."""
    template = uuid7()
    await run(
        conn,
        "INSERT INTO legal_templates (id, kind, version, body, sha256) VALUES (:id, CAST(:kind AS legal_template_kind),"
        " :version, :body, sha256(convert_to(:body, 'UTF8')))",
        id=template,
        kind=kind,
        version=f"t-{template.hex[-12:]}",
        body=f"[[LEGAL-PLACEHOLDER:{kind}-{template.hex}]]\n",
    )
    return template


async def test_only_a_verified_e2_claimant_or_a_member_accepts_terms_for_an_organisation(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    """Acceptances are permanent evidence, so an outsider must never write one for an organisation. Besides its owners,
    admins and signatories, only the claimant of their own open E2 claim with a verified email code, on an
    organisation that is not E2 yet, may accept, and only the Master Enterprise Terms."""
    right, _ = otp
    async with as_app(owner_engine) as conn:
        unclaimed = await add_org(conn)
        verified = await add_org(conn, verification="e2")
        met = await add_legal_template(conn, "master_enterprise_terms")
        tos = await add_legal_template(conn, "tos")
        stranger = await w.add_user(conn, _email("terms-stranger"), "Stranger")
        claimant = await w.add_user(conn, _email("terms-claimant"), "Claimant")
        e1_claimant = await w.add_user(conn, _email("terms-e1"), "E1 claimant")
        confirm = "SELECT app_confirm_claim_otp(:id, :h)"
        refused = "row-level security"

        await act(conn, stranger)
        await expect(conn, MET_ACCEPTANCE, refused, id=uuid7(), org=unclaimed, u=stranger, t=met)
        await act(conn, claimant)
        claim = await _claim(conn, unclaimed, claimant, "terms.example.test", "e2", right)
        await expect(conn, MET_ACCEPTANCE, refused, id=uuid7(), org=unclaimed, u=claimant, t=met)  # code unverified
        assert await run(conn, confirm, id=claim, h=right) is True
        await expect(conn, MET_ACCEPTANCE, refused, id=uuid7(), org=unclaimed, u=claimant, t=tos)  # terms only
        await run(conn, MET_ACCEPTANCE, id=uuid7(), org=unclaimed, u=claimant, t=met)
        # A verified E1 claim is no E2 claim, and an organisation that is already E2 is disputed, never re-signed.
        await act(conn, e1_claimant)
        e1_claim = await _claim(conn, unclaimed, e1_claimant, "terms.example.test", "e1", right)
        assert await run(conn, confirm, id=e1_claim, h=right) is True
        await expect(conn, MET_ACCEPTANCE, refused, id=uuid7(), org=unclaimed, u=e1_claimant, t=met)
        await act(conn, claimant)
        on_e2 = await _claim(conn, verified, claimant, "verified.example.test", "e2", right)
        assert await run(conn, confirm, id=on_e2, h=right) is True
        await expect(conn, MET_ACCEPTANCE, refused, id=uuid7(), org=verified, u=claimant, t=met)


async def test_e2_approval_is_staff_admin_only_needs_the_terms_and_delivers_held_tags(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    """E2 needs the current Master Enterprise Terms accepted by the claimant: not by another member, and not a
    superseded version."""
    right, _ = otp
    decide = "SELECT app_decide_claim(:id, true, 'documents checked')"
    async with as_app(owner_engine) as conn:
        org = await add_org(conn, verification="e1")
        tag = await _held_tag(conn, org, "held_pending_verification")
        admin = await w.add_user(conn, _email("claims-admin"), "Admin", staff_role="admin")
        moderator = await w.add_user(conn, _email("claims-mod"), "Moderator", staff_role="moderator")
        claimant = await w.add_user(conn, _email("signatory"), "Signatory")
        owner = await w.add_user(conn, _email("e1-owner"), "Owner")
        await run(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{owner,admin}')",
            id=uuid7(),
            org=org,
            u=owner,
        )
        superseded = await add_legal_template(conn, "master_enterprise_terms")
        await act(conn, claimant)
        claim = await _claim(conn, org, claimant, "signatory.example.test", "e2", right)
        assert await run(conn, "SELECT app_confirm_claim_otp(:id, :h)", id=claim, h=right) is True
        assert await run(conn, MARK_DNS, id=claim) is True
        await run(conn, "UPDATE org_claims SET status = 'pending_review' WHERE id = :id", id=claim)
        await act(conn, moderator)
        await expect(conn, decide, "staff admin only", id=claim)
        await act(conn, admin)
        await expect(conn, decide, "Master Enterprise Terms", id=claim)
        # Another member's acceptance is not the claimant's.
        await act(conn, owner)
        await run(conn, MET_ACCEPTANCE, id=uuid7(), org=org, u=owner, t=superseded)
        await act(conn, admin)
        await expect(conn, decide, "Master Enterprise Terms", id=claim)
        # The claimant of an open E2 claim may accept the terms before being a member; a newer version supersedes it.
        await act(conn, claimant)
        await run(conn, MET_ACCEPTANCE, id=uuid7(), org=org, u=claimant, t=superseded)
        await as_owner(conn)
        current = await add_legal_template(conn, "master_enterprise_terms")
        await act(conn, admin)
        await expect(conn, decide, "Master Enterprise Terms", id=claim)
        await act(conn, claimant)
        await run(conn, MET_ACCEPTANCE, id=uuid7(), org=org, u=claimant, t=current)
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


async def test_staff_approval_needs_the_claimed_domain_proven(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    """Staff approve a claim (E1 or E2) only once the email code and the DNS TXT record are verified; for E2 an active
    owner, admin or signatory of an organisation already E1 on the claimed domain needs neither again."""
    right, _ = otp
    decide = "SELECT app_decide_claim(:id, true, 'reviewed')"
    unproven = "domain is not proven"
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("proof-admin"), "Admin", staff_role="admin")
        unclaimed = await add_org(conn)
        capped_org = await add_org(conn)
        e1 = await add_org(conn, verification="e1")
        await run(conn, "UPDATE organizations SET verified_domain = 'e1.example.test' WHERE id = :id", id=e1)
        claimant = await w.add_user(conn, _email("prover"), "Prover")
        outsider = await w.add_user(conn, _email("outsider"), "Outsider")
        owner = await w.add_user(conn, _email("e1-owner"), "Owner")
        await run(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{owner,admin}')",
            id=uuid7(),
            org=e1,
            u=owner,
        )
        met = await add_legal_template(conn, "master_enterprise_terms")
        # An E2 claim on an unclaimed organisation: refused until both the code and the DNS record are verified.
        await act(conn, claimant)
        claim = await _claim(conn, unclaimed, claimant, "prover.example.test", "e2", right)
        await act(conn, admin)
        await expect(conn, decide, unproven, id=claim)
        await act(conn, claimant)
        assert await run(conn, "SELECT app_confirm_claim_otp(:id, :h)", id=claim, h=right) is True
        await run(conn, MET_ACCEPTANCE, id=uuid7(), org=unclaimed, u=claimant, t=met)
        await act(conn, admin)
        await expect(conn, decide, unproven, id=claim)  # the DNS TXT record is still missing
        await act(conn, claimant)
        assert await run(conn, MARK_DNS, id=claim) is True
        await act(conn, admin)
        await run(conn, decide, id=claim)
        # An E1 claim sent to manual review without a verified code (reissues spent) is never approved.
        await act(conn, claimant)
        capped = await _claim(conn, capped_org, claimant, "prover.example.test", "e1", right)
        await run(conn, "UPDATE org_claims SET status = 'pending_review' WHERE id = :id", id=capped)
        await act(conn, admin)
        await expect(conn, decide, unproven, id=capped)
        # E2 for an organisation already E1 on the claimed domain: its owner needs no new proof, an outsider does.
        for user in (outsider, owner):
            await act(conn, user)
            e2_claim = await _claim(conn, e1, user, "e1.example.test", "e2", right)
            if user == owner:
                await run(conn, MET_ACCEPTANCE, id=uuid7(), org=e1, u=owner, t=met)
            await act(conn, admin)
            if user == outsider:
                await expect(conn, decide, unproven, id=e2_claim)
            else:
                await run(conn, decide, id=e2_claim)
        await as_owner(conn)
        assert await run(conn, "SELECT verification::text FROM organizations WHERE id = :id", id=e1) == "e2"


async def _prove_domain(conn: AsyncConnection, claim: UUID, otp_hash: bytes) -> None:
    """As the claimant: the claim's email code and DNS TXT record verified."""
    assert await run(conn, "SELECT app_confirm_claim_otp(:id, :h)", id=claim, h=otp_hash) is True
    assert await run(conn, MARK_DNS, id=claim) is True


async def _add_membership(conn: AsyncConnection, org: UUID, user: UUID, roles: str) -> UUID:
    membership = uuid7()
    await run(
        conn,
        "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, CAST(:roles AS org_role[]))",
        id=membership,
        org=org,
        u=user,
        roles=roles,
    )
    return membership


@pytest.mark.parametrize("level", ["e1", "e2"])
async def test_an_upheld_dispute_transfers_the_organisation(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes], level: str
) -> None:
    """Competing claims go to dispute review, never an automatic transfer (docs/spec/06 6.2, AC-DIR-2); staff admin
    upholding the dispute transfers the organisation in the same statement: the earlier claimant's approved claim is
    rejected, naming the claim that superseded it, and their membership is removed, so they can no longer remove the
    new owner. Other members stay."""
    right, _ = otp
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("dispute-admin"), "Admin", staff_role="admin")
        org = await add_org(conn, official_domains="{first.example.test}")
        first = await w.add_user(conn, _email("first"), "First claimant")
        second = await w.add_user(conn, _email("second"), "Second claimant")
        reviewer = await w.add_user(conn, _email("dispute-reviewer"), "Reviewer")
        met = await add_legal_template(conn, "master_enterprise_terms")
        await act(conn, first)  # E1 at once on an official domain; the owner then invites a reviewer
        earlier = await _claim(conn, org, first, "first.example.test", "e1", right)
        await _prove_domain(conn, earlier, right)
        assert await run(conn, "SELECT app_approve_claim_e1(:id)::text", id=earlier) == "approved"
        await _add_membership(conn, org, reviewer, "{reviewer}")
        await act(conn, second)  # another domain, proven, and the claim disputed
        disputed = await _claim(conn, org, second, "second.example.test", level, right)
        await _prove_domain(conn, disputed, right)
        if level == "e2":
            await run(conn, MET_ACCEPTANCE, id=uuid7(), org=org, u=second, t=met)
        await run(conn, "UPDATE org_claims SET status = 'disputed' WHERE id = :id", id=disputed)
        await act(conn, admin)
        await run(conn, "SELECT app_decide_claim(:id, true, 'dispute upheld')", id=disputed)

        await as_owner(conn)
        claims = await conn.execute(
            text("SELECT id, status::text AS status, decision_reason FROM org_claims WHERE org_id = :org"), {"org": org}
        )
        assert {row.id: (row.status, row.decision_reason) for row in claims.all()} == {
            earlier: ("rejected", f"superseded by claim {disputed} (dispute upheld)"),
            disputed: ("approved", "dispute upheld"),
        }
        members = await conn.execute(
            text("SELECT user_id, status::text AS status FROM memberships WHERE org_id = :org"), {"org": org}
        )
        assert {row.user_id: row.status for row in members.all()} == {
            first: "removed",
            second: "active",
            reviewer: "active",  # other members stay; staff correct them with app_staff_remove_membership()
        }
        verified = "SELECT verification::text, verified_domain::text FROM organizations WHERE id = :id"
        assert tuple((await conn.execute(text(verified), {"id": org})).one()) == (level, "second.example.test")
        await act(conn, first)
        assert await run(conn, "SELECT app_is_member(:id)", id=org) is False
        removal = await conn.execute(
            text("UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :u"),
            {"org": org, "u": second},
        )
        assert removal.rowcount == 0
        await act(conn, second)
        assert await run(conn, "SELECT app_is_member(:id, '{owner,admin}')", id=org) is True


async def test_staff_admin_removes_a_membership_with_a_reason(owner_engine: AsyncEngine) -> None:
    """Staff correct an organisation's roster (e.g. after an upheld dispute) through app_staff_remove_membership():
    staff admin only, with a reason for the caller's audit event; removing is idempotent and keeps the row."""
    remove = "SELECT app_staff_remove_membership(:id, :reason)"
    async with as_app(owner_engine) as conn:
        org = await add_org(conn, verification="e1")
        admin = await w.add_user(conn, _email("roster-admin"), "Admin", staff_role="admin")
        moderator = await w.add_user(conn, _email("roster-mod"), "Moderator", staff_role="moderator")
        owner = await w.add_user(conn, _email("roster-owner"), "Owner")
        member = await w.add_user(conn, _email("roster-member"), "Member")
        await _add_membership(conn, org, owner, "{owner,admin}")
        membership = await _add_membership(conn, org, member, "{owner,signatory}")
        for caller in (owner, moderator, None):  # not the organisation's owner either: its own roster rules apply
            await act(conn, caller)
            await expect(conn, remove, "staff admin only", id=membership, reason="dispute upheld")
        await act(conn, admin)
        for reason in (None, "  "):
            await expect(conn, remove, "a reason is required", id=membership, reason=reason)
        await expect(conn, remove, "no such membership", id=uuid7(), reason="dispute upheld")
        assert await run(conn, remove, id=membership, reason="dispute upheld") is True
        assert await run(conn, remove, id=membership, reason="dispute upheld") is False  # already removed
        await act(conn, member)
        assert await run(conn, "SELECT app_is_member(:id)", id=org) is False
        await act(conn, owner)
        assert await run(conn, "SELECT app_is_member(:id, '{owner}')", id=org) is True


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


TAG = (
    "INSERT INTO tags (id, proposal_id, org_id, developer_id, status)"
    " VALUES (:id, :p, :org, :dev, CAST(:status AS tag_status))"
)


async def test_one_open_tag_per_developer_and_org_and_a_closed_tag_never_reopens(owner_engine: AsyncEngine) -> None:
    """ "One open engagement or held tag per (developer, org)" (docs/spec/06 6.3) is uq_tags_open_developer_org over
    closed_at IS NULL. Withdrawing closes a tag; app_close_tag closes one without changing its status (the developer,
    or a member of the organisation for a delivered tag: Phase 3 closes tags when the engagement ends); the app never
    sets closed_at itself and nothing reopens a tag."""
    async with as_app(owner_engine) as conn:
        unclaimed = await add_org(conn)
        e1 = await add_org(conn, verification="e1")
        e2 = await add_org(conn, verification="e2")
        developer = await w.add_user(conn, _email("tagger"), "Developer")
        stranger = await w.add_user(conn, _email("tag-stranger"), "Stranger")
        members = {org: await w.add_user(conn, _email("tag-member"), "Member") for org in (e1, e2)}
        for org, member in members.items():
            await run(
                conn,
                "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, '{reviewer}')",
                id=uuid7(),
                org=org,
                u=member,
            )
        niche = uuid7()
        await run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Tags')", id=niche, s=f"t-{niche.hex}")
        problem = await w.add_problem(conn, developer, niche)
        proposal, _ = await w.add_proposal(conn, developer, niche, problem)
        closed = "SELECT closed_at IS NOT NULL FROM tags WHERE id = :id"

        await act(conn, developer)
        first = uuid7()
        await run(conn, TAG, id=first, p=proposal, org=unclaimed, dev=developer, status="held_unclaimed")
        again = {"p": proposal, "org": unclaimed, "dev": developer, "status": "held_unclaimed"}
        await expect(conn, TAG, "uq_tags_open_developer_org", id=uuid7(), **again)
        await expect(conn, "UPDATE tags SET closed_at = now() WHERE id = :id", "permission denied", id=first)
        await run(conn, "UPDATE tags SET status = 'withdrawn' WHERE id = :id", id=first)
        assert await run(conn, closed, id=first) is True  # withdrawing closed it
        await run(conn, TAG, id=uuid7(), **again)  # so the organisation can be tagged again

        await as_owner(conn)  # the trigger holds for every role
        await expect(conn, "UPDATE tags SET closed_at = NULL WHERE id = :id", "never reopens", id=first)
        await expect(conn, "UPDATE tags SET status = 'held_unclaimed' WHERE id = :id", "never reopens", id=first)
        await run(conn, "UPDATE tags SET status = 'released' WHERE id = :id", id=first)  # closing to closing is fine
        await expect(
            conn,
            "INSERT INTO tags (id, proposal_id, org_id, developer_id, status) VALUES (:id, :p, :org, :dev, 'expired')",
            "ck_tags_closing_statuses_are_closed",
            id=uuid7(),
            p=proposal,
            org=e1,
            dev=developer,
        )

        await act(conn, developer)
        delivered, held = uuid7(), uuid7()
        await run(conn, TAG, id=delivered, p=proposal, org=e2, dev=developer, status="delivered")
        await run(conn, TAG, id=held, p=proposal, org=e1, dev=developer, status="held_pending_verification")
        close = "SELECT app_close_tag(:id)"
        for caller in (stranger, members[e1], None):  # a held tag is not the organisation's to close
            await act(conn, caller)
            await expect(conn, close, "the developer or a member of the tagged organisation", id=delivered)
            await expect(conn, close, "the developer or a member of the tagged organisation", id=held)
        await act(conn, members[e2])  # the organisation's side ends it (e.g. a decline in Phase 3)
        assert await run(conn, close, id=delivered) is True
        assert await run(conn, close, id=delivered) is False  # already closed
        await act(conn, developer)
        assert await run(conn, "SELECT status::text FROM tags WHERE id = :id", id=delivered) == "delivered"
        assert await run(conn, closed, id=delivered) is True
        await run(conn, TAG, id=uuid7(), p=proposal, org=e2, dev=developer, status="delivered")  # tag again
        assert await run(conn, close, id=held) is True  # the developer closes their own held tag
        await act(conn, members[e1])
        assert await run(conn, "SELECT app_held_tag_count(:id)", id=e1) == 0  # closed tags are not counted


async def test_the_provenance_worker_reads_every_chain_head_and_nothing_more(owner_engine: AsyncEngine) -> None:
    """The hourly anchor job (REQ-AUD-01) gets the head (seq, event_hash) of every audit chain from
    app_audit_chain_heads(); provenance_worker cannot read audit_events itself, and no other role may call it."""
    chains = [f"test:{uuid4().hex}" for _ in range(2)]
    async with as_app(owner_engine) as conn:
        for chain, count in zip(chains, (1, 3), strict=True):
            for _ in range(count):
                await run(
                    conn,
                    "INSERT INTO audit_events (id, chain_id, actor_kind, action)"
                    " VALUES (:id, :c, 'system', 'test.head')",
                    id=uuid7(),
                    c=chain,
                )
        last = await conn.execute(
            text(
                "SELECT DISTINCT ON (chain_id) chain_id, seq, event_hash FROM audit_events"
                " WHERE chain_id = ANY (:c) ORDER BY chain_id, seq DESC"
            ),
            {"c": chains},
        )
        expected = {row.chain_id: (row.seq, row.event_hash) for row in last.all()}
        assert {chain: seq for chain, (seq, _) in expected.items()} == {chains[0]: 1, chains[1]: 3}
        heads = "SELECT chain_id, seq, event_hash FROM app_audit_chain_heads() WHERE chain_id = ANY (:c)"
        for role in ("bridge_app", "audit_reader", "aggregate_worker", "tier2_reader", "dsr_exporter"):
            await conn.execute(text(f"SET LOCAL ROLE {role}"))
            await expect(conn, heads, "permission denied", c=chains)
        await conn.execute(text("SET LOCAL ROLE provenance_worker"))
        found = (await conn.execute(text(heads), {"c": chains})).all()
        assert {row.chain_id: (row.seq, row.event_hash) for row in found} == expected
        await expect(conn, "SELECT 1 FROM audit_events", "permission denied")


async def test_staff_admin_adds_a_niche_without_a_deploy(owner_engine: AsyncEngine) -> None:
    """AC-DIR-5 (the database half of the admin route): app_add_niche() is staff admin only, adds a top-level niche or
    a child of an active top-level one (two levels), refuses a taken or malformed slug, and the app reads the new niche
    at once."""
    tag = uuid4().hex[:10]
    add = "SELECT app_add_niche(:slug, :name, :parent, :isic)"
    niche = "SELECT slug, name_en, parent_id, isic_code, active FROM niches WHERE id = :id"
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("niche-admin"), "Admin", staff_role="admin")
        moderator = await w.add_user(conn, _email("niche-mod"), "Moderator", staff_role="moderator")
        developer = await w.add_user(conn, _email("niche-dev"), "Developer")
        retired = f"retired-{tag}"
        await run(
            conn,
            "INSERT INTO niches (id, slug, name_en, active) VALUES (:id, :s, 'Retired', false)",
            id=uuid7(),
            s=retired,
        )
        top = {"slug": f"water-{tag}", "name": " Water & sanitation ", "parent": None, "isic": "E36"}
        for caller in (developer, moderator, None):
            await act(conn, caller)
            await expect(conn, add, "staff admin only", **top)
        await act(conn, admin)
        parent = await run(conn, add, **top)
        row = (await conn.execute(text(niche), {"id": parent})).one()
        assert tuple(row) == (top["slug"], "Water & sanitation", None, "E36", True)
        child = await run(conn, add, slug=f"water-kiosks-{tag}", name="Water kiosks", parent=top["slug"], isic=None)
        assert (await conn.execute(text(niche), {"id": child})).one().parent_id == parent
        refusals = (
            ({"slug": top["slug"], "name": "Again", "parent": None, "isic": None}, "the slug is taken"),
            ({"slug": f"deep-{tag}", "name": "Deep", "parent": f"water-kiosks-{tag}", "isic": None}, "top-level"),
            ({"slug": f"under-retired-{tag}", "name": "Orphan", "parent": retired, "isic": None}, "top-level"),
            ({"slug": f"lost-{tag}", "name": "Lost", "parent": f"missing-{tag}", "isic": None}, "no such parent"),
            ({"slug": f"Bad Slug {tag}", "name": "Bad", "parent": None, "isic": None}, "lower-case"),
            ({"slug": f"blank-{tag}", "name": "  ", "parent": None, "isic": None}, "English name"),
            ({"slug": f"isic-{tag}", "name": "ISIC", "parent": None, "isic": "k64; drop"}, "ISIC code"),
        )
        for params, refusal in refusals:
            await expect(conn, add, refusal, **params)
        await act(conn, developer)  # selectable at once: every signed-in user reads niches
        assert await run(conn, "SELECT count(*) FROM niches WHERE id = ANY (:ids)", ids=[parent, child]) == 2
        await expect(
            conn,
            "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Direct')",
            "permission denied",
            id=uuid7(),
            s=f"direct-{tag}",
        )


async def test_llm_call_inputs_are_read_by_staff_admin_only(owner_engine: AsyncEngine) -> None:
    """A user reads their call rows but not the sanitised inputs; staff admin reads those through the function."""
    async with as_app(owner_engine) as conn:
        user = await w.add_user(conn, _email("llm-inputs"), "LLM")
        admin = await w.add_user(conn, _email("llm-admin"), "Admin", staff_role="admin")
        moderator = await w.add_user(conn, _email("llm-mod"), "Moderator", staff_role="moderator")
        call = uuid7()
        await act(conn, user)
        await run(
            conn,
            "INSERT INTO llm_calls (id, user_id, task, model, status, inputs)"
            " VALUES (:id, :u, 't', 'm', 'ok', CAST(:inputs AS jsonb))",
            id=call,
            u=user,
            inputs='{"title": "Solar cold rooms"}',
        )
        assert await run(conn, "SELECT task FROM llm_calls WHERE id = :id", id=call) == "t"
        await expect(conn, "SELECT inputs FROM llm_calls WHERE id = :id", "permission denied", id=call)
        read = "SELECT app_llm_call_inputs(:id)"
        for caller in (user, moderator, None):
            await act(conn, caller)
            await expect(conn, read, "staff admin only", id=call)
        await act(conn, admin)
        assert await run(conn, read, id=call) == {"title": "Solar cold rooms"}
        assert await run(conn, read, id=uuid7()) is None


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
