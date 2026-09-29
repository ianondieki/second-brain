"""Shared helpers for the P14 checkout API tests (REQ-BIL-08, the REQ-BIL-04 interface).

Every test runs on ``FakePaymentProvider`` (D-36); nothing reaches a network. ``instant`` installs a fake that settles
at once, ``slow`` one that waits on the app clock. ``plans_seeded`` upserts ``config/plans.yaml`` into the session
database (the checkout reads the ``plans`` rows, as the payments policy does).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.billing.providers.fake import FakePaymentProvider
from bridge.config import get_settings
from bridge.seed.reference import seed_plans
from tests.integration.proposals.helpers import rows


@pytest.fixture(scope="session")
async def plans_seeded(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_plans(conn, get_settings())


def install(client: httpx.AsyncClient, provider: FakePaymentProvider) -> FakePaymentProvider:
    client.app.state.payment_provider = provider  # type: ignore[attr-defined]
    return provider


def instant(client: httpx.AsyncClient) -> FakePaymentProvider:
    return install(client, FakePaymentProvider(delay=timedelta(0)))


def slow(client: httpx.AsyncClient, delay: timedelta = timedelta(minutes=10)) -> FakePaymentProvider:
    return install(client, FakePaymentProvider(delay=delay))


async def buy(client: httpx.AsyncClient, plan_code: str, **extra: Any) -> httpx.Response:
    return await client.post("/api/billing/checkouts", json={"plan_code": plan_code, **extra})


async def status_of(client: httpx.AsyncClient, checkout_id: str) -> httpx.Response:
    return await client.get(f"/api/billing/checkouts/{checkout_id}")


async def payment_row(owner_engine: AsyncEngine, checkout_id: str | UUID) -> Any:
    sql = "SELECT p.*, pl.code AS plan_code FROM payments p JOIN plans pl ON pl.id = p.plan_id WHERE p.id = :id"
    found = await rows(owner_engine, sql, id=str(checkout_id))
    return found[0] if found else None


async def payments_of(owner_engine: AsyncEngine, *, user: UUID | None = None, org: UUID | None = None) -> list[Any]:
    if org is not None:
        return await rows(owner_engine, "SELECT * FROM payments WHERE org_id = :o ORDER BY created_at", o=org)
    sql = "SELECT * FROM payments WHERE user_id = :u AND org_id IS NULL ORDER BY created_at"
    return await rows(owner_engine, sql, u=user)


async def live_plans(owner_engine: AsyncEngine, *, user: UUID | None = None, org: UUID | None = None) -> list[str]:
    column, value = ("s.org_id", org) if org is not None else ("s.user_id", user)
    sql = (
        f"SELECT pl.code FROM subscriptions s JOIN plans pl ON pl.id = s.plan_id WHERE {column} = :v"
        " AND s.status IN ('trialing', 'active', 'past_due')"
    )
    return [r.code for r in await rows(owner_engine, sql, v=value)]


async def audit_actions(owner_engine: AsyncEngine, payment_id: str | UUID) -> list[str]:
    sql = (
        "SELECT action FROM audit_events WHERE subject_type = 'payment' AND subject_id = :id ORDER BY occurred_at, seq"
    )
    return [r.action for r in await rows(owner_engine, sql, id=str(payment_id))]


@pytest.fixture
async def moved_clock(owner_engine: AsyncEngine) -> AsyncIterator[Any]:
    """``await moved_clock(timedelta)``: enable the dev/test clock and move it forward (as ``python -m bridge.seed``
    and ``POST /api/test-clock/advance`` would); the clock is put back as it was afterwards (other tests share it)."""
    [before] = await rows(owner_engine, "SELECT enabled, clock_offset FROM test_clock WHERE singleton")

    async def move(by: timedelta) -> None:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE test_clock SET enabled = true, clock_offset = clock_offset + :by WHERE singleton"),
                {"by": by},
            )

    yield move
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE test_clock SET enabled = :e, clock_offset = :o WHERE singleton"),
            {"e": before.enabled, "o": before.clock_offset},
        )
