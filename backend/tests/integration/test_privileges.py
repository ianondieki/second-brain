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
    draft_proposal: UUID
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
        draft_proposal, draft_version = await w.add_proposal(conn, user, niche, problem, registered=False)
    return Developer(user, published_version, draft_proposal, draft_version)


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
    """The app registers a version (status, cert_id) but never chooses registered_at or the handle it is shown under:
    the trigger sets both (the owner's developer handle, never another developer's) and the ORM reads them back on the
    same flush. Only provenance_worker, bound to the owner, fills the registration hashes; the app role holds no UPDATE
    on them, and a worker bound to another user matches no row."""
    factory = async_sessionmaker(app_session_engine, expire_on_commit=False)
    digest = hashlib.sha256(b"manifest").digest()
    fill = text(
        "UPDATE proposal_versions SET content_hash = :h, prev_version_hash = :h, manifest_version = '1' WHERE id = :id"
    )
    async with factory() as session:
        await bind_tenant(session, user_id=developer.user_id)
        with pytest.raises(DBAPIError, match="owner_handle and the registration hashes are set at registration"):
            async with session.begin_nested():  # a draft never names a handle, its owner's or another's
                await session.execute(
                    text(
                        "INSERT INTO proposal_versions (id, proposal_id, version_no, owner_handle) VALUES (:id, :p, 9,"
                        " 'alice')"
                    ),
                    {"id": uuid7(), "p": developer.draft_proposal},
                )
        version = await session.get(ProposalVersion, developer.draft_version)
        assert version is not None
        version.status = VersionStatus.REGISTERED
        version.cert_id = uuid4().hex[:16]
        await session.flush()
        stamped = (
            await session.execute(
                text(
                    "SELECT v.registered_at, now() AS now, d.handle FROM proposal_versions v JOIN proposals p"
                    " ON p.id = v.proposal_id JOIN developer_profiles d ON d.user_id = p.owner_id WHERE v.id = :id"
                ),
                {"id": version.id},
            )
        ).one()
        assert version.registered_at == stamped.registered_at == stamped.now
        assert version.owner_handle == stamped.handle
        for column in ("content_hash = :h", "registered_at = now()", "owner_handle = 'alice'"):
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
    (app.user_id); staff admin|moderator (never support) and the registration job (provenance_worker) compute any
    user's. Inside the SECURITY DEFINER function current_user is its owner and session_user the login role, so the
    job is recognised by the role it switched to (the ``role`` setting, changed only by a membership-checked SET
    ROLE): proven here on a session logged in as bridge_app, exactly as in production, and under the harness's SET
    ROLE. bridge_app holds that membership, so the binding stops a query bug or an ORM load, not SQL the app role
    itself runs (D-32)."""
    async with owner_engine.begin() as conn:  # committed: the bridge_app session below reads them
        other = await w.add_user(conn, _email("digest-other"), "Other")
        support = await w.add_user(conn, _email("digest-support"), "Support", staff_role="support")
        moderator = await w.add_user(conn, _email("digest-mod"), "Moderator", staff_role="moderator")
        salted = "SELECT sha256(subject_salt || uuid_send(id)) FROM users WHERE id = :u"
        expected = {user: await run(conn, salted, u=user) for user in (developer.user_id, other)}

    async with as_app(owner_engine) as conn:
        await act(conn, developer.user_id)
        assert await run(conn, SUBJECT_DIGEST, u=developer.user_id) == expected[developer.user_id]
        await expect(conn, SUBJECT_DIGEST, DIGEST_REFUSED, u=other)
        await act(conn, None)  # no app.user_id: nobody's digest (the NULL-safe check)
        await expect(conn, SUBJECT_DIGEST, DIGEST_REFUSED, u=developer.user_id)
        await act(conn, support)  # support staff see no pseudonyms of other users
        await expect(conn, SUBJECT_DIGEST, DIGEST_REFUSED, u=other)
        await act(conn, moderator)
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
        mark = "SELECT app_mark_kyc_images_purged(:id)"
        for caller in (subject, moderator):  # a signed-in request never marks images purged (they would be kept)
            await act(conn, caller)
            await expect(conn, mark, "the kyc.purge job", id=review)
        await act(conn, None)  # the kyc.purge job: no user bound
        assert await run(conn, "SELECT count(*) FROM app_kyc_purge_due() AS r(id) WHERE r.id = :id", id=review) == 1
        assert await run(conn, mark, id=review) is True
        assert await run(conn, mark, id=review) is False
        await act(conn, admin)  # staff admin may mark by hand (already marked: nothing changes)
        assert await run(conn, mark, id=review) is False


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


# A user's report: inserted without RETURNING (the reporter cannot read the queue).
FILE_CASE = (
    "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source, reporter_id, status, classifier,"
    " assigned_to, decided_by, decided_at) VALUES (:id, 'proposal', :subject, '{abuse}',"
    " CAST(:source AS moderation_source), :reporter, CAST(:status AS moderation_case_status),"
    " CAST(:classifier AS jsonb), :assigned, :decided_by, CAST(:decided_at AS timestamptz))"
)
OPEN_CASE = (
    "SELECT app_open_moderation_case(:type, :subject, CAST(:reasons AS text[]), CAST(:source AS moderation_source),"
    " CAST(:classifier AS jsonb))"
)


async def test_users_only_report_and_system_sources_file_through_the_function(owner_engine: AsyncEngine) -> None:
    """A user files only a report, in their own name: an open case without classifier output. The system sources
    (prescreen, regex, claim_dispute, tier2_similarity) file only through app_open_moderation_case(), which checks the
    caller against the subject (the owner or staff for the pre-screen and regex; the claimant of a disputed claim or
    staff admin; staff for the Tier-2 similarity job, which calls it as tier2_moderation) and keeps one unresolved
    case per subject and source (a new call adds its reasons and returns that case)."""
    async with as_app(owner_engine) as conn:
        niche = uuid7()
        await run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Mod')", id=niche, s=f"q-{niche.hex}")
        owner = await w.add_user(conn, _email("case-owner"), "Owner")
        stranger = await w.add_user(conn, _email("case-stranger"), "Stranger")
        claimant = await w.add_user(conn, _email("case-claimant"), "Claimant")
        moderator = await w.add_user(conn, _email("case-mod"), "Moderator", staff_role="moderator")
        admin = await w.add_user(conn, _email("case-admin"), "Admin", staff_role="admin")
        problem = await w.add_problem(conn, owner, niche)
        proposal, _ = await w.add_proposal(conn, owner, niche, problem)
        earlier, _ = await w.add_proposal(conn, stranger, niche, problem)
        disputed = await _claim(
            conn, await add_org(conn, verification="e2"), claimant, "d.example.test", "e1", bytes(32)
        )
        await run(conn, "UPDATE org_claims SET status = 'disputed' WHERE id = :id", id=disputed)
        open_claim = await _claim(conn, await add_org(conn), claimant, "o.example.test", "e1", bytes(32))
        case = {"type": "proposal", "subject": proposal, "reasons": "{spam}", "source": "regex", "classifier": None}

        await act(conn, stranger)  # a report, in the reporter's own name only
        report = uuid7()
        report_row = {
            "subject": proposal,
            "source": "report",
            "reporter": stranger,
            "status": "open",
            "assigned": None,
            "decided_by": None,
            "decided_at": None,
        }
        await run(conn, FILE_CASE, id=report, **report_row, classifier=None)
        for change in (
            {"source": "regex", "reporter": None},  # a system source
            {"source": "prescreen"},  # a system source, even with the reporter set
            {"reporter": None},
            {"reporter": owner},  # in another user's name
            {"status": "held"},
            {"assigned": moderator},  # the queue's routing and decisions are staff's (UPDATE policy)
            {"decided_by": stranger},
            {"decided_at": datetime.now(UTC)},
        ):
            await expect(conn, FILE_CASE, "row-level security", id=uuid7(), **(report_row | change), classifier=None)
        await expect(conn, FILE_CASE, "row-level security", id=uuid7(), **report_row, classifier='{"label": "spam"}')
        await expect(conn, OPEN_CASE, "may not file", **case)  # the function checks the caller: not the owner
        await act(conn, None)
        await expect(
            conn, FILE_CASE, "row-level security", id=uuid7(), **(report_row | {"reporter": None}), classifier=None
        )
        await expect(conn, OPEN_CASE, "may not file", **case)

        await act(conn, owner)  # the pre-screen and the regex holds on the owner's content
        flagged = case | {"source": "prescreen", "classifier": '{"label": "spam", "score": 0.97}'}
        first = await run(conn, OPEN_CASE, **flagged)
        assert (
            await run(conn, OPEN_CASE, **(flagged | {"reasons": "{malicious_link,spam}", "classifier": None})) == first
        )
        regex = await run(conn, OPEN_CASE, **case)
        on_problem = await run(conn, OPEN_CASE, **(case | {"type": "problem", "subject": problem}))
        assert len({first, regex, on_problem}) == 3
        for change, refusal in (
            ({"source": "report"}, "a system source only"),
            ({"source": "claim_dispute"}, "does not file cases about"),  # a proposal is no claim
            ({"type": "message"}, "does not file cases about"),
            ({"subject": uuid7()}, "may not file"),  # no such proposal
            ({"source": "tier2_similarity"}, "may not file"),  # staff only
            ({"reasons": "{}"}, "reasons"),
            ({"reasons": '{"  "}'}, "reasons"),
            ({"reasons": "{" + ",".join(f"r{i}" for i in range(21)) + "}"}, "reasons"),
            ({"classifier": "[1, 2]"}, "JSON object"),
            ({"classifier": '{"note": "' + "x" * 8200 + '"}'}, "JSON object"),
        ):
            await expect(conn, OPEN_CASE, refusal, **(case | change))

        await act(conn, claimant)  # a claim dispute: the claimant of the disputed claim, or staff admin
        dispute = {"type": "org_claim", "subject": disputed, "reasons": "{competing_claim}", "source": "claim_dispute"}
        dispute_case = await run(conn, OPEN_CASE, **dispute, classifier=None)
        await expect(conn, OPEN_CASE, "may not file", **(dispute | {"subject": open_claim}), classifier=None)
        await act(conn, stranger)
        await expect(conn, OPEN_CASE, "may not file", **dispute, classifier=None)
        await act(conn, admin)
        assert await run(conn, OPEN_CASE, **dispute, classifier=None) == dispute_case

        # The Tier-2 similarity job reads the full-text embeddings as tier2_moderation, which reads only in a staff
        # context, and files the case without switching back. Classifier output holds ids and scores only.
        await act(conn, moderator)
        await conn.execute(text("SET LOCAL ROLE tier2_moderation"))
        similarity = f'{{"similar_to": "{earlier}", "cosine": 0.93}}'
        similar = await run(
            conn,
            OPEN_CASE,
            **(case | {"source": "tier2_similarity", "reasons": "{near_copy}", "classifier": similarity}),
        )

        await act(conn, moderator)  # the queue: staff read it
        rows = await conn.execute(
            text(
                "SELECT id, subject_type, source::text AS source, status::text AS status, reasons, reporter_id,"
                " classifier FROM moderation_cases WHERE subject_id = ANY (:ids)"
            ),
            {"ids": [proposal, problem, disputed]},
        )
        spam, near = {"label": "spam", "score": 0.97}, {"similar_to": str(earlier), "cosine": 0.93}
        assert {r.id: (r.subject_type, r.source, r.status, r.reasons, r.reporter_id, r.classifier) for r in rows} == {
            report: ("proposal", "report", "open", ["abuse"], stranger, None),
            first: ("proposal", "prescreen", "open", ["spam", "malicious_link"], None, spam),  # reasons added
            regex: ("proposal", "regex", "open", ["spam"], None, None),
            on_problem: ("problem", "regex", "open", ["spam"], None, None),
            dispute_case: ("org_claim", "claim_dispute", "open", ["competing_claim"], None, None),
            similar: ("proposal", "tier2_similarity", "open", ["near_copy"], None, near),
        }
        # Once decided, the next hit files a new case.
        decide = "UPDATE moderation_cases SET status = 'rejected', decided_by = :u, decided_at = now() WHERE id = :id"
        await run(conn, decide, u=moderator, id=first)
        await act(conn, owner)
        assert await run(conn, OPEN_CASE, **flagged) not in (first, None)


# What the app's DNS-check code calls once it has resolved the claim's TXT record (the lookup itself is app-side).
MARK_DNS = "SELECT app_mark_claim_dns_verified(:id)"
CLAIM_STATUS = "SELECT status::text FROM org_claims WHERE id = :id"
DISPUTE_MARK = "only the claim functions mark a claim disputed"  # org_claims_status_guard()
# The organisation's owner group: its active members holding owner or admin.
OWNER_GROUP = (
    "SELECT array_agg(user_id ORDER BY user_id) FROM memberships"
    " WHERE org_id = :org AND status = 'active' AND roles && '{owner,admin}'::org_role[]"
)


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


async def test_a_claim_is_timed_by_the_database_so_the_cooldown_holds(owner_engine: AsyncEngine) -> None:
    """The 24-hour cooldown between claims reads created_at, so the database sets it: a claim sent with a backdated
    created_at is stamped now(), and withdrawing it and claiming again is still refused."""
    new_claim = (
        "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status, created_at)"
        " VALUES (:id, :org, :u, 'cool.example.test', 'info@cool.example.test', 'e1', 'otp_sent',"
        " now() - interval '2 days')"
    )
    async with as_app(owner_engine) as conn:
        org = await add_org(conn)
        claimant = await w.add_user(conn, _email("cooldown"), "Claimant")
        await act(conn, claimant)
        claim = uuid7()
        await run(conn, new_claim, id=claim, org=org, u=claimant)
        assert await run(conn, "SELECT created_at = now() FROM org_claims WHERE id = :id", id=claim) is True
        await run(conn, "UPDATE org_claims SET status = 'withdrawn' WHERE id = :id", id=claim)
        await expect(
            conn, new_claim, "one claim per claimant and organisation per 24 hours", id=uuid7(), org=org, u=claimant
        )


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
        # Not a member, on an organisation with an owner: in review as a dispute (approving it below transfers).
        assert await run(conn, CLAIM_STATUS, id=claim) == "disputed"
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
    owner, admin or signatory of an organisation already E1 on the claimed domain needs neither again, and only on
    that domain: the organisation's own signatory claiming another domain proves nothing."""
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
        await _add_membership(conn, e1, owner, "{owner,admin}")
        signatory = await w.add_user(conn, _email("e1-signatory"), "Signatory")
        await _add_membership(conn, e1, signatory, "{signatory}")
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
        # The E1 shortcut holds only on the organisation's verified domain: its signatory, terms accepted, claiming E2
        # on another domain is refused (without the domain equality in app_decide_claim it would be approved).
        await act(conn, signatory)
        await run(conn, MET_ACCEPTANCE, id=uuid7(), org=e1, u=signatory, t=met)
        elsewhere = await _claim(conn, e1, signatory, "elsewhere.example.test", "e2", right)
        await act(conn, admin)
        await expect(conn, decide, unproven, id=elsewhere)
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


async def _add_membership(conn: AsyncConnection, org: UUID, user: UUID, roles: str, status: str = "active") -> UUID:
    membership = uuid7()
    await run(
        conn,
        "INSERT INTO memberships (id, org_id, user_id, roles, status)"
        " VALUES (:id, :org, :u, CAST(:roles AS org_role[]), CAST(:status AS membership_status))",
        id=membership,
        org=org,
        u=user,
        roles=roles,
        status=status,
    )
    return membership


async def _invite(conn: AsyncConnection, org: UUID, invited_by: UUID, roles: str, *, accepted: bool = False) -> UUID:
    """A Phase 1 invitation to ``org`` (pending unless ``accepted``)."""
    invitation = uuid7()
    await run(
        conn,
        "INSERT INTO invitations (id, org_id, email, roles, token_hash, invited_by, expires_at, accepted_at)"
        " VALUES (:id, :org, :email, CAST(:roles AS org_role[]), :hash, :by, now() + interval '7 days',"
        " CASE WHEN :accepted THEN now() END)",
        id=invitation,
        org=org,
        email=_email("invitee"),
        roles=roles,
        hash=invitation.bytes,
        by=invited_by,
        accepted=accepted,
    )
    return invitation


@pytest.mark.parametrize("level", ["e1", "e2"])
async def test_an_upheld_dispute_transfers_the_organisation(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes], level: str
) -> None:
    """Competing claims go to dispute review, never an automatic transfer (docs/spec/06 6.2, AC-DIR-2); staff admin
    upholding the dispute transfers the organisation in the same transaction, and the new claimant is its only owner
    and admin: the earlier claimant's approved claim is rejected, naming the claim that superseded it, and their
    membership is removed with no role but viewer (nobody reactivates them with power); every other member loses
    owner and admin but keeps their other roles (viewer when none is left), so the self-signup founder can no longer
    remove the new owner; every pending invitation issued under the old control (by anyone but the new claimant),
    or carrying owner or admin, is revoked; and a membership removed before the dispute loses owner and admin too, so
    reactivating it restores no power. The new claimant re-promotes people afterwards."""
    right, _ = otp
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("dispute-admin"), "Admin", staff_role="admin")
        org = await add_org(conn, source="self_signup", official_domains="{first.example.test}")
        founder = await w.add_user(conn, _email("founder"), "Self-signup founder")
        first = await w.add_user(conn, _email("first"), "First claimant")
        second = await w.add_user(conn, _email("second"), "Second claimant")
        reviewer = await w.add_user(conn, _email("dispute-reviewer"), "Reviewer")
        signer = await w.add_user(conn, _email("dispute-signer"), "Signer")
        departed = await w.add_user(conn, _email("departed"), "Departed owner")
        await _add_membership(conn, org, founder, "{owner,admin}")  # app_create_organization() at self-signup
        met = await add_legal_template(conn, "master_enterprise_terms")
        elsewhere = await add_org(conn)
        await _invite(conn, elsewhere, founder, "{owner}")  # another organisation's invitation: untouched
        await act(conn, first)  # the founder holds the organisation: even an official domain's claim is a dispute
        earlier = await _claim(conn, org, first, "first.example.test", "e1", right)
        await _prove_domain(conn, earlier, right)
        assert await run(conn, "SELECT app_approve_claim_e1(:id)::text", id=earlier) == "disputed"
        await act(conn, admin)
        await run(conn, "SELECT app_decide_claim(:id, true, 'first claim upheld')", id=earlier)
        await act(conn, first)  # the new owner re-promotes the founder and builds the roster
        promote = "UPDATE memberships SET roles = '{owner,admin}' WHERE org_id = :org AND user_id = :u"
        assert (await conn.execute(text(promote), {"org": org, "u": founder})).rowcount == 1
        await _add_membership(conn, org, reviewer, "{reviewer}")
        await _add_membership(conn, org, signer, "{admin,signatory}")
        await _add_membership(conn, org, second, "{admin}")
        await _add_membership(conn, org, departed, "{owner,admin}", status="removed")  # left before the dispute
        by_first = await _invite(conn, org, first, "{reviewer}")
        accepted = await _invite(conn, org, first, "{viewer}", accepted=True)
        await act(conn, founder)
        by_founder = await _invite(conn, org, founder, "{finance}")
        await act(conn, second)
        by_second = await _invite(conn, org, second, "{viewer}")
        admin_by_second = await _invite(conn, org, second, "{admin}")
        await act(conn, first)  # second is removed (an active admin's claim would be no dispute) ...
        remove = "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :u"
        assert (await conn.execute(text(remove), {"org": org, "u": second})).rowcount == 1
        await act(conn, second)  # ... and claims another domain: marked disputed when filed, and it stays so
        disputed = await _claim(conn, org, second, "second.example.test", level, right)
        assert await run(conn, CLAIM_STATUS, id=disputed) == "disputed"
        await expect(conn, "UPDATE org_claims SET status = 'pending_review' WHERE id = :id", DISPUTE_MARK, id=disputed)
        await _prove_domain(conn, disputed, right)
        if level == "e2":
            await run(conn, MET_ACCEPTANCE, id=uuid7(), org=org, u=second, t=met)
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
        roster = "SELECT user_id, status::text AS status, roles::text[] AS roles FROM memberships WHERE org_id = :org"
        members = await conn.execute(text(roster), {"org": org})
        assert {row.user_id: (row.status, sorted(row.roles)) for row in members.all()} == {
            first: ("removed", ["viewer"]),
            second: ("active", ["admin", "owner"]),
            founder: ("active", ["viewer"]),
            signer: ("active", ["signatory"]),
            reviewer: ("active", ["reviewer"]),
            departed: ("removed", ["viewer"]),
        }
        revoked = await conn.execute(
            text("SELECT id, revoked_at IS NOT NULL AS revoked FROM invitations WHERE org_id = ANY (:orgs)"),
            {"orgs": [org, elsewhere]},
        )
        invitations = {row.id: row.revoked for row in revoked.all()}
        assert {accepted, by_second} <= set(invitations)  # kept: accepted, or the new claimant's without power
        assert {i for i, is_revoked in invitations.items() if is_revoked} == {by_first, by_founder, admin_by_second}
        verified = "SELECT verification::text, verified_domain::text FROM organizations WHERE id = :id"
        assert tuple((await conn.execute(text(verified), {"id": org})).one()) == (level, "second.example.test")
        remove_second = "UPDATE memberships SET status = 'removed' WHERE org_id = :org AND user_id = :u"
        reactivate_first = "UPDATE memberships SET status = 'active' WHERE org_id = :org AND user_id = :u"
        for ousted in (first, founder):  # neither the earlier claimant nor the founder holds any power now
            await act(conn, ousted)
            assert await run(conn, "SELECT app_is_member(:id, '{owner,admin}')", id=org) is False
            assert (await conn.execute(text(remove_second), {"org": org, "u": second})).rowcount == 0
            assert (await conn.execute(text(reactivate_first), {"org": org, "u": first})).rowcount == 0
        await act(conn, second)
        assert await run(conn, "SELECT app_is_member(:id, '{owner,admin}')", id=org) is True
        # Reactivated by the new owner, the earlier claimant comes back without power.
        assert (await conn.execute(text(reactivate_first), {"org": org, "u": first})).rowcount == 1
        await act(conn, first)
        assert await run(conn, "SELECT app_is_member(:id)", id=org) is True
        assert await run(conn, "SELECT app_is_member(:id, '{owner,admin,signatory}')", id=org) is False


async def test_approving_a_claim_that_is_not_disputed_transfers_nothing(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    """Only an upheld dispute transfers the organisation: staff approving an ordinary claim (here the E2 upgrade of
    an E1 organisation by its own signatory, through the E1 shortcut) leaves the earlier approved claim of another
    claimant approved and every membership as it was."""
    right, _ = otp
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("upgrade-admin"), "Admin", staff_role="admin")
        org = await add_org(conn, official_domains="{upgrade.example.test}")
        first = await w.add_user(conn, _email("upgrade-first"), "First claimant")
        signatory = await w.add_user(conn, _email("upgrade-signatory"), "Signatory")
        met = await add_legal_template(conn, "master_enterprise_terms")
        await act(conn, first)  # E1 at once on an official domain
        earlier = await _claim(conn, org, first, "upgrade.example.test", "e1", right)
        await _prove_domain(conn, earlier, right)
        assert await run(conn, "SELECT app_approve_claim_e1(:id)::text", id=earlier) == "approved"
        await as_owner(conn)
        await _add_membership(conn, org, signatory, "{signatory}")
        await act(conn, signatory)  # E2 on the organisation's verified domain: no new domain proof needed
        await run(conn, MET_ACCEPTANCE, id=uuid7(), org=org, u=signatory, t=met)
        upgrade = await _claim(conn, org, signatory, "upgrade.example.test", "e2", right)
        await run(conn, "UPDATE org_claims SET status = 'pending_review' WHERE id = :id", id=upgrade)
        await act(conn, admin)
        await run(conn, "SELECT app_decide_claim(:id, true, 'E2 documents checked')", id=upgrade)

        await as_owner(conn)
        claims = await conn.execute(
            text("SELECT id, status::text AS status FROM org_claims WHERE org_id = :org"), {"org": org}
        )
        assert {row.id: row.status for row in claims.all()} == {earlier: "approved", upgrade: "approved"}
        members = await conn.execute(
            text("SELECT user_id, status::text AS status, roles::text[] AS roles FROM memberships WHERE org_id = :org"),
            {"org": org},
        )
        assert {row.user_id: (row.status, sorted(row.roles)) for row in members.all()} == {
            first: ("active", ["admin", "owner"]),
            signatory: ("active", ["admin", "owner", "signatory"]),
        }
        assert await run(conn, "SELECT verification::text FROM organizations WHERE id = :id", id=org) == "e2"


async def test_a_competing_claim_is_decided_as_a_dispute_whatever_its_label(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    """Whether a claim is a dispute is decided in SQL, never by its label (round 5): a claim competes when another
    user holds an approved claim on the organisation or is an active owner or admin of it, and the claimant is not an
    active owner, admin or signatory. It is marked disputed when filed (org_claims_guard) or when the automatic E1
    check finds the competition (app_approve_claim_e1, not manual review), and staff approving it is the dispute's
    outcome, the transfer, even with the label still pending_review. The claimant can neither mark a claim disputed
    nor clear the mark. An approved outsider never ends up next to the earlier owner: one owner group, never two."""
    right, _ = otp
    decide = "SELECT app_decide_claim(:id, true, 'documents checked')"
    approve = "SELECT app_approve_claim_e1(:id)::text"
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("compete-admin"), "Admin", staff_role="admin")
        org = await add_org(conn, official_domains="{first.example.test}")
        contested, plain = await add_org(conn), await add_org(conn)
        first, stranger, a, b, c = [await w.add_user(conn, _email(n), n) for n in ("first", "stranger", "a", "b", "c")]
        # The reviewer's probe: an outsider's claim on an organisation already E1, on another domain, proven.
        await act(conn, first)
        earlier = await _claim(conn, org, first, "first.example.test", "e1", right)
        await _prove_domain(conn, earlier, right)
        assert await run(conn, approve, id=earlier) == "approved"
        await act(conn, stranger)
        competing = await _claim(conn, org, stranger, "second.example.test", "e1", right)
        assert await run(conn, CLAIM_STATUS, id=competing) == "disputed"
        await _prove_domain(conn, competing, right)  # the email code and the DNS record still verify
        assert await run(conn, approve, id=competing) == "disputed"
        for status in ("pending_review", "otp_sent", "dns_pending"):
            await expect(conn, f"UPDATE org_claims SET status = '{status}' WHERE id = :id", DISPUTE_MARK, id=competing)
        filed_disputed = (  # nor is an ordinary claim marked by its claimant, when filed or later
            "INSERT INTO org_claims (id, org_id, claimant_user_id, domain, email_address, level, status)"
            " VALUES (:id, :org, :u, 'plain.example.test', 'info@plain.example.test', 'e1', CAST(:s AS claim_status))"
        )
        refused = "marked disputed only by the database"
        await expect(conn, filed_disputed, refused, id=uuid7(), org=plain, u=stranger, s="disputed")
        ordinary = uuid7()
        await run(conn, filed_disputed, id=ordinary, org=plain, u=stranger, s="otp_sent")
        await expect(conn, "UPDATE org_claims SET status = 'disputed' WHERE id = :id", DISPUTE_MARK, id=ordinary)
        await act(conn, admin)
        await run(conn, decide, id=competing)
        await as_owner(conn)
        assert await run(conn, OWNER_GROUP, org=org) == [stranger]
        assert await run(conn, CLAIM_STATUS, id=earlier) == "rejected"
        assert await run(conn, "SELECT verified_domain::text FROM organizations WHERE id = :id", id=org) == (
            "second.example.test"
        )
        # Claims filed before any competition existed: ordinary labels, and still decided as the disputes they became.
        claims: dict[UUID, UUID] = {}
        for user, name in ((a, "a"), (b, "b"), (c, "c")):
            await act(conn, user)
            claims[user] = await _claim(conn, contested, user, f"{name}.contested.example.test", "e1", right)
            await _prove_domain(conn, claims[user], right)
        await act(conn, a)
        assert await run(conn, approve, id=claims[a]) == "pending_review"  # other open claims: manual review
        await act(conn, admin)
        await run(conn, decide, id=claims[a])  # nobody held the organisation: no dispute
        await act(conn, b)
        await run(conn, "UPDATE org_claims SET status = 'pending_review' WHERE id = :id", id=claims[b])
        await act(conn, admin)
        await run(conn, decide, id=claims[b])  # labelled pending_review, decided as the dispute it is
        await as_owner(conn)
        assert await run(conn, OWNER_GROUP, org=contested) == [b]
        assert await run(conn, CLAIM_STATUS, id=claims[a]) == "rejected"
        await act(conn, c)  # the automatic E1 check finds the competition: a dispute, not manual review
        assert await run(conn, approve, id=claims[c]) == "disputed"


async def test_an_ousted_claimant_cannot_rejoin_through_a_new_claim(
    owner_engine: AsyncEngine, otp: tuple[bytes, bytes]
) -> None:
    """The security review's T9 to T15: after an upheld dispute the ousted owner, and a co-owner demoted to viewer,
    file new claims a day later. Each is marked disputed when filed and the claimant cannot relabel it for a routine
    review; approving one is again the dispute's outcome (the claimant becomes the only owner and admin), so nobody
    rejoins next to the new owner and then demotes them."""
    right, _ = otp
    decide = "SELECT app_decide_claim(:id, true, 'reviewed')"
    async with as_app(owner_engine) as conn:
        admin = await w.add_user(conn, _email("ousted-admin"), "Admin", staff_role="admin")
        org = await add_org(conn, official_domains="{corp.example.test}")
        ousted, demoted, newcomer = [await w.add_user(conn, _email(n), n) for n in ("ousted", "demoted", "newcomer")]
        await act(conn, ousted)
        original = await _claim(conn, org, ousted, "corp.example.test", "e1", right)
        await _prove_domain(conn, original, right)
        assert await run(conn, "SELECT app_approve_claim_e1(:id)::text", id=original) == "approved"
        await _add_membership(conn, org, demoted, "{owner}")
        await act(conn, newcomer)
        upheld = await _claim(conn, org, newcomer, "corp-ke.example.test", "e1", right)
        await _prove_domain(conn, upheld, right)
        await act(conn, admin)
        await run(conn, decide, id=upheld)
        await as_owner(conn)  # a day later (the claim cooldown)
        await run(conn, "UPDATE org_claims SET created_at = now() - interval '2 days' WHERE org_id = :org", org=org)
        refiled: dict[UUID, UUID] = {}
        for user in (ousted, demoted):
            await act(conn, user)
            refiled[user] = await _claim(conn, org, user, "corp.example.test", "e1", right)
            assert await run(conn, CLAIM_STATUS, id=refiled[user]) == "disputed"
            relabel = "UPDATE org_claims SET status = 'pending_review' WHERE id = :id"
            await expect(conn, relabel, DISPUTE_MARK, id=refiled[user])
        await act(conn, ousted)
        await _prove_domain(conn, refiled[ousted], right)
        await act(conn, admin)
        await run(conn, decide, id=refiled[ousted])
        await as_owner(conn)
        assert await run(conn, OWNER_GROUP, org=org) == [ousted]
        assert await run(conn, CLAIM_STATUS, id=upheld) == "rejected"
        await act(conn, newcomer)
        assert await run(conn, "SELECT app_is_member(:id, '{owner,admin}')", id=org) is False


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
    """The hourly anchor job (REQ-AUD-01) gets the head (seq, event_hash, occurred_at) of every audit chain from
    app_audit_chain_heads(), and the heads not anchored yet, oldest first, from app_unanchored_chain_heads();
    provenance_worker cannot read audit_events or chain_anchors itself, and no other role may call either."""
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
                "SELECT DISTINCT ON (chain_id) chain_id, seq, event_hash, occurred_at FROM audit_events"
                " WHERE chain_id = ANY (:c) ORDER BY chain_id, seq DESC"
            ),
            {"c": chains},
        )
        expected = {row.chain_id: (row.seq, row.event_hash, row.occurred_at) for row in last.all()}
        assert {chain: head[0] for chain, head in expected.items()} == {chains[0]: 1, chains[1]: 3}
        heads = "SELECT chain_id, seq, event_hash, occurred_at FROM app_audit_chain_heads() WHERE chain_id = ANY (:c)"
        unanchored = (  # in the function's order (WITH ORDINALITY keeps it through the filter)
            "SELECT h.chain_id FROM app_unanchored_chain_heads() WITH ORDINALITY AS h(chain_id, seq, event_hash,"
            " occurred_at, n) WHERE h.chain_id = ANY (:c) ORDER BY h.n"
        )
        for role in ("bridge_app", "audit_reader", "aggregate_worker", "tier2_reader", "dsr_exporter"):
            await conn.execute(text(f"SET LOCAL ROLE {role}"))
            await expect(conn, heads, "permission denied", c=chains)
            await expect(conn, unanchored, "permission denied", c=chains)
        await conn.execute(text("SET LOCAL ROLE provenance_worker"))
        found = (await conn.execute(text(heads), {"c": chains})).all()
        assert {row.chain_id: (row.seq, row.event_hash, row.occurred_at) for row in found} == expected
        await expect(conn, "SELECT 1 FROM audit_events", "permission denied")
        assert list((await conn.execute(text(unanchored), {"c": chains})).scalars()) == chains  # oldest head first
        seq, event_hash, _ = expected[chains[0]]
        await run(conn, ANCHOR, id=uuid7(), chain=chains[0], seq=seq, hash=event_hash, tsa_time=datetime.now(UTC))
        assert list((await conn.execute(text(unanchored), {"c": chains})).scalars()) == [chains[1]]


ANCHOR = (
    "INSERT INTO chain_anchors (id, chain_id, seq, event_hash, tsa_token, tsa_time, tsa_serial)"
    " VALUES (:id, :chain, :seq, :hash, '\\x01', CAST(:tsa_time AS timestamptz), 'serial')"
)
ROOT = (
    "INSERT INTO transparency_roots (day, merkle_root, signature, key_id, snapshot_at)"
    " VALUES (CAST(:day AS date), :root, '\\x02', :key, CAST(:snapshot AS timestamptz))"
)
NAIROBI_TODAY = "SELECT CAST(now() AT TIME ZONE 'Africa/Nairobi' AS date)"


async def test_anchors_name_a_real_chain_event_and_roots_a_closed_day(owner_engine: AsyncEngine) -> None:
    """chain_anchors and transparency_roots are append-only and one per head or day, so a forged row would be
    permanent and block the real one. provenance_worker (the only writer) may anchor only an existing audit event
    (its chain, sequence number and hash) at a TSA time no later than the database clock allows and no earlier than
    the anchored event (one minute of clock skew either way: a real head anchored ten years back is refused), and
    publish a root only for a Nairobi day that has ended, from a snapshot taken after that day ended and no later than
    now (``snapshot_at``, when given)."""
    chain = f"test:{uuid4().hex}"
    async with as_app(owner_engine) as conn:
        for _ in range(2):
            await run(
                conn,
                "INSERT INTO audit_events (id, chain_id, actor_kind, action) VALUES (:id, :c, 'system', 'test.anchor')",
                id=uuid7(),
                c=chain,
            )
        events = await conn.execute(
            text("SELECT seq, event_hash FROM audit_events WHERE chain_id = :c ORDER BY seq"), {"c": chain}
        )
        earlier, head = events.all()
        key = f"test-{uuid4().hex[:8]}"
        await run(conn, "INSERT INTO provenance_keys (key_id, public_key) VALUES (:k, :pk)", k=key, pk=bytes(32))
        today = await run(conn, NAIROBI_TODAY)
        await conn.execute(text("SET LOCAL ROLE provenance_worker"))
        anchor = {"chain": chain, "seq": head.seq, "hash": head.event_hash, "tsa_time": datetime.now(UTC)}
        refused = "an anchor names an existing audit event"
        for change in (
            {"hash": hashlib.sha256(b"forged").digest()},
            {"seq": head.seq + 1},
            {"chain": f"test:{uuid4().hex}"},
        ):
            await expect(conn, ANCHOR, refused, id=uuid7(), **(anchor | change))
        future = datetime.now(UTC) + timedelta(hours=1)
        await expect(
            conn, ANCHOR, "TSA time is later than the database clock", id=uuid7(), **(anchor | {"tsa_time": future})
        )
        long_ago = datetime.now(UTC) - timedelta(days=3650)
        await expect(
            conn, ANCHOR, "TSA time is earlier than the anchored event", id=uuid7(), **(anchor | {"tsa_time": long_ago})
        )
        await run(conn, ANCHOR, id=uuid7(), **anchor)
        await run(conn, ANCHOR, id=uuid7(), **(anchor | {"seq": earlier.seq, "hash": earlier.event_hash}))
        root = {"root": hashlib.sha256(b"root").digest(), "key": key, "snapshot": None}
        for day in (today, today + timedelta(days=1)):
            await expect(conn, ROOT, "a root closes a Nairobi day that has ended", day=day, **root)
        yesterday = today - timedelta(days=1)
        began = await run(conn, "SELECT CAST(CAST(:d AS date) AS timestamp) AT TIME ZONE 'Africa/Nairobi'", d=yesterday)
        for snapshot in (datetime.now(UTC) + timedelta(hours=1), began + timedelta(hours=12)):  # future; mid-day
            await expect(
                conn,
                ROOT,
                "the snapshot is taken after the day ended",
                day=yesterday,
                **(root | {"snapshot": snapshot}),
            )
        await run(conn, ROOT, day=yesterday, **(root | {"snapshot": datetime.now(UTC) - timedelta(minutes=1)}))
        await run(conn, ROOT, day=today - timedelta(days=2), **root)  # snapshot_at may still be left out


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


BATCH_CALL = (
    "INSERT INTO llm_calls (id, user_id, task, model, status, cost_usd, batch_id, custom_id)"
    " VALUES (:id, :u, 't', 'm', :status, :cost, :batch, :item)"
)
# How the ledger settles an item: untargeted, since a targeted ON CONFLICT is refused by RLS for system rows.
SETTLE = BATCH_CALL + " ON CONFLICT DO NOTHING"
USER_SPEND = "SELECT coalesce(sum(cost_usd), 0) FROM llm_spend WHERE user_id = :u"
GLOBAL_SPEND = "SELECT app_llm_spend_usd(:t)"


async def test_only_the_app_reads_the_spend_view(owner_engine: AsyncEngine) -> None:
    """llm_spend (the spend rule, security_invoker) is read by bridge_app for the tenant monthly sum; no worker or
    Tier-2 role reads it, and nobody writes it."""
    assert await roles_holding(owner_engine, "llm_spend", "SELECT") == {"bridge_app"}
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert await roles_holding(owner_engine, "llm_spend", privilege) == set()


async def test_a_batch_reservation_counts_until_its_item_settles_once(owner_engine: AsyncEngine) -> None:
    """A Message Batches item is reserved at submission (status batch_reserved, the estimated cost) and settled once
    its result arrives. Spend (llm_spend, the one rule behind the tenant monthly sum and app_llm_spend_usd) counts a
    reservation until its item settles, then only the settled row; an item is reserved once and settles once (a
    second settle is skipped by ON CONFLICT DO NOTHING); a batch id always comes with an item id. Tenants still read
    only their own rows, through llm_calls and llm_spend alike."""
    async with as_app(owner_engine) as conn:
        user = await w.add_user(conn, _email("batch-user"), "Batch")
        other = await w.add_user(conn, _email("batch-other"), "Other")
        since = await run(conn, "SELECT now() - interval '1 second'")
        before = await run(conn, GLOBAL_SPEND, t=since)
        await act(conn, user)
        batch = f"msgbatch_{uuid4().hex[:20]}"
        item = {"u": user, "batch": batch, "item": "item-1"}
        await run(conn, BATCH_CALL, id=uuid7(), status="batch_reserved", cost=Decimal("2.00"), **item)
        assert await run(conn, USER_SPEND, u=user) == Decimal("2.00")  # reserved: counted
        assert await run(conn, GLOBAL_SPEND, t=since) - before == Decimal("2.00")
        reserve_again = {"id": uuid7(), "status": "batch_reserved", "cost": Decimal("2.00")}
        await expect(conn, BATCH_CALL, "uq_llm_calls_batch_reservation", **reserve_again, **item)
        settle = {"status": "ok", "cost": Decimal("1.50")}
        assert (await conn.execute(text(SETTLE), {"id": uuid7(), **settle, **item})).rowcount == 1
        assert (await conn.execute(text(SETTLE), {"id": uuid7(), **settle, **item})).rowcount == 0  # skipped
        failed = {"id": uuid7(), "status": "error", "cost": Decimal("0")}
        await expect(conn, BATCH_CALL, "uq_llm_calls_batch_settlement", **failed, **item)  # settles once
        assert await run(conn, USER_SPEND, u=user) == Decimal("1.50")  # settled: only the settled row
        assert await run(conn, GLOBAL_SPEND, t=since) - before == Decimal("1.50")
        unpaired = {"id": uuid7(), "u": user, "cost": Decimal("0")}
        await expect(conn, BATCH_CALL, "ck_llm_calls_batch_pair", **unpaired, status="ok", batch=batch, item=None)
        await expect(conn, BATCH_CALL, "ck_llm_calls_batch_pair", **unpaired, status="ok", batch=None, item="item-9")
        await expect(
            conn,
            BATCH_CALL,
            "ck_llm_calls_batch_reserved_has_batch",
            **unpaired,
            status="batch_reserved",
            batch=None,
            item=None,
        )
        # A system job's item (no user, no organisation; the job binds no user) settles the same way.
        await act(conn, None)
        system = {"u": None, "batch": batch, "item": "item-2"}
        await run(conn, BATCH_CALL, id=uuid7(), status="batch_reserved", cost=Decimal("1.00"), **system)
        for _ in range(2):
            await conn.execute(text(SETTLE), {"id": uuid7(), "status": "ok", "cost": Decimal("0.25"), **system})
        assert await run(conn, GLOBAL_SPEND, t=since) - before == Decimal("1.75")
        await act(conn, other)  # RLS unchanged: another tenant reads none of these rows, raw or through the view
        assert await run(conn, "SELECT count(*) FROM llm_spend WHERE user_id = :u", u=user) == 0
        assert await run(conn, "SELECT count(*) FROM llm_calls WHERE batch_id = :b", b=batch) == 0
        assert await run(conn, GLOBAL_SPEND, t=since) - before == Decimal("1.75")  # the total, never the rows


TENANT_BATCH_CALL = (
    "INSERT INTO llm_calls (id, org_id, user_id, task, model, status, cost_usd, batch_id, custom_id)"
    " VALUES (:id, :org, :u, 't', 'm', :status, :cost, :batch, :item)"
)
ORG_SPEND = "SELECT coalesce(sum(cost_usd), 0) FROM llm_spend WHERE org_id = :org"
SETTLES_ONLY = "settles only a reservation of its own tenant"  # llm_calls_batch_guard()


async def test_a_batch_item_belongs_to_its_tenant(owner_engine: AsyncEngine) -> None:
    """The review probes L1, L1b, L2, L2b and L9 (round 5): a batch item is identified within its tenant (org_id and
    user_id, NULL for none), so another tenant's rows naming the same (batch_id, custom_id) neither settle, cancel nor
    block it. A settlement settles only a reservation of its own tenant: one for an item only another tenant reserved
    is refused, as is one under another organisation or user than the reservation's (a mis-bound ledger).
    Reservations of different tenants for one pair coexist, each counting until its own tenant settles it. A request
    bound to a user writes no platform job's batch row (no user, no organisation); the job, binding no user, does."""
    async with as_app(owner_engine) as conn:
        victim = await w.add_user(conn, _email("batch-victim"), "Victim")
        intruder = await w.add_user(conn, _email("batch-intruder"), "Intruder")
        org = await add_org(conn, verification="e1")
        await _add_membership(conn, org, victim, "{owner,admin}")
        since = await run(conn, "SELECT now() - interval '1 second'")
        before = await run(conn, GLOBAL_SPEND, t=since)
        batch = f"msgbatch_{uuid4().hex[:20]}"
        mine, theirs = {"org": org, "u": victim, "batch": batch}, {"org": None, "u": intruder, "batch": batch}
        system = {"org": None, "u": None, "batch": batch}
        settle = TENANT_BATCH_CALL + " ON CONFLICT DO NOTHING"
        reserved = {"status": "batch_reserved"}
        await act(conn, victim, org)
        for item, cost in (("item-1", 50), ("item-2", 40)):
            await run(conn, TENANT_BATCH_CALL, id=uuid7(), **reserved, cost=Decimal(cost), item=item, **mine)
        await act(conn, intruder)  # L1: a zero-cost settlement of the victim's item, as a user or a system row
        for tenant in (theirs, system):
            for sql in (TENANT_BATCH_CALL, settle):
                await expect(conn, sql, SETTLES_ONLY, id=uuid7(), status="ok", cost=Decimal(0), item="item-1", **tenant)
        # L2: the intruder reserves a pair the victim has not reserved yet: the intruder's own item.
        await run(conn, TENANT_BATCH_CALL, id=uuid7(), **reserved, cost=Decimal(5), item="item-3", **theirs)
        await act(conn, victim, org)  # L2b: the victim still reserves that pair, and settles it as the victim's
        await run(conn, TENANT_BATCH_CALL, id=uuid7(), **reserved, cost=Decimal(30), item="item-3", **mine)
        for item, cost in (("item-1", 38), ("item-3", 20)):  # L1b: the real settlement is never dropped
            params = {"id": uuid7(), "status": "ok", "cost": Decimal(cost), "item": item, **mine}
            assert (await conn.execute(text(settle), params)).rowcount == 1
        # L9: settled under no organisation although reserved under one (a mis-bound ledger): refused.
        unbound = mine | {"org": None}
        await expect(conn, settle, SETTLES_ONLY, id=uuid7(), status="ok", cost=Decimal(1), item="item-2", **unbound)
        assert await run(conn, ORG_SPEND, org=org) == Decimal(98)  # 38 settled, 40 reserved, 20 settled
        await act(conn, intruder)  # the victim's settlement of item-3 cancelled only the victim's reservation
        assert await run(conn, USER_SPEND, u=intruder) == Decimal(5)
        assert await run(conn, GLOBAL_SPEND, t=since) - before == Decimal(103)
        job_item = {"id": uuid7(), **reserved, "cost": Decimal(1), "item": "item-4", **system}
        await expect(conn, TENANT_BATCH_CALL, "row-level security", **job_item)
        await act(conn, None)
        await run(conn, TENANT_BATCH_CALL, **job_item)
        await act(conn, intruder)
        job_settles = {"id": uuid7(), "status": "ok", "cost": Decimal(0), "item": "item-4", **system}
        await expect(conn, settle, "row-level security", **job_settles)
        assert await run(conn, GLOBAL_SPEND, t=since) - before == Decimal(104)


LLM_CALL = (
    "INSERT INTO llm_calls (id, user_id, task, model, status, cost_usd, input_tokens, output_tokens,"
    " cache_read_tokens, cache_write_tokens, latency_ms) VALUES (:id, :u, 't', 'm', 'ok', :cost, :input, :output,"
    " :cache_read, :cache_write, :latency)"
)


async def test_a_ledger_row_cannot_blow_or_offset_the_global_spend(owner_engine: AsyncEngine) -> None:
    """The global daily cap sums every row, so one row a user writes must stay a plausible single call: its cost is
    0 to 100 USD, and no token count or latency is negative (a negative cost would offset real spend)."""
    async with as_app(owner_engine) as conn:
        user = await w.add_user(conn, _email("llm-bounds"), "LLM")
        await act(conn, user)
        call = {"cost": Decimal("100"), "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "latency": None}
        await run(conn, LLM_CALL, id=uuid7(), u=user, **call)  # the bounds themselves are allowed
        for change, constraint in (
            ({"cost": Decimal("999999")}, "ck_llm_calls_cost_usd_range"),
            ({"cost": Decimal("100.000001")}, "ck_llm_calls_cost_usd_range"),
            ({"cost": Decimal("-5")}, "ck_llm_calls_cost_usd_range"),
            ({"input": -1}, "ck_llm_calls_counts_not_negative"),
            ({"output": -1}, "ck_llm_calls_counts_not_negative"),
            ({"cache_read": -1}, "ck_llm_calls_counts_not_negative"),
            ({"cache_write": -1}, "ck_llm_calls_counts_not_negative"),
            ({"latency": -1}, "ck_llm_calls_counts_not_negative"),
        ):
            await expect(conn, LLM_CALL, constraint, id=uuid7(), u=user, **(call | change))


REPORT = (
    "INSERT INTO moderation_cases (id, subject_type, subject_id, reasons, source, reporter_id)"
    " VALUES (:id, 'proposal', :subject, CAST(:reasons AS text[]), 'report', :reporter)"
)
INVITATION = "INSERT INTO directory_invitations (id, org_id, to_address, reason) VALUES (:id, :org, :address, :reason)"


async def test_reports_and_directory_invitations_are_bounded(owner_engine: AsyncEngine) -> None:
    """What any signed-in user may write into the staff queues is bounded in the table (rate limits stay app-side):
    a moderation case has 1 to 50 non-blank reasons of at most 200 characters (as app_open_moderation_case files
    them), for a report and for a staff edit alike; a directory invitation goes to an address of at most 254
    characters with one @, and its reason, when given, is non-blank and at most 500 characters."""
    async with as_app(owner_engine) as conn:
        niche = uuid7()
        await run(
            conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Bounds')", id=niche, s=f"b-{niche.hex}"
        )
        reporter = await w.add_user(conn, _email("bounds-reporter"), "Reporter")
        moderator = await w.add_user(conn, _email("bounds-mod"), "Moderator", staff_role="moderator")
        problem = await w.add_problem(conn, reporter, niche)
        proposal, _ = await w.add_proposal(conn, reporter, niche, problem)
        org = await add_org(conn)
        await act(conn, reporter)
        report = uuid7()
        await run(
            conn,
            REPORT,
            id=report,
            subject=proposal,
            reasons="{" + ",".join(f"r{i}" for i in range(50)) + "}",
            reporter=reporter,
        )
        for reasons in (
            "{}",
            '{"  "}',
            '{abuse,""}',
            "{abuse,NULL}",
            "{" + ",".join(f"r{i}" for i in range(51)) + "}",
            "{" + "x" * 201 + "}",
        ):
            await expect(
                conn,
                REPORT,
                "ck_moderation_cases_reasons_valid",
                id=uuid7(),
                subject=proposal,
                reasons=reasons,
                reporter=reporter,
            )
        await run(conn, INVITATION, id=uuid7(), org=org, address="partnerships@bounds.example.test", reason=None)
        for address, reason, constraint in (
            ("no-at-sign.example.test", None, "ck_directory_invitations_to_address"),
            ("two@at@bounds.example.test", None, "ck_directory_invitations_to_address"),
            ("a b@bounds.example.test", None, "ck_directory_invitations_to_address"),
            ("x" * 250 + "@b.test", None, "ck_directory_invitations_to_address"),
            ("info@bounds.example.test", "   ", "ck_directory_invitations_reason"),
            ("info@bounds.example.test", "x" * 501, "ck_directory_invitations_reason"),
        ):
            await expect(conn, INVITATION, constraint, id=uuid7(), org=org, address=address, reason=reason)
        await act(conn, moderator)  # the bound holds for a staff edit too
        await expect(
            conn,
            "UPDATE moderation_cases SET reasons = '{}' WHERE id = :id",
            "ck_moderation_cases_reasons_valid",
            id=report,
        )
