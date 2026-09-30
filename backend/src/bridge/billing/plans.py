"""The plan catalogue from ``backend/config/plans.yaml`` (REQ-BIL-01). Placeholders until G3; code reads limits
from here and never hard-codes them."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from bridge.models.enums import BillingInterval, PlanSide


@dataclass(frozen=True, slots=True)
class PlanSpec:
    code: str
    side: PlanSide
    name: str
    price_kes_minor: int
    interval: BillingInterval
    limits: dict[str, Any]
    default: bool = False
    upgrade_to: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def purchasable(self) -> bool:
        """Whether a checkout may buy it (P14): a paid plan sold self-serve. Never the side's default (free) plan, a
        free plan (Student), custom pricing (Enterprise / Government) or a plan that needs admin approval (Social
        Impact)."""
        return (
            not self.default
            and self.price_kes_minor > 0
            and self.interval is not BillingInterval.NONE
            and not any(self.extra.get(key) for key in _NOT_SELF_SERVE)
        )


# Plans a checkout never sells, whatever their price: a person decides (an invoice, an approval, eligibility).
_NOT_SELF_SERVE = ("custom_pricing", "requires_admin_approval", "eligibility", "discount_of")


@dataclass(frozen=True, slots=True)
class Catalog:
    plans: dict[str, PlanSpec]
    # plans.yaml `status`: "placeholder-until-G3" until the human sets the G3 prices (D-44: shown as sample prices).
    status: str = ""

    @property
    def sample_prices(self) -> bool:
        """Whether the prices are placeholders (D-44): anything but ``final`` is."""
        return self.status != "final"

    def default_for(self, side: PlanSide) -> PlanSpec:
        for plan in self.plans.values():
            if plan.side == side and plan.default:
                return plan
        raise LookupError(f"plans.yaml has no default plan for {side}")

    def upgrade_for(self, code: str) -> PlanSpec | None:
        """The next plan up from ``code`` (what a 402 offers), or None at the top of the ladder."""
        target = self.plans[code].upgrade_to
        return self.plans[target] if target else None


_KNOWN = {"code", "side", "name", "price_kes_minor", "interval", "limits", "default", "upgrade_to"}


def parse(data: dict[str, Any]) -> Catalog:
    """Build and validate the catalogue: unique codes, exactly one default per side, upgrades to an existing plan of
    the same side and no upgrade loops."""
    plans: dict[str, PlanSpec] = {}
    for raw in data["plans"]:
        spec = PlanSpec(
            code=str(raw["code"]),
            side=PlanSide(raw["side"]),
            name=str(raw["name"]),
            price_kes_minor=int(raw["price_kes_minor"]),
            interval=BillingInterval(raw["interval"]),
            limits=dict(raw["limits"]),
            default=bool(raw.get("default", False)),
            upgrade_to=str(raw["upgrade_to"]) if raw.get("upgrade_to") else None,
            extra={k: v for k, v in raw.items() if k not in _KNOWN},
        )
        if spec.code in plans:
            raise ValueError(f"duplicate plan code {spec.code}")
        plans[spec.code] = spec
    for side in PlanSide:
        defaults = [p.code for p in plans.values() if p.side == side and p.default]
        if len(defaults) != 1:
            raise ValueError(f"plans.yaml needs exactly one default plan for {side}, found {defaults}")
    for spec in plans.values():
        seen = {spec.code}
        target = spec.upgrade_to
        while target:
            if target not in plans:
                raise ValueError(f"{spec.code} upgrades to unknown plan {target}")
            if plans[target].side != spec.side:
                raise ValueError(f"{spec.code} upgrades to {target} on the other side")
            if target in seen:
                raise ValueError(f"upgrade loop through {target}")
            seen.add(target)
            target = plans[target].upgrade_to
    return Catalog(plans, status=str(data.get("status") or ""))


@lru_cache(maxsize=4)
def load(path: Path) -> Catalog:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
