"""REQ-UX-01, REQ-UX-05 (P25-B): ``GET /api/me/search`` and ``GET /api/me/activity`` as routes, without a database.

Given a signed-in person, when the palette searches or the Home asks for the calendar, then: signed out is 401; ``q``
outside 2 to 80 characters once trimmed (or a ``weeks`` outside 1 to 52) is 422 and nothing is read; a search is
counted against the person's rate limit before anything is read, and past it is 429 ``rate_limited`` with
``Retry-After`` and no read; each read runs in a read-only transaction of its own with a 2 s statement timeout, as
the caller; the search says ``Cache-Control: private, no-store`` and the calendar ``private, max-age=60``; both
bodies have exactly the shapes the OpenAPI document gives.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any
from uuid import UUID

import httpx
import pytest

from bridge.auth.deps import current_session
from bridge.auth.models import Session, User
from bridge.auth.sessions import LiveSession
from bridge.config import get_settings
from bridge.db import get_session
from bridge.main import create_app
from bridge.me import activity, caller, router, search
from bridge.me.caller import Caller
from bridge.me.schemas import SearchGroup, SearchItem, SearchResults
from bridge.teams import limits
from tests.unit.public.openapi_shape import conforms

USER = UUID(int=1)
WHO = Caller(USER, "developer")


class FakeDb:
    """The request's session: what was run on it, in order."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.open = True  # the session dependency's lookup left a transaction open

    def in_transaction(self) -> bool:
        return self.open

    async def commit(self) -> None:
        self.log.append("commit")
        self.open = False

    def begin(self) -> FakeDb:
        return self

    async def __aenter__(self) -> FakeDb:
        self.log.append("begin")
        self.open = True
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.log.append("end")
        self.open = False

    async def execute(self, statement: Any) -> None:
        self.log.append(str(statement))


class Scene:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, refuse: bool = False) -> None:
        self.calls: list[tuple[str, Any]] = []

        async def spend(db: FakeDb, secret: str, **kwargs: Any) -> None:
            self.calls.append(("spend", kwargs))
            db.log.append("spend")
            if refuse:
                raise limits.too_many(kwargs["code"], kwargs["message"], 7)

        async def caller_of(db: FakeDb, live: LiveSession) -> Caller:
            self.calls.append(("caller", live.user.id))
            return WHO

        async def run(db: FakeDb, who: Caller, term: str) -> SearchResults:
            db.log.append("search")
            self.calls.append(("search", (who, term)))
            item = SearchItem(id="1", title="SACCO float", subtitle=None, href="/problems/1")
            return SearchResults(q=term, groups=[SearchGroup(kind="problems", items=[item])])

        async def read(db: FakeDb, who: Caller, weeks: int) -> Any:
            db.log.append("activity")
            self.calls.append(("activity", (who, weeks)))
            return activity.calendar(
                who.side, date(2026, 10, 2), date(2026, 10, 8), [("quiz_answered", date(2026, 10, 8), 1)]
            )

        monkeypatch.setattr(limits, "spend", spend)
        monkeypatch.setattr(caller, "caller_of", caller_of)
        monkeypatch.setattr(search, "run", run)
        monkeypatch.setattr(activity, "read", read)


def signed_in() -> LiveSession:
    user = User(id=USER, email="amina@example.test", display_name="Amina")
    return LiveSession(token="t", row=Session(user_id=USER, mfa_pending=False), user=user)


@asynccontextmanager
async def client(*, signed: bool = True) -> AsyncIterator[tuple[httpx.AsyncClient, FakeDb]]:
    app = create_app(get_settings())
    db = FakeDb()
    app.dependency_overrides[get_session] = lambda: db
    if signed:
        app.dependency_overrides[current_session] = signed_in
    transport = httpx.ASGITransport(app=app, client=("203.0.113.7", 4000))
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as http:
        http.app = app  # type: ignore[attr-defined]
        yield http, db


READ_ONLY = ["begin", "SET TRANSACTION READ ONLY", "SET LOCAL statement_timeout = '2s'"]


@pytest.mark.parametrize("path", ["/api/me/search?q=sacco", "/api/me/activity"])
async def test_signed_out_is_401(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    scene = Scene(monkeypatch)
    async with client(signed=False) as (http, _db):
        response = await http.get(path)
    assert response.status_code == 401
    assert scene.calls == []


async def test_a_search_is_counted_then_read_as_the_caller_read_only_with_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = Scene(monkeypatch)
    async with client() as (http, db):
        response = await http.get("/api/me/search", params={"q": "  sacco  "})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "q": "sacco",
        "groups": [
            {
                "kind": "problems",
                "items": [{"id": "1", "title": "SACCO float", "subtitle": None, "href": "/problems/1"}],
            }
        ],
    }
    assert response.headers["cache-control"] == "private, no-store"
    assert db.log == ["spend", "commit", *READ_ONLY, "search", "end"]
    spent = scene.calls[0][1]
    assert (spent["user_id"], spent["limit"], spent["window"].total_seconds()) == (USER, 30, 10)
    assert (spent["purpose"], spent["code"]) == ("me_search", "rate_limited")
    assert scene.calls[1:] == [("caller", USER), ("search", (WHO, "sacco"))]


async def test_past_the_rate_limit_it_is_429_with_retry_after_and_nothing_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = Scene(monkeypatch, refuse=True)
    async with client() as (http, db):
        response = await http.get("/api/me/search", params={"q": "sacco"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "7"
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "rate_limited"
    assert [name for name, _ in scene.calls] == ["spend"]
    assert db.log == ["spend"]


@pytest.mark.parametrize(
    "params",
    [{}, {"q": ""}, {"q": "s"}, {"q": "   s   "}, {"q": "x" * 81}, {"q": "x" * 201}, {"q": "ab\x00"}],
)
async def test_a_query_outside_two_to_eighty_characters_is_422_and_nothing_is_read(
    monkeypatch: pytest.MonkeyPatch, params: dict[str, str]
) -> None:
    scene = Scene(monkeypatch)
    async with client() as (http, db):
        response = await http.get("/api/me/search", params=params)
    assert response.status_code == 422
    assert scene.calls == []
    assert db.log == []
    assert "x" * 81 not in response.text


async def test_the_calendar_reads_as_the_caller_read_only_and_may_be_kept_a_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = Scene(monkeypatch)
    async with client() as (http, db):
        response = await http.get("/api/me/activity")
        custom = await http.get("/api/me/activity", params={"weeks": 52})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, max-age=60"
    body = response.json()
    assert (body["from"], body["to"], body["timezone"], body["total"]) == (
        "2026-10-02",
        "2026-10-08",
        "Africa/Nairobi",
        1,
    )
    assert custom.status_code == 200
    assert db.log[:5] == ["commit", *READ_ONLY, "activity"]
    assert [call for call in scene.calls if call[0] == "activity"] == [("activity", (WHO, 26)), ("activity", (WHO, 52))]


@pytest.mark.parametrize("weeks", ["0", "53", "-1", "many"])
async def test_weeks_outside_one_to_fifty_two_is_422(monkeypatch: pytest.MonkeyPatch, weeks: str) -> None:
    scene = Scene(monkeypatch)
    async with client() as (http, _db):
        response = await http.get("/api/me/activity", params={"weeks": weeks})
    assert response.status_code == 422
    assert scene.calls == []


async def test_both_bodies_have_the_documented_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    Scene(monkeypatch)
    async with client() as (http, _db):
        document = http.app.openapi()  # type: ignore[attr-defined]
        found = await http.get("/api/me/search", params={"q": "sacco"})
        calendar = await http.get("/api/me/activity")
    components = document["components"]["schemas"]
    for path, response in (("/api/me/search", found), ("/api/me/activity", calendar)):
        schema = document["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        conforms(response.json(), schema, components)


def test_the_limits_are_thirty_searches_in_ten_seconds_and_two_second_statements() -> None:
    assert (router.SEARCHES, router.SEARCH_WINDOW.total_seconds(), router.READ_TIMEOUT) == (30, 10, "2s")
