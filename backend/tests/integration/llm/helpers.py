"""Helpers for the SQL ledger tests: the service over the SQL stores, scripted replies, login sessions and the stored
rows."""

from __future__ import annotations

import json
import secrets
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.llm import registry as registry_module
from bridge.llm.adapter import ModelAdapter, ModelResponse
from bridge.llm.client import LLMService
from bridge.llm.deps import sql_service
from bridge.llm.registry import Registry
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
    """The app's default service (``bridge.llm.deps.sql_service``: the SQL ledger, the plan caps and the consent
    table, all as ``db``'s tenant) over a scripted adapter."""
    roomy = {"llm_global_daily_cap_usd": ROOMY_GLOBAL_CAP, "llm_prototype_total_cap_usd": ROOMY_GLOBAL_CAP}
    cfg = get_settings().model_copy(update={**roomy, **overrides})
    reg = registry or registry_module.load(cfg.llm_models_file)
    return sql_service(db, factory=factory, settings=cfg, registry=reg, adapter=adapter)


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


async def login(
    factory: async_sessionmaker[AsyncSession], user_id: UUID, *, expires_in: timedelta = timedelta(hours=1)
) -> UUID:
    """A login session of ``user_id`` (``sessions.id``), written by bridge_app as the login endpoint does (the table
    has no RLS); a negative ``expires_in`` gives an expired one."""
    session_id, now = uuid7(), clock.utcnow()
    row = {"id": session_id, "user": user_id, "hash": secrets.token_bytes(32), "expires": now + expires_in, "now": now}
    async with factory() as db:
        await db.execute(
            text(
                "INSERT INTO sessions (id, user_id, token_hash, expires_at, last_seen_at)"
                " VALUES (:id, :user, :hash, :expires, :now)"
            ),
            row,
        )
        await db.commit()
    return session_id
