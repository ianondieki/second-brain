"""REQ-UX-03 (P24-B): ``GET /api/public/problems/{problem_id}`` as a route, without a database.

Signed out, ``public, max-age=60`` on 200 only, one load per id per minute, at most 256 ids held; any id the reader
does not find (a draft, a held or archived problem, an organisation's own or invited Brief, a delisted organisation's
Brief: the statement's predicate, proven against rows in ``integration/public``) is the same 404 as elsewhere,
``no-store``, never cached and keeping no slot; a miss is rate-limited; the body has the OpenAPI document's shape.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from bridge.provenance import verify
from bridge.public import feed, router
from bridge.public.schemas import PublicProblem
from tests.unit.public.openapi_shape import conforms
from tests.unit.public.test_problem_page import row
from tests.unit.public.test_routes import client


class Pages:
    """A fake reader: ``found`` ids have a page; every call is recorded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, found: set[UUID], *, allowed: bool = True) -> None:
        self.found, self.throttled = found, 0
        self.loads: list[UUID] = []

        async def allow(*_: Any, **__: Any) -> bool:
            self.throttled += 1
            return allowed

        async def problem(factory: Any, problem_id: UUID, *, demo: bool) -> PublicProblem | None:
            self.loads.append(problem_id)
            return feed.problem_page(row(id=problem_id), demo=demo) if problem_id in self.found else None

        monkeypatch.setattr(verify, "allow", allow)
        monkeypatch.setattr(feed, "problem", problem)


def path(problem_id: UUID | str) -> str:
    return f"/api/public/problems/{problem_id}"


async def test_a_signed_out_visitor_reads_a_public_problem_once_a_minute(monkeypatch: pytest.MonkeyPatch) -> None:
    public = uuid4()
    pages = Pages(monkeypatch, {public})
    async with client() as http:
        first, second = await http.get(path(public)), await http.get(path(public))
        document = http.app.openapi()  # type: ignore[attr-defined]
    assert (first.status_code, first.headers["cache-control"]) == (200, "public, max-age=60")
    assert first.json() == second.json()
    assert (pages.loads, pages.throttled) == ([public], 1)
    schema = document["paths"]["/api/public/problems/{problem_id}"]["get"]["responses"]["200"]["content"]
    conforms(first.json(), schema["application/json"]["schema"], document["components"]["schemas"])


UNREADABLE = ["draft", "held", "archived", "org-only-brief", "invited-brief", "delisted-org-brief"]


@pytest.mark.parametrize("label", UNREADABLE)
async def test_any_problem_the_public_reader_cannot_read_is_the_same_uncached_404(
    monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    hidden = uuid4()  # the reader's statement does not return it (integration: test_public_reads)
    pages = Pages(monkeypatch, set())
    async with client() as http:
        first, again = await http.get(path(hidden)), await http.get(path(hidden))
        slots = len(http.app.state.public_caches.problems)  # type: ignore[attr-defined]
    for response in (first, again):
        assert response.status_code == 404, label
        assert response.json() == {"detail": {"code": "not_found", "message": "No such problem."}}
        assert response.headers["cache-control"] == "no-store"
    assert pages.loads == [hidden, hidden]  # never cached
    assert slots == 0  # and it keeps no slot


async def test_a_malformed_id_is_refused_before_any_read(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = Pages(monkeypatch, set())
    async with client() as http:
        response = await http.get(path("not-a-uuid"))
    assert response.status_code == 422
    assert (pages.loads, pages.throttled) == ([], 0)


async def test_past_the_limit_a_miss_gets_429_and_nothing_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = Pages(monkeypatch, {uuid4()}, allowed=False)
    async with client() as http:
        response = await http.get(path(uuid4()))
    assert (response.status_code, response.json()["detail"]["code"]) == (429, "rate_limited")
    assert pages.loads == []


async def test_a_worker_holds_at_most_the_cap_of_problem_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    assert router.PROBLEM_CACHE_CAP == 256
    monkeypatch.setattr(router, "PROBLEM_CACHE_CAP", 3)
    ids = [uuid4() for _ in range(4)]
    pages = Pages(monkeypatch, set(ids))
    async with client() as http:
        for problem_id in ids:
            assert (await http.get(path(problem_id))).status_code == 200
        held = len(http.app.state.public_caches.problems)  # type: ignore[attr-defined]
        assert (await http.get(path(ids[0]))).status_code == 200  # the least recently read left: read again
    assert held == 3
    assert pages.loads == [*ids, ids[0]]
