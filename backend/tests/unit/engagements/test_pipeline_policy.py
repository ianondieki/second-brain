"""REQ-ENG-14 (docs/platform/tasks/P27.md track B): the board's "no movement" threshold comes from policy.yaml's
``pipeline`` section (``stalled_after_bd``, default 5 Kenyan business days), validated strictly: a missing section, an
unknown key or a value out of range stops the first read that needs it."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.engagements.pipeline_policy import (
    PipelinePolicy,
    get_pipeline_policy,
    load_pipeline_policy,
    parse_pipeline_policy,
)
from bridge.engagements.policy import POLICY_FILE, PolicyError


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(loaded)


def test_the_shipped_values() -> None:
    assert load_pipeline_policy() == PipelinePolicy(stalled_after_bd=5)
    assert get_pipeline_policy() is get_pipeline_policy()


BAD = [("stalled_after_bd", 0), ("stalled_after_bd", True), ("stalled_after_bd", 61), ("stalled_after_bd", "5")]


@pytest.mark.parametrize(("key", "value"), [*BAD, ("x", 1)])
def test_a_bad_or_unknown_value_stops_the_app(key: str, value: object) -> None:
    raw = data()
    raw["pipeline"][key] = value
    with pytest.raises(PolicyError, match="pipeline"):
        parse_pipeline_policy(raw)


def test_a_missing_section_or_version_stops_the_app() -> None:
    raw = data()
    del raw["pipeline"]
    with pytest.raises(PolicyError, match="pipeline"):
        parse_pipeline_policy(raw)
    with pytest.raises(PolicyError, match="version"):
        parse_pipeline_policy({"version": 2})
