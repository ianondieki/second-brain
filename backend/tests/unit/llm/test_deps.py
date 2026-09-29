"""REQ-LLM-01: the app's default LLM wiring (``bridge.llm.deps``).

Startup builds the runtime once: the registry, the (keyless, in tests) Anthropic adapter and, when LLM_PROVIDER is
free, one OpenAI-compatible adapter per free slot (D-37). A request's ``LLMDep`` is ``routed_client`` over the request's
session and the app's session factory, whose services are ``sql_service``. What ``sql_service`` composes (the SQL
ledger, the plan caps, the consent table) runs against PostgreSQL in ``tests/integration/llm``, whose every service is
built by it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import yaml
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from bridge.auth.sessions import LiveSession
from bridge.llm import deps
from bridge.llm import registry as registry_module
from bridge.llm.anthropic_adapter import AnthropicAdapter
from bridge.llm.client import LLMService
from bridge.llm.demo_data import DemoDataRule
from bridge.llm.fakes import FakeAdapter
from bridge.llm.guard import SessionConsentChecker
from bridge.llm.openai_adapter import OpenAICompatibleAdapter
from bridge.llm.routing import LLMRuntime, RoutedLLMClient
from bridge.llm.sql_ledger import SqlLedger
from bridge.main import create_app
from tests.unit.llm.helpers import settings
from tests.unit.llm.test_provider_settings import SLOT_1
from tests.unit.llm.test_registry import raw


async def test_startup_builds_the_registry_and_a_keyless_adapter() -> None:
    cfg = settings()
    app = create_app(cfg)
    async with app.router.lifespan_context(app):
        runtime = app.state.llm_runtime
        assert isinstance(runtime, LLMRuntime)
        assert runtime.registry is registry_module.load(cfg.llm_models_file)
        assert isinstance(runtime.anthropic, AnthropicAdapter)
        assert repr(runtime.anthropic) == "AnthropicAdapter(configured=False)"  # no key: calls are refused
        assert (runtime.provider, runtime.free, runtime.anthropic_configured) == ("fake", (), False)
        assert runtime.demo_fallback is True  # APP_ENV=test


def test_the_free_provider_gets_one_adapter_per_slot() -> None:
    cfg = settings(llm_provider=None, **SLOT_1)
    runtime = deps.build_runtime(cfg)
    assert runtime.provider == "free"
    [route] = runtime.free
    assert route.slot == cfg.llm_free_slots()[0]
    assert isinstance(route.adapter, OpenAICompatibleAdapter)
    assert route.registry == runtime.registry.for_free_slot(route.slot)
    assert "free-one-key-not-real" not in repr(runtime)
    # Only the free provider builds slot adapters; Anthropic runs only with LLM_PROVIDER=anthropic and a key.
    other = deps.build_runtime(settings(llm_provider="anthropic", anthropic_api_key=SecretStr("k"), **SLOT_1))
    assert (other.provider, other.free, other.anthropic_configured) == ("anthropic", (), True)


def test_a_malformed_registry_stops_startup(tmp_path: Path) -> None:
    bad = tmp_path / "models.yaml"
    bad.write_text("version: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version must be 1"):
        deps.build_runtime(settings(llm_models_file=bad))


async def test_a_request_gets_the_routed_client_over_its_own_session(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = settings()
    app = create_app(cfg)
    captured: dict[str, Any] = {}

    def capture(db: AsyncSession, **kwargs: Any) -> str:
        captured.update(db=db, **kwargs)
        return "client"

    monkeypatch.setattr(deps, "routed_client", capture)
    async with app.router.lifespan_context(app):
        db = AsyncSession()
        request = Request({"type": "http", "app": app, "headers": []})
        live = cast(LiveSession, object())  # a signed-in session (current_session has bound db to its user)
        assert deps.get_llm(request, db, cfg, live) == "client"  # type: ignore[comparison-overlap]
        assert captured == {
            "db": db,
            "factory": app.state.session_factory,
            "settings": cfg,
            "runtime": app.state.llm_runtime,
        }


async def test_the_routed_client_runs_every_route_on_the_sql_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each route's service is ``sql_service`` over the request's session; the router counts free requests in the
    SQL ledger and guards its fallback with the consent table and the demo accounts, all as the request's tenant."""
    cfg = settings()
    runtime = deps.build_runtime(cfg)
    db = AsyncSession()
    built: list[dict[str, Any]] = []

    def capture(session: AsyncSession, **kwargs: Any) -> LLMService:
        built.append({"db": session, **kwargs})
        return cast(LLMService, object())

    monkeypatch.setattr(deps, "sql_service", capture)
    factory = cast(Any, object())
    client = deps.routed_client(db, factory=factory, settings=cfg, runtime=runtime)
    assert isinstance(client, RoutedLLMClient)
    assert isinstance(client._ledger, SqlLedger)
    assert isinstance(client._consents, SessionConsentChecker)
    assert isinstance(client._data_rule, DemoDataRule)
    rule = client._data_rule
    adapter = FakeAdapter()
    client._build(runtime.registry, adapter, rule)
    assert built == [
        {
            "db": db,
            "factory": factory,
            "settings": cfg,
            "registry": runtime.registry,
            "adapter": adapter,
            "data_rule": rule,
        }
    ]


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


class Recorder:
    """Stands in for the module's structlog logger (cached loggers ignore ``capture_logs`` once used)."""

    def __init__(self) -> None:
        self.events: dict[str, tuple[str, dict[str, Any]]] = {}

    def info(self, event: str, **fields: Any) -> None:
        self.events[event] = ("info", fields)

    def error(self, event: str, **fields: Any) -> None:
        self.events[event] = ("error", fields)


def test_anthropic_with_unverified_prices_is_logged_at_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D-37: the runtime starts (every call falls back or is refused) and says why, without any key or price."""
    data = raw()
    data["pricing_status"] = "placeholder-unverified"
    models = tmp_path / "models.yaml"
    models.write_text(yaml.safe_dump(data), encoding="utf-8")
    recorder = Recorder()
    monkeypatch.setattr(deps, "log", recorder)
    runtime = deps.build_runtime(settings(llm_provider="anthropic", llm_models_file=models))
    assert runtime.registry.prices_verified is False
    level, fields = recorder.events["llm.runtime"]
    assert (level, fields["provider"], fields["prices_verified"], fields["free_slots"]) == (
        "info",
        "anthropic",
        False,
        [],
    )
    assert recorder.events["llm.prices_unverified"][0] == "error"
