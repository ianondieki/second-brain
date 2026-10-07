"""REQ-TRACK-03 (P23-3): every /api response carries ``X-App-Now``, the platform clock in ISO 8601 UTC with a ``Z``.

A page counts a deadline down from this instant, never from the browser's clock alone. Where the dev/test clock can
move the platform clock (every environment but production) it is the database's ``app_clock_now()`` (the moved clock:
tests/integration/engagements/test_app_now.py); production's database never enables that clock, so there it is the
wall clock without a query. Without a database (an app built without its lifespan, or the database down) it falls back
to the wall clock: the header is for display, and ``overdue`` and ``past_deadline`` stay the authority. Error
answers carry it too (a refused CSRF token, an unknown path, a validation error, an unexpected failure).
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
        refused = await client.post("/api/auth/logout")  # no CSRF token: 403 before any route
        unknown = await client.get("/api/no-such-thing")
        invalid = await client.get("/api/p23-3/count", params={"n": "many"})
        broken = await client.get("/api/p23-3/boom")
    assert [r.status_code for r in (refused, unknown, invalid, broken)] == [403, 404, 422, 500]
    assert refused.json()["detail"]["code"] == "csrf_failed"
    for response in (refused, unknown, invalid, broken):
        assert response.headers[APP_NOW_HEADER] == STAMP


async def test_only_api_answers_carry_it() -> None:
    async with client_of(create_app(get_settings())) as client:
        probe = await client.get("/healthz")
    assert probe.status_code == 200
    assert APP_NOW_HEADER not in probe.headers


def test_the_header_is_documented() -> None:
    header = json.loads(render())["components"]["headers"][APP_NOW_HEADER]
    assert header["schema"] == {"type": "string", "format": "date-time"}
    assert "UTC" in header["description"]
