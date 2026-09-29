"""REQ-LLM-01 against PostgreSQL (T2.2 review M2 and m3; revision 0002 item G): Message Batches reservations.

``batch_submit`` writes one ``batch_reserved`` row per item (its batch-price estimate) as the bound tenant, so the
subject's monthly sum and ``app_llm_spend_usd()`` (both read the ``llm_spend`` view) count a batch in flight and refuse
the next one at the cap; ``batch_poll`` settles each item once with an untargeted ``ON CONFLICT DO NOTHING`` (a platform
job's items too, whose rows bridge_app cannot read back), and a repeat poll writes and counts nothing again. An item
missing from the provider's results keeps its reservation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pytest
from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.billing import plans
from bridge.config import get_settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.llm.adapter import BatchItemError, ModelResponse
from bridge.llm.budget import cap_from_limits, day_start, month_start
from bridge.llm.client import BatchItem
from bridge.llm.errors import LLMBudgetExceeded, LLMProviderError
from bridge.llm.fakes import FakeAdapter, Reply
from bridge.llm.sql_ledger import SqlLedger
from bridge.llm.types import CallContext, Result
from bridge.models.enums import PlanSide
from tests.integration.llm.conftest import People
from tests.integration.llm.helpers import TASK, USAGE, reply, service, stored
from tests.integration.llm.test_sql_caps_and_tier2 import seed_spend
from tests.unit.llm.rig import registry_with, rig, screen
from tests.unit.llm.schemas import Verdict

Factory = async_sessionmaker[AsyncSession]
BATCHABLE = registry_with(moderation_prescreen={"batchable": True})
IDS = ["a", "b", "c"]
RESERVED = "batch_reserved"


def items(*ids: str) -> list[BatchItem]:
    return [BatchItem(custom_id, screen(f"teaser {custom_id}")) for custom_id in ids]


def total(rows: list[RowMapping]) -> Decimal:
    return sum((Decimal(r["cost_usd"]) for r in rows), Decimal(0))


def split(rows: list[RowMapping]) -> tuple[list[RowMapping], list[RowMapping]]:
    """(reservations, settlements)"""
    return [r for r in rows if r["status"] == RESERVED], [r for r in rows if r["status"] != RESERVED]


async def org_spend(factory: Factory, people: People) -> Decimal:
    """Organisation A's spend this month, as its monthly cap reads it (A bound, through RLS)."""
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        ledger = SqlLedger(factory, caller=db)
        return await ledger.tenant_spent_usd(org_id=people.org_a, user_id=people.a, since=month_start(clock.utcnow()))


async def platform_spend(factory: Factory) -> Decimal:
    async with factory() as db:
        return await SqlLedger(factory, caller=db).global_spent_usd(since=day_start(clock.utcnow()))


async def one_batch_estimate() -> Decimal:
    """The reservations of one ``items(*IDS)`` batch (the estimate reads text lengths; every nonce has 16 chars)."""
    probe = rig(FakeAdapter(), reg=BATCHABLE)
    await probe.service.batch_submit(TASK, items(*IDS), Verdict, ctx=CallContext(trace_id="probe"))
    return sum((e.cost_usd for e in probe.ledger.entries), Decimal(0))


class ResultsWithout(FakeAdapter):
    """The provider's results lack the items in ``missing``."""

    def __init__(self, replies: list[Reply], missing: set[str]) -> None:
        super().__init__(replies)
        self.missing = missing

    async def batch_results(self, batch_id: str) -> dict[str, ModelResponse | BatchItemError]:
        results = await super().batch_results(batch_id)
        return {custom_id: item for custom_id, item in results.items() if custom_id not in self.missing}


async def test_items_are_reserved_at_submission_and_settle_once(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"batch-{people.tag}"
    ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
    adapter = FakeAdapter([reply()] * len(IDS) * 2)  # the ended batch's results, fetched by each poll
    org_before, platform_before = await org_spend(factory, people), await platform_spend(factory)
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        svc = service(db, factory, adapter, registry=BATCHABLE)
        handle = await svc.batch_submit(TASK, items(*IDS), Verdict, ctx=ctx)
        held = await stored(owner_engine, trace)
        assert [(r["status"], r["batch_id"], r["custom_id"]) for r in held] == [
            (RESERVED, handle.batch_id, custom_id) for custom_id in IDS
        ]
        assert {(r["org_id"], r["user_id"], r["input_tokens"], r["output_tokens"]) for r in held} == {
            (people.org_a, people.a, 0, 0)
        }
        assert total(held) > 0
        assert await org_spend(factory, people) - org_before == total(held)  # the batch in flight counts
        assert await platform_spend(factory) - platform_before == total(held)
        first = await svc.batch_poll(handle, Verdict)
        again = await svc.batch_poll(handle, Verdict)
    reservations, settlements = split(await stored(owner_engine, trace))
    assert reservations == held
    assert sorted((r["status"], r["custom_id"]) for r in settlements) == [("ok", custom_id) for custom_id in IDS]
    real = BATCHABLE.cost_usd(handle.model, USAGE, batch=True) * len(IDS)
    assert total(settlements) == real  # the repeat poll wrote nothing
    assert await org_spend(factory, people) - org_before == real  # settled: the reservations no longer count
    assert await platform_spend(factory) - platform_before == real
    for poll in (first, again):
        outcome = poll.results["a"]
        assert isinstance(outcome, Result)
        assert outcome.budget.spent_usd == org_before + real


@pytest.mark.parametrize("scope", ["global", "tenant"])
async def test_the_caps_refuse_further_batches_while_one_is_in_flight(
    factory: Factory, owner_engine: AsyncEngine, people: People, scope: Literal["global", "tenant"]
) -> None:
    """The review's scenario against SQL: room for about one and a half batches."""
    one = await one_batch_estimate()
    room = one * Decimal("1.5")
    trace = f"batch-cap-{scope}-{people.tag}"
    ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
    adapter = FakeAdapter([reply()] * len(IDS))
    overrides: dict[str, Decimal] = {}
    if scope == "global":
        overrides["llm_global_daily_cap_usd"] = await platform_spend(factory) + room
    else:
        cap = cap_from_limits(plans.load(get_settings().plans_file).default_for(PlanSide.ORG).limits)
        assert cap is not None
        assert cap > room
        await seed_spend(owner_engine, cap - room, org=people.org_a, user=people.a)
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        svc = service(db, factory, adapter, registry=BATCHABLE, **overrides)
        handle = await svc.batch_submit(TASK, items(*IDS), Verdict, ctx=ctx)
        for _ in range(2):
            with pytest.raises(LLMBudgetExceeded) as info:
                await svc.batch_submit(TASK, items(*IDS), Verdict, ctx=ctx)
            assert info.value.scope == scope
        assert len(adapter.requests) == len(IDS)  # only the first batch reached the provider
        await svc.batch_poll(handle, Verdict)  # settled far below the estimate: room again
        await svc.batch_submit(TASK, items(*IDS), Verdict, ctx=ctx)
    assert len(adapter.requests) == 2 * len(IDS)
    statuses = [r["status"] for r in await stored(owner_engine, trace)]
    assert statuses == [RESERVED] * 3 + ["blocked_budget"] * 2 + ["ok"] * 3 + [RESERVED] * 3


async def test_a_platform_jobs_batch_settles_once_although_bridge_app_cannot_read_its_rows(
    factory: Factory, owner_engine: AsyncEngine
) -> None:
    trace = f"batch-system-{uuid7().hex[-12:]}"
    adapter = FakeAdapter([reply()] * 4)
    before = await platform_spend(factory)
    async with factory() as db:  # a platform job: no tenant bound, rows with no user and no organisation
        svc = service(db, factory, adapter, registry=BATCHABLE)
        handle = await svc.batch_submit(TASK, items("a", "b"), Verdict, ctx=CallContext(trace_id=trace))
        held = await stored(owner_engine, trace)
        assert [(r["status"], r["org_id"], r["user_id"]) for r in held] == [(RESERVED, None, None)] * 2
        assert await platform_spend(factory) - before == total(held)
        for _ in range(2):
            done = await svc.batch_poll(handle, Verdict)
            assert all(isinstance(done.results[custom_id], Result) for custom_id in ("a", "b"))
    reservations, settlements = split(await stored(owner_engine, trace))
    assert (len(reservations), [r["status"] for r in settlements]) == (2, ["ok", "ok"])
    assert await platform_spend(factory) - before == total(settlements)


async def test_an_item_missing_from_the_results_keeps_its_reservation(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    trace = f"batch-missing-{people.tag}"
    ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
    org_before = await org_spend(factory, people)
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        svc = service(db, factory, ResultsWithout([reply()] * len(IDS), missing={"b"}), registry=BATCHABLE)
        handle = await svc.batch_submit(TASK, items(*IDS), Verdict, ctx=ctx)
        done = await svc.batch_poll(handle, Verdict)
    missing = done.results["b"]
    assert isinstance(missing, LLMProviderError)
    assert missing.transient
    reservations, settlements = split(await stored(owner_engine, trace))
    assert sorted(r["custom_id"] for r in settlements) == ["a", "c"]
    [held] = [r for r in reservations if r["custom_id"] == "b"]
    assert await org_spend(factory, people) - org_before == Decimal(held["cost_usd"]) + total(settlements)
