"""REQ-LLM-01: the in-memory ledger, dead-letter sink and human queue (the SQL ledger: tests/integration/llm)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import String

from bridge.llm import registry
from bridge.llm.errors import LLMBatchNotOwned
from bridge.llm.ledger import CallStatus, InMemoryLedger, LedgerEntry
from bridge.llm.models import LlmCall
from bridge.llm.sinks import DeadLetter, InMemoryDeadLetters, InMemoryHumanQueue, RefusalEvent
from bridge.llm.types import TRACE_ID, TokenUsage
from tests.unit.llm.helpers import NOW, ORG, OWNER, USER


def entry(cost: str, org: object = None, user: object = None, when: object = NOW) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        created_at=when,  # type: ignore[arg-type]
        org_id=org,  # type: ignore[arg-type]
        user_id=user,  # type: ignore[arg-type]
        task="t",
        purpose="tier1_only",
        model="m",
        status=CallStatus.BLOCKED_BUDGET,
        stop_reason=None,
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=Decimal(cost),
        latency_ms=0,
        trace_id="tr",
        attempt=1,
        inputs={"fields": []},
    )


async def test_in_memory_ledger_sums_by_subject_and_window() -> None:
    ledger = InMemoryLedger()
    await ledger.record(entry("1", org=ORG))
    await ledger.record(entry("2", org=ORG, user=USER))
    await ledger.record(entry("4", user=USER))
    await ledger.record(entry("8", when=NOW - timedelta(days=40)))
    since = NOW - timedelta(days=1)
    assert await ledger.tenant_spent_usd(org_id=ORG, user_id=None, since=since) == Decimal(3)
    assert await ledger.tenant_spent_usd(org_id=None, user_id=USER, since=since) == Decimal(4)
    assert await ledger.global_spent_usd(since=since) == Decimal(7)
    assert await ledger.global_spent_usd(since=NOW - timedelta(days=41)) == Decimal(15)


async def test_in_memory_ledger_reserves_and_settles_a_batch_item_once() -> None:
    """The SQL rules (revision 0002: one reservation and one settlement per item; the llm_spend view counts a
    reservation until its item settles, then the settled row), kept in memory."""
    ledger = InMemoryLedger()
    since = NOW - timedelta(days=1)
    hold = replace(entry("2", org=ORG), status=CallStatus("batch_reserved"), batch_id="b1", custom_id="i1")
    await ledger.reserve([hold, replace(hold, id=uuid4(), custom_id="i2")])
    assert await ledger.tenant_spent_usd(org_id=ORG, user_id=None, since=since) == Decimal(4)
    with pytest.raises(ValueError, match="reserved"):  # the item is reserved already
        await ledger.reserve([replace(hold, id=uuid4())])
    with pytest.raises(ValueError, match="batch_reserved"):  # a reservation is a batch_reserved row
        await ledger.reserve([replace(hold, id=uuid4(), custom_id="i3", status=CallStatus.OK)])
    result = replace(hold, id=uuid4(), status=CallStatus.OK, cost_usd=Decimal("1.5"))
    assert await ledger.settle(result) is True
    assert await ledger.settle(replace(result, id=uuid4(), status=CallStatus.PROVIDER_ERROR)) is False
    assert await ledger.tenant_spent_usd(org_id=ORG, user_id=None, since=since) == Decimal("3.5")  # i2 still held
    assert await ledger.global_spent_usd(since=since) == Decimal("3.5")
    assert await ledger.settle(replace(result, id=uuid4(), custom_id="i9")) is True  # settles with no reservation
    assert await ledger.global_spent_usd(since=since) == Decimal(5)
    with pytest.raises(ValueError, match="batch item"):  # a settlement names its item...
        await ledger.settle(replace(result, id=uuid4(), batch_id=None, custom_id=None))
    with pytest.raises(ValueError, match="batch item"):  # ...and is final
        await ledger.settle(replace(result, id=uuid4(), custom_id="i8", status=CallStatus("batch_reserved")))
    assert len(ledger.entries) == 4


async def test_in_memory_ledger_keeps_a_batch_items_rows_with_the_tenant_that_reserved_it() -> None:
    """As revision 0002 rounds 5 and 6 do: a batch is the tenant's of its earliest reservation, and every settlement
    is written with that tenant (``app_llm_settle_batch_item``), so another tenant (or the same user without the
    organisation) can neither settle nor cancel the reservation. Another tenant's later reservation of the same item
    coexists, counts towards that tenant only and takes nothing."""
    ledger = InMemoryLedger()
    since = NOW - timedelta(days=1)
    hold = replace(entry("2", org=ORG, user=USER), status=CallStatus("batch_reserved"), batch_id="b1", custom_id="i1")
    await ledger.reserve([hold])
    for org, user in ((None, OWNER), (ORG, None), (None, USER)):
        stranger = replace(hold, id=uuid4(), org_id=org, user_id=user)
        with pytest.raises(LLMBatchNotOwned):
            await ledger.settle(replace(stranger, status=CallStatus.OK, cost_usd=Decimal(0)))
        assert await ledger.batch_owned("b1", org_id=org, user_id=user) is False
    squat = replace(hold, id=uuid4(), org_id=None, user_id=OWNER, cost_usd=Decimal(7))
    await ledger.reserve([squat])  # a later reservation of another tenant: it coexists...
    assert await ledger.batch_owned("b1", org_id=ORG, user_id=USER) is True  # ...and takes nothing
    assert await ledger.batch_owned("b1", org_id=None, user_id=OWNER) is False
    assert await ledger.tenant_spent_usd(org_id=ORG, user_id=None, since=since) == Decimal(2)
    assert await ledger.tenant_spent_usd(org_id=None, user_id=OWNER, since=since) == Decimal(7)
    assert await ledger.settle(replace(hold, id=uuid4(), status=CallStatus.OK, cost_usd=Decimal(1))) is True
    assert await ledger.tenant_spent_usd(org_id=ORG, user_id=None, since=since) == Decimal(1)
    assert await ledger.tenant_spent_usd(org_id=None, user_id=OWNER, since=since) == Decimal(7)  # still counts
    assert len(ledger.entries) == 3


async def test_in_memory_ledger_judges_a_batch_by_its_earliest_reservation() -> None:
    """``app_llm_batch_owned``: the tenant of the batch's first reservation; false for a batch with none. A platform
    job (no organisation, no user) settles any batch, with the batch tenant's organisation and user."""
    ledger = InMemoryLedger()
    assert await ledger.batch_owned("b1", org_id=None, user_id=None) is False  # unknown batch
    platform = replace(entry("1"), status=CallStatus("batch_reserved"), batch_id="p1", custom_id="i1")
    await ledger.reserve([platform])
    assert await ledger.batch_owned("p1", org_id=None, user_id=None) is True
    assert await ledger.batch_owned("p1", org_id=ORG, user_id=USER) is False
    hold = replace(entry("2", org=ORG, user=USER), status=CallStatus("batch_reserved"), batch_id="b1", custom_id="i1")
    await ledger.reserve([hold])
    assert await ledger.batch_owned("b1", org_id=ORG, user_id=USER) is True
    assert await ledger.batch_owned("b1", org_id=None, user_id=None) is False
    job = replace(hold, id=uuid4(), org_id=None, user_id=None, status=CallStatus.OK, cost_usd=Decimal(1))
    assert await ledger.settle(job) is True
    assert (ledger.entries[-1].org_id, ledger.entries[-1].user_id) == (ORG, USER)  # the batch tenant's row
    assert await ledger.settle(replace(job, id=uuid4())) is False  # settled once
    with pytest.raises(LLMBatchNotOwned):  # a settlement of a batch with no reservation
        await ledger.settle(replace(job, id=uuid4(), batch_id="unknown"))


async def test_sinks_keep_what_they_receive() -> None:
    letters, queue = InMemoryDeadLetters(), InMemoryHumanQueue()
    letter = DeadLetter(uuid4(), NOW, "t", "tr", ORG, None, "schema_error", "m", 2, "bad json")
    await letters.put(letter)
    event = RefusalEvent("t", "tr", None, USER, "m", "cyber", None)
    await queue.refusal(event)
    assert letters.letters == [letter]
    assert queue.events == [event]


def test_names_and_trace_ids_fit_the_llm_calls_columns() -> None:
    """The registry refuses longer task and model names and CallContext longer trace ids, so no row can fail on
    length after a paid attempt."""
    columns = LlmCall.__table__.c
    assert cast(String, columns.task.type).length == cast(String, columns.model.type).length == registry.NAME_CHARS
    assert TRACE_ID.pattern.endswith(f"{{1,{cast(String, columns.trace_id.type).length}}}")


def test_token_usage_adds_up() -> None:
    total = TokenUsage(1, 2, 3, 4, 1) + TokenUsage(10, 20, 30, 40, 10)
    assert total == TokenUsage(11, 22, 33, 44, 11)
