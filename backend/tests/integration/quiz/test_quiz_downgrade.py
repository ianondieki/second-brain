"""Revision 0009's downgrade is destructive (REQ-DEV-01; a database of its own: it commits): it drops the quiz, the
developers' attempts, flags, streaks and leaderboard opt-ins included. Under the CLAUDE.md stop rule it needs a backup
and the human's decision, so it refuses while any quiz table has a row unless run with ``-x allow_quiz_loss=true``;
the refusal leaves the database at 0009 as it was. Empty tables downgrade without the flag (the round trip in
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

QUIZ_TABLES = ("quiz_sets", "quiz_questions", "quiz_attempts", "quiz_flags", "quiz_profiles")


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_quiz_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "0009"))
        yield database
    finally:
        drop_database(admin_url, name)


def _state(url: URL) -> tuple[str, dict[str, int | None]]:
    """The revision and each quiz table's row count (None when the table does not exist)."""
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            counts: dict[str, int | None] = {}
            for table in QUIZ_TABLES:
                exists = conn.execute(sa.text("SELECT to_regclass(:t) IS NOT NULL"), {"t": f"public.{table}"})
                counts[table] = (
                    conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one() if exists.scalar_one() else None
                )
            return version, counts
    finally:
        engine.dispose()


def _with_flag(config: Config) -> None:
    config.cmd_opts = argparse.Namespace(x=["allow_quiz_loss=true"])
    command.downgrade(config, "0008")


async def test_the_downgrade_refuses_to_drop_the_quiz_unless_told_to(url: URL) -> None:
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            await w.build(conn, "quiz")  # two quiz sets of five questions, two attempts, two flags, two profiles
    finally:
        await engine.dispose()
    held = {"quiz_sets": 2, "quiz_questions": 10, "quiz_attempts": 2, "quiz_flags": 2, "quiz_profiles": 2}
    assert _state(url) == ("0009", held)
    with pytest.raises(RuntimeError, match="hold the quiz and the developers' attempts and streaks"):
        run_alembic(url, lambda config: command.downgrade(config, "0008"))
    assert _state(url) == ("0009", held)  # nothing was dropped
    run_alembic(url, _with_flag)
    assert _state(url) == ("0008", dict.fromkeys(QUIZ_TABLES))
    run_alembic(url, lambda config: command.upgrade(config, "0009"))
    assert _state(url) == ("0009", dict.fromkeys(QUIZ_TABLES, 0))
