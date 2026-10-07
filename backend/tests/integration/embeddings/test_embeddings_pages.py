"""Revision 0012's reader pages (REQ-PERS-02, REQ-EMB-01; review MINOR, round 3), in a database of their own so a page
holds only this module's rows: the readers walk the rows without a vector first (never embedded first, then the
oldest time, then the id), skip an empty text without losing the page, and reach the rows with a vector (another model
or version, or a changed text; oldest first) only while the page is not full."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.integration import world as w
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.embeddings.schema_world import decide, named_niche, problems, profiles, set_problem, set_profile
from tests.integration.engagements import tracker as t
from tests.integration.teams.schema_world import developer


@pytest.fixture(scope="module")
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_embed_pages_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "head"))
        yield database
    finally:
        drop_database(admin_url, name)


@asynccontextmanager
async def rolled_back(url: URL) -> AsyncIterator[AsyncConnection]:
    """One rolled-back transaction of the module's database, as the owner (tracker.as_app)."""
    engine = role_engine(url, "bridge_owner")
    try:
        async with t.as_app(engine) as conn:
            yield conn
    finally:
        await engine.dispose()


async def _aged(conn: AsyncConnection, table: str, key: str, row: UUID, column: str, days: int) -> None:
    await t.as_owner(conn)
    aged = f"UPDATE {table} SET {column} = now() - make_interval(days => :d) WHERE {key} = :id"
    await t.run(conn, aged, d=days, id=row)


async def test_a_profile_page_skips_empty_texts_and_reaches_vectors_only_when_short(url: URL) -> None:
    """Given two consented developers with nothing to embed (the smallest ids), two never embedded, one whose vector the
    owner removed but whose time stays (a day ago), and two embedded with another model (two and three days ago),
    When the worker reads pages of 1, 2, 4 and 10, Then the empty ones never appear and never shorten a page; the rows
    without a vector come first (the never embedded, then the one with a time), then the embedded ones oldest first."""
    async with rolled_back(url) as conn:
        empties = [await developer(conn, f"empty{n}", peers=False) for n in range(2)]
        for user in empties:
            await decide(conn, user, True)
        topic = await named_niche(conn, "Pages")
        never = [await developer(conn, f"never{n}", peers=False, liked=(topic,)) for n in range(2)]
        lost, older, oldest = [await developer(conn, label, peers=False, liked=(topic,)) for label in "abc"]
        for user in (*never, lost, older, oldest):
            await decide(conn, user, True)
        assert await set_profile(conn, lost)
        for user in (older, oldest):
            assert await set_profile(conn, user, model="previous")
        await _aged(conn, "developer_profiles", "user_id", lost, "profile_embedded_at", 1)
        await t.run(conn, "UPDATE developer_profiles SET profile_embedding = NULL WHERE user_id = :u", u=lost)
        await _aged(conn, "developer_profiles", "user_id", older, "profile_embedded_at", 2)
        await _aged(conn, "developer_profiles", "user_id", oldest, "profile_embedded_at", 3)
        order = [*sorted(never), lost, oldest, older]
        for limit in (1, 2, 4, 10):
            assert [row.id for row in await profiles(conn, limit=limit)] == order[:limit], limit


async def test_a_problem_page_skips_empty_texts_and_reaches_vectors_only_when_short(url: URL) -> None:
    """The same for problems: blank problems never appear and never shorten a page; the problems without a vector come
    first (by id), then those with another model's vector, oldest first."""
    async with rolled_back(url) as conn:
        author = await developer(conn, "author", peers=False)
        topic = await named_niche(conn, "Problem pages")
        blank = [await w.add_problem(conn, author, topic) for _ in range(2)]
        for problem_id in blank:
            await t.run(conn, "UPDATE problems SET title = ' ', statement = ' ' WHERE id = :id", id=problem_id)
        never = [await w.add_problem(conn, author, topic) for _ in range(2)]
        older, oldest = await w.add_problem(conn, author, topic), await w.add_problem(conn, author, topic)
        for problem_id, days in ((older, 2), (oldest, 3)):
            assert await set_problem(conn, problem_id, model="previous")
            await _aged(conn, "problems", "id", problem_id, "embedded_at", days)
        order = [*sorted(never), oldest, older]
        for limit in (1, 2, 3, 10):
            assert [row.id for row in await problems(conn, limit=limit)] == order[:limit], limit
