"""REQ-SCOUT-02: the scout's weights come from config/matching/weights_v1.yaml, validated and failing closed."""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import time
from typing import Any

import pytest
import yaml

from bridge.matching.config import WEIGHTS_FILE, WeightsError, get_weights, parse_weights


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(WEIGHTS_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def test_the_real_file_loads() -> None:
    weights = get_weights()
    assert weights.keywords + weights.niche + weights.tagged + weights.evidence == 100
    assert (weights.keywords, weights.niche, weights.tagged, weights.evidence) == (50, 30, 10, 10)
    assert weights.model_weight == 0.4  # docs/spec/06 6.8: final = 0.6 deterministic + 0.4 LLM
    assert weights.max_model_shift == 5  # until REQ-SCOUT-06's eval gate
    assert (weights.digest_items, weights.top_3_items) == (10, 3)
    assert weights.first_run_days == 30
    assert weights.scan_after == time(7, 0)
    assert weights.band("under_500k") is not None
    assert weights.band("nope") is None


def test_the_digest_size_follows_the_plan_and_fails_safe() -> None:
    weights = get_weights()
    assert weights.digest_size("full") == 10
    assert weights.digest_size("top_3") == 3
    assert weights.digest_size(None) == 3  # an unknown value is the smallest digest


BROKEN: list[tuple[Callable[[dict[str, Any]], object], str]] = [
    (lambda d: d.update(version=2), "version 1"),
    (lambda d: d.update(extra={}), "unknown sections"),
    (lambda d: d["deterministic"].update(keywords=60), "sum to 100"),
    (lambda d: d["deterministic"].pop("tagged"), "exactly"),
    (lambda d: d["deterministic"].update(niche=True), "whole number"),
    (lambda d: d["keywords"].update(none_listed=1.5), "from 0 to 1"),
    (lambda d: d["final"].update(model_weight=-0.1), "from 0 to 1"),
    (lambda d: d["final"].update(max_model_shift=-1), "from 0 to 100"),
    (lambda d: d["final"].pop("max_model_shift"), "exactly"),
    (lambda d: d["limits"].update(digest_items=11), "from 1 to 10"),
    (lambda d: d["limits"].update(model_top_n=16), "from 0 to 15"),
    (lambda d: d["limits"].update(preview_items=5), "whole digest"),
    (lambda d: d["schedule"].update(scan_after="7am"), "HH:MM"),
    (lambda d: d.update(budget_bands=[]), "non-empty"),
    (lambda d: d["budget_bands"].append({"code": "Big Budget", "label": "x"}), "code"),
    (lambda d: d["budget_bands"].append(dict(d["budget_bands"][0])), "distinct"),
    (lambda d: d["budget_bands"].append({"code": "x"}), "exactly a code and a label"),
]


@pytest.mark.parametrize(("change", "message"), BROKEN)
def test_a_broken_file_is_refused(change: Callable[[dict[str, Any]], object], message: str) -> None:
    data = raw()
    change(data)
    with pytest.raises(WeightsError, match=message):
        parse_weights(data)
