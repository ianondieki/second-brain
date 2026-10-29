"""REQ-LLM-01: the ``llm_calls`` row the SQL ledger writes for an entry (no database: the mapping only).

The table's CHECKs (``cost_usd`` between 0 and 100, token and latency columns zero or more) are met by clamping, so
the row of a paid attempt is never refused; ``purpose`` is stored only for consent-covered tasks.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from bridge.llm.ledger import CallStatus, LedgerEntry
from bridge.llm.sql_ledger import MAX_ROW_COST_USD, row_values
from tests.unit.llm.helpers import NOW, ORG, USER

ENTRY = LedgerEntry(
    id=uuid4(),
    created_at=NOW,
    org_id=ORG,
    user_id=USER,
    task="moderation_prescreen",
    purpose="tier1_only",
    model="m",
    status=CallStatus.OK,
    stop_reason="end_turn",
    input_tokens=10,
    output_tokens=20,
    cache_read_tokens=30,
    cache_creation_tokens=40,
    cost_usd=Decimal("0.012345"),
    latency_ms=250,
    trace_id="tr",
    attempt=2,
    inputs={"fields": []},
    batch_id="b",
    custom_id="c",
    output={"verdict": "clean"},
    error="e",
)


def test_an_entry_maps_to_the_table_columns() -> None:
    values = row_values(ENTRY)
    assert values == {
        "id": ENTRY.id,
        "created_at": NOW,
        "org_id": ORG,
        "user_id": USER,
        "task": "moderation_prescreen",
        "purpose": None,  # Tier-1-only tasks need no consent purpose
        "model": "m",
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_tokens": 30,
        "cache_write_tokens": 40,
        "cost_usd": Decimal("0.012345"),
        "latency_ms": 250,
        "status": "ok",
        "stop_reason": "end_turn",
        "trace_id": "tr",
        "batch_id": "b",  # a Message Batches item: its batch and custom id
        "custom_id": "c",
        "inputs": {"fields": []},
    }
    assert row_values(replace(ENTRY, purpose="tier2_llm_assistant"))["purpose"] == "tier2_llm_assistant"
    assert row_values(replace(ENTRY, stop_reason="s" * 50))["stop_reason"] == "s" * 40


@pytest.mark.parametrize(
    ("change", "column", "stored"),
    [
        ({"cost_usd": Decimal("150")}, "cost_usd", MAX_ROW_COST_USD),
        ({"cost_usd": Decimal("-1")}, "cost_usd", Decimal(0)),
        ({"input_tokens": -1}, "input_tokens", 0),
        ({"output_tokens": -5}, "output_tokens", 0),
        ({"cache_read_tokens": -1}, "cache_read_tokens", 0),
        ({"cache_creation_tokens": -1}, "cache_write_tokens", 0),
        ({"latency_ms": -3}, "latency_ms", 0),
    ],
)
def test_values_outside_the_checks_are_clamped_and_logged(
    change: dict[str, object], column: str, stored: object, capsys: pytest.CaptureFixture[str]
) -> None:
    values = row_values(replace(ENTRY, **change))  # type: ignore[arg-type]
    assert values[column] == stored
    out = capsys.readouterr().out
    assert "llm.ledger_clamped" in out
    assert column in out


def test_values_at_the_bounds_are_kept_without_a_log(capsys: pytest.CaptureFixture[str]) -> None:
    edge = replace(ENTRY, cost_usd=MAX_ROW_COST_USD, input_tokens=0, latency_ms=0)
    assert (row_values(edge)["cost_usd"], row_values(edge)["input_tokens"]) == (MAX_ROW_COST_USD, 0)
    assert "llm.ledger_clamped" not in capsys.readouterr().out
