"""REQ-DIR-05: the Briefs' daily cap comes from policy.yaml's ``briefs`` section, validated strictly."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.problems.brief_policy import BriefsPolicy, load_briefs_policy, parse_briefs_policy


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(loaded)


def test_the_shipped_values() -> None:
    assert load_briefs_policy() == BriefsPolicy(daily_posts=20)


@pytest.mark.parametrize(("key", "value"), [("daily_posts", 0), ("daily_posts", True), ("daily_posts", 201), ("x", 1)])
def test_a_bad_or_unknown_value_stops_the_app(key: str, value: object) -> None:
    raw = data()
    raw["briefs"][key] = value
    with pytest.raises(PolicyError, match="briefs"):
        parse_briefs_policy(raw)


def test_a_missing_section_or_version_stops_the_app() -> None:
    raw = data()
    del raw["briefs"]
    with pytest.raises(PolicyError, match="briefs"):
        parse_briefs_policy(raw)
    with pytest.raises(PolicyError, match="version"):
        parse_briefs_policy({"version": 2})
