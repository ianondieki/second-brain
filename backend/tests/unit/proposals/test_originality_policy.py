"""REQ-PROP-04: the originality check's numbers come from policy.yaml's ``originality`` section, validated strictly."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.proposals.originality_policy import (
    OriginalityPolicy,
    load_originality_policy,
    parse_originality_policy,
)


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(loaded)


def test_the_shipped_values_are_the_specs() -> None:
    """docs/spec/06 6.3: Jaccard 0.8, cosine 0.88, at most 10 a day; 0.75 is the card's "some overlap"."""
    assert load_originality_policy() == OriginalityPolicy(
        jaccard_high=0.8,
        cosine_high=0.88,
        cosine_some=0.75,
        daily_limit=10,
        max_candidates=200,
        max_explained=3,
        explanation_max_chars=300,
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("jaccard_high", 0),
        ("jaccard_high", 1.5),
        ("cosine_high", True),
        ("cosine_some", "0.7"),
        ("daily_limit", 0),
        ("daily_limit", 2.0),
        ("max_explained", True),
        ("explanation_max_chars", 10),
        ("x", 1),
    ],
)
def test_a_bad_or_unknown_value_stops_the_app(key: str, value: object) -> None:
    raw = data()
    raw["originality"][key] = value
    with pytest.raises(PolicyError):
        parse_originality_policy(raw)


def test_some_must_be_below_high() -> None:
    raw = data()
    raw["originality"]["cosine_some"] = raw["originality"]["cosine_high"]
    with pytest.raises(PolicyError, match="below"):
        parse_originality_policy(raw)


def test_a_missing_section_or_value_stops_the_app() -> None:
    raw = data()
    del raw["originality"]["daily_limit"]
    with pytest.raises(PolicyError, match="originality"):
        parse_originality_policy(raw)
    raw = data()
    del raw["originality"]
    with pytest.raises(PolicyError, match="originality"):
        parse_originality_policy(raw)
