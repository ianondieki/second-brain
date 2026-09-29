"""REQ-LLM-01: the app's default LLM wiring (``bridge.llm.deps``).

Startup builds the registry and the (keyless, in tests) adapter once; a request's ``LLMDep`` is ``sql_service`` over
the request's session and the app's session factory. What ``sql_service`` composes (the SQL ledger, the plan caps, the
consent table) runs against PostgreSQL in ``tests/integration/llm``, whose every service is built by it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from bridge.auth.sessions import LiveSession
from bridge.llm import deps
from bridge.llm import registry as registry_module
from bridge.llm.anthropic_adapter import AnthropicAdapter
from bridge.main import create_app
from tests.unit.llm.helpers import settings


async def test_startup_builds_the_registry_and_a_keyless_adapter() -> None:
    cfg = settings()
    app = create_app(cfg)
    async with app.router.lifespan_context(app):
        assert app.state.llm_registry is registry_module.load(cfg.llm_models_file)
        assert isinstance(app.state.llm_adapter, AnthropicAdapter)
        assert repr(app.state.llm_adapter) == "AnthropicAdapter(configured=False)"  # no key: calls are refused


def test_a_malformed_registry_stops_startup(tmp_path: Path) -> None:
    bad = tmp_path / "models.yaml"
    bad.write_text("version: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version must be 1"):
        deps.build_runtime(settings(llm_models_file=bad))


async def test_a_request_gets_the_sql_service_over_its_own_session(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = settings()
    app = create_app(cfg)
    captured: dict[str, Any] = {}

    def capture(db: AsyncSession, **kwargs: Any) -> str:
        captured.update(db=db, **kwargs)
        return "service"

    monkeypatch.setattr(deps, "sql_service", capture)
    async with app.router.lifespan_context(app):
        db = AsyncSession()
        request = Request({"type": "http", "app": app, "headers": []})
        live = cast(LiveSession, object())  # a signed-in session (current_session has bound db to its user)
        assert deps.get_llm(request, db, cfg, live) == "service"  # type: ignore[comparison-overlap]
        assert captured == {
            "db": db,
            "factory": app.state.session_factory,
            "settings": cfg,
            "registry": app.state.llm_registry,
            "adapter": app.state.llm_adapter,
        }


async def test_a_request_without_a_signed_in_session_gets_no_llm_client() -> None:
    """Security review 2026-09-29: ``LLMDep`` needs a signed-in session whose second factor is done (``CurrentSession``,
    which binds the database session to the user), so a request never makes an unbound, platform-scope call."""
    cfg = settings()
    app = create_app(cfg)

    @app.get("/_llm_probe")
    async def probe(llm: deps.LLMDep) -> dict[str, str]:  # pragma: no cover - never reached without a session
        return {"llm": type(llm).__name__}

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/_llm_probe")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthenticated"
