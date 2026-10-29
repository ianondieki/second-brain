"""Two-connection tests of revision 0003 (a database of their own: they commit).

- An outsider's refused write takes no lock on another party's engagement: the visibility trigger refuses before any
  SECURITY DEFINER trigger reads or locks the engagement (review P1, MAJOR 1).
- Finalising an agreement and planning its milestones are serialised on the agreement's row: a milestone planned while
  another transaction finalises waits and is then refused, and deleting the last milestone while another transaction
  finalises makes the finalisation wait and then fail (review P1, MAJOR 2).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import URL

from bridge.ids import uuid7
from tests.integration.conftest import create_database, drop_database, run_alembic
from tests.integration.engagements.tracker import APPEND, PDF_SHA256, event_params

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '3s'"
MILESTONE = (
    "INSERT INTO milestones (id, agreement_id, engagement_id, seq, deliverable, amount_kes_minor, due_date,"
    " review_window_bd) VALUES (:id, :a, :e, :seq, 'Pilot', 1000, :due, 5)"
)
FINALISE = (
    "UPDATE agreements SET ip_terms = 'non_exclusive_licence', deemed_acceptance_days = 10, final_pdf_sha256 = :sha,"
    " status = 'final' WHERE id = :a"
)


@dataclass(frozen=True, slots=True)
class Committed:
    developer: UUID
    org: UUID
    engagement: UUID
    agreement: UUID
    milestone: UUID


@pytest.fixture(scope="module")
def engine(admin_url: URL) -> Iterator[sa.Engine]:
    name = f"bridge_ser_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
        yield engine
        engine.dispose()
    finally:
        drop_database(admin_url, name)


def committed(engine: sa.Engine) -> Committed:
    """As the owner, committed: an engagement in NEGOTIATION (inserted there, as fixtures may) with a draft agreement
    and one milestone."""
    developer, org, niche, proposal, version, engagement, agreement, milestone = (uuid7() for _ in range(8))
    statements: list[tuple[str, dict[str, object]]] = [
        (
            "INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Developer')",
            {"id": developer, "email": f"{developer.hex}@example.test"},
        ),
        (
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification) VALUES (:id, 'company',"
            " 'Serial Ltd', :slug, 'seed', 'e2')",
            {"id": org, "slug": f"serial-{org.hex}"},
        ),
        ("INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Serial')", {"id": niche, "s": f"s-{niche.hex}"}),
        (
            "INSERT INTO proposals (id, owner_id, title, niche_id) VALUES (:id, :o, 'Serial', :n)",
            {"id": proposal, "o": developer, "n": niche},
        ),
        (
            "INSERT INTO proposal_versions (id, proposal_id, version_no) VALUES (:id, :p, 1)",
            {"id": version, "p": proposal},
        ),
        (
            "INSERT INTO engagements (id, proposal_id, org_id, developer_id, version_id, origin, state)"
            " VALUES (:id, :p, :o, :d, :v, 'tagged', 'NEGOTIATION')",
            {"id": engagement, "p": proposal, "o": org, "d": developer, "v": version},
        ),
        (
            "INSERT INTO agreements (id, engagement_id, version, created_by) VALUES (:id, :e, 1, :d)",
            {"id": agreement, "e": engagement, "d": developer},
        ),
        (MILESTONE, {"id": milestone, "a": agreement, "e": engagement, "seq": 1, "due": date(2027, 3, 31)}),
    ]
    with engine.begin() as conn:
        conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
        for sql, params in statements:
            conn.execute(sa.text(sql), params)
    return Committed(developer, org, engagement, agreement, milestone)


def race(engine: sa.Engine, first: Callable[[sa.Connection], None], second: Callable[[sa.Connection], None]) -> str:
    """Run ``first`` in a transaction that stays open until ``second`` (another connection, as the owner, lock timeout
    3 s) either waits on a lock or finishes; then commit ``first``. Returns "waited" or "did not wait", followed by
    the second transaction's error ("" when it committed)."""
    errors: list[BaseException] = []
    pid: list[int] = []
    finished = threading.Event()

    def other() -> None:
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
                conn.exec_driver_sql(LOCK_TIMEOUT)
                pid.append(conn.execute(sa.text("SELECT pg_backend_pid()")).scalar_one())
                second(conn)
        except BaseException as exc:  # reported by the main thread
            errors.append(exc)
        finally:
            finished.set()

    blocked = sa.text("SELECT count(*) FROM pg_locks WHERE pid = :pid AND NOT granted")
    waited = False
    with engine.begin() as conn:
        conn.exec_driver_sql("SET LOCAL ROLE bridge_owner")
        first(conn)
        thread = threading.Thread(target=other)
        thread.start()
        deadline = time.monotonic() + 10
        while not waited and not finished.is_set() and time.monotonic() < deadline:
            time.sleep(0.05)
            if pid:
                waited = bool(conn.execute(blocked, {"pid": pid[0]}).scalar_one())
    thread.join(timeout=30)
    assert not thread.is_alive()
    error = str(getattr(errors[0], "orig", errors[0])).splitlines()[0] if errors else ""
    return ("waited" if waited else "did not wait") + (f": {error}" if error else "")


def test_an_outsider_takes_no_lock_on_another_partys_engagement(engine: sa.Engine) -> None:
    """While a party's append holds the engagement's row lock, an outsider's event on it is refused at once with the
    generic privilege error: the refusal comes before any trigger that locks or reads the engagement."""
    fixture = committed(engine)
    outsider = uuid7()
    errors: list[str] = []
    with engine.begin() as party:  # holds the row lock of an append until it commits
        party.exec_driver_sql("SET LOCAL ROLE bridge_owner")
        party.execute(
            sa.text(APPEND), event_params(fixture.engagement, None, "system", "note", "NEGOTIATION", "NEGOTIATION")
        )
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL ROLE bridge_app")
            conn.exec_driver_sql(LOCK_TIMEOUT)
            conn.execute(sa.text("SELECT set_config('app.user_id', :u, true)"), {"u": str(outsider)})
            for from_state in ("NEGOTIATION", "SUBMITTED"):
                savepoint = conn.begin_nested()
                try:
                    conn.execute(
                        sa.text(APPEND),
                        event_params(fixture.engagement, outsider, "developer", "note", from_state, from_state),
                    )
                except sa.exc.DBAPIError as exc:
                    errors.append(f"{exc.orig.sqlstate} {exc.orig.diag.message_primary}")  # type: ignore[union-attr]
                savepoint.rollback()
    assert len(errors) == 2
    assert errors[0] == errors[1]
    assert errors[0].startswith("42501 ")  # insufficient_privilege, not a lock timeout (55P03)


def test_a_milestone_planned_during_finalisation_waits_and_is_refused(engine: sa.Engine) -> None:
    fixture = committed(engine)

    def finalise(conn: sa.Connection) -> None:
        conn.execute(sa.text(FINALISE), {"sha": PDF_SHA256, "a": fixture.agreement})

    def plan(conn: sa.Connection) -> None:
        conn.execute(
            sa.text(MILESTONE),
            {"id": uuid7(), "a": fixture.agreement, "e": fixture.engagement, "seq": 2, "due": date(2027, 4, 30)},
        )

    outcome = race(engine, finalise, plan)
    assert outcome.startswith("waited: ")
    assert "planned while their agreement is a draft" in outcome
    with engine.connect() as conn:
        assert (
            conn.execute(
                sa.text("SELECT count(*) FROM milestones WHERE agreement_id = :a"), {"a": fixture.agreement}
            ).scalar_one()
            == 1
        )


def test_finalising_while_the_last_milestone_is_deleted_waits_and_fails(engine: sa.Engine) -> None:
    fixture = committed(engine)

    def delete(conn: sa.Connection) -> None:
        conn.execute(sa.text("DELETE FROM milestones WHERE id = :m"), {"m": fixture.milestone})

    def finalise(conn: sa.Connection) -> None:
        conn.execute(sa.text(FINALISE), {"sha": PDF_SHA256, "a": fixture.agreement})

    outcome = race(engine, delete, finalise)
    assert outcome.startswith("waited: ")
    assert "needs at least one milestone" in outcome
    with engine.connect() as conn:
        status = conn.execute(sa.text("SELECT status::text FROM agreements WHERE id = :a"), {"a": fixture.agreement})
        assert status.scalar_one() == "draft"
