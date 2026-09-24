"""REQ-BIL-01: plans.yaml placeholders and the 402 entitlement check (AC-SUB-1 itself closes in Phase 2)."""

from __future__ import annotations

import pytest

from bridge.billing import plans
from bridge.billing.entitlements import Entitlements, PlanLimitExceeded, check_count, require_feature
from bridge.config import get_settings
from bridge.models.enums import PlanSide

SETTINGS = get_settings()
CATALOG = plans.load(SETTINGS.plans_file)


def test_catalog_matches_the_spec_placeholders() -> None:
    free = CATALOG.plans["dev_free"]
    assert free.limits["active_proposals"] == 3
    assert free.limits["tags_per_proposal"] == 5
    assert free.limits["followed_niches"] == 1
    pro = CATALOG.plans["dev_pro_monthly"]
    assert pro.price_kes_minor == 49_900
    assert pro.limits["active_proposals"] is None
    claimed = CATALOG.plans["org_claimed"]
    assert claimed.limits["full_unlocks_per_month"] == 5
    assert claimed.limits["seats"] == 2
    assert CATALOG.plans["org_starter"].price_kes_minor == 1_500_000
    assert CATALOG.plans["org_growth"].limits["full_unlocks_per_month"] is None
    for spec in CATALOG.plans.values():
        assert "llm_monthly_cap_usd" in spec.limits
    assert CATALOG.default_for(PlanSide.DEVELOPER).code == "dev_free"
    assert CATALOG.default_for(PlanSide.ORG).code == "org_claimed"


def test_no_per_tag_or_per_submission_fee_exists() -> None:
    for spec in CATALOG.plans.values():
        assert not any("fee" in key for key in spec.limits)


def ent(code: str) -> Entitlements:
    spec = CATALOG.plans[code]
    return Entitlements(spec.code, spec.side, dict(spec.limits))


def test_under_the_cap_passes_and_at_the_cap_returns_402_with_upgrade_path() -> None:
    free = ent("dev_free")
    check_count(SETTINGS, free, "active_proposals", used=2)
    with pytest.raises(PlanLimitExceeded) as info:
        check_count(SETTINGS, free, "active_proposals", used=3)
    assert info.value.status_code == 402
    detail = info.value.detail
    assert isinstance(detail, dict)
    assert detail["code"] == "plan_limit"
    assert detail["limit"] == 3
    assert detail["upgrade"] == {"plan": "dev_pro_monthly", "url": "/billing/upgrade?plan=dev_pro_monthly"}


def test_unlimited_never_blocks() -> None:
    check_count(SETTINGS, ent("dev_pro_monthly"), "active_proposals", used=10_000)


def test_unknown_limits_fail_closed() -> None:
    with pytest.raises(PlanLimitExceeded):
        check_count(SETTINGS, ent("dev_free"), "no_such_limit", used=0)


def test_features_need_an_explicit_true() -> None:
    require_feature(SETTINGS, ent("dev_pro_monthly"), "viewer_analytics")
    with pytest.raises(PlanLimitExceeded) as info:
        require_feature(SETTINGS, ent("dev_pro_monthly"), "whatsapp_reminders")  # "release-2" is not true
    assert info.value.status_code == 402
    with pytest.raises(PlanLimitExceeded):
        require_feature(SETTINGS, ent("org_claimed"), "csv_export")


def test_duplicate_plan_codes_are_rejected() -> None:
    raw = {
        "upgrade_paths": {"developer": "a", "org": "b"},
        "plans": [
            {
                "code": "a",
                "side": "developer",
                "name": "A",
                "price_kes_minor": 0,
                "interval": "none",
                "limits": {},
                "default": True,
            },
            {
                "code": "a",
                "side": "org",
                "name": "B",
                "price_kes_minor": 0,
                "interval": "none",
                "limits": {},
                "default": True,
            },
        ],
    }
    with pytest.raises(ValueError, match="duplicate"):
        plans.parse(raw)
