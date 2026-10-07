"""REQ-TRACK-03 (P23-3): every /api response the CSRF check lets through carries ``X-App-Now``, the platform clock in
ISO 8601 UTC with a ``Z``.

A page counts a deadline down from this instant, never from the browser's clock alone. Where the dev/test clock can
move the platform clock (every environment but production) it is the database's ``app_clock_now()`` (the moved clock:
tests/integration/engagements/test_app_now.py); production's database never enables that clock, so there it is the
wall clock without a query. Without a database (an app built without its lifespan, or the database down) it falls back
to the wall clock and logs why: the header is for display, and ``overdue`` and ``past_deadline`` stay the authority.
Error answers carry it too (an unknown path, a validation error, an unexpected failure); a request the CSRF guard
refuses gets neither the clock query nor the header.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from sqlalchemy.exc import OperationalError, ProgrammingError

from bridge import clock, main
from bridge.config import get_settings
from bridge.errors import ERROR_RESPONSES
from bridge.main import APP_NOW_HEADER, create_app
from bridge.openapi import render
from tests.unit.test_app import production_settings

FIXED = datetime(2026, 10, 7, 9, 30, 15, 123_456, tzinfo=UTC)
STAMP = "2026-10-07T09:30:15.123Z"


@pytest.fixture(autouse=True)
def frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clock, "utcnow", lambda: FIXED)


class Unused:
    """An engine production must never query for the header."""

    def connect(self) -> Any:
        raise AssertionError("production stamps the wall clock without a query")


class Down:
    """An engine whose database cannot be reached."""

    def connect(self) -> Any:
        raise OperationalError("SELECT app_clock_now()", {}, ConnectionRefusedError("down"))


class NoClock:
    """An engine whose database has no app_clock_now() (a broken or missing dev/test clock)."""

    def connect(self) -> Any:
        raise ProgrammingError("SELECT app_clock_now()", {"secret": "never logged"}, LookupError("no function"))


class Counting:
    """An engine that counts the connections asked of it (each refused, so the header falls back)."""

    def __init__(self) -> None:
        self.connects = 0

    def connect(self) -> Any:
        self.connects += 1
        raise OperationalError("SELECT app_clock_now()", {}, ConnectionRefusedError("down"))


class Recorder:
    """Stands in for bridge.main's structlog logger (cached loggers ignore ``capture_logs`` once used)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def warning(self, event: str, **fields: Any) -> None:
        self.events.append(("warning", event, fields))


@asynccontextmanager
async def client_of(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        yield client


def failing(app: FastAPI) -> FastAPI:
    broken = APIRouter(prefix="/api/p23-3", responses=ERROR_RESPONSES)

    @broken.get("/boom")
    async def boom() -> None:
        raise RuntimeError("unexpected")

    @broken.get("/count")
    async def count(n: int) -> int:
        return n

    app.include_router(broken)
    return app


def test_the_header_name() -> None:
    assert APP_NOW_HEADER == "X-App-Now"


async def test_production_stamps_the_wall_clock_without_a_query() -> None:
    app = create_app(production_settings())
    app.state.engine = Unused()
    async with client_of(app) as client:
        response = await client.get("/api/auth/csrf")
    assert response.status_code == 200, response.text
    assert response.headers[APP_NOW_HEADER] == STAMP
    assert datetime.fromisoformat(response.headers[APP_NOW_HEADER]) == FIXED.replace(microsecond=123_000)


@pytest.mark.parametrize("engine", [None, Down()], ids=["no-database", "database-down"])
async def test_without_a_database_it_falls_back_to_the_wall_clock(engine: object) -> None:
    app = create_app(get_settings())  # APP_ENV=test: the dev/test clock may move the platform clock
    if engine is not None:
        app.state.engine = engine
    async with client_of(app) as client:
        response = await client.get("/api/auth/csrf")
    assert response.status_code == 200, response.text
    assert response.headers[APP_NOW_HEADER] == STAMP


async def test_a_broken_clock_is_logged_and_the_answer_still_carries_the_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(main, "log", recorder)
    app = create_app(get_settings())
    app.state.engine = NoClock()
    async with client_of(app) as client:
        response = await client.get("/api/auth/csrf")
    assert response.status_code == 200, response.text
    assert response.headers[APP_NOW_HEADER] == STAMP  # never a 500 for the header's sake
    assert recorder.events == [("warning", "app_now.fallback", {"error_type": "ProgrammingError"})]


async def test_error_answers_carry_it_too() -> None:
    app = failing(create_app(get_settings()))
    async with client_of(app) as client:
        unknown = await client.get("/api/no-such-thing")
        invalid = await client.get("/api/p23-3/count", params={"n": "many"})
        broken = await client.get("/api/p23-3/boom")
    assert [r.status_code for r in (unknown, invalid, broken)] == [404, 422, 500]
    for response in (unknown, invalid, broken):
        assert response.headers[APP_NOW_HEADER] == STAMP


async def test_a_request_the_csrf_guard_refuses_costs_no_clock_query_and_gets_no_header() -> None:
    """Outside production the header costs a pooled connection; a state-changing request without a valid CSRF token
    (checked first: the guard's own HMAC, no I/O) gets neither, so a flood of them cannot queue real requests."""
    engine = Counting()
    app = create_app(get_settings())
    app.state.engine = engine
    async with client_of(app) as client:
        missing = await client.post("/api/auth/logout")
        client.cookies.set(get_settings().csrf_cookie_name, "nonce.forged")  # the cookie and the header agree; no MAC
        forged = await client.post("/api/auth/logout", headers={"X-CSRF-Token": "nonce.forged"})
        assert engine.connects == 0
        for refused in (missing, forged):
            assert (refused.status_code, refused.json()["detail"]["code"]) == (403, "csrf_failed")
            assert APP_NOW_HEADER not in refused.headers
        allowed = await client.get("/api/auth/csrf")  # a safe method passes the guard: one clock read
    assert engine.connects == 1
    assert allowed.headers[APP_NOW_HEADER] == STAMP


async def test_only_api_answers_carry_it() -> None:
    async with client_of(create_app(get_settings())) as client:
        probe = await client.get("/healthz")
    assert probe.status_code == 200
    assert APP_NOW_HEADER not in probe.headers


def test_the_header_is_documented() -> None:
    header = json.loads(render())["components"]["headers"][APP_NOW_HEADER]
    assert header["schema"] == {"type": "string", "format": "date-time"}
    assert "UTC" in header["description"]
