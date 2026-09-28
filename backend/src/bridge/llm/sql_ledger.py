"""``SqlLedger``: the ``llm_calls`` ledger in PostgreSQL (REQ-LLM-01; T2.1 schema v2; AC-SEC-6; ADR-005 decision 5).

It runs as ``bridge_app`` under Row-Level Security, as the tenant the caller's session is bound to (``bind_tenant``;
read at every operation, so binding after the service was built still counts). The insert policy lets a row name only
that user and only an organisation that user is an active member of; the select policy lets members sum their
organisation's rows and users their own. The platform-wide daily total comes from ``app_llm_spend_usd()`` (a SECURITY
DEFINER aggregate: no row becomes visible). ``inputs`` is written but never read back: bridge_app holds no SELECT on
it; staff admin reads it through ``app_llm_call_inputs()``.

Every operation runs in its own short transaction from ``factory`` (a second pooled connection), never in the
caller's. A row is committed at once, so it survives the caller's rollback (a blocked call raises and the request
rolls back, but its row stays; a paid attempt is never lost with the request's work), and a caller inside ``as_role``
or a failed transaction still records. ``check_subject`` refuses a subject the bound tenant could not write or whose
spend it could not read, before anything is sent: otherwise RLS would refuse the row after the paid call, or sum no
rows and let the cap pass (fail closed).

The table's CHECKs (``cost_usd`` between 0 and 100 USD, token and latency columns zero or more) are met by clamping,
never by refusing: the row is written after the attempt was paid for, and a refused insert would lose it. A clamp is
logged (``llm.ledger_clamped``, error level) naming the columns. A clamped row still counts 100 USD towards the caps,
so the subject and the platform stop sooner, never later (fail closed); the pre-call caps keep real attempts far
below the bound.

Stored as the table defines it: ``purpose`` only for consent-covered tasks (NULL for Tier-1-only ones). The entry's
``attempt``, ``batch_id``, ``error`` and ``output`` have no column in ``llm_calls``: the attempt reaches the
``llm.call`` log, errors the exception and the dead-letter queue, and non-confidential outputs are not kept (no task
is non-confidential today).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.db import bind_tenant, tenant_of
from bridge.llm.errors import LLMConfigError
from bridge.llm.ledger import LedgerEntry
from bridge.llm.models import LlmCall
from bridge.llm.registry import Purpose
from bridge.logging import get_logger

STOP_REASON_CHARS = 40  # llm_calls.stop_reason; provider stop reasons are shorter, a longer one is cut, not lost
MAX_ROW_COST_USD = Decimal(100)  # the llm_calls CHECK on cost_usd (a schema bound, not a spending cap)
COUNT_COLUMNS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "latency_ms")
log = get_logger("bridge.llm")


def row_values(entry: LedgerEntry) -> dict[str, Any]:
    """The ``llm_calls`` row of ``entry``, clamped into the table's CHECKs (see the module docstring)."""
    values: dict[str, Any] = {
        "id": entry.id,
        "created_at": entry.created_at,
        "org_id": entry.org_id,
        "user_id": entry.user_id,
        "task": entry.task,
        "purpose": None if entry.purpose == Purpose.TIER1_ONLY.value else entry.purpose,
        "model": entry.model,
        "input_tokens": entry.input_tokens,
        "output_tokens": entry.output_tokens,
        "cache_read_tokens": entry.cache_read_tokens,
        "cache_write_tokens": entry.cache_creation_tokens,
        "cost_usd": min(max(entry.cost_usd, Decimal(0)), MAX_ROW_COST_USD),
        "latency_ms": entry.latency_ms,
        "status": entry.status.value,
        "stop_reason": entry.stop_reason[:STOP_REASON_CHARS] if entry.stop_reason is not None else None,
        "trace_id": entry.trace_id,
        "inputs": dict(entry.inputs),
    }
    clamped = ["cost_usd"] if values["cost_usd"] != entry.cost_usd else []
    for column in COUNT_COLUMNS:
        if values[column] < 0:
            values[column] = 0
            clamped.append(column)
    if clamped:
        log.error("llm.ledger_clamped", columns=clamped, task=entry.task, trace_id=entry.trace_id)
    return values


class SqlLedger:
    """``LedgerStore`` over ``llm_calls``. ``caller`` is the caller's session: only its tenant binding is read."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], *, caller: AsyncSession) -> None:
        self._factory = factory
        self._caller = caller
        self._members: set[tuple[UUID, UUID]] = set()  # (user, organisation) memberships already confirmed

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        user_id, org_id = tenant_of(self._caller)
        async with self._factory() as db:
            await bind_tenant(db, user_id=user_id, org_id=org_id)
            yield db

    async def check_subject(self, *, org_id: UUID | None, user_id: UUID | None) -> None:
        bound_user, bound_org = tenant_of(self._caller)
        if user_id is not None and user_id != bound_user:
            raise LLMConfigError("the call's user is not the user its database session is bound to")
        if org_id is None:
            return
        if bound_org is not None and bound_org != org_id:
            raise LLMConfigError("the call's organisation is not the one its database session is bound to")
        if bound_user is None or not await self._is_member(bound_user, org_id):
            raise LLMConfigError("the call's organisation has no active member bound to its database session")

    async def _is_member(self, user_id: UUID, org_id: UUID) -> bool:
        if (user_id, org_id) in self._members:
            return True
        async with self._session() as db:
            member = bool((await db.execute(select(func.app_is_member(org_id)))).scalar_one())
        if member:
            self._members.add((user_id, org_id))
        return member

    async def record(self, entry: LedgerEntry) -> None:
        values = row_values(entry)
        async with self._session() as db:
            # No RETURNING: a system row (no user, no organisation) is not readable by bridge_app.
            await db.execute(insert(LlmCall).values(**values))
            await db.commit()

    async def tenant_spent_usd(self, *, org_id: UUID | None, user_id: UUID | None, since: datetime) -> Decimal:
        await self.check_subject(org_id=org_id, user_id=user_id)
        if org_id is not None:
            subject = LlmCall.org_id == org_id
        elif user_id is not None:
            subject = LlmCall.org_id.is_(None) & (LlmCall.user_id == user_id)
        else:
            raise LLMConfigError("a platform call has no tenant spend (the global cap applies)")
        stmt = select(func.coalesce(func.sum(LlmCall.cost_usd), 0)).where(subject, LlmCall.created_at >= since)
        async with self._session() as db:
            return Decimal((await db.execute(stmt)).scalar_one())

    async def global_spent_usd(self, *, since: datetime) -> Decimal:
        async with self._session() as db:
            return Decimal((await db.execute(select(func.app_llm_spend_usd(since)))).scalar_one())
