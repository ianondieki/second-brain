"""REQ-LLM-01: the kill switch, the global daily cap, the per-tenant monthly cap from plans.limits and the 80% soft
cap signal (ADR-005 decision 5)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from bridge.billing import entitlements
from bridge.billing.entitlements import Entitlements
from bridge.llm import budget
from bridge.llm.budget import (
    BudgetGuard,
    EntitlementsCaps,
    RecordingBudgetListener,
    StaticCaps,
    cap_from_limits,
    day_start,
    month_start,
)
from bridge.llm.errors import LLMBlocked, LLMBudgetExceeded, LLMKillSwitch, LLMRequestCapReached
from bridge.llm.ledger import CallStatus, InMemoryLedger, LedgerEntry
from bridge.llm.registry import ZERO_PRICES, ModelSpec, Prices
from bridge.llm.types import BudgetStatus, CallContext
from bridge.models.enums import PlanSide
from tests.unit.llm.helpers import NOW, ORG, USER, settings

RATIO = Decimal("0.8")


def entry(cost: str, *, org: Any = None, user: Any = None, when: Any = NOW) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        created_at=when,
        org_id=org,
        user_id=user,
        task="t",
        purpose="tier1_only",
        model="m",
        status=CallStatus.OK,
        stop_reason="end_turn",
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=Decimal(cost),
        latency_ms=1,
        trace_id="tr",
        attempt=1,
        inputs={},
    )


def guard(ledger: InMemoryLedger, caps: StaticCaps | None = None, **overrides: Any) -> BudgetGuard:
    return BudgetGuard(
        settings=settings(**overrides),
        ledger=ledger,
        caps=caps or StaticCaps(),
        soft_cap_ratio=RATIO,
        listener=RecordingBudgetListener(),
        now=lambda: NOW,
    )


async def test_kill_switch_refuses_before_anything_else() -> None:
    with pytest.raises(LLMKillSwitch) as info:
        await guard(InMemoryLedger(), llm_kill_switch=True).check(CallContext(), Decimal(0))
    assert info.value.code == "llm_kill_switch"


async def test_global_daily_cap_counts_today_only() -> None:
    ledger = InMemoryLedger()
    ledger.entries += [entry("4.00", when=NOW - timedelta(days=1)), entry("0.90", user=USER)]
    g = guard(ledger, llm_global_daily_cap_usd=Decimal("1.00"))
    await g.check(CallContext(), Decimal("0.10"))  # 0.90 + 0.10 == cap: allowed
    with pytest.raises(LLMBudgetExceeded) as info:
        await g.check(CallContext(), Decimal("0.11"))
    assert info.value.scope == "global"
    assert info.value.spent_usd == Decimal("0.90")


async def test_zero_global_cap_refuses_any_spend() -> None:
    g = guard(InMemoryLedger(), llm_global_daily_cap_usd=Decimal(0))
    with pytest.raises(LLMBudgetExceeded):
        await g.check(CallContext(), Decimal("0.000001"))


async def test_tenant_cap_counts_this_month_and_this_subject() -> None:
    ledger = InMemoryLedger()
    ledger.entries += [
        entry("1.00", org=ORG, when=month_start(NOW) - timedelta(seconds=1)),  # last month
        entry("1.50", org=ORG, user=USER),
        entry("3.00", user=USER),  # the user's own spend, not the org's
    ]
    caps = StaticCaps(caps={ORG: Decimal("2.00")})
    g = guard(ledger, caps)
    snap = await g.check(CallContext(org_id=ORG, user_id=USER), Decimal("0.50"))
    assert (snap.spent_usd, snap.cap_usd) == (Decimal("1.50"), Decimal("2.00"))
    with pytest.raises(LLMBudgetExceeded) as info:
        await g.check(CallContext(org_id=ORG), Decimal("0.51"))
    assert info.value.scope == "tenant"


async def test_user_subject_uses_rows_without_an_org() -> None:
    ledger = InMemoryLedger()
    ledger.entries += [entry("0.40", user=USER), entry("5.00", org=ORG, user=USER)]
    g = guard(ledger, StaticCaps(default=Decimal("0.50")))
    snap = await g.check(CallContext(user_id=USER), Decimal("0.10"))
    assert snap.spent_usd == Decimal("0.40")


async def test_platform_calls_and_unlimited_plans_have_no_tenant_cap() -> None:
    ledger = InMemoryLedger()
    g = guard(ledger, StaticCaps(default=None))
    assert (await g.check(CallContext(), Decimal("1"))).cap_usd is None
    assert (await g.check(CallContext(org_id=ORG), Decimal("1"))).cap_usd is None
    assert await g.after(CallContext(), budget.Snapshot(None, None), Decimal("1")) == BudgetStatus()


async def test_soft_cap_crossing_is_signalled_once() -> None:
    ledger = InMemoryLedger()
    listener = RecordingBudgetListener()
    g = BudgetGuard(
        settings=settings(),
        ledger=ledger,
        caps=StaticCaps(default=Decimal("1.00")),
        soft_cap_ratio=RATIO,
        listener=listener,
        now=lambda: NOW,
    )
    ctx = CallContext(org_id=ORG)
    below = await g.after(ctx, budget.Snapshot(Decimal("0.50"), Decimal("1.00")), Decimal("0.10"))
    assert not below.soft_cap_reached
    crossed = await g.after(ctx, budget.Snapshot(Decimal("0.70"), Decimal("1.00")), Decimal("0.10"))
    assert crossed.soft_cap_reached
    assert crossed.spent_usd == Decimal("0.80")
    already = await g.after(ctx, budget.Snapshot(Decimal("0.85"), Decimal("1.00")), Decimal("0.01"))
    assert already.soft_cap_reached
    assert len(listener.events) == 1
    assert listener.events[0].org_id == ORG


async def test_soft_cap_without_a_listener_still_sets_the_flag() -> None:
    g = BudgetGuard(
        settings=settings(), ledger=InMemoryLedger(), caps=StaticCaps(), soft_cap_ratio=RATIO, now=lambda: NOW
    )
    status = await g.after(CallContext(user_id=USER), budget.Snapshot(Decimal("0"), Decimal("1")), Decimal("0.9"))
    assert status.soft_cap_reached
    assert g.now() == NOW


def test_windows_are_utc_month_and_day() -> None:
    assert month_start(NOW).isoformat() == "2026-09-01T00:00:00+00:00"
    assert day_start(NOW).isoformat() == "2026-09-27T00:00:00+00:00"


@pytest.mark.parametrize(
    ("limits", "expected"),
    [({}, Decimal(0)), ({"llm_monthly_cap_usd": None}, None), ({"llm_monthly_cap_usd": 0.5}, Decimal("0.5"))],
)
def test_cap_from_plan_limits(limits: dict[str, Any], expected: Decimal | None) -> None:
    assert cap_from_limits(limits) == expected


@pytest.mark.parametrize("bad", [True, [1], {"x": 1}])
def test_non_numeric_cap_is_a_type_error(bad: Any) -> None:
    with pytest.raises(TypeError):
        cap_from_limits({"llm_monthly_cap_usd": bad})


async def test_entitlements_caps_read_the_live_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real provider asks bridge.billing.entitlements for the org's or the user's plan."""
    calls: list[dict[str, Any]] = []

    async def fake_for_subject(db: Any, cfg: Any, **subject: Any) -> Entitlements:
        calls.append(subject)
        side = PlanSide.ORG if "org_id" in subject else PlanSide.DEVELOPER
        return Entitlements("p", side, {"llm_monthly_cap_usd": 10.0 if side is PlanSide.ORG else 0.5})

    monkeypatch.setattr(entitlements, "for_subject", fake_for_subject)
    caps = EntitlementsCaps(db=None, settings=settings())  # type: ignore[arg-type]
    assert await caps.monthly_cap_usd(org_id=ORG, user_id=USER) == Decimal("10.0")
    assert await caps.monthly_cap_usd(org_id=None, user_id=USER) == Decimal("0.5")
    assert calls == [{"org_id": ORG}, {"user_id": USER}]


async def test_the_real_plans_carry_a_cap_for_every_default_plan() -> None:
    from bridge.billing import plans

    catalog = plans.load(settings().plans_file)
    for side in PlanSide:
        assert cap_from_limits(catalog.default_for(side).limits) is not None


# ------------------------------------------------------------------------ D-37: free slot requests, prototype total


def sent(model: str, status: CallStatus = CallStatus.OK, *, when: Any = NOW, user: Any = USER) -> LedgerEntry:
    return replace(entry("0", user=user, when=when), model=model, status=status)


FREE = ModelSpec("free1:vendor/m", False, 8192, ZERO_PRICES, daily_requests=3)


async def test_a_free_slot_refuses_once_todays_attempts_reach_its_daily_cap() -> None:
    """Counted in the ledger: today's rows of the slot's model that reached the provider (not blocked ones)."""
    ledger = InMemoryLedger()
    ledger.entries += [
        sent(FREE.id, when=NOW - timedelta(days=1)),  # yesterday
        sent(FREE.id, CallStatus.BLOCKED_BUDGET),  # refused before sending
        sent(FREE.id, CallStatus.BLOCKED_TIER2),
        sent("free2:vendor/m"),  # another slot
        sent(FREE.id),
        sent(FREE.id, CallStatus.SCHEMA_ERROR, user=None),  # every attempt that was sent counts, any tenant
    ]
    g = guard(ledger, llm_global_daily_cap_usd=Decimal(0), llm_prototype_total_cap_usd=Decimal(0))
    assert await ledger.calls_since(model=FREE.id, since=day_start(NOW)) == 2
    await g.check(CallContext(user_id=USER), Decimal(0), model=FREE)  # 2 of 3: allowed, although both caps are 0
    ledger.entries.append(sent(FREE.id, CallStatus.PROVIDER_ERROR))
    with pytest.raises(LLMRequestCapReached) as info:
        await g.check(CallContext(user_id=USER), Decimal(0), model=FREE)
    assert info.value.code == "llm_request_cap"
    assert isinstance(info.value, LLMBlocked)
    # a model without a daily cap is never counted
    await g.check(CallContext(), Decimal(0), model=replace(FREE, daily_requests=None))


async def test_the_kill_switch_comes_before_the_request_cap() -> None:
    with pytest.raises(LLMKillSwitch):
        await guard(InMemoryLedger(), llm_kill_switch=True).check(CallContext(), Decimal(0), model=FREE)


async def test_the_prototype_total_counts_every_day_of_the_ledger() -> None:
    """D-37: USD 5 in total for the prototype, from the ledger's lifetime spend (every provider; only Anthropic
    costs money)."""
    ledger = InMemoryLedger()
    ledger.entries += [entry("3.00", user=USER, when=NOW - timedelta(days=40)), entry("1.95", org=ORG, user=USER)]
    g = guard(ledger, llm_global_daily_cap_usd=Decimal(100), llm_prototype_total_cap_usd=Decimal("5.00"))
    await g.check(CallContext(), Decimal("0.05"))  # 4.95 + 0.05 == total: allowed
    with pytest.raises(LLMBudgetExceeded) as info:
        await g.check(CallContext(), Decimal("0.06"))
    assert (info.value.scope, info.value.spent_usd, info.value.cap_usd) == ("total", Decimal("4.95"), Decimal("5.00"))


async def test_a_paid_model_meets_the_spend_caps_even_at_a_zero_estimate() -> None:
    """P7 review: whether an attempt spends is the model's (its prices), never the estimate's; a call without a model
    counts as paid (fail closed)."""
    ledger = InMemoryLedger()
    ledger.entries.append(entry("1.00", user=USER))
    g = guard(ledger, llm_global_daily_cap_usd=Decimal("0.50"))
    paid = ModelSpec("m", False, 1000, Prices(*(Decimal(v) for v in ("1", "5", "0.1", "1.25", "2"))))
    for model in (paid, None):
        with pytest.raises(LLMBudgetExceeded) as info:
            await g.check(CallContext(), Decimal(0), model=model)
        assert info.value.scope == "global"
    await g.check(CallContext(), Decimal(0), model=FREE)  # a zero-priced free slot spends nothing
    assert (paid.paid, FREE.paid) == (True, False)


async def test_without_a_total_only_the_daily_and_tenant_caps_apply() -> None:
    """Staging and production have no prototype total unless it is set: the lifetime sum is not even read."""
    ledger = InMemoryLedger()
    ledger.entries.append(entry("500", user=USER, when=NOW - timedelta(days=40)))
    g = guard(ledger, app_env="staging", llm_global_daily_cap_usd=Decimal(1), llm_prototype_total_cap_usd=None)
    await g.check(CallContext(), Decimal("0.50"))


async def test_the_daily_cap_is_checked_before_the_total() -> None:
    ledger = InMemoryLedger()
    ledger.entries.append(entry("0.99", user=USER))
    g = guard(ledger, llm_global_daily_cap_usd=Decimal("1.00"), llm_prototype_total_cap_usd=Decimal("0.50"))
    with pytest.raises(LLMBudgetExceeded) as info:
        await g.check(CallContext(), Decimal("0.02"))
    assert info.value.scope == "global"


async def test_a_call_that_costs_nothing_passes_spend_caps_already_overrun() -> None:
    """A free slot's attempt spends nothing, so an overrun (calls in flight may pass a cap) never blocks it."""
    ledger = InMemoryLedger()
    ledger.entries += [entry("5.03", org=ORG, user=USER)]
    caps = StaticCaps(caps={ORG: Decimal("1.00")})
    g = guard(ledger, caps, llm_global_daily_cap_usd=Decimal("1.00"), llm_prototype_total_cap_usd=Decimal("5.00"))
    snap = await g.check(CallContext(org_id=ORG, user_id=USER), Decimal(0), model=FREE)
    assert (snap.spent_usd, snap.cap_usd) == (Decimal("5.03"), Decimal("1.00"))
    with pytest.raises(LLMBudgetExceeded) as info:
        await guard(ledger, llm_global_daily_cap_usd=Decimal("1.00")).check(CallContext(), Decimal("0.000001"))
    assert info.value.scope == "global"
    total = guard(ledger, llm_global_daily_cap_usd=Decimal(100), llm_prototype_total_cap_usd=Decimal("5.00"))
    with pytest.raises(LLMBudgetExceeded) as info:
        await total.check(CallContext(), Decimal("0.000001"))
    assert info.value.scope == "total"
