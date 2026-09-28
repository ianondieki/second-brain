"""The ``llm_calls`` ledger (REQ-LLM-01; ADR-005 decision 5; THREAT_MODEL "which prompt/model produced a decision").

Every attempt writes one ``LedgerEntry``: calls refused before sending (kill switch, caps, Tier-2 guard) with zero
tokens, and every model attempt with its tokens (cache reads and writes included), cost, latency, status and stop
reason. ``model`` is the model the attempt targeted (a refused call names the task's model). ``inputs`` holds the
sanitised Tier-1 field values and, for Tier-2 fields, only the name, tier and length: a Tier-2 value never reaches
the ledger, with or without consent (AC-SEC-6). Output text is kept only for tasks marked ``confidential: false``.

``LedgerStore`` is the seam; ``InMemoryLedger`` serves tests and fakes. ``check_subject`` runs first in every call:
a store that cannot write the subject's rows or read its spend refuses the call before anything is sent, never after
a paid attempt. The SQL store over the ``llm_calls`` table (T2.1) is ``bridge.llm.sql_ledger.SqlLedger``.
"""

from __future__ import annotations

from collections.abc import Mapping
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
    batch_id: str | None = None
    output: Mapping[str, Any] | None = None
    error: str | None = None


class LedgerStore(Protocol):
    async def check_subject(self, *, org_id: UUID | None, user_id: UUID | None) -> None:
        """Raise ``LLMConfigError`` unless this store may write the subject's rows and read its spend."""
        ...

    async def record(self, entry: LedgerEntry) -> None: ...

    async def tenant_spent_usd(self, *, org_id: UUID | None, user_id: UUID | None, since: datetime) -> Decimal:
        """Spend of one billing subject since ``since``: the organisation's rows when ``org_id`` is given, else the
        user's own rows (those without an organisation)."""
        ...

    async def global_spent_usd(self, *, since: datetime) -> Decimal: ...


class InMemoryLedger:
    """``LedgerStore`` in memory (unit tests, ``FakeLLMClient``)."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    async def check_subject(self, *, org_id: UUID | None, user_id: UUID | None) -> None:
        return None  # memory holds any subject

    async def record(self, entry: LedgerEntry) -> None:
        self.entries.append(entry)

    async def tenant_spent_usd(self, *, org_id: UUID | None, user_id: UUID | None, since: datetime) -> Decimal:
        if org_id is not None:
            rows = (e for e in self.entries if e.org_id == org_id)
        else:
            rows = (e for e in self.entries if e.org_id is None and e.user_id == user_id)
        return sum((e.cost_usd for e in rows if e.created_at >= since), Decimal(0))

    async def global_spent_usd(self, *, since: datetime) -> Decimal:
        return sum((e.cost_usd for e in self.entries if e.created_at >= since), Decimal(0))
