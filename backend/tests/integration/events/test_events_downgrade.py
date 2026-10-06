"""Revision 0010's downgrade is destructive (REQ-DEV-02; a database of its own: it commits): it drops the events (the
organisations' drafts and the staff decisions with them), the developers' Remind me rows and the trend cards with their
sources. Under the CLAUDE.md stop rule it needs a backup and the human's decision, so it refuses while any of the
tables has a row unless run with ``-x allow_events_loss=true``; the refusal leaves the database at 0010 as it was.
Empty tables downgrade without the flag (the round trip in ``test_migrations.py``)."""

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

TABLES = ("events", "event_reminders", "trend_cards", "trend_card_sources")


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_events_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "0010"))
        yield database
    finally:
        drop_database(admin_url, name)


def _state(url: URL) -> tuple[str, dict[str, int | None]]:
    """The revision and each table's row count (None when the table does not exist)."""
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
            return version, counts
    finally:
        engine.dispose()


def _with_flag(config: Config) -> None:
    config.cmd_opts = argparse.Namespace(x=["allow_events_loss=true"])
    command.downgrade(config, "0009")


async def test_the_downgrade_refuses_to_drop_events_reminders_and_trends_unless_told_to(url: URL) -> None:
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            await w.build(conn, "events")  # two events and a reminder per tenant, two trend cards of two sources
    finally:
        await engine.dispose()
    held = {"events": 4, "event_reminders": 2, "trend_cards": 2, "trend_card_sources": 4}
    assert _state(url) == ("0010", held)
    with pytest.raises(RuntimeError, match="hold the events, the developers' reminders and the trend cards"):
        run_alembic(url, lambda config: command.downgrade(config, "0009"))
    assert _state(url) == ("0010", held)  # nothing was dropped
    run_alembic(url, _with_flag)
    assert _state(url) == ("0009", dict.fromkeys(TABLES))
    run_alembic(url, lambda config: command.upgrade(config, "0010"))
    assert _state(url) == ("0010", dict.fromkeys(TABLES, 0))
