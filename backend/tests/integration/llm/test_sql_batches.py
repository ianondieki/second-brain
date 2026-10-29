"""REQ-LLM-01 against PostgreSQL (T2.2 review M2 and m3; revision 0002 items G and H, rounds 5 and 6): Message
Batches reservations.

``batch_submit`` writes one ``batch_reserved`` row per item (its batch-price estimate) as the bound tenant, so the
subject's monthly sum and ``app_llm_spend_usd()`` (both read the ``llm_spend`` view) count a batch in flight and refuse
the next one at the cap. ``batch_poll`` asks ``app_llm_batch_owned()`` first (the tenant of the batch's earliest
reservation) and refuses another tenant's batch before reading its state or results; it settles each item once
through ``app_llm_settle_batch_item()``, with the batch tenant's organisation and user (a platform job's items too,
whose rows bridge_app cannot read back), and a repeat poll writes and counts nothing again. An item missing from the
provider's results keeps its reservation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.billing import plans
from bridge.config import get_settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.llm.adapter import BatchItemError, BatchState, ModelResponse
from bridge.llm.budget import cap_from_limits, day_start, month_start
from bridge.llm.client import BatchHandle, BatchItem
from bridge.llm.errors import LLMBatchNotOwned, LLMBudgetExceeded, LLMProviderError
from bridge.llm.fakes import FakeAdapter, Reply
from bridge.llm.ledger import CallStatus, LedgerEntry
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

    def __init__(self, replies: Sequence[Reply], missing: set[str]) -> None:
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
    """Not settled, since the results may have been cut short and the item billed: every poll reports it as transient
    and its reservation keeps counting (fail closed) until a poll whose results hold it settles it once."""
    trace = f"batch-missing-{people.tag}"
    ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
    org_before = await org_spend(factory, people)
    adapter = ResultsWithout([reply()] * len(IDS) * 3, missing={"b"})  # three polls of three items
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        svc = service(db, factory, adapter, registry=BATCHABLE)
        handle = await svc.batch_submit(TASK, items(*IDS), Verdict, ctx=ctx)
        for _ in range(2):
            done = await svc.batch_poll(handle, Verdict)
            missing = done.results["b"]
            assert isinstance(missing, LLMProviderError)
            assert missing.transient
            reservations, settlements = split(await stored(owner_engine, trace))
            assert sorted(r["custom_id"] for r in settlements) == ["a", "c"]
            assert sorted(r["custom_id"] for r in reservations) == IDS  # b's reservation is still there
            [held] = [r for r in reservations if r["custom_id"] == "b"]
            assert await org_spend(factory, people) - org_before == Decimal(held["cost_usd"]) + total(settlements)
        adapter.missing = set()
        found = await svc.batch_poll(handle, Verdict)
    assert isinstance(found.results["b"], Result)
    reservations, settlements = split(await stored(owner_engine, trace))
    assert sorted(r["custom_id"] for r in settlements) == IDS
    assert await org_spend(factory, people) - org_before == total(settlements)


class Watched(FakeAdapter):
    """Records which batches' state and results were read."""

    def __init__(self, replies: Sequence[Reply]) -> None:
        super().__init__(replies)
        self.reads: list[str] = []

    async def batch_state(self, batch_id: str) -> BatchState:
        self.reads.append(f"state {batch_id}")
        return await super().batch_state(batch_id)

    async def batch_results(self, batch_id: str) -> dict[str, ModelResponse | BatchItemError]:
        self.reads.append(f"results {batch_id}")
        return await super().batch_results(batch_id)


def settlement(batch_id: str, custom_id: str, *, org: UUID | None, user: UUID | None, trace: str) -> LedgerEntry:
    """An item's final row as ``batch_poll`` writes it, naming ``org`` and ``user``."""
    return LedgerEntry(
        id=uuid7(),
        created_at=clock.utcnow(),
        org_id=org,
        user_id=user,
        task=TASK,
        purpose="tier1_only",
        model="m",
        status=CallStatus.OK,
        stop_reason="end_turn",
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=Decimal("0.001"),
        latency_ms=0,
        trace_id=trace,
        attempt=1,
        inputs={"fields": []},
        batch_id=batch_id,
        custom_id=custom_id,
    )


async def submit_as_a(factory: Factory, people: People, adapter: FakeAdapter, trace: str) -> BatchHandle:
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        ctx = CallContext(org_id=people.org_a, user_id=people.a, trace_id=trace)
        return await service(db, factory, adapter, registry=BATCHABLE).batch_submit(TASK, items(*IDS), Verdict, ctx=ctx)


async def test_another_tenant_cannot_settle_or_cancel_an_items_reservation(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    """Organisation B, polling a handle that names A's batch (one provider account serves every tenant), is refused
    before the batch's state or results are read (``app_llm_batch_owned``); B's ledger settling one of its items
    directly is refused by ``app_llm_settle_batch_item``. A's reservations keep counting and A's own poll settles
    them, as A."""
    trace = f"batch-cross-{people.tag}"
    adapter = Watched([reply()] * len(IDS))
    org_before = await org_spend(factory, people)
    handle = await submit_as_a(factory, people, adapter, trace)
    held = await stored(owner_engine, trace)
    forged = handle.model_copy(update={"org_id": people.org_b, "user_id": people.b, "trace_id": f"{trace}-b"})
    async with factory() as db:
        await bind_tenant(db, user_id=people.b)
        with pytest.raises(LLMBatchNotOwned):
            await service(db, factory, adapter, registry=BATCHABLE).batch_poll(forged, Verdict)
        assert adapter.reads == []  # neither its state nor its results
        ledger = SqlLedger(factory, caller=db)
        for org in (people.org_b, None):
            with pytest.raises(LLMBatchNotOwned):
                await ledger.settle(settlement(handle.batch_id, "a", org=org, user=people.b, trace=f"{trace}-b"))
    assert await stored(owner_engine, f"{trace}-b") == []
    assert await org_spend(factory, people) - org_before == total(held)  # A's reservations still count
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        await service(db, factory, adapter, registry=BATCHABLE).batch_poll(handle, Verdict)
    reservations, settlements = split(await stored(owner_engine, trace))
    assert (reservations, sorted(r["custom_id"] for r in settlements)) == (held, IDS)
    assert {(r["org_id"], r["user_id"]) for r in settlements} == {(people.org_a, people.a)}
    assert await org_spend(factory, people) - org_before == total(settlements)


async def test_a_later_reservation_of_another_tenant_does_not_take_the_batch(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    """Round 6: a batch is the tenant's of its earliest reservation (created_at is the database's). B reserving an
    item of A's batch afterwards (a squatted item) is accepted as B's own row, but B still cannot poll the batch,
    A's poll settles every item as A, and B's reservation keeps counting against B."""
    trace = f"batch-squat-{people.tag}"
    adapter = Watched([reply()] * len(IDS))
    handle = await submit_as_a(factory, people, adapter, trace)
    squat = replace(
        settlement(handle.batch_id, "a", org=people.org_b, user=people.b, trace=f"{trace}-b"),
        status=CallStatus.BATCH_RESERVED,
        stop_reason=None,
        cost_usd=Decimal(3),
    )
    async with factory() as db:
        await bind_tenant(db, user_id=people.b)
        await SqlLedger(factory, caller=db).reserve([squat])
        forged = handle.model_copy(update={"org_id": people.org_b, "user_id": people.b, "trace_id": f"{trace}-b"})
        with pytest.raises(LLMBatchNotOwned):
            await service(db, factory, adapter, registry=BATCHABLE).batch_poll(forged, Verdict)
    assert adapter.reads == []
    async with factory() as db:
        await bind_tenant(db, user_id=people.a)
        await service(db, factory, adapter, registry=BATCHABLE).batch_poll(handle, Verdict)
    _, settlements = split(await stored(owner_engine, trace))
    assert {(r["custom_id"], r["org_id"], r["user_id"]) for r in settlements} == {
        (custom_id, people.org_a, people.a) for custom_id in IDS
    }
    [kept] = await stored(owner_engine, f"{trace}-b")
    assert (kept["status"], kept["org_id"], kept["user_id"]) == (RESERVED, people.org_b, people.b)
    async with factory() as db:
        await bind_tenant(db, user_id=people.b)
        spent = await SqlLedger(factory, caller=db).tenant_spent_usd(
            org_id=people.org_b, user_id=people.b, since=month_start(clock.utcnow())
        )
    assert spent == Decimal(3)


async def test_a_platform_job_settles_an_items_row_with_the_batch_tenant(
    factory: Factory, owner_engine: AsyncEngine, people: People
) -> None:
    """``app_llm_settle_batch_item`` for the platform job (nothing bound), e.g. once the batch's user has left the
    organisation: the row names the batch tenant's organisation and user, whatever the entry names, and settles once."""
    trace = f"batch-job-{people.tag}"
    handle = await submit_as_a(factory, people, FakeAdapter(), trace)
    org_before = await org_spend(factory, people)
    async with factory() as db:  # nothing bound
        ledger = SqlLedger(factory, caller=db)
        row = settlement(handle.batch_id, "a", org=None, user=None, trace=trace)
        assert await ledger.settle(row) is True
        assert await ledger.settle(replace(row, id=uuid7())) is False
    [done] = split(await stored(owner_engine, trace))[1]
    assert (done["custom_id"], done["org_id"], done["user_id"]) == ("a", people.org_a, people.a)
    [held] = [r for r in split(await stored(owner_engine, trace))[0] if r["custom_id"] == "a"]
    assert await org_spend(factory, people) - org_before == Decimal(done["cost_usd"]) - Decimal(held["cost_usd"])
