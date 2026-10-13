"""REQ-FND-04 (P28 track PD): the public demo's status route, module fence and robots header, without a database.

- AT-PD-2: with the mode off, or without the ``bridge.demo`` module (a production image), ``GET /api/public/demo``
  says ``enabled: false`` and the sign-in route is 404.
- Every API answer says ``X-Robots-Tag: noindex, nofollow`` while the mode is on, and none says it otherwise.
- The lock dependency refuses with 403 ``public_demo_locked`` only while the mode is on.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import httpx
import pytest

from bridge import public_demo
from bridge.config import Settings, get_settings
from bridge.errors import ApiError
from bridge.main import create_app


def public(**update: Any) -> Settings:
    return get_settings().model_copy(update={"public_demo": True, **update})


# ---------------------------------------------------------------------------------------------- the module fence


def test_the_status_off_is_empty() -> None:
    assert public_demo.status(get_settings()).model_dump() == {"enabled": False, "personas": [], "reset_hour_eat": None}


@pytest.mark.parametrize("missing", ["bridge.demo.public_access", "bridge.demo"])
def test_an_image_without_the_module_has_no_public_demo(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    real = importlib.util.find_spec

    def find_spec(name: str, package: str | None = None) -> object:
        if name == public_demo.PERSONA_MODULE and missing == "bridge.demo":
            raise ModuleNotFoundError("No module named 'bridge.demo'")
        return None if name == missing else real(name, package)

    monkeypatch.setattr("importlib.util.find_spec", find_spec)
    assert public_demo.persona_module(public()) is None
    assert public_demo.persona_router(public()) is None
    assert public_demo.status(public()) == public_demo.OFF


async def test_the_lock_dependency_refuses_only_in_the_public_demo() -> None:
    await public_demo.refuse_in_public_demo(get_settings())
    with pytest.raises(ApiError) as refused:
        await public_demo.refuse_in_public_demo(public())
    assert refused.value.status_code == 403
    detail: object = refused.value.detail  # an ApiError's detail is a mapping (HTTPException types it as text)
    assert detail == {"code": "public_demo_locked", "message": "This is switched off in the public demo."}


# ---------------------------------------------------------------------------------------- the routes and headers


async def get(settings: Settings, path: str) -> httpx.Response:
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        return await client.get(path)


async def test_get_public_demo_when_off() -> None:
    response = await get(get_settings(), "/api/public/demo")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "personas": [], "reset_hour_eat": None}
    assert response.headers["cache-control"] == "public, max-age=60"
    assert "x-robots-tag" not in response.headers


@pytest.mark.parametrize("path", ["/healthz", "/api/public/demo", "/api/no-such-route", "/api/auth/csrf"])
async def test_every_answer_is_noindex_in_the_public_demo(path: str) -> None:
    response = await get(public(), path)
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "x-robots-tag" not in (await get(get_settings(), path)).headers


async def test_the_sign_in_route_is_404_when_the_mode_is_off() -> None:
    """AT-PD-2: not mounted (a CSRF-valid POST, so the 404 is the router's, not the CSRF guard's 403)."""
    app = create_app(get_settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        token = (await client.get("/api/auth/csrf")).json()["csrf_token"]
        response = await client.post(
            "/api/auth/demo/sign-in", json={"persona": "amina"}, headers={"X-CSRF-Token": token}
        )
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")


async def test_the_sign_in_needs_the_csrf_token() -> None:
    app = create_app(public())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as client:
        response = await client.post("/api/auth/demo/sign-in", json={"persona": "amina"})
    assert (response.status_code, response.json()["detail"]["code"]) == (403, "csrf_failed")


def test_the_openapi_document_leaves_the_sign_in_out() -> None:
    """Like the test clock, the persona sign-in is a dev-image route: never in the API document."""
    paths = create_app(public()).openapi()["paths"]
    assert "/api/public/demo" in paths
    assert "/api/auth/demo/sign-in" not in paths
