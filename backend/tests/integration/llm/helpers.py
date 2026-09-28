"""Helpers for the SQL ledger tests: the service over the SQL stores, scripted replies and the stored rows."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.config import get_settings
from bridge.llm import registry as registry_module
from bridge.llm.adapter import ModelAdapter, ModelResponse
from bridge.llm.budget import EntitlementsCaps
from bridge.llm.client import LLMService
from bridge.llm.guard import SessionConsentChecker
from bridge.llm.registry import Registry
from bridge.llm.sql_ledger import SqlLedger
from bridge.llm.types import TokenUsage

TASK = "moderation_prescreen"
OK = {"injection_suspected": False, "verdict": "clean", "reason": "fine"}
USAGE = TokenUsage(input_tokens=812, output_tokens=31, cache_read_input_tokens=600, cache_creation_input_tokens=300)
ROOMY_GLOBAL_CAP = Decimal(10**6)  # the test database's daily total is every test's spend


def service(
    db: AsyncSession,
    factory: async_sessionmaker[AsyncSession],
    adapter: ModelAdapter,
    *,
    registry: Registry | None = None,
    **overrides: Any,
) -> LLMService:
    """``LLMService`` over the SQL ledger, the plan caps and the consent table, all as ``db``'s tenant."""
    cfg = get_settings().model_copy(update={"llm_global_daily_cap_usd": ROOMY_GLOBAL_CAP, **overrides})
    return LLMService(
        adapter=adapter,
        registry=registry or registry_module.load(cfg.llm_models_file),
        settings=cfg,
        ledger=SqlLedger(factory, caller=db),
        consents=SessionConsentChecker(db),
        caps=EntitlementsCaps(db, cfg),
    )


def reply(
    body: dict[str, Any] | None = None, *, stop_reason: str = "end_turn", usage: TokenUsage = USAGE
) -> ModelResponse:
    return ModelResponse(text=json.dumps(OK if body is None else body), stop_reason=stop_reason, usage=usage, model="m")


async def stored(owner_engine: AsyncEngine, trace_id: str) -> list[RowMapping]:
    """Every column of the call's rows, read as the table owner (no RLS, no column grants), in creation order (the
    ids are UUIDv7, monotonic within one process)."""
    async with owner_engine.connect() as conn:
        result = await conn.execute(text("SELECT * FROM llm_calls WHERE trace_id = :t ORDER BY id"), {"t": trace_id})
        return list(result.mappings())
