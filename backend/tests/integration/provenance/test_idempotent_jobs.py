"""REQ-PROV-01 (THREAT_MODEL D: "registration backlog blocks publishing"): a real Procrastinate worker, running as
``bridge_app`` on the test database, takes a registration from the publish call to "Timestamped". Duplicate queueing is
harmless: every step is idempotent, so the audit event is written once."""

from __future__ import annotations

from typing import Any

from procrastinate import PsycopgConnector
from procrastinate.periodic import PeriodicRegistry
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant
from bridge.jobs.app import app
from bridge.jobs.provenance import ProvenanceRuntime
from bridge.models.enums import ProvenanceStatus
from bridge.provenance.service import enqueue_registration
from tests.integration.provenance.builders import registered_version


def worker_conninfo(database_url: URL) -> str:
    """libpq conninfo for the test database that runs every statement as bridge_app (like production)."""
    plain = database_url.set(drivername="postgresql").render_as_string(hide_password=False)
    return f"{plain}?options=-c%20role%3Dbridge_app"


async def run_worker(database_url: URL) -> None:
    worker_app = app.with_connector(PsycopgConnector(conninfo=worker_conninfo(database_url)))
    worker_app.periodic_registry = PeriodicRegistry()  # type: ignore[no-untyped-call]  # the queue, not the clock
    async with worker_app.open_async():
        await worker_app.run_worker_async(
            queues=["provenance"], wait=False, install_signal_handlers=False, listen_notify=False
        )


async def test_a_worker_registers_a_published_version_once(
    database_url: URL, owner_engine: AsyncEngine, runtime: ProvenanceRuntime
) -> None:
    async with owner_engine.begin() as conn:  # leftovers queued by other tests' direct calls
        await conn.execute(text("DELETE FROM procrastinate_jobs WHERE queue_name = 'provenance' AND status = 'todo'"))
    built = await registered_version(owner_engine, runtime.wrapper)
    async with runtime.session_factory() as session:
        await bind_tenant(session, user_id=built.owner_id)
        await enqueue_registration(session, built.version_id)
        await enqueue_registration(session, built.version_id)  # a double publish click
        await session.commit()

    await run_worker(database_url)

    async with owner_engine.connect() as conn:
        record: Any = (
            await conn.execute(
                text("SELECT status, tsa_token FROM provenance_records WHERE version_id = :v"), {"v": built.version_id}
            )
        ).one()
        events = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM audit_events WHERE action = 'proposal.version_registered' AND subject_id = :v"
                ),
                {"v": built.version_id},
            )
        ).scalar_one()
        statuses = (
            await conn.execute(
                text("SELECT task_name, status FROM procrastinate_jobs WHERE args->>'version_id' = :v ORDER BY id"),
                {"v": str(built.version_id)},
            )
        ).all()
    assert record.status == ProvenanceStatus.TIMESTAMPED
    assert record.tsa_token is not None
    assert events == 1
    assert {s.status for s in statuses} == {"succeeded"}
    assert [s.task_name for s in statuses].count("provenance.hash_manifest") == 2
    assert [s.task_name for s in statuses].count("provenance.timestamp_manifest") == 1
