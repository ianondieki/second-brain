"""The app's LLM wiring (REQ-LLM-01): the default ``LLMClient`` of a request or a job.

The runtime is built once at startup (``build_runtime``, ``app.state.llm_runtime``): the registry
(``ai/models.yaml``), the Anthropic adapter and, when ``LLM_PROVIDER`` is free (D-37), one OpenAI-compatible adapter
per configured free slot. Each signed-in request (``CurrentSession``; 401 otherwise) gets a fresh ``RoutedLLMClient``
(``routed_client``; ``bridge.llm.routing``) whose route services are ``sql_service``s, each with one nonce, over the SQL
stores, all acting as the request's bound tenant: the ``llm_calls`` ledger (``SqlLedger``, rows committed on their
own), the monthly caps of the subject's plan (``EntitlementsCaps``), the consent table (``SessionConsentChecker``) and,
on free slots, the demo accounts (``SqlDemoAccounts``). A job calls ``routed_client`` (or ``sql_service`` for one
fixed provider) with its own session after ``bind_tenant``. Dead letters, refusals and soft-cap crossings go to the
logging in-memory sinks until their tables and hooks exist (T2.3, Phase 4). Unit tests use ``FakeLLMClient``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.config import Settings
from bridge.llm import registry as registry_module
from bridge.llm.adapter import ModelAdapter
from bridge.llm.anthropic_adapter import adapter_from_settings
from bridge.llm.budget import EntitlementsCaps
from bridge.llm.client import LLMClient, LLMService
from bridge.llm.demo_data import DataRule, DemoDataRule, SqlDemoAccounts
from bridge.llm.guard import SessionConsentChecker
from bridge.llm.openai_adapter import OpenAICompatibleAdapter
from bridge.llm.registry import Registry
from bridge.llm.routing import FreeRoute, LLMRuntime, RoutedLLMClient
from bridge.llm.sql_ledger import SqlLedger
from bridge.logging import get_logger

log = get_logger("bridge.llm")


def build_runtime(settings: Settings) -> LLMRuntime:
    """The registry, the Anthropic adapter (built without a key in dev and test; calls then raise ``LLMUnavailable``
    or fall back) and the free slots' adapters when ``LLM_PROVIDER`` is free. A malformed ``ai/models.yaml`` stops the
    app at startup."""
    registry = registry_module.load(settings.llm_models_file)
    provider = settings.llm_effective_provider
    free: tuple[FreeRoute, ...] = ()
    if provider == "free":  # the settings refuse free slots outside dev and test
        timeout = registry.transport.timeout_seconds
        free = tuple(
            FreeRoute(slot, registry.for_free_slot(slot), OpenAICompatibleAdapter(slot, timeout_seconds=timeout))
            for slot in settings.llm_free_slots()
        )
    key = settings.anthropic_api_key
    runtime = LLMRuntime(
        registry=registry,
        anthropic=adapter_from_settings(settings, registry),
        anthropic_configured=key is not None and bool(key.get_secret_value().strip()),
        provider=provider,
        demo_fallback=settings.llm_demo_fallback,
        free=free,
    )
    log.info(
        "llm.runtime",
        provider=provider,
        free_slots=[route.slot.name for route in free],
        prices_verified=registry.prices_verified,
        demo_fallback=runtime.demo_fallback,
    )
    if provider == "anthropic" and not registry.prices_verified:
        log.error("llm.prices_unverified", detail="Anthropic stays off until ai/models.yaml marks the prices verified")
    return runtime


def sql_service(
    db: AsyncSession,
    *,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    registry: Registry,
    adapter: ModelAdapter,
    data_rule: DataRule | None = None,
) -> LLMService:
    """``LLMService`` over the SQL stores as ``db``'s tenant; ``factory`` opens the ledger's own transactions."""
    return LLMService(
        adapter=adapter,
        registry=registry,
        settings=settings,
        ledger=SqlLedger(factory, caller=db),
        consents=SessionConsentChecker(db),
        caps=EntitlementsCaps(db, settings),
        data_rule=data_rule,
    )


def routed_client(
    db: AsyncSession,
    *,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    runtime: LLMRuntime,
) -> RoutedLLMClient:
    """The ``RoutedLLMClient`` of ``db``'s tenant: each route's service is ``sql_service``; free slots get the D-37
    rule over ``users.demo_account``."""

    def build(registry: Registry, adapter: ModelAdapter, rule: DataRule | None) -> LLMService:
        return sql_service(db, factory=factory, settings=settings, registry=registry, adapter=adapter, data_rule=rule)

    return RoutedLLMClient(
        runtime=runtime,
        services=build,
        ledger=SqlLedger(factory, caller=db),
        consents=SessionConsentChecker(db),
        data_rule=DemoDataRule(SqlDemoAccounts(factory, caller=db)),
    )


def get_llm(request: Request, db: Db, settings: SettingsDep, live: CurrentSession) -> LLMClient:
    """A request's client: only for a signed-in session with its second factor done (``CurrentSession``: 401
    otherwise), which binds ``db`` to the user first, so a request never makes an unbound, platform-scope call."""
    del live  # required for its checks and its tenant binding
    state = request.app.state
    return routed_client(db, factory=state.session_factory, settings=settings, runtime=state.llm_runtime)


LLMDep = Annotated[LLMClient, Depends(get_llm)]
