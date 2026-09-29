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
rows and let the cap pass (fail closed). It also refuses a call with no subject from a session bound to a tenant: that
is a platform job's call (an unbound session), and its row would count towards no plan cap.

The table's CHECKs (``cost_usd`` between 0 and 100 USD, token and latency columns zero or more) are met by clamping,
never by refusing: the row is written after the attempt was paid for, and a refused insert would lose it. A clamp is
logged (``llm.ledger_clamped``, error level) naming the columns. A clamped row still counts 100 USD towards the caps,
so the subject and the platform stop sooner, never later (fail closed); the pre-call caps keep real attempts far
below the bound.

Message Batches (revision 0002): ``reserve`` inserts an accepted batch's ``batch_reserved`` rows in one transaction
(the database sets a reservation's ``created_at``). A batch is the tenant's of its earliest reservation:
``batch_owned`` asks ``app_llm_batch_owned()`` (a SECURITY DEFINER: bridge_app cannot read other tenants' rows or
system rows) and, for a tenant's handle, that a reservation naming exactly the handle's organisation and user exists,
so the handle's subject is the one its settlements are written for. ``settle`` writes an item's final row through
``app_llm_settle_batch_item()``, which writes it with the batch tenant's organisation and user for that tenant or the
platform job (nothing bound), refuses anybody else (``LLMBatchNotOwned``), and returns false when an earlier poll
settled the item (``ON CONFLICT DO NOTHING`` on the partial unique index). Both sums follow the ``llm_spend`` rule:
the tenant sum reads the view (``security_invoker``, so the caller's RLS applies as on ``llm_calls``) and
``app_llm_spend_usd()`` sums it as the owner.

Stored as the table defines it: ``purpose`` only for consent-covered tasks (NULL for Tier-1-only ones). The entry's
``attempt``, ``error`` and ``output`` have no column in ``llm_calls``: the attempt reaches the ``llm.call`` log, errors
the exception and the dead-letter queue, and non-confidential outputs are not kept (no task is non-confidential today).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Numeric, Uuid, bindparam, column, func, insert, select, table, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.db import bind_tenant, tenant_of
from bridge.llm.errors import LLMBatchNotOwned, LLMConfigError
from bridge.llm.ledger import CallStatus, LedgerEntry, check_plain, check_reservation, check_settlement
from bridge.llm.models import LlmCall
from bridge.llm.registry import Purpose
from bridge.logging import get_logger

STOP_REASON_CHARS = 40  # llm_calls.stop_reason; provider stop reasons are shorter, a longer one is cut, not lost
MAX_ROW_COST_USD = Decimal(100)  # the llm_calls CHECK on cost_usd (a schema bound, not a spending cap)
COUNT_COLUMNS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "latency_ms")
log = get_logger("bridge.llm")
INSUFFICIENT_PRIVILEGE = "42501"  # app_llm_settle_batch_item: not the caller's batch, or no such batch
# The row's columns app_llm_settle_batch_item takes, in its order; it writes org_id, user_id and created_at itself.
SETTLE_COLUMNS = (
    "batch_id",
    "custom_id",
    "id",
    "task",
    "purpose",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "cost_usd",
    "latency_ms",
    "status",
    "stop_reason",
    "trace_id",
    "inputs",
)
SETTLE = text(
    "SELECT app_llm_settle_batch_item(" + ", ".join(f"p_{name} => :{name}" for name in SETTLE_COLUMNS) + ")"
).bindparams(bindparam("inputs", type_=JSONB), bindparam("cost_usd", type_=Numeric(12, 6)))
# The spend rule (revision 0002): every llm_calls row except a batch reservation whose item has settled.
LLM_SPEND = table(
    "llm_spend",
    column("org_id", Uuid),
    column("user_id", Uuid),
    column("cost_usd", Numeric(12, 6)),
    column("created_at", DateTime(timezone=True)),
)


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
        "batch_id": entry.batch_id,
        "custom_id": entry.custom_id,
        "inputs": dict(entry.inputs),
    }
    clamped = ["cost_usd"] if values["cost_usd"] != entry.cost_usd else []
    for name in COUNT_COLUMNS:
        if values[name] < 0:
            values[name] = 0
            clamped.append(name)
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
        if org_id is None and user_id is None:
            if bound_user is not None or bound_org is not None:
                raise LLMConfigError(
                    "a call with no user and no organisation is a platform job's; this database session is bound to"
                    " a tenant"
                )
            return
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
        check_plain(entry)
        values = row_values(entry)
        async with self._session() as db:
            # No RETURNING: a system row (no user, no organisation) is not readable by bridge_app.
            await db.execute(insert(LlmCall).values(**values))
            await db.commit()

    async def reserve(self, entries: Sequence[LedgerEntry]) -> None:
        for entry in entries:
            check_reservation(entry)
        if not entries:
            return
        async with self._session() as db:
            conn = await db.connection()
            await conn.execute(insert(LlmCall), [row_values(e) for e in entries])  # one transaction: all or none
            await db.commit()

    async def settle(self, entry: LedgerEntry) -> bool:
        check_settlement(entry)
        values = row_values(entry)  # its org_id, user_id and created_at are the database's: see SETTLE
        params = {name: values[name] for name in SETTLE_COLUMNS}
        async with self._session() as db:
            try:
                settled = bool((await db.execute(SETTLE, params)).scalar_one())
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) == INSUFFICIENT_PRIVILEGE:
                    raise LLMBatchNotOwned(str(entry.batch_id)) from exc
                raise
            await db.commit()
        return settled

    async def batch_owned(self, batch_id: str, *, org_id: UUID | None, user_id: UUID | None) -> bool:
        async with self._session() as db:
            owned = bool((await db.execute(select(func.app_llm_batch_owned(batch_id)))).scalar_one())
            if not owned or (org_id is None and user_id is None):
                return owned  # a platform job's batch is owned only by a caller with nothing bound
            calls = LlmCall.__table__.c
            exact = select(calls.id).where(
                calls.batch_id == batch_id,
                calls.status == CallStatus.BATCH_RESERVED.value,
                calls.org_id.is_not_distinct_from(org_id),
                calls.user_id.is_not_distinct_from(user_id),
            )
            return bool((await db.execute(select(exact.exists()))).scalar_one())

    async def tenant_spent_usd(self, *, org_id: UUID | None, user_id: UUID | None, since: datetime) -> Decimal:
        await self.check_subject(org_id=org_id, user_id=user_id)
        spend = LLM_SPEND.c
        if org_id is not None:
            subject = spend.org_id == org_id
        elif user_id is not None:
            subject = spend.org_id.is_(None) & (spend.user_id == user_id)
        else:
            raise LLMConfigError("a platform call has no tenant spend (the global cap applies)")
        stmt = select(func.coalesce(func.sum(spend.cost_usd), 0)).where(subject, spend.created_at >= since)
        async with self._session() as db:
            return Decimal((await db.execute(stmt)).scalar_one())

    async def global_spent_usd(self, *, since: datetime) -> Decimal:
        async with self._session() as db:
            return Decimal((await db.execute(select(func.app_llm_spend_usd(since)))).scalar_one())
