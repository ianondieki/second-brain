"""Revision 0006's downgrade is destructive (a database of its own: it commits): it drops ``engagement_notes``, the
parties' questions, answers and reasons, which are part of the engagements' record. Under the CLAUDE.md stop rule it
needs a backup and the human's decision, so it refuses while the table has a row unless run with
``-x allow_note_loss=true``; the refusal leaves the database at 0006 with its notes. An empty table downgrades without
the flag (the round trip in ``test_migrations.py``)."""

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


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_ndg_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "0006"))
        yield database
    finally:
        drop_database(admin_url, name)


def _state(url: URL) -> tuple[str, int | None]:
    """The revision and the number of notes (None when the table does not exist)."""
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            if not conn.execute(sa.text("SELECT to_regclass('public.engagement_notes') IS NOT NULL")).scalar_one():
                return version, None
            return version, conn.execute(sa.text("SELECT count(*) FROM engagement_notes")).scalar_one()
    finally:
        engine.dispose()


def _with_flag(config: Config) -> None:
    config.cmd_opts = argparse.Namespace(x=["allow_note_loss=true"])
    command.downgrade(config, "0005")


async def test_the_downgrade_refuses_to_drop_notes_unless_told_to(url: URL) -> None:
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            await w.build(conn, "notes")  # a note on each tenant's engagement (world.add_tracker_rows)
    finally:
        await engine.dispose()
    assert _state(url) == ("0006", 2)
    with pytest.raises(RuntimeError, match="engagement_notes holds the parties' questions"):
        run_alembic(url, lambda config: command.downgrade(config, "0005"))
    assert _state(url) == ("0006", 2)  # nothing was dropped
    run_alembic(url, _with_flag)
    assert _state(url) == ("0005", None)
    run_alembic(url, lambda config: command.upgrade(config, "0006"))
    assert _state(url) == ("0006", 0)
