"""The app's LLM wiring (REQ-LLM-01): the default ``LLMClient`` of a request or a job.

The registry (``ai/models.yaml``) and the adapter are built once at startup (``build_runtime``, stored on
``app.state`` by the lifespan). Each signed-in request (``CurrentSession``; 401 otherwise) gets a fresh
``LLMService`` (one nonce per request) over the SQL stores, all acting as the request's bound tenant: the
``llm_calls`` ledger (``SqlLedger``, rows committed on their own), the monthly caps of the subject's plan
(``EntitlementsCaps``) and the consent table (``SessionConsentChecker``). A job calls ``sql_service`` with its own
session after ``bind_tenant``. Dead letters, refusals and soft-cap crossings go to the logging in-memory sinks until
their tables and hooks exist (T2.3, Phase 4). Unit tests use ``FakeLLMClient``.
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
from bridge.llm.guard import SessionConsentChecker
from bridge.llm.registry import Registry
from bridge.llm.sql_ledger import SqlLedger


def build_runtime(settings: Settings) -> tuple[Registry, ModelAdapter]:
    """The registry and the provider adapter (built without a key in dev and test; calls then raise
    ``LLMUnavailable``). A malformed ``ai/models.yaml`` stops the app at startup."""
    registry = registry_module.load(settings.llm_models_file)
    return registry, adapter_from_settings(settings, registry)


def sql_service(
    db: AsyncSession,
    *,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    registry: Registry,
    adapter: ModelAdapter,
) -> LLMService:
    """``LLMService`` over the SQL stores as ``db``'s tenant; ``factory`` opens the ledger's own transactions."""
    return LLMService(
        adapter=adapter,
        registry=registry,
        settings=settings,
        ledger=SqlLedger(factory, caller=db),
        consents=SessionConsentChecker(db),
        caps=EntitlementsCaps(db, settings),
    )


def get_llm(request: Request, db: Db, settings: SettingsDep, live: CurrentSession) -> LLMClient:
    """A request's client: only for a signed-in session with its second factor done (``CurrentSession``: 401
    otherwise), which binds ``db`` to the user first, so a request never makes an unbound, platform-scope call."""
    del live  # required for its checks and its tenant binding
    state = request.app.state
    return sql_service(
        db,
        factory=state.session_factory,
        settings=settings,
        registry=state.llm_registry,
        adapter=state.llm_adapter,
    )


LLMDep = Annotated[LLMClient, Depends(get_llm)]
