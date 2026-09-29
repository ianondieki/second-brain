"""The ``llm_calls`` ledger (REQ-LLM-01; ADR-005 decision 5; THREAT_MODEL "which prompt/model produced a decision").

Every attempt writes one ``LedgerEntry``: calls refused before sending (kill switch, caps, Tier-2 guard) with zero
tokens, and every model attempt with its tokens (cache reads and writes included), cost, latency, status and stop
reason. ``model`` is the model the attempt targeted (a refused call names the task's model). ``inputs`` holds the
sanitised Tier-1 field values and, for Tier-2 fields, only the name, tier and length: a Tier-2 value never reaches
the ledger, with or without consent (AC-SEC-6). Output text is kept only for tasks marked ``confidential: false``.

Message Batches items (revision 0002): ``reserve`` writes one ``batch_reserved`` row per item of an accepted batch, at
its estimate; ``settle`` writes the item's final row once (``False`` when it had settled before). Spend follows the
``llm_spend`` rule: every row counts except a reservation whose item has settled, so an item counts from submission
and only once. Every row of an item names the tenant (organisation and user) of its reservation: a settlement from
another tenant is refused, so it can neither cancel the reservation nor move the cost (schema round 5 enforces the
same with a trigger). ``record`` writes every other row.

``LedgerStore`` is the seam; ``InMemoryLedger`` serves tests and fakes, with the same rules. ``check_subject`` runs
first in every call: a store that cannot write the subject's rows or read its spend refuses the call before anything
is sent, never after a paid attempt. The SQL store over the ``llm_calls`` table (T2.1) is
``bridge.llm.sql_ledger.SqlLedger``.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class CallStatus(StrEnum):
    OK = "ok"
    REFUSAL = "refusal"
    MAX_TOKENS = "max_tokens"
    SCHEMA_ERROR = "schema_error"
    UNSUPPORTED_STOP = "unsupported_stop"
    PROVIDER_ERROR = "provider_error"
    BLOCKED_KILL_SWITCH = "blocked_kill_switch"
    BLOCKED_BUDGET = "blocked_budget"
    BLOCKED_TIER2 = "blocked_tier2"
    BLOCKED_CONSENT = "blocked_consent"
    BATCH_RESERVED = "batch_reserved"  # a batch item in flight, at its estimate, until its final row settles it


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    id: UUID
    created_at: datetime
    org_id: UUID | None
    user_id: UUID | None
    task: str
    purpose: str
    model: str
    status: CallStatus
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: Decimal
    latency_ms: int
    trace_id: str
    attempt: int
    inputs: Mapping[str, Any]
    batch_id: str | None = None  # a Message Batches item: the provider's batch id and the item's custom id
    custom_id: str | None = None
    output: Mapping[str, Any] | None = None
    error: str | None = None


BatchItemKey = tuple[str, str]


def item_key(entry: LedgerEntry) -> BatchItemKey | None:
    """The batch item a row belongs to (its batch and custom id), or None for a synchronous call's row."""
    if entry.batch_id is None or entry.custom_id is None:
        return None
    return entry.batch_id, entry.custom_id


def check_plain(entry: LedgerEntry) -> None:
    if entry.batch_id is not None or entry.custom_id is not None or entry.status is CallStatus.BATCH_RESERVED:
        raise ValueError("a batch item's rows are written by reserve and settle")


def check_reservation(entry: LedgerEntry) -> None:
    if entry.status is not CallStatus.BATCH_RESERVED or item_key(entry) is None:
        raise ValueError("a reservation is a batch_reserved row naming its batch item")


def check_settlement(entry: LedgerEntry) -> None:
    if entry.status is CallStatus.BATCH_RESERVED or item_key(entry) is None:
        raise ValueError("a settlement names its batch item and has its final status")


class LedgerStore(Protocol):
    async def check_subject(self, *, org_id: UUID | None, user_id: UUID | None) -> None:
        """Raise ``LLMConfigError`` unless this store may write the subject's rows and read its spend."""
        ...

    async def record(self, entry: LedgerEntry) -> None:
        """Write one row that belongs to no batch item."""
        ...

    async def reserve(self, entries: Sequence[LedgerEntry]) -> None:
        """Write the reservations of an accepted batch's items, all or none; an item is reserved once."""
        ...

    async def settle(self, entry: LedgerEntry) -> bool:
        """Write a batch item's final row unless the item has settled before; True when this call settled it."""
        ...

    async def tenant_spent_usd(self, *, org_id: UUID | None, user_id: UUID | None, since: datetime) -> Decimal:
        """Spend of one billing subject since ``since``: the organisation's rows when ``org_id`` is given, else the
        user's own rows (those without an organisation)."""
        ...

    async def global_spent_usd(self, *, since: datetime) -> Decimal: ...


class InMemoryLedger:
    """``LedgerStore`` in memory (unit tests, ``FakeLLMClient``), with the SQL store's batch rules."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    async def check_subject(self, *, org_id: UUID | None, user_id: UUID | None) -> None:
        return None  # memory holds any subject

    async def record(self, entry: LedgerEntry) -> None:
        check_plain(entry)
        self.entries.append(entry)

    async def reserve(self, entries: Sequence[LedgerEntry]) -> None:
        for entry in entries:
            check_reservation(entry)
            self._check_tenant(entry)
        keys = [item_key(e) for e in entries]
        held = {item_key(e) for e in self.entries if e.status is CallStatus.BATCH_RESERVED}
        if len(set(keys)) != len(keys) or not held.isdisjoint(keys):
            raise ValueError("a batch item is reserved already")
        self.entries.extend(entries)

    async def settle(self, entry: LedgerEntry) -> bool:
        check_settlement(entry)
        self._check_tenant(entry)  # before the conflict check, as a BEFORE INSERT trigger runs
        if item_key(entry) in self._settled():
            return False
        self.entries.append(entry)
        return True

    def _check_tenant(self, entry: LedgerEntry) -> None:
        """Every row of a batch item names the organisation and user of its first row (revision 0002 round 5)."""
        key = item_key(entry)
        for e in self.entries:
            if item_key(e) == key and (e.org_id, e.user_id) != (entry.org_id, entry.user_id):
                raise ValueError("this batch item's rows belong to another tenant")

    def _settled(self) -> set[BatchItemKey | None]:
        return {
            item_key(e) for e in self.entries if e.batch_id is not None and e.status is not CallStatus.BATCH_RESERVED
        }

    def _spend(self, since: datetime) -> Iterator[LedgerEntry]:
        """The ``llm_spend`` rule: every row since ``since`` but a reservation whose item has settled."""
        settled = self._settled()
        for e in self.entries:
            if e.created_at >= since and not (e.status is CallStatus.BATCH_RESERVED and item_key(e) in settled):
                yield e

    async def tenant_spent_usd(self, *, org_id: UUID | None, user_id: UUID | None, since: datetime) -> Decimal:
        if org_id is not None:
            rows = (e for e in self._spend(since) if e.org_id == org_id)
        else:
            rows = (e for e in self._spend(since) if e.org_id is None and e.user_id == user_id)
        return sum((e.cost_usd for e in rows), Decimal(0))

    async def global_spent_usd(self, *, since: datetime) -> Decimal:
        return sum((e.cost_usd for e in self._spend(since)), Decimal(0))
