"""Revision 0012's downgrade (REQ-PERS-02; review MINOR 4), in a database of its own (it commits): the vectors are
derived data, so the downgrade proceeds with rows and nulls every vector, model and version on both tables (once the
hashes go nothing would say which text a vector came from); the rows they were computed from stay, and after a
re-upgrade the worker lists them again."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import URL

from tests.integration import world as w
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.embeddings.schema_world import (
    decide,
    listed,
    named_niche,
    problems,
    set_problem,
    set_profile,
)
from tests.integration.teams.schema_world import developer

VECTORS = (
    "SELECT (SELECT count(*) FROM developer_profiles WHERE user_id = :u AND profile_embedding IS NULL"
    " AND embed_model IS NULL AND embed_version IS NULL),"
    " (SELECT count(*) FROM problems WHERE id = :p AND embedding IS NULL AND embed_model IS NULL"
    " AND embed_version IS NULL)"
)


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_embed_down_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "head"))
        yield database
    finally:
        drop_database(admin_url, name)


async def test_the_downgrade_nulls_the_vectors_and_a_re_upgrade_lists_the_rows_again(url: URL) -> None:
    owner = role_engine(url, "bridge_owner")
    try:
        async with owner.begin() as conn:
            user = await developer(conn, "down", peers=False, liked=(await named_niche(conn, "Downgrade"),))
            await decide(conn, user, True)
            issue = await w.add_problem(conn, user, await named_niche(conn, "Problem"))
            assert await set_profile(conn, user)
            assert await set_problem(conn, issue)
        async with owner.connect() as conn:
            assert tuple((await conn.execute(sa.text(VECTORS), {"u": user, "p": issue})).one()) == (0, 0)
    finally:
        await owner.dispose()

    run_alembic(url, lambda config: command.downgrade(config, "0011"))  # no flag: derived data only
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            assert tuple(conn.execute(sa.text(VECTORS), {"u": user, "p": issue}).one()) == (1, 1)
    finally:
        engine.dispose()

    run_alembic(url, lambda config: command.upgrade(config, "head"))
    owner = role_engine(url, "bridge_owner")
    try:
        async with owner.connect() as conn, conn.begin():
            assert await listed(conn, user) == {user}
            assert issue in {row.id for row in await problems(conn)}
    finally:
        await owner.dispose()
