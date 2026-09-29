"""Two-connection test of revision 0005 (a database of its own: it commits): activations of one subject are serialised.

``app_activate_paid_subscription`` takes a per-subject advisory lock before it reads the subject's live subscription.
Two paid payments of one developer activated at the same time: the second waits for the first to commit, then cancels
the subscription the first activated and starts its own. Without the lock the second's cancellation would miss the
first's new subscription (its statement's snapshot predates that commit) and its insert would fail on the one-live-
subscription index.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import URL

from bridge.ids import uuid7
from tests.integration.conftest import create_database, drop_database, run_alembic

ACTIVATE = sa.text("SELECT app_activate_paid_subscription(:id)")


@pytest.fixture(scope="module")
def engine(admin_url: URL) -> Iterator[sa.Engine]:
    name = f"bridge_pay_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
        yield engine
        engine.dispose()
    finally:
        drop_database(admin_url, name)


def _paid(engine: sa.Engine) -> tuple[UUID, UUID, UUID, UUID]:
    """As the owner, committed: a developer on the free plan with two succeeded, unlinked payments (a month and a
    year). Returns (developer, free subscription, monthly payment, yearly payment)."""
    developer, free_plan, subscription = uuid7(), uuid7(), uuid7()
    plans = {"month": (uuid7(), 49_900), "year": (uuid7(), 499_000)}
    payments = {"month": uuid7(), "year": uuid7()}
    with engine.begin() as conn:
        conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
        conn.execute(
            sa.text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Payer')"),
            {"id": developer, "email": f"{developer.hex}@example.test"},
        )
        conn.execute(
            sa.text(
                'INSERT INTO plans (id, code, side, name, price_kes_minor, "interval", limits, is_default)'
                " VALUES (:id, :code, 'developer', 'Free', 0, 'none', '{}'::jsonb, true) ON CONFLICT DO NOTHING"
            ),
            {"id": free_plan, "code": f"free-{free_plan.hex}"},
        )
        free = conn.execute(sa.text("SELECT id FROM plans WHERE side = 'developer' AND is_default")).scalar_one()
        conn.execute(
            sa.text(
                "INSERT INTO subscriptions (id, user_id, plan_id, status, current_period_start)"
                " VALUES (:id, :u, :p, 'active', now())"
            ),
            {"id": subscription, "u": developer, "p": free},
        )
        for interval, (plan, price) in plans.items():
            conn.execute(
                sa.text(
                    'INSERT INTO plans (id, code, side, name, price_kes_minor, "interval", limits)'
                    " VALUES (:id, :code, 'developer', 'Pro', :price, CAST(:interval AS billing_interval), '{}'::jsonb)"
                ),
                {"id": plan, "code": f"pro-{plan.hex}", "price": price, "interval": interval},
            )
            conn.execute(
                sa.text(
                    "INSERT INTO payments (id, user_id, plan_id, amount_kes_minor, provider, provider_ref,"
                    " initiated_by) VALUES (:id, :u, :p, :price, 'fake', :ref, :u)"
                ),
                {"id": payments[interval], "u": developer, "p": plan, "price": price, "ref": f"fake_{uuid7().hex}"},
            )
            conn.execute(sa.text("UPDATE payments SET status = 'succeeded' WHERE id = :id"), {"id": payments[interval]})
    return developer, subscription, payments["month"], payments["year"]


def _as(conn: sa.Connection, user: UUID) -> None:
    conn.exec_driver_sql("SET LOCAL ROLE bridge_app")
    conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user)})


def test_two_activations_of_one_subject_are_serialised(engine: sa.Engine) -> None:
    developer, free, monthly, yearly = _paid(engine)
    errors: list[BaseException] = []
    pid: list[int] = []
    activated: list[UUID] = []
    finished = threading.Event()

    def second() -> None:
        try:
            with engine.begin() as conn:
                _as(conn, developer)
                conn.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
                pid.append(conn.execute(sa.text("SELECT pg_backend_pid()")).scalar_one())
                activated.append(conn.execute(ACTIVATE, {"id": yearly}).scalar_one())
        except BaseException as exc:  # reported by the main thread
            errors.append(exc)
        finally:
            finished.set()

    blocked = sa.text("SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted")
    waited = False
    with engine.begin() as first:  # holds the subject's lock until it commits on exit
        _as(first, developer)
        first_subscription = first.execute(ACTIVATE, {"id": monthly}).scalar_one()
        thread = threading.Thread(target=second)
        thread.start()
        deadline = time.monotonic() + 10
        while not waited and not finished.is_set() and time.monotonic() < deadline:
            time.sleep(0.05)
            if pid:
                waited = bool(first.execute(blocked, {"pid": pid[0]}).scalar_one())
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert waited, "the second activation did not wait for the first"
    assert not errors, errors
    with engine.connect() as conn:
        found = conn.execute(
            sa.text("SELECT id, status::text FROM subscriptions WHERE user_id = :u ORDER BY created_at, id"),
            {"u": developer},
        ).all()
    assert [tuple(row) for row in found] == [
        (free, "cancelled"),
        (first_subscription, "cancelled"),
        (activated[0], "active"),
    ]
