"""Orchestrator re-check #29 (P5 decision 8) with a real Procrastinate worker: a decline's written reason reaches the
developer's notification through the job's arguments, and none of the worker's log records carries it."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import pytest
from procrastinate import PsycopgConnector
from procrastinate.periodic import PeriodicRegistry
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.db import create_session_factory
from bridge.engagements import notify
from bridge.jobs import notifications
from bridge.jobs.app import app
from bridge.notifications.email import FakeEmailProvider
from tests.integration.engagements.api_world import Tracker, build, deals_on, notification_jobs, open_engagement, seats
from tests.integration.provenance.test_idempotent_jobs import worker_conninfo

REASON = "Our board froze every new supplier this quarter."


@pytest.fixture
async def runtime(app_engine: AsyncEngine) -> AsyncIterator[FakeEmailProvider]:
    provider = FakeEmailProvider()
    notifications.use_runtime(
        notifications.NotificationRuntime(
            get_settings(), session_factory=create_session_factory(app_engine), email_provider=provider
        )
    )
    yield provider
    notifications.use_runtime(None)


async def test_the_worker_never_logs_a_decline_reason(
    database_url: URL,
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    runtime: FakeEmailProvider,
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    async with seats(app_engine, deals_on(), world) as s:
        await Tracker(engagement).ok(s.reviewer, "decline", {"reason": "OTHER", "other_text": REASON})
    [(job_id, args)] = await notification_jobs(owner_engine, engagement)
    assert args["reason_text"] == REASON  # it travels in the arguments (an id instead is a follow-up)
    async with owner_engine.begin() as conn:  # only this test's job: other tests leave theirs unrun
        await conn.execute(
            text("DELETE FROM procrastinate_jobs WHERE queue_name = :q AND status = 'todo' AND id <> :id"),
            {"q": notify.QUEUE, "id": job_id},
        )

    worker_app = app.with_connector(PsycopgConnector(conninfo=worker_conninfo(database_url)))
    worker_app.periodic_registry = PeriodicRegistry()  # type: ignore[no-untyped-call]  # the queue, not the clock
    with caplog.at_level(logging.DEBUG, logger="procrastinate"):
        async with worker_app.open_async():
            await worker_app.run_worker_async(
                queues=[notify.QUEUE], wait=False, install_signal_handlers=False, listen_notify=False
            )

    assert "engagements.notify" in caplog.text  # the worker logged the job
    assert REASON not in caplog.text
    assert all(REASON not in repr(getattr(record, "job", "")) for record in caplog.records)
    async with owner_engine.connect() as conn:
        status = (
            await conn.execute(text("SELECT status::text FROM procrastinate_jobs WHERE id = :id"), {"id": job_id})
        ).scalar()
        body = (
            await conn.execute(
                text("SELECT body FROM in_app_notifications WHERE user_id = :u AND kind = 'engagement.n03'"),
                {"u": world.developer},
            )
        ).scalar_one()
    assert status == "succeeded"
    assert body.endswith(f"Their reason: {REASON}")
