"""App skeleton: health endpoint, security headers, OpenAPI export is current, start-up fails closed."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from bridge.config import Settings
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


def production_settings(**overrides: Any) -> Settings:
    """Settings that pass validation for ``APP_ENV=production`` (Postmark, https, Secure cookies, a real embedder,
    no LLM key with the kill switch on)."""
    values: dict[str, Any] = {
        "app_env": "production",
        "database_url": SecretStr("postgresql+psycopg://bridge_app:unused@localhost:5432/bridge"),
        "secret_key": SecretStr("s" * 32),
        "recovery_code_pepper": SecretStr("p" * 32),
        "data_encryption_key": SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="),
        "email_provider": "postmark",
        "postmark_server_token": SecretStr("pm-unit-test-token"),
        "public_base_url": "https://bridge.test",
        "cookie_secure": True,
        "embedder": "bge-m3",  # REQ-EMB-01: production refuses the fake embedder
        "llm_kill_switch": True,  # REQ-LLM-01: production runs keyless only with every LLM call refused
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        pytest.param({"sms_provider": "fake"}, "SMS_PROVIDER=fake is not allowed when APP_ENV=production", id="fake"),
        pytest.param(
            {
                "sms_provider": "africastalking",
                "africastalking_username": "sandbox",
                "africastalking_api_key": SecretStr("at-unit-test-key-not-real"),
            },
            "not the sandbox",
            id="africastalking-sandbox",
        ),
    ],
)
async def test_production_start_up_fails_closed_without_a_live_sms_provider(
    overrides: dict[str, Any], reason: str
) -> None:
    """REQ-PROV-04: the API refuses to start in production when D1 codes could not reach a real phone."""
    app = create_app(production_settings(**overrides))
    with pytest.raises(ValueError, match=reason):
        async with app.router.lifespan_context(app):
            pytest.fail("the app started")
    assert not hasattr(app.state, "sms_provider")
    assert not hasattr(app.state, "engine")  # refused before anything was opened
