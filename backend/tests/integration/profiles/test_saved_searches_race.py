"""Revision 0008 (REQ-PERS-03; P21 track C, D-57 (7)): the cap of 10 saved searches per user holds for concurrent
sessions, in a database of its own (the sessions commit).

``saved_searches_cap`` (AFTER INSERT) takes a per-user advisory lock before it counts, and the count then reads every
committed row: of two sessions saving an eleventh search at once, the second waits for the first, counts its committed
row and is refused.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.engagements import tracker as t
from tests.integration.profiles.test_saved_searches_schema import SAVE, search


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_p21s_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "head"))
        yield database
    finally:
        drop_database(admin_url, name)


async def test_two_saves_racing_past_the_ninth_leave_exactly_ten(url: URL) -> None:
    """Given a developer with nine saved searches committed, When two of their sessions save one more each at once,
    Then the second waits for the first's per-user lock, counts its committed row and is refused (check_violation,
    saved_searches_at_most_10): exactly one of the two is saved, ten in all."""
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        async with owner.begin() as conn:
            user = await w.add_user(conn, f"racer-{uuid7().hex}@example.test", "Racer")
        async with app.begin() as conn:
            await t.act(conn, user)
            for n in range(9):
                await conn.execute(sa.text(SAVE), search(user, name=f"Search {n}"))
        async with app.connect() as first, app.connect() as second:
            for session in (first, second):
                await session.begin()
                await t.act(session, user)
            pid = await t.backend_pid(second)
            await first.execute(sa.text(SAVE), search(user, name="Tenth, first"))
            racing = asyncio.create_task(second.execute(sa.text(SAVE), search(user, name="Tenth, second")))
            await t.wait_until_blocked(first, pid, racing)
            await first.commit()
            with pytest.raises(DBAPIError, match="at most 10 per user"):
                await racing
            await second.rollback()
        async with app.begin() as conn:
            await t.act(conn, user)
            names = set((await conn.execute(sa.text("SELECT name FROM saved_searches"))).scalars())
            assert names == {f"Search {n}" for n in range(9)} | {"Tenth, first"}
    finally:
        await owner.dispose()
        await app.dispose()
