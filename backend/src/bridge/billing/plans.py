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
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Catalog:
    plans: dict[str, PlanSpec]
    upgrade_paths: dict[PlanSide, str]

    def default_for(self, side: PlanSide) -> PlanSpec:
        for plan in self.plans.values():
            if plan.side == side and plan.default:
                return plan
        raise LookupError(f"plans.yaml has no default plan for {side}")

    def upgrade_for(self, side: PlanSide) -> PlanSpec:
        return self.plans[self.upgrade_paths[side]]


_KNOWN = {"code", "side", "name", "price_kes_minor", "interval", "limits", "default"}


def parse(data: dict[str, Any]) -> Catalog:
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
            extra={k: v for k, v in raw.items() if k not in _KNOWN},
        )
        if spec.code in plans:
            raise ValueError(f"duplicate plan code {spec.code}")
        plans[spec.code] = spec
    paths = {PlanSide(side): str(code) for side, code in data["upgrade_paths"].items()}
    catalog = Catalog(plans, paths)
    for side in PlanSide:
        catalog.default_for(side)
        catalog.upgrade_for(side)
    return catalog


@lru_cache(maxsize=4)
def load(path: Path) -> Catalog:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
