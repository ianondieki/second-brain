"""REQ-BIL-08 (P14): which plans of ``config/plans.yaml`` a checkout sells, and the sample-price label (D-44).

A checkout sells a paid, self-serve plan only: never a side's default (free) plan, a free plan (Student), custom
pricing (Enterprise / Government) or a plan that needs a person to approve it (Social Impact). Until the human sets
the G3 prices, ``status`` is a placeholder and the plans are labelled "Sample prices, not final".
"""

from __future__ import annotations

from typing import Any

import pytest

from bridge.billing import plans
from bridge.billing.checkout import new_provider_ref
from bridge.config import get_settings


def test_the_catalogue_sells_pro_starter_and_growth_only() -> None:
    catalog = plans.load(get_settings().plans_file)
    sold = sorted(code for code, spec in catalog.plans.items() if spec.purchasable)
    assert sold == ["dev_pro_monthly", "dev_pro_yearly", "org_growth", "org_starter"]


def _plan(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "code": "paid",
        "side": "developer",
        "name": "Paid",
        "price_kes_minor": 100,
        "interval": "month",
        "limits": {},
    }
    return raw | overrides


@pytest.mark.parametrize(
    "overrides",
    [
        {"default": True},
        {"price_kes_minor": 0},
        {"interval": "none"},
        {"custom_pricing": True},
        {"requires_admin_approval": True},
        {"eligibility": "verified Kenyan university or TVET email"},
        {"discount_of": ["paid"]},
    ],
)
def test_a_plan_a_person_must_decide_on_is_never_sold(overrides: dict[str, Any]) -> None:
    free = {"code": "free", "side": "developer", "name": "Free", "price_kes_minor": 0, "interval": "none"}
    org_free = free | {"code": "org_free", "side": "org"}
    defaults = [free | {"limits": {}, "default": True}, org_free | {"limits": {}, "default": True}]
    if overrides.get("default"):  # the side's default plan itself
        catalog = plans.parse({"plans": [_plan(**overrides), org_free | {"limits": {}, "default": True}]})
    else:
        catalog = plans.parse({"plans": [_plan(**overrides), *defaults]})
    assert catalog.plans["paid"].purchasable is False


def test_a_paid_self_serve_plan_is_sold() -> None:
    free = {"price_kes_minor": 0, "interval": "none", "limits": {}, "default": True}
    catalog = plans.parse(
        {
            "plans": [
                _plan(),
                {"code": "f1", "side": "developer", "name": "F", **free},
                {"code": "f2", "side": "org", "name": "F", **free},
            ]
        }
    )
    assert catalog.plans["paid"].purchasable is True


def test_prices_are_samples_until_the_status_is_final() -> None:
    assert plans.load(get_settings().plans_file).status == "placeholder-until-G3"
    assert plans.load(get_settings().plans_file).sample_prices is True
    assert plans.Catalog({}, status="final").sample_prices is False
    assert plans.Catalog({}).sample_prices is True  # no status: a sample (fail safe)


def test_provider_references_are_platform_generated_and_unguessable() -> None:
    refs = {new_provider_ref() for _ in range(200)}
    assert len(refs) == 200
    for ref in refs:
        assert ref.startswith("chk_")
        assert len(ref) == 36
        assert ref.replace("-", "").replace("_", "").isalnum()
