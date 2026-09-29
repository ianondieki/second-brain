"""REQ-LLM-01 P7 (D-37) against PostgreSQL: the app's ``routed_client`` with a free slot behind respx (no network).

A real account (no ``users.demo_account``, or false) never reaches a free provider: the call is answered by the
labelled fake before any HTTP request and writes no ledger row. A seeded demo account's call reaches the slot and is
recorded at no cost, counted against the slot's daily cap under RLS. The demo column (schema v3, not merged yet) is
added inside one owner transaction that is rolled back.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import respx
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.config import Settings, get_settings
from bridge.db import bind_tenant
from bridge.llm.budget import day_start
from bridge.llm.deps import build_runtime, routed_client
from bridge.llm.registry import free_model_key
from bridge.llm.sql_ledger import SqlLedger
from bridge.llm.types import CallContext
from tests.integration.llm.conftest import People
from tests.integration.llm.helpers import OK, ROOMY_GLOBAL_CAP, TASK, as_app_with_demo_account, stored
from tests.unit.llm.rig import screen
from tests.unit.llm.schemas import Verdict

Factory = async_sessionmaker[AsyncSession]
BASE = "https://free-int.example/v1"


def free_settings(tag: str) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "llm_provider": "free",
        "llm_global_daily_cap_usd": ROOMY_GLOBAL_CAP,
        "llm_prototype_total_cap_usd": ROOMY_GLOBAL_CAP,
        "llm_free_1_base_url": BASE,
        "llm_free_1_api_key": SecretStr("sk-int-key-not-real"),
        "llm_free_1_model": f"vendor/m-{tag}",
        "llm_free_1_daily_requests": 5,
    }
    return get_settings().model_copy(update=values)


def chat() -> httpx.Response:
    choice = {"index": 0, "message": {"role": "assistant", "content": json.dumps(OK)}, "finish_reason": "stop"}
    return httpx.Response(200, json={"choices": [choice], "usage": {"prompt_tokens": 40, "completion_tokens": 8}})


async def test_a_real_accounts_call_never_reaches_a_free_provider(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    cfg = free_settings(people.tag)
    trace = f"route-real-{people.tag}"
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        async with factory() as db:
            await bind_tenant(db, user_id=people.a)
            client = routed_client(db, factory=factory, settings=cfg, runtime=build_runtime(cfg))
            result = await client.complete(TASK, screen(), Verdict, ctx=CallContext(user_id=people.a, trace_id=trace))
    assert not route.called
    assert (result.demo_fallback, result.fallback_reason) == (True, "not_demo_data")
    assert await stored(owner_engine, trace) == []


async def test_a_seeded_demo_accounts_call_reaches_the_free_slot_and_is_recorded(
    owner_engine: AsyncEngine, people: People
) -> None:
    cfg = free_settings(people.tag)
    runtime = build_runtime(cfg)
    key = free_model_key(runtime.free[0].slot)
    trace = f"route-demo-{people.tag}"
    async with owner_engine.connect() as conn:
        outer = await conn.begin()
        try:
            joined = await as_app_with_demo_account(conn, people.a)  # every session joins this transaction
            db = joined()
            await bind_tenant(db, user_id=people.a)
            client = routed_client(db, factory=joined, settings=cfg, runtime=runtime)
            with respx.mock(assert_all_called=True) as router:
                route = router.post(f"{BASE}/chat/completions").mock(return_value=chat())
                result = await client.complete(
                    TASK, screen(), Verdict, ctx=CallContext(user_id=people.a, trace_id=trace)
                )
            assert route.call_count == 1
            assert (result.demo_fallback, result.model) == (False, key)
            assert result.cost_usd == Decimal(0)
            assert await SqlLedger(joined, caller=db).calls_since(model=key, since=day_start(clock.utcnow())) == 1
            rows = await conn.execute(
                text("SELECT status, model, cost_usd, user_id FROM llm_calls WHERE trace_id = :t"), {"t": trace}
            )
            assert [tuple(r) for r in rows] == [("ok", key, 0, people.a)]
            await db.close()
        finally:
            await outer.rollback()
    assert await stored(owner_engine, trace) == []  # rolled back with the column
