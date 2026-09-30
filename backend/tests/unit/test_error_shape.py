"""REQ-FND-01 (P16-E1 item 1): one error shape. Every documented error of every route is ``ApiErrorBody`` as JSON
(``{"detail": {"code", "message", ...}}``; FastAPI's 422 list is the one documented exception, and ``ApiErrorBody``
allows it), every ``/api`` route lists the shared error responses, and at runtime the framework's own refusals (an
unknown path, a method a path does not take) and an unexpected failure answer in the same shape."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from bridge import errors, testclock
from bridge.config import get_settings
from bridge.errors import ERROR_RESPONSES, ApiError, error_detail, http_error
from bridge.main import API_PREFIX, SECURITY_HEADERS, create_app
from bridge.openapi import render

ERROR_REF = {"$ref": "#/components/schemas/ApiErrorBody"}
# The health probes answer {"status": ...} for uptime monitors, outside /api (bridge.api.health).
PROBES = {("get", "/readyz", "503")}


def _schema() -> dict[str, Any]:
    document: dict[str, Any] = json.loads(render())
    return document


def test_every_documented_error_is_the_api_error_body_as_json() -> None:
    found: list[str] = []
    checked = 0
    for path, operations in _schema()["paths"].items():
        for method, operation in operations.items():
            for status, response in operation["responses"].items():
                if status[0] not in "45" or (method, path, status) in PROBES:
                    continue
                checked += 1
                if response.get("content") != {"application/json": {"schema": ERROR_REF}}:
                    found.append(f"{method.upper()} {path} {status}: {response.get('content')}")
    assert checked > 1000  # every route, not a handful
    assert found == []


def test_the_error_body_allows_the_422_list_and_nothing_else_beside_the_detail() -> None:
    body = _schema()["components"]["schemas"]["ApiErrorBody"]
    assert body["required"] == ["detail"]
    variants = body["properties"]["detail"]["anyOf"]
    assert {"$ref": "#/components/schemas/ApiErrorDetail"} in variants
    assert {"items": {"additionalProperties": True, "type": "object"}, "type": "array"} in variants
    assert "HTTPValidationError" not in _schema()["components"]["schemas"]  # the 422 is ApiErrorBody everywhere


def test_every_api_route_lists_the_shared_error_responses() -> None:
    """In the document, and on the routes left out of it (the dev/test clock)."""
    shared = sorted(map(str, ERROR_RESPONSES))
    missing = {
        f"{method.upper()} {path}": sorted(set(shared) - set(operation["responses"]))
        for path, operations in _schema()["paths"].items()
        if path.startswith(API_PREFIX)
        for method, operation in operations.items()
    }
    assert len(missing) > 100
    assert {route: statuses for route, statuses in missing.items() if statuses} == {}
    clock = [route for route in testclock.build_router(get_settings()).routes if isinstance(route, APIRoute)]
    assert clock
    assert all(set(shared) <= set(map(str, route.responses)) for route in clock)


def test_an_api_error_passes_as_it_is_and_a_framework_string_gets_a_code() -> None:
    raised = ApiError(402, "plan_limit", "Upgrade to tag more organisations.", upgrade={"plan": "p", "url": "/u"})
    detail: Any = raised.detail
    assert error_detail(402, detail) == detail
    assert error_detail(404, "Not Found") == {"code": "not_found", "message": "Not found."}
    assert error_detail(405, "Method Not Allowed") == {
        "code": "method_not_allowed",
        "message": "This method is not allowed here.",
    }
    assert error_detail(400, "There was an error parsing the body") == {
        "code": "bad_request",
        "message": "There was an error parsing the body.",
    }
    assert error_detail(413, None) == {"code": "request_entity_too_large", "message": "Request Entity Too Large."}
    assert error_detail(499, "") == {"code": "error", "message": "Error."}
    assert error_detail(409, {"code": 7, "message": "not a code"}) == {"code": "conflict", "message": "Conflict."}


async def test_the_handler_keeps_headers_and_answers_bodiless_statuses_without_a_body() -> None:
    limited = await http_error(None, StarletteHTTPException(429, "Too Many Requests", headers={"Retry-After": "60"}))  # type: ignore[arg-type]
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert json.loads(bytes(limited.body)) == {"detail": {"code": "too_many_requests", "message": "Too Many Requests."}}
    empty = await http_error(None, StarletteHTTPException(304))  # type: ignore[arg-type]
    assert (empty.status_code, bytes(empty.body)) == (304, b"")
    with pytest.raises(ValueError, match="not an HTTP error"):
        await http_error(None, ValueError("not an HTTP error"))  # type: ignore[arg-type]


def _app_with_a_failing_route() -> FastAPI:
    app = create_app(get_settings())
    broken = APIRouter(prefix="/api/p16-e1", responses=ERROR_RESPONSES)

    @broken.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret-ish detail: user@example.com")

    app.include_router(broken)
    return app


@asynccontextmanager
async def _client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        client.headers["X-CSRF-Token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]
        yield client


async def test_an_unknown_path_answers_like_a_hidden_resource() -> None:
    async with _client(create_app(get_settings())) as client:
        unknown = await client.get("/api/no-such-thing")
        outside = await client.get("/no-such-page")
    for response in (unknown, outside):
        assert response.status_code == 404
        assert response.headers["content-type"] == "application/json"
        assert response.json() == {"detail": errors.not_found().detail}  # the same body as bridge.errors.not_found()


async def test_a_method_a_path_does_not_take_answers_405_in_the_shape() -> None:
    async with _client(create_app(get_settings())) as client:
        response = await client.delete("/api/auth/me")
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"
    assert response.json() == {"detail": {"code": "method_not_allowed", "message": "This method is not allowed here."}}


async def test_an_unexpected_failure_answers_500_in_the_shape_without_its_text() -> None:
    async with _client(_app_with_a_failing_route()) as client:
        response = await client.get("/api/p16-e1/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": errors.INTERNAL_ERROR}
    assert "example.com" not in response.text
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


async def test_the_failure_is_still_raised_after_the_answer() -> None:
    """Starlette answers with the handler's body, then raises the exception so the server logs it."""
    transport = httpx.ASGITransport(app=_app_with_a_failing_route())
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with pytest.raises(RuntimeError, match="secret-ish"):
            await client.get("/api/p16-e1/boom")
