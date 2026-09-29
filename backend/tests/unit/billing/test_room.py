"""REQ-BIL-02 (AC-PROP-2 helper): ``check_room`` refuses a batch that would pass a cap, whole, with the 402 body of
``check_count``; a batch that fits, or an unlimited cap, passes."""

from __future__ import annotations

import pytest

from bridge.billing import plans
from bridge.billing.entitlements import Entitlements, PlanLimitExceeded, check_count, check_room
from bridge.config import get_settings

SETTINGS = get_settings()
CATALOG = plans.load(SETTINGS.plans_file)


def ent(code: str) -> Entitlements:
    spec = CATALOG.plans[code]
    return Entitlements(spec.code, spec.side, dict(spec.limits))


def test_a_batch_that_fits_passes() -> None:
    free = ent("dev_free")  # tags_per_proposal: 5
    check_room(SETTINGS, free, "tags_per_proposal", used=0, adding=5)
    check_room(SETTINGS, free, "tags_per_proposal", used=4, adding=1)


@pytest.mark.parametrize(("used", "adding"), [(5, 1), (4, 2), (0, 6), (3, 3)])
def test_a_batch_past_the_cap_is_refused_whole(used: int, adding: int) -> None:
    with pytest.raises(PlanLimitExceeded) as info:
        check_room(SETTINGS, ent("dev_free"), "tags_per_proposal", used=used, adding=adding)
    assert info.value.status_code == 402
    assert info.value.detail == {
        "code": "plan_limit",
        "message": "This needs a higher plan.",
        "limit_key": "tags_per_proposal",
        "limit": 5,
        "used": used,
        "plan": "dev_free",
        "upgrade": {"plan": "dev_pro_monthly", "url": "/billing/upgrade?plan=dev_pro_monthly"},
    }


def test_pro_allows_twenty_and_the_top_plan_offers_no_upgrade() -> None:
    pro = ent("dev_pro_monthly")
    check_room(SETTINGS, pro, "tags_per_proposal", used=15, adding=5)
    with pytest.raises(PlanLimitExceeded) as info:
        check_room(SETTINGS, pro, "tags_per_proposal", used=20, adding=1)
    assert isinstance(info.value.detail, dict)
    assert info.value.detail["upgrade"] is None


def test_unlimited_caps_never_block_and_unknown_keys_fail_closed() -> None:
    check_room(SETTINGS, ent("dev_pro_monthly"), "active_proposals", used=10_000, adding=50)
    with pytest.raises(PlanLimitExceeded):
        check_room(SETTINGS, ent("dev_free"), "no_such_limit", used=0, adding=1)


def test_check_count_is_one_more() -> None:
    check_count(SETTINGS, ent("dev_free"), "tags_per_proposal", used=4)
    with pytest.raises(PlanLimitExceeded):
        check_count(SETTINGS, ent("dev_free"), "tags_per_proposal", used=5)


def test_adding_nothing_is_a_bug() -> None:
    with pytest.raises(ValueError, match="adding"):
        check_room(SETTINGS, ent("dev_free"), "tags_per_proposal", used=0, adding=0)
