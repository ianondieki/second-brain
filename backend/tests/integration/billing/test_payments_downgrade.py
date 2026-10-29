"""Revision 0005's downgrade is destructive (a database of its own: it commits): it drops ``payments``, which holds
financial records. Under the CLAUDE.md stop rule it needs a backup and the human's decision, so it refuses while
``payments`` has a row unless run with ``-x allow_payment_loss=true``; the refusal leaves the database at 0005 with its
payment. An empty ``payments`` downgrades without the flag (the round trip in ``test_migrations.py``)."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from bridge.ids import uuid7
from tests.integration.conftest import create_database, drop_database, run_alembic


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_pdg_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "0005"))  # this revision's guard, not later ones
        yield database
    finally:
        drop_database(admin_url, name)


def _payment(url: URL) -> None:
    user, plan = uuid7(), uuid7()
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
            conn.execute(
                sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Payer')"),
                {"id": user, "email": f"{user.hex}@example.test"},
            )
            conn.execute(
                sa.text(
                    'INSERT INTO plans (id, code, side, name, price_kes_minor, "interval", limits)'
                    " VALUES (:id, :code, 'developer', 'Pro', 49900, 'month', '{}'::jsonb)"
                ),
                {"id": plan, "code": f"pro-{plan.hex}"},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO payments (id, user_id, plan_id, amount_kes_minor, provider, provider_ref,"
                    " initiated_by) VALUES (:id, :u, :p, 49900, 'fake', :ref, :u)"
                ),
                {"id": uuid7(), "u": user, "p": plan, "ref": f"fake_{uuid7().hex}"},
            )
    finally:
        engine.dispose()


def _state(url: URL) -> tuple[str, bool]:
    engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as conn:
            version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            payments = conn.execute(sa.text("SELECT to_regclass('public.payments') IS NOT NULL")).scalar_one()
            return version, bool(payments)
    finally:
        engine.dispose()


def _with_flag(config: Config) -> None:
    config.cmd_opts = argparse.Namespace(x=["allow_payment_loss=true"])
    command.downgrade(config, "0004")


def test_the_downgrade_refuses_to_drop_payment_records_unless_told_to(url: URL) -> None:
    _payment(url)
    with pytest.raises(RuntimeError, match="payments holds financial records"):
        run_alembic(url, lambda config: command.downgrade(config, "0004"))
    assert _state(url) == ("0005", True)  # nothing was dropped
    run_alembic(url, _with_flag)
    assert _state(url) == ("0004", False)
    run_alembic(url, lambda config: command.upgrade(config, "0005"))
    assert _state(url) == ("0005", True)
