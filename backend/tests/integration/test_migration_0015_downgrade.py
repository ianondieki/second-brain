"""Revision 0015's downgrade is destructive (P28-M; a database of its own: it commits): it drops the nudges ledger, the
organisations' niche defaults and escalation contacts and every procurement decision. Under the CLAUDE.md stop rule
it needs a backup and the human's decision, so it refuses while any of them holds data, unless run with ``-x
allow_p28_loss=true``; and it refuses in any case while an engagement names a contact without a contact-by date
(revision 0003's CHECK, which it restores, would refuse the row); and, without the flag, while an engagement is in
PROCUREMENT_ROUTE or paused from it (revision 0014's code has no command that leaves 3b). A refusal leaves the
database at 0015 as it was.
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
from tests.integration.engagements import tracker as t

TABLES = ("engagement_nudges", "org_niche_defaults", "org_escalation_contacts")


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_p28_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "0015"))
        yield database
    finally:
        drop_database(admin_url, name)


def _state(url: URL) -> tuple[str, dict[str, int | None]]:
    """The revision and each table's row count (None when the table is gone)."""
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
    config.cmd_opts = argparse.Namespace(x=["allow_p28_loss=true"])
    command.downgrade(config, "0014")


async def _owner_sql(url: URL, *statements: str) -> w.World:
    """As the owner, committed: the two-tenant world, then ``statements`` (``:org`` and ``:user`` are tenant A's)."""
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            world = await w.build(conn, "p28")  # per tenant: a nudge, a niche default and an escalation contact
            for statement in statements:
                await conn.execute(sa.text(statement), {"org": world.a.org_id, "user": world.a.user_id})
            return world
    finally:
        await engine.dispose()


async def test_the_downgrade_refuses_to_drop_p28_data_unless_told_to(url: URL) -> None:
    await _owner_sql(url)
    held: dict[str, int | None] = {"engagement_nudges": 2, "org_niche_defaults": 2, "org_escalation_contacts": 2}
    assert _state(url) == ("0015", held)
    with pytest.raises(RuntimeError, match="engagement_nudges, org_niche_defaults, org_escalation_contacts hold"):
        run_alembic(url, lambda config: command.downgrade(config, "0014"))
    assert _state(url) == ("0015", held)  # nothing was dropped
    run_alembic(url, _with_flag)
    assert _state(url) == ("0014", dict.fromkeys(held))
    run_alembic(url, lambda config: command.upgrade(config, "0015"))
    assert _state(url) == ("0015", dict.fromkeys(held, 0))


async def test_a_contact_without_its_date_holds_the_downgrade_even_when_told(url: URL) -> None:
    """An engagement naming its contact without a contact-by date (allowed since 0015, for a public entity's 3b)
    cannot go back under revision 0003's CHECK: the downgrade refuses with the flag too, and nothing changes."""
    await _owner_sql(
        url,
        "UPDATE engagements SET contact_user_id = :user, contact_channel = 'email' WHERE org_id = :org",
    )
    before = _state(url)
    with pytest.raises(RuntimeError, match="names a contact without a contact-by date"):
        run_alembic(url, _with_flag)
    assert _state(url) == before


async def test_an_engagement_in_or_paused_from_3b_holds_the_downgrade(url: URL) -> None:
    """Revision 0014's code has no command that leaves PROCUREMENT_ROUTE, so the downgrade refuses (without the flag)
    while an engagement is in 3b and while one is on hold from it; a hold entered from UNDER_REVIEW holds nothing. Once
    the 3b engagement has ended, the downgrade runs without the flag (no other 0015 data exists here)."""
    engine = role_engine(url, "bridge_owner")
    try:
        async with engine.begin() as conn:
            p = await t.parties(conn)
            await t.run(conn, "UPDATE organizations SET public_entity = true WHERE id = :org", org=p.org)
            await t.act(conn, p.developer)
            procuring = await t.engage(conn, p)
            await t.walk(conn, p, procuring, "UNDER_REVIEW")
            await t.act(conn, p.signatory, p.org)
            await t.append(conn, procuring, p.signatory, "signatory", "approve", "UNDER_REVIEW", "PROCUREMENT_ROUTE")
            await t.as_owner(conn)
            q = await t.parties(conn)  # a hold from UNDER_REVIEW, which 0014's code resumes
            await t.act(conn, q.developer)
            reviewed = await t.engage(conn, q)
            await t.walk(conn, q, reviewed, "UNDER_REVIEW")
            await t.append(conn, reviewed, q.developer, "developer", "pause", "UNDER_REVIEW", "ON_HOLD")
        with pytest.raises(RuntimeError, match=r"engagements \(in PROCUREMENT_ROUTE or paused from it\) hold"):
            run_alembic(url, lambda config: command.downgrade(config, "0014"))
        async with engine.begin() as conn:
            await t.act(conn, p.developer)
            await t.append(conn, procuring, p.developer, "developer", "pause", "PROCUREMENT_ROUTE", "ON_HOLD")
        with pytest.raises(RuntimeError, match=r"engagements \(in PROCUREMENT_ROUTE or paused from it\) hold"):
            run_alembic(url, lambda config: command.downgrade(config, "0014"))
        assert _state(url)[0] == "0015"
        async with engine.begin() as conn:
            await t.act(conn, p.developer)
            await t.append(conn, procuring, p.developer, "developer", "resume", "ON_HOLD", "PROCUREMENT_ROUTE")
            await t.append(conn, procuring, p.developer, "developer", "withdraw", "PROCUREMENT_ROUTE", "WITHDRAWN")
    finally:
        await engine.dispose()
    run_alembic(url, lambda config: command.downgrade(config, "0014"))
    assert _state(url)[0] == "0014"
