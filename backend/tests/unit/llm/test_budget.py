"""REQ-LLM-01: the kill switch, the global daily cap, the per-tenant monthly cap from plans.limits and the 80% soft
cap signal (ADR-005 decision 5)."""

from __future__ import annotations

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
from bridge.llm.errors import LLMBudgetExceeded, LLMKillSwitch
from bridge.llm.ledger import CallStatus, InMemoryLedger, LedgerEntry
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
