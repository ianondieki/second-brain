"""REQ-AUTH-01 Phase 2 follow-ups 7 and 8 (task card; THREAT_MODEL.md §1): cancelling two-step sign-in setup, the
pending secret's 15-minute lifetime, and new recovery codes.

Races run the first request's service call in a transaction the test holds open, start the second request through
the API, wait until PostgreSQL shows it blocked by that transaction (the lock-and-wait pattern of
``test_concurrent_appends_to_one_chain_are_serialised``; no fixed sleeps), then commit, so the order is forced.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

import bridge.clock
from bridge.auth import service, sessions, totp
from bridge.auth.crypto import decode_key, encrypt
from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.profiles.consents import consents_version
from bridge.seed.reference import seed_all
from tests.integration.api import make_client, outbox, refresh_csrf

PASSWORD = "correct horse battery staple"
ENROL = "/api/auth/totp/enrol"
CONFIRM = "/api/auth/totp/confirm"
CODES = "/api/auth/totp/recovery-codes"
NOT_A_CODE = "1234567"  # seven digits: refused as invalid_code by any secret, never by chance


@pytest.fixture(scope="module", autouse=True)
async def seeded(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())


@pytest.fixture
async def client(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app_engine) as c:
        yield c


def now_counter() -> int:
    return int(time.time() // 30)


def new_ip() -> str:
    n = uuid4().int
    return f"10.{n >> 16 & 255}.{n >> 8 & 255}.{n & 255}"


def error(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, str(response.json()["detail"]["code"])


async def verified(client: httpx.AsyncClient) -> str:
    """A developer account signed in through its emailed link in this browser; returns the address."""
    address = f"user-{uuid4().hex[:10]}@example.com"
    body: dict[str, Any] = {
        "email": address,
        "password": PASSWORD,
        "display_name": "Test User",
        "side": "developer",
        "accept_terms": True,
        "consents": {},
        "consents_version": consents_version(get_settings()),
    }
    assert (await client.post("/api/auth/signup", json=body)).status_code == 202
    message = [m for m in outbox(client).outbox if m.to == address][-1]
    match = re.search(r"/auth/link#token=([A-Za-z0-9_\-]+)", message.text)
    assert match, message.text
    assert (await client.post("/api/auth/magic-link/consume", json={"token": match.group(1)})).status_code == 200
    await refresh_csrf(client)
    return address


async def begin(client: httpx.AsyncClient) -> str:
    started = await client.post(ENROL, json={"password": PASSWORD})
    assert started.status_code == 200, started.text
    return str(started.json()["secret"])


async def enrolled(client: httpx.AsyncClient) -> list[str]:
    """Turn two-step sign-in on; returns the recovery codes shown at setup."""
    secret = await begin(client)
    confirmed = await client.post(CONFIRM, json={"code": totp.code_at(secret, now_counter())})
    assert confirmed.status_code == 200, confirmed.text
    return list(confirmed.json()["recovery_codes"])


async def user_row(owner_engine: AsyncEngine, address: str) -> dict[str, Any]:
    async with owner_engine.connect() as conn:
        row = await conn.execute(
            text("SELECT id, totp_pending_enc, totp_enabled_at, totp_recovery_hashes FROM users WHERE email = :e"),
            {"e": address},
        )
        return dict(row.mappings().one())


def hashes_of(codes: list[str]) -> list[str]:
    pepper = get_settings().recovery_code_pepper.get_secret_value()
    return sorted(totp.recovery_hash(code, pepper) for code in codes)


async def live_session(db: AsyncSession, client: httpx.AsyncClient) -> sessions.LiveSession:
    """The browser's session, loaded in a transaction the test controls."""
    token = client.cookies.get(get_settings().session_cookie_name)
    assert token
    live = await sessions.lookup(db, token)
    assert live is not None
    await bind_tenant(db, user_id=live.user.id)
    return live


async def blocked_behind(
    holder: AsyncSession, request: Coroutine[Any, Any, httpx.Response]
) -> asyncio.Task[httpx.Response]:
    """Start ``request`` and return once PostgreSQL shows it waiting on a lock held by ``holder``'s open transaction."""
    pid = (await holder.execute(text("SELECT pg_backend_pid()"))).scalar_one()
    waiting = text("SELECT count(*) FROM pg_locks WHERE NOT granted AND :pid = ANY(pg_blocking_pids(pid))")
    task = asyncio.ensure_future(request)
    deadline = time.monotonic() + 60
    while not task.done() and time.monotonic() < deadline:
        if (await holder.execute(waiting, {"pid": pid})).scalar_one():
            return task
        await asyncio.sleep(0.05)  # lets the request run up to its lock; the order comes from the lock, not a delay
    task.cancel()
    raise AssertionError("the second request did not wait on the first one's user-row lock")


# ------------------------------------------------------------------ follow-up 7: cancel setup, pending-secret lifetime


async def test_cancel_clears_the_pending_secret_and_a_late_confirmation_finds_nothing(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    address = await verified(client)
    secret = await begin(client)
    del client.headers["X-CSRF-Token"]
    assert error(await client.delete(ENROL)) == (403, "csrf_failed")  # a cross-site DELETE changes nothing
    assert (await user_row(owner_engine, address))["totp_pending_enc"] is not None
    await refresh_csrf(client)
    assert (await client.delete(ENROL)).status_code == 204
    assert (await user_row(owner_engine, address))["totp_pending_enc"] is None
    late = await client.post(CONFIRM, json={"code": totp.code_at(secret, now_counter())})
    assert error(late) == (409, "no_pending_enrolment")
    assert error(await client.delete(ENROL)) == (409, "no_pending_enrolment")  # nothing left to cancel


async def test_cancel_answers_totp_already_enabled_when_two_step_sign_in_is_on(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    address = await verified(client)
    await enrolled(client)
    assert error(await client.delete(ENROL)) == (409, "totp_already_enabled")
    row = await user_row(owner_engine, address)
    assert row["totp_enabled_at"] is not None
    assert len(row["totp_recovery_hashes"]) == 10


async def test_cancel_needs_a_signed_in_session(client: httpx.AsyncClient) -> None:
    assert error(await client.delete(ENROL)) == (401, "unauthenticated")


async def test_a_pending_secret_expires_after_15_minutes(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closed tab is covered too: a secret pending for over 15 minutes (the magic-link lifetime) is cleared by the
    confirmation, which then answers as if nothing were pending."""
    address = await verified(client)
    secret = await begin(client)
    started = datetime.now(UTC)
    monkeypatch.setattr(bridge.clock, "utcnow", lambda: started + timedelta(minutes=14))
    assert error(await client.post(CONFIRM, json={"code": NOT_A_CODE})) == (401, "invalid_code")  # still pending
    monkeypatch.setattr(bridge.clock, "utcnow", lambda: started + timedelta(minutes=16))
    late = await client.post(CONFIRM, json={"code": totp.code_at(secret, now_counter())})
    assert error(late) == (409, "no_pending_enrolment")
    row = await user_row(owner_engine, address)
    assert row["totp_pending_enc"] is None
    assert row["totp_enabled_at"] is None


async def test_a_pending_secret_stored_without_its_start_time_counts_as_expired(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    """Secrets left pending before the start time was sealed with them cannot be confirmed; setup starts again."""
    address = await verified(client)
    secret = await begin(client)
    user_id = (await user_row(owner_engine, address))["id"]
    key = decode_key(get_settings().data_encryption_key.get_secret_value())
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET totp_pending_enc = :blob WHERE id = :u"),
            {"blob": encrypt(key, secret.encode("ascii"), user_id.bytes), "u": user_id},
        )
    late = await client.post(CONFIRM, json={"code": totp.code_at(secret, now_counter())})
    assert error(late) == (409, "no_pending_enrolment")
    assert (await user_row(owner_engine, address))["totp_pending_enc"] is None


async def test_a_cancel_behind_a_committing_confirmation_answers_totp_already_enabled(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    """THREAT_MODEL §1 "Cancel setup reads 'off' before a lost confirmation commits": the DELETE waits on the
    confirmation's user-row lock, then reports two-step sign-in on (the page then says the codes were not shown)."""
    address = await verified(client)
    secret = await begin(client)
    async with create_session_factory(app_engine)() as first:
        live = await live_session(first, client)
        await service.confirm_totp_enrolment(first, get_settings(), live, totp.code_at(secret, now_counter()))
        cancel = await blocked_behind(first, client.delete(ENROL))
        await first.commit()
    assert error(await cancel) == (409, "totp_already_enabled")
    row = await user_row(owner_engine, address)
    assert row["totp_enabled_at"] is not None
    assert row["totp_pending_enc"] is None
    assert len(row["totp_recovery_hashes"]) == 10


async def test_a_confirmation_behind_a_committing_cancel_finds_nothing_pending(
    client: httpx.AsyncClient, app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    address = await verified(client)
    secret = await begin(client)
    async with create_session_factory(app_engine)() as first:
        live = await live_session(first, client)
        await service.cancel_totp_enrolment(first, live)
        confirm = await blocked_behind(first, client.post(CONFIRM, json={"code": totp.code_at(secret, now_counter())}))
        await first.commit()
    assert error(await confirm) == (409, "no_pending_enrolment")
    row = await user_row(owner_engine, address)
    assert row["totp_enabled_at"] is None
    assert row["totp_pending_enc"] is None
    assert row["totp_recovery_hashes"] == []
