"""REQ-LLM-01 P7 (D-37) against PostgreSQL: ``SqlDemoAccounts`` reads ``users.demo_account`` as ``bridge_app``.

Schema v3 adds the column (set by the owner role in the demo seed only). Until it is merged the column does not
exist: every account reads as "not a demo account" (fail closed) and the caller's transaction is untouched, since the
read runs in its own session. The positive path adds the column inside one owner transaction that is rolled back.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.llm import demo_data
from bridge.llm.demo_data import SqlDemoAccounts
from tests.integration.llm.conftest import People

Factory = async_sessionmaker[AsyncSession]


async def test_an_unreadable_column_is_no_demo_account_and_leaves_the_callers_transaction_alone(
    factory: Factory, people: People, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(demo_data, "DEMO_ACCOUNT", text("SELECT no_such_column FROM users WHERE id = :id"))
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        assert (await db.execute(text("SELECT 1"))).scalar_one() == 1  # the caller's transaction is open
        assert await SqlDemoAccounts(factory, caller=db).is_demo(people.a) is False
        assert (await db.execute(text("SELECT 2"))).scalar_one() == 2  # and still usable


async def test_on_this_schema_nobody_is_a_demo_account(factory: Factory, people: People) -> None:
    """Before schema v3 there is no column; after it, a new account defaults to false: false either way."""
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        accounts = SqlDemoAccounts(factory, caller=db)
        assert await accounts.is_demo(people.a) is False
        assert await accounts.is_demo(uuid7()) is False


async def test_with_the_schema_v3_column_a_seeded_demo_account_reads_true(
    owner_engine: AsyncEngine, people: People
) -> None:
    async with owner_engine.connect() as conn:
        outer = await conn.begin()
        try:
            exists = await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns"
                    " WHERE table_name = 'users' AND column_name = 'demo_account'"
                )
            )
            if exists.first() is None:
                await conn.execute(text("ALTER TABLE users ADD COLUMN demo_account boolean NOT NULL DEFAULT false"))
            await conn.execute(text("GRANT SELECT (demo_account) ON users TO bridge_app"))
            await conn.execute(text("UPDATE users SET demo_account = true WHERE id = :id"), {"id": people.a})
            await conn.execute(text("SET LOCAL ROLE bridge_app"))  # read as the app role, under its grants and RLS
            joined = async_sessionmaker(bind=conn, expire_on_commit=False)  # sessions join the open transaction
            caller = joined()
            await bind_tenant(caller, user_id=people.a)
            accounts = SqlDemoAccounts(joined, caller=caller)
            assert await accounts.is_demo(people.a) is True
            assert await accounts.is_demo(people.b) is False
            assert await accounts.is_demo(uuid7()) is False
            await caller.close()
        finally:
            await outer.rollback()
