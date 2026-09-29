"""Pre-call budget checks (REQ-LLM-01; ADR-005 decision 5; docs/spec/09 Cost controls).

Before every attempt: ``LLM_KILL_SWITCH=1`` refuses; a free provider slot's daily request cap
(``LLM_FREE_<N>_DAILY_REQUESTS``, UTC day, D-37) refuses once today's attempts on the slot's model reach it
(``LLMRequestCapReached``); the global daily cap (``LLM_GLOBAL_DAILY_CAP_USD``, UTC day) refuses when today's spend
plus the attempt's upper estimate would pass it; the prototype's lifetime total (``LLM_PROTOTYPE_TOTAL_CAP_USD``,
D-37: every row of the ledger, and only Anthropic costs money) does the same; the billing subject's monthly cap
(``plans.limits.llm_monthly_cap_usd``, UTC calendar month) does the same (the 100% hard cap: callers such as scouts
catch ``LLMBudgetExceeded`` and degrade). The spend caps apply to attempts that cost something: a free slot's
attempt (estimate 0) spends nothing, so a cap overrun by calls in flight never blocks it. After a call the subject's
spend is compared with the soft-cap ratio of ``ai/models.yaml`` (80%): ``BudgetStatus.soft_cap_reached`` is set, and
``BudgetListener`` hears the crossing once (the soft-cap email is Phase 4). Concurrent calls may each pass the
check, so a cap (the request cap included) can be overrun by at most the calls in flight.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.billing import entitlements
from bridge.config import Settings
from bridge.llm.errors import LLMBudgetExceeded, LLMKillSwitch, LLMRequestCapReached
from bridge.llm.ledger import LedgerStore
from bridge.llm.registry import ModelSpec
from bridge.llm.types import BudgetStatus, CallContext
from bridge.logging import get_logger

CAP_LIMIT_KEY = "llm_monthly_cap_usd"
LEDGER_START = datetime(1970, 1, 1, tzinfo=UTC)  # the prototype total counts every row the ledger holds
log = get_logger("bridge.llm")


def cap_from_limits(limits: Mapping[str, Any]) -> Decimal | None:
    """The monthly cap from plan limits: ``None`` is unlimited; a plan without the key gets 0 (fail closed, as
    ``Entitlements.limit`` treats unknown keys)."""
    if CAP_LIMIT_KEY not in limits:
        return Decimal(0)
    value = limits[CAP_LIMIT_KEY]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise TypeError(f"{CAP_LIMIT_KEY} is not a number")
    return Decimal(str(value))


class CapProvider(Protocol):
    async def monthly_cap_usd(self, *, org_id: UUID | None, user_id: UUID | None) -> Decimal | None: ...


class EntitlementsCaps:
    """Caps from the subject's live plan (``bridge.billing.entitlements.for_subject``; the side's free plan when
    there is none). ``db`` is the caller's session; its tenant scope applies."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self._db = db
        self._settings = settings

    async def monthly_cap_usd(self, *, org_id: UUID | None, user_id: UUID | None) -> Decimal | None:
        if org_id is not None:
            ent = await entitlements.for_subject(self._db, self._settings, org_id=org_id)
        else:
            ent = await entitlements.for_subject(self._db, self._settings, user_id=user_id)
        return cap_from_limits(ent.limits)


@dataclass
class StaticCaps:
    """Fixed caps for tests and fakes: ``caps`` by org or user id, else ``default`` (``None`` = unlimited)."""

    default: Decimal | None = None
    caps: dict[UUID, Decimal | None] = field(default_factory=dict)

    async def monthly_cap_usd(self, *, org_id: UUID | None, user_id: UUID | None) -> Decimal | None:
        subject = org_id if org_id is not None else user_id
        return self.caps.get(subject, self.default) if subject is not None else self.default


@dataclass(frozen=True, slots=True)
class SoftCapEvent:
    org_id: UUID | None
    user_id: UUID | None
    spent_usd: Decimal
    cap_usd: Decimal


class BudgetListener(Protocol):
    async def soft_cap_reached(self, event: SoftCapEvent) -> None: ...


class RecordingBudgetListener:
    """Logs and keeps soft-cap crossings (until the Phase 4 email)."""

    def __init__(self) -> None:
        self.events: list[SoftCapEvent] = []

    async def soft_cap_reached(self, event: SoftCapEvent) -> None:
        self.events.append(event)
        log.info("llm.soft_cap_reached", spent_usd=str(event.spent_usd), cap_usd=str(event.cap_usd))


@dataclass(frozen=True, slots=True)
class Snapshot:
    """The subject's spend and cap when an attempt was allowed (None when there is no subject or no cap)."""

    spent_usd: Decimal | None
    cap_usd: Decimal | None


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class BudgetGuard:
    def __init__(
        self,
        *,
        settings: Settings,
        ledger: LedgerStore,
        caps: CapProvider,
        soft_cap_ratio: Decimal,
        listener: BudgetListener | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._ledger = ledger
        self._caps = caps
        self._ratio = soft_cap_ratio
        self._listener = listener
        self._now = now or (lambda: clock.utcnow())

    def now(self) -> datetime:
        return self._now()

    def check_kill_switch(self) -> None:
        if self._settings.llm_kill_switch:
            raise LLMKillSwitch()

    async def check(self, ctx: CallContext, estimate_usd: Decimal, *, model: ModelSpec | None = None) -> Snapshot:
        """Raise ``LLMKillSwitch``, ``LLMRequestCapReached`` or ``LLMBudgetExceeded`` when the attempt on ``model``
        may not run."""
        self.check_kill_switch()
        now = self._now()
        if model is not None and model.daily_requests is not None:
            sent = await self._ledger.calls_since(model=model.id, since=day_start(now))
            if sent >= model.daily_requests:
                raise LLMRequestCapReached(model.id)
        paid = estimate_usd > 0
        if paid:
            global_cap = self._settings.llm_global_daily_cap_usd
            global_spent = await self._ledger.global_spent_usd(since=day_start(now))
            if global_spent + estimate_usd > global_cap:
                raise LLMBudgetExceeded("global", spent_usd=global_spent, cap_usd=global_cap)
            total_cap = self._settings.llm_prototype_total_cap_usd
            total_spent = await self._ledger.global_spent_usd(since=LEDGER_START)
            if total_spent + estimate_usd > total_cap:
                raise LLMBudgetExceeded("total", spent_usd=total_spent, cap_usd=total_cap)
        snap = await self.snapshot(ctx)
        spent, cap = snap.spent_usd, snap.cap_usd
        if paid and spent is not None and cap is not None and spent + estimate_usd > cap:
            raise LLMBudgetExceeded("tenant", spent_usd=spent, cap_usd=cap)
        return snap

    async def snapshot(self, ctx: CallContext) -> Snapshot:
        """The subject's spend this month and its cap, without checking anything."""
        if ctx.org_id is None and ctx.user_id is None:
            return Snapshot(None, None)
        cap = await self._caps.monthly_cap_usd(org_id=ctx.org_id, user_id=ctx.user_id)
        if cap is None:
            return Snapshot(None, None)
        since = month_start(self._now())
        return Snapshot(await self._ledger.tenant_spent_usd(org_id=ctx.org_id, user_id=ctx.user_id, since=since), cap)

    async def after(self, ctx: CallContext, snapshot: Snapshot, cost_usd: Decimal) -> BudgetStatus:
        """The subject's month after an attempt that cost ``cost_usd``; tells the listener about a soft-cap crossing."""
        if snapshot.spent_usd is None or snapshot.cap_usd is None:
            return BudgetStatus()
        spent = snapshot.spent_usd + cost_usd
        threshold = snapshot.cap_usd * self._ratio
        reached = spent >= threshold
        if reached and snapshot.spent_usd < threshold and self._listener is not None:
            await self._listener.soft_cap_reached(SoftCapEvent(ctx.org_id, ctx.user_id, spent, snapshot.cap_usd))
        return BudgetStatus(spent_usd=spent, cap_usd=snapshot.cap_usd, soft_cap_reached=reached)
