"""REQ-BIL-01: the 402 names the next plan up from the subject's own plan; the catalogue is validated."""

from __future__ import annotations

from typing import Any

import pytest

from bridge.billing import plans
from bridge.billing.entitlements import Entitlements, PlanLimitExceeded, check_count
from bridge.config import get_settings

SETTINGS = get_settings()
CATALOG = plans.load(SETTINGS.plans_file)


@pytest.mark.parametrize(
    ("code", "key", "upgrade"),
    [
        ("dev_free", "active_proposals", "dev_pro_monthly"),
        ("org_claimed", "seats", "org_starter"),
        ("org_starter", "seats", "org_growth"),
        ("org_growth", "scout_agents", "org_enterprise"),
        ("dev_pro_monthly", "tags_per_proposal", None),
    ],
)
def test_402_offers_the_next_plan_up(code: str, key: str, upgrade: str | None) -> None:
    spec = CATALOG.plans[code]
    ent = Entitlements(spec.code, spec.side, dict(spec.limits))
    cap = ent.limit(key)
    assert cap is not None
    with pytest.raises(PlanLimitExceeded) as info:
        check_count(SETTINGS, ent, key, used=cap)
    detail = info.value.detail
    assert isinstance(detail, dict)
    assert (detail["upgrade"]["plan"] if detail["upgrade"] else None) == upgrade


def _raw(**overrides: Any) -> dict[str, Any]:
    base = {
        "plans": [
            {
                "code": "a",
                "side": "developer",
                "name": "A",
                "price_kes_minor": 0,
                "interval": "none",
                "limits": {},
                "default": True,
                "upgrade_to": "b",
            },
            {"code": "b", "side": "developer", "name": "B", "price_kes_minor": 1, "interval": "month", "limits": {}},
            {
                "code": "c",
                "side": "org",
                "name": "C",
                "price_kes_minor": 0,
                "interval": "none",
                "limits": {},
                "default": True,
            },
        ]
    }
    base["plans"][overrides.pop("index", 0)].update(overrides)
    return base


def test_a_valid_catalogue_parses() -> None:
    assert plans.parse(_raw()).upgrade_for("a") is not None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"index": 1, "default": True}, "exactly one default"),
        ({"upgrade_to": "c"}, "other side"),
        ({"upgrade_to": "zz"}, "unknown plan"),
        ({"index": 1, "upgrade_to": "a"}, "loop"),
    ],
)
def test_bad_catalogues_are_refused(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        plans.parse(_raw(**change))
