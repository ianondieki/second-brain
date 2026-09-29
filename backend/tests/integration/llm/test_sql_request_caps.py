"""REQ-LLM-01 P7 (D-37) against PostgreSQL: a free slot's daily request count and the prototype's lifetime total are
read from the ``llm_calls`` ledger, as ``bridge_app`` under Row-Level Security.

The request count reads the rows the bound tenant may read (RLS): today's rows of the slot's model that reached the
provider, never blocked ones. A platform-wide count needs a SECURITY DEFINER count (open in the REQ-LLM-01 card). The
lifetime total reads every tenant's rows through ``app_llm_spend_usd()``.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.config import FreeSlot, get_settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.llm import registry as registry_module
from bridge.llm.budget import LEDGER_START, day_start
from bridge.llm.errors import LLMBudgetExceeded, LLMRequestCapReached
from bridge.llm.fakes import FakeAdapter
from bridge.llm.registry import free_model_key
from bridge.llm.sql_ledger import SqlLedger
from bridge.llm.types import CallContext
from tests.integration.llm.conftest import People
from tests.integration.llm.helpers import OK, TASK, reply, service, stored
from tests.unit.llm.rig import screen
from tests.unit.llm.schemas import Verdict

Factory = async_sessionmaker[AsyncSession]


def free_slot(tag: str, requests: int) -> FreeSlot:
    return FreeSlot(1, "https://free.example/v1", SecretStr("k"), f"vendor/m-{tag}", requests, "json_object")


async def test_a_free_slot_counts_todays_sent_rows_and_refuses_at_its_cap(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    slot = free_slot(people.tag, 2)
    key = free_model_key(slot)
    reg = registry_module.load(get_settings().llm_models_file).for_free_slot(slot)
    trace = f"freecap-{people.tag}"
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        adapter = FakeAdapter([OK, "not json", OK])
        svc = service(db, factory, adapter, registry=reg)
        ctx = CallContext(user_id=people.a, trace_id=trace)
        await svc.complete(TASK, screen(), Verdict, ctx=ctx)  # one attempt
        with pytest.raises(LLMRequestCapReached):  # a schema failure, then its retry is the third attempt
            await svc.complete(TASK, screen(), Verdict, ctx=ctx)
        with pytest.raises(LLMRequestCapReached):
            await svc.complete(TASK, screen(), Verdict, ctx=ctx)
        ledger = SqlLedger(factory, caller=db)
        assert await ledger.calls_since(model=key, since=day_start(clock.utcnow())) == 2
    assert len(adapter.requests) == 2
    rows = await stored(owner_engine, trace)
    assert [(r["status"], r["model"], r["cost_usd"]) for r in rows] == [
        ("ok", key, 0),
        ("schema_error", key, 0),
        ("blocked_budget", key, 0),
        ("blocked_budget", key, 0),
    ]


async def test_the_count_reads_only_what_the_bound_tenant_may_read(factory: Factory, people: People) -> None:
    """RLS: user B's rows of the same slot are not in user A's count (the platform-wide count is open)."""
    slot = free_slot(people.tag, 10)
    key = free_model_key(slot)
    reg = registry_module.load(get_settings().llm_models_file).for_free_slot(slot)
    for user in (people.a, people.b):
        async with factory() as db:
            await bind_tenant(db, user_id=user)
            svc = service(db, factory, FakeAdapter([reply()]), registry=reg)
            await svc.complete(TASK, screen(), Verdict, ctx=CallContext(user_id=user))
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        assert await SqlLedger(factory, caller=db).calls_since(model=key, since=day_start(clock.utcnow())) == 1


async def test_the_count_is_the_slots_model_only(factory: Factory, people: People) -> None:
    """P7 review mutant M41: the same tenant's rows of another model today are not the slot's."""
    reg = registry_module.load(get_settings().llm_models_file)
    one, other = free_slot(people.tag, 10), replace(free_slot(people.tag, 10), number=2, model=f"vendor/o-{people.tag}")
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        for slot, calls in ((one, 1), (other, 2)):
            svc = service(db, factory, FakeAdapter([reply()] * calls), registry=reg.for_free_slot(slot))
            for _ in range(calls):
                await svc.complete(TASK, screen(), Verdict, ctx=CallContext(user_id=people.a))
        ledger = SqlLedger(factory, caller=db)
        today = day_start(clock.utcnow())
        assert await ledger.calls_since(model=free_model_key(one), since=today) == 1
        assert await ledger.calls_since(model=free_model_key(other), since=today) == 2


async def test_the_prototype_total_reads_every_tenants_lifetime_spend(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"total-{uuid7().hex[-12:]}"
    async with factory() as db:
        await bind_tenant(db, user_id=people.b)
        await service(db, factory, FakeAdapter([reply()])).complete(
            TASK, screen(), Verdict, ctx=CallContext(user_id=people.b)
        )
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        lifetime = await SqlLedger(factory, caller=db).global_spent_usd(since=LEDGER_START)
        assert lifetime > 0  # B's paid attempt counts, although A reads none of B's rows
        svc = service(db, factory, FakeAdapter([reply()]), llm_prototype_total_cap_usd=lifetime + Decimal("0.000001"))
        with pytest.raises(LLMBudgetExceeded) as info:
            await svc.complete(TASK, screen(), Verdict, ctx=CallContext(user_id=people.a, trace_id=trace))
    assert info.value.scope == "total"
    assert info.value.spent_usd >= lifetime
    [row] = await stored(owner_engine, trace)
    assert row["status"] == "blocked_budget"
