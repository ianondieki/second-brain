"""Revision 0013's downgrade is destructive (P27-M; a database of its own: it commits): it drops the organisations'
assignments and internal recommendations, every prior-knowledge declaration (append-only evidence), every calendar
feed and the developers' D3 references and nudge dismissals. Under the CLAUDE.md stop rule it needs a backup and the
human's decision, so it refuses while any of the tables has a row or any profile holds one of the four columns, unless
run with ``-x allow_p27_loss=true``; the refusal leaves the database at 0013 as it was. Empty tables and profiles
without the columns set downgrade without the flag (the round trip in ``test_migrations.py``)."""

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

TABLES = ("engagement_assignments", "engagement_recommendations", "prior_knowledge_declarations", "calendar_feeds")
D3_HELD = (
    "SELECT count(*) FROM developer_profiles WHERE github_login IS NOT NULL OR kecobo_number IS NOT NULL"
    " OR kipi_number IS NOT NULL OR ip_nudge_dismissed_at IS NOT NULL"
)


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_p27_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        # Revision 0013's rules at 0013 (a later revision's downgrade would otherwise run first in the downgrade test).
        run_alembic(database, lambda config: command.upgrade(config, "0013"))
        yield database
    finally:
        drop_database(admin_url, name)


def _state(url: URL) -> tuple[str, dict[str, int | None]]:
    """The revision, each table's row count and the profiles holding a D3 column (None when the table or column is
    gone)."""
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
                    " AND column_name = 'github_login')"
                )
            )
            counts["d3"] = conn.execute(sa.text(D3_HELD)).scalar_one() if column.scalar_one() else None
            return version, counts
    finally:
        engine.dispose()


def _with_flag(config: Config) -> None:
    config.cmd_opts = argparse.Namespace(x=["allow_p27_loss=true"])
    command.downgrade(config, "0012")


async def test_the_downgrade_refuses_to_drop_p27_data_unless_told_to(url: URL) -> None:
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            await w.build(conn, "p27")  # per tenant: an assignment, a recommendation, a declaration, two feeds
    finally:
        await engine.dispose()
    held: dict[str, int | None] = {
        "engagement_assignments": 2,
        "engagement_recommendations": 2,
        "prior_knowledge_declarations": 2,
        "calendar_feeds": 4,
        "d3": 0,
    }
    assert _state(url) == ("0013", held)
    with pytest.raises(RuntimeError, match="hold the organisations' assignments and recommendations"):
        run_alembic(url, lambda config: command.downgrade(config, "0012"))
    assert _state(url) == ("0013", held)  # nothing was dropped
    run_alembic(url, _with_flag)
    assert _state(url) == ("0012", dict.fromkeys(held))
    run_alembic(url, lambda config: command.upgrade(config, "0013"))
    assert _state(url) == ("0013", dict.fromkeys(held, 0))


async def test_a_d3_reference_alone_holds_the_downgrade(url: URL) -> None:
    """No P27 row at all, one developer with a self-reported GitHub login: the downgrade still refuses (it would drop
    what they entered)."""
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            user = await w.add_user(conn, f"d3-{uuid4().hex}@example.test", "D3")
            await conn.execute(
                sa.text("INSERT INTO developer_profiles (user_id, handle, github_login) VALUES (:u, :h, 'octo-cat')"),
                {"u": user, "h": f"d3-{user.hex}"},
            )
    finally:
        await engine.dispose()
    with pytest.raises(RuntimeError, match=r"developer_profiles \(D3 references or nudge dismissals\) hold"):
        run_alembic(url, lambda config: command.downgrade(config, "0012"))
    assert _state(url)[1]["d3"] == 1
