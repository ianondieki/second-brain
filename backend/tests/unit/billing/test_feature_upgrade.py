"""REQ-ENG-17 with REQ-BIL-01 (P28 track D): a feature the plan lacks is the paywall's 402 ``plan_limit``, whose
``upgrade`` names the plan that has the feature: the first up the subscriber's ladder with it, else the side's cheapest
(self-serve first), else null; a plan with the feature passes. The caps' 402 still offers the next plan up."""

from __future__ import annotations

from typing import Any, cast

import pytest

from bridge.billing import plans
from bridge.billing.entitlements import Entitlements, PlanLimitExceeded, check_count, require_feature
from bridge.config import get_settings

SETTINGS = get_settings()
CATALOG = plans.load(SETTINGS.plans_file)


def ent(code: str) -> Entitlements:
    spec = CATALOG.plans[code]
    return Entitlements(spec.code, spec.side, dict(spec.limits))


@pytest.mark.parametrize("code", ["org_claimed", "org_starter", "org_social_impact"])
def test_csv_export_without_the_feature_offers_growth(code: str) -> None:
    with pytest.raises(PlanLimitExceeded) as refused:
        require_feature(SETTINGS, ent(code), "csv_export")
    assert refused.value.status_code == 402
    assert cast(dict[str, Any], refused.value.detail) == {
        "code": "plan_limit",
        "message": "This needs a higher plan.",
        "limit_key": "csv_export",
        "limit": None,
        "used": None,
        "plan": code,
        "upgrade": {"plan": "org_growth", "url": "/billing/upgrade?plan=org_growth"},
    }


@pytest.mark.parametrize("code", ["org_growth", "org_enterprise"])
def test_a_plan_with_csv_export_passes(code: str) -> None:
    require_feature(SETTINGS, ent(code), "csv_export")


def test_a_feature_no_plan_of_the_side_has_offers_nothing() -> None:
    with pytest.raises(PlanLimitExceeded) as refused:
        require_feature(SETTINGS, ent("org_claimed"), "no_such_feature")
    detail = cast(dict[str, Any], refused.value.detail)
    assert detail["upgrade"] is None
    assert detail["message"] == "This is beyond your plan. Contact us to raise the limit."


def test_a_cap_still_offers_the_next_plan_up() -> None:
    with pytest.raises(PlanLimitExceeded) as refused:
        check_count(SETTINGS, ent("org_claimed"), "seats", used=2)
    assert cast(dict[str, Any], refused.value.detail)["upgrade"]["plan"] == "org_starter"


def test_the_ladder_comes_first_then_the_cheapest_self_serve_plan() -> None:
    assert CATALOG.first_with("org_claimed", "csv_export") is CATALOG.plans["org_growth"]
    assert CATALOG.first_with("org_growth", "csv_export") is CATALOG.plans["org_enterprise"]  # the next one up
    assert CATALOG.first_with("org_social_impact", "csv_export") is CATALOG.plans["org_growth"]  # off the ladder
    assert CATALOG.first_with("org_claimed", "pipeline_analytics") is None  # "coming-soon" is not true
