"""REQ-LLM-01 (ADR-005 decision 5; T2.1 schema v2): the ``llm_calls`` ledger in PostgreSQL, as ``bridge_app`` under
Row-Level Security.

One row per call attempt, blocked and refused ones included, with the call's tenant, tokens, cost, latency, status,
stop reason and trace id, committed on its own so it survives the caller's rollback; organisation A reads none of
organisation B's rows; ``inputs`` is unreadable by bridge_app and read by staff admin only, through
``app_llm_call_inputs()``. AC-SEC-6 and the caps against SQL are in ``test_sql_caps_and_tier2.py``.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.config import get_settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.llm import registry
from bridge.llm.errors import LLMBudgetExceeded, LLMKillSwitch, LLMRefused, Tier2NotAllowed
from bridge.llm.fakes import FakeAdapter
from bridge.llm.types import CallContext, InputField, Instruction, Message, Tier
from tests.integration.llm.conftest import People
from tests.integration.llm.helpers import TASK, USAGE, reply, service, stored
from tests.unit.llm.rig import screen
from tests.unit.llm.schemas import Verdict

SPEC = registry.load(get_settings().llm_models_file).task(TASK)
Factory = async_sessionmaker[AsyncSession]


async def test_one_row_per_call_with_its_tenant_tokens_cost_latency_and_trace(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"one-{people.tag}"
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        svc = service(db, factory, FakeAdapter([reply()]))
        ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
        result = await svc.complete(TASK, screen(), Verdict, ctx=ctx)
    [row] = await stored(owner_engine, trace)
    assert (row["org_id"], row["user_id"], row["task"], row["model"]) == (people.org_a, people.a, TASK, SPEC.model)
    assert row["purpose"] is None  # a Tier-1-only task needs no consent purpose
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"], row["cache_write_tokens"]) == (
        USAGE.input_tokens,
        USAGE.output_tokens,
        USAGE.cache_read_input_tokens,
        USAGE.cache_creation_input_tokens,
    )
    assert row["cost_usd"] == result.cost_usd > 0
    assert (row["status"], row["stop_reason"], row["trace_id"]) == ("ok", "end_turn", trace)
    assert row["latency_ms"] is not None
    assert row["latency_ms"] >= 0
    assert abs(row["created_at"] - clock.utcnow()) < timedelta(minutes=5)
    [field] = row["inputs"]["fields"]  # the sanitised Tier-1 value, as the model saw it
    assert (field["name"], field["tier"], field["value"]) == ("teaser.summary", "tier1", "Solar kiosks for markets")
    assert re.fullmatch(r"[0-9a-f]{64}", row["inputs"]["prompt_sha256"])


async def test_blocked_and_refused_calls_are_rows_that_survive_the_callers_rollback(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"blocked-{people.tag}"
    ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
    tier2 = [
        Message.system("You screen teasers."),
        Message.user(Instruction("Screen:"), InputField("confidential.m", "x", tier=Tier.TIER2, owner_id=people.a)),
    ]
    adapter = FakeAdapter([reply(stop_reason="refusal")])
    marker = uuid7()
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        await db.execute(  # the caller's own work, never committed
            text(
                "INSERT INTO llm_calls (id, user_id, task, model, status, trace_id)"
                " VALUES (:id, :u, 'c', 'm', 'ok', :t)"
            ),
            {"id": marker, "u": people.a, "t": trace},
        )
        with pytest.raises(LLMKillSwitch):
            await service(db, factory, adapter, llm_kill_switch=True).complete(TASK, screen(), Verdict, ctx=ctx)
        with pytest.raises(Tier2NotAllowed):
            await service(db, factory, adapter).complete(TASK, tier2, Verdict, ctx=ctx)
        no_budget = service(db, factory, adapter, llm_global_daily_cap_usd=Decimal(0))
        with pytest.raises(LLMBudgetExceeded):
            await no_budget.complete(TASK, screen(), Verdict, ctx=ctx)
        with pytest.raises(LLMRefused):
            await service(db, factory, adapter).complete(TASK, screen(), Verdict, ctx=ctx)
        await db.rollback()
    rows = await stored(owner_engine, trace)
    assert [r["status"] for r in rows] == ["blocked_kill_switch", "blocked_tier2", "blocked_budget", "refusal"]
    assert marker not in {r["id"] for r in rows}  # the caller's write rolled back; the ledger's rows did not
    assert len(adapter.requests) == 1  # only the refused attempt reached the model
    for row in rows[:3]:  # nothing sent, nothing billed; the rows still name the targeted model and the tenant
        assert (row["model"], row["cost_usd"], row["input_tokens"], row["output_tokens"]) == (SPEC.model, 0, 0, 0)
        assert (row["org_id"], row["user_id"], row["stop_reason"]) == (people.org_a, people.a, None)
    for row in rows[:2]:  # refused before sanitising: names and lengths only
        assert all("value" not in f for f in row["inputs"]["fields"])
    assert (rows[3]["stop_reason"], rows[3]["output_tokens"]) == ("refusal", USAGE.output_tokens)
    assert rows[3]["cost_usd"] > 0
