"""REQ-LLM-01: the in-memory ledger, dead-letter sink and human queue (the SQL ledger follows T2.1)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from bridge.llm.ledger import CallStatus, InMemoryLedger, LedgerEntry
from bridge.llm.sinks import DeadLetter, InMemoryDeadLetters, InMemoryHumanQueue, RefusalEvent
from bridge.llm.types import TokenUsage
from tests.unit.llm.helpers import NOW, ORG, USER


def entry(cost: str, org: object = None, user: object = None, when: object = NOW) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        created_at=when,  # type: ignore[arg-type]
        org_id=org,  # type: ignore[arg-type]
        user_id=user,  # type: ignore[arg-type]
        task="t",
        purpose="tier1_only",
        model=None,
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


async def test_sinks_keep_what_they_receive() -> None:
    letters, queue = InMemoryDeadLetters(), InMemoryHumanQueue()
    letter = DeadLetter(uuid4(), NOW, "t", "tr", ORG, None, "schema_error", "m", 2, "bad json")
    await letters.put(letter)
    event = RefusalEvent("t", "tr", None, USER, "m", "cyber", None)
    await queue.refusal(event)
    assert letters.letters == [letter]
    assert queue.events == [event]


def test_token_usage_adds_up() -> None:
    total = TokenUsage(1, 2, 3, 4, 1) + TokenUsage(10, 20, 30, 40, 10)
    assert total == TokenUsage(11, 22, 33, 44, 11)
