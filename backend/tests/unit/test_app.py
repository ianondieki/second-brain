"""App skeleton: health endpoint, security headers, OpenAPI export is current."""

from __future__ import annotations

import httpx
import pytest

from bridge.main import create_app
from bridge.openapi import OPENAPI_PATH, render


async def test_healthz_and_security_headers() -> None:
    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_committed_openapi_matches_the_routes() -> None:
    if not OPENAPI_PATH.exists():
        pytest.fail("backend/openapi.json is missing: run `make openapi`")
    assert OPENAPI_PATH.read_text(encoding="utf-8") == render(), "run `make openapi` and commit the result"
