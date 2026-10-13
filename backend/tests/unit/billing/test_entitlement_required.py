"""REQ-ENG-17 with REQ-BIL-01 (P28 track D): a read the plan does not include is 403 ``entitlement_required`` naming
the plan that has it: the first up the subscriber's upgrade ladder with the feature, else the side's cheapest
(self-serve first); a plan with the feature passes."""

from __future__ import annotations

import pytest

from bridge.billing import plans
from bridge.billing.entitlements import EntitlementRequired, Entitlements, require_entitlement
from bridge.config import get_settings

SETTINGS = get_settings()
CATALOG = plans.load(SETTINGS.plans_file)


def ent(code: str) -> Entitlements:
    spec = CATALOG.plans[code]
    return Entitlements(spec.code, spec.side, dict(spec.limits))


@pytest.mark.parametrize("code", ["org_claimed", "org_starter", "org_social_impact"])
def test_csv_export_without_the_entitlement_names_growth(code: str) -> None:
    with pytest.raises(EntitlementRequired) as refused:
        require_entitlement(SETTINGS, ent(code), "csv_export")
    assert refused.value.status_code == 403
    assert refused.value.detail == {
        "code": "entitlement_required",
        "message": "This needs the Growth plan.",
        "limit_key": "csv_export",
        "plan": code,
        "upgrade": {"plan": "org_growth", "name": "Growth", "url": "/billing/upgrade?plan=org_growth"},
    }


@pytest.mark.parametrize("code", ["org_growth", "org_enterprise"])
def test_a_plan_with_csv_export_passes(code: str) -> None:
    require_entitlement(SETTINGS, ent(code), "csv_export")


def test_a_feature_no_plan_of_the_side_has_names_none() -> None:
    with pytest.raises(EntitlementRequired) as refused:
        require_entitlement(SETTINGS, ent("org_claimed"), "no_such_feature")
    assert refused.value.detail["upgrade"] is None  # type: ignore[index]
    assert refused.value.detail["message"] == "This is not part of your plan."  # type: ignore[index]


def test_the_ladder_comes_first_then_the_cheapest_self_serve_plan() -> None:
    assert CATALOG.first_with("org_claimed", "csv_export") is CATALOG.plans["org_growth"]
    assert CATALOG.first_with("org_growth", "csv_export") is CATALOG.plans["org_enterprise"]  # the next one up
    assert CATALOG.first_with("org_social_impact", "csv_export") is CATALOG.plans["org_growth"]  # off the ladder
    assert CATALOG.first_with("org_claimed", "pipeline_analytics") is None  # "coming-soon" is not true
