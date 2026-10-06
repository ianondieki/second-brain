"""Revision 0011's downgrade is destructive (REQ-DEV-03; a database of its own: it commits): it drops the developers'
blocks, team-up invitations, team threads with their messages and read markers, the proposals' contributor credit and
every developer's peers opt-in. Under the CLAUDE.md stop rule it needs a backup and the human's decision, so it refuses
while any of the tables has a row or any profile is opted in, unless run with ``-x allow_teams_loss=true``; the
refusal leaves the database at 0011 as it was. Empty tables and no opt-in downgrade without the flag (the round trip in
``test_migrations.py``)."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from tests.integration import world as w
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic

TABLES = (
    "developer_blocks",
    "team_invitations",
    "team_threads",
    "team_messages",
    "team_thread_reads",
    "proposal_contributors",
)
OPTED_IN = "SELECT count(*) FROM developer_profiles WHERE peers_visible"


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_teams_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "0011"))
        yield database
    finally:
        drop_database(admin_url, name)


def _state(url: URL) -> tuple[str, dict[str, int | None]]:
    """The revision, each table's row count and the opted-in profiles (None when the table or column is gone)."""
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            counts: dict[str, int | None] = {}
            for table in TABLES:
                exists = conn.execute(sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"})
                counts[table] = (
                    conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() if exists.scalar_one() else None
                )
            column = conn.execute(
                sa.text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'developer_profiles'"
                    " AND column_name = 'peers_visible')"
                )
            )
            counts["opted_in"] = conn.execute(sa.text(OPTED_IN)).scalar_one() if column.scalar_one() else None
            return version, counts
    finally:
        engine.dispose()


def _with_flag(config: Config) -> None:
    config.cmd_opts = argparse.Namespace(x=["allow_teams_loss=true"])
    command.downgrade(config, "0010")


async def test_the_downgrade_refuses_to_drop_teams_and_opt_ins_unless_told_to(url: URL) -> None:
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            await w.build(conn, "teams")  # per tenant: a block, a team with two messages, a read, two credits
    finally:
        await engine.dispose()
    held: dict[str, int | None] = {
        "developer_blocks": 2,
        "team_invitations": 2,
        "team_threads": 2,
        "team_messages": 4,
        "team_thread_reads": 2,
        "proposal_contributors": 4,
        "opted_in": 4,
    }
    assert _state(url) == ("0011", held)
    with pytest.raises(RuntimeError, match="hold the developers' blocks, team-ups, team threads"):
        run_alembic(url, lambda config: command.downgrade(config, "0010"))
    assert _state(url) == ("0011", held)  # nothing was dropped
    run_alembic(url, _with_flag)
    assert _state(url) == ("0010", dict.fromkeys(held))
    run_alembic(url, lambda config: command.upgrade(config, "0011"))
    assert _state(url) == ("0011", dict.fromkeys(held, 0))


async def test_an_opt_in_alone_holds_the_downgrade(url: URL) -> None:
    """No team row at all, one developer opted in: the downgrade still refuses (it would drop their choice)."""
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            user = await w.add_user(conn, f"opted-{uuid4().hex}@example.test", "Opted")
            await conn.execute(
                sa.text("INSERT INTO developer_profiles (user_id, handle, peers_visible) VALUES (:u, :h, true)"),
                {"u": user, "h": f"opted-{user.hex}"},
            )
    finally:
        await engine.dispose()
    with pytest.raises(RuntimeError, match=r"developer_profiles \(peers opt-ins\) hold"):
        run_alembic(url, lambda config: command.downgrade(config, "0010"))
    assert _state(url)[1]["opted_in"] == 1
