"""REQ-PROP-05: the assistant's limits come from policy.yaml's ``assistant`` section, validated strictly."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.proposals.assistant_policy import AssistantPolicy, load_assistant_policy, parse_assistant_policy


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(loaded)


def test_the_shipped_values() -> None:
    assert load_assistant_policy() == AssistantPolicy(
        max_calls_per_user_day=20, max_in_flight_per_user=1, tier2_overlap_words=8, max_reason_chars=300
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [("max_calls_per_user_day", 0), ("max_in_flight_per_user", True), ("tier2_overlap_words", 2), ("x", 1)],
)
def test_a_bad_or_unknown_value_stops_the_app(key: str, value: object) -> None:
    raw = data()
    raw["assistant"][key] = value
    with pytest.raises(PolicyError):
        parse_assistant_policy(raw)


def test_a_missing_section_stops_the_app() -> None:
    raw = data()
    del raw["assistant"]
    with pytest.raises(PolicyError, match="assistant"):
        parse_assistant_policy(raw)
