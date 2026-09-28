"""REQ-LLM-01: the app's default LLM wiring (``bridge.llm.deps``).

Startup builds the registry and the (keyless, in tests) adapter once; a request's ``LLMDep`` is ``sql_service`` over
the request's session and the app's session factory. What ``sql_service`` composes (the SQL ledger, the plan caps, the
consent table) runs against PostgreSQL in ``tests/integration/llm``, whose every service is built by it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

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
        assert deps.get_llm(request, db, cfg) == "service"  # type: ignore[comparison-overlap]
        assert captured == {
            "db": db,
            "factory": app.state.session_factory,
            "settings": cfg,
            "registry": app.state.llm_registry,
            "adapter": app.state.llm_adapter,
        }
