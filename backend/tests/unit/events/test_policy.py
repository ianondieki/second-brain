"""REQ-DEV-02 (D-60): the events' daily cap comes from policy.yaml's ``events`` section, validated strictly."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.events.policy import EventsPolicy, get_events_policy, load_events_policy, parse_events_policy


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(loaded)


def test_the_shipped_values() -> None:
    assert load_events_policy() == EventsPolicy(daily_posts=10)
    assert get_events_policy() is get_events_policy()


@pytest.mark.parametrize(("key", "value"), [("daily_posts", 0), ("daily_posts", True), ("daily_posts", 201), ("x", 1)])
def test_a_bad_or_unknown_value_stops_the_app(key: str, value: object) -> None:
    raw = data()
    raw["events"][key] = value
    with pytest.raises(PolicyError, match="events"):
        parse_events_policy(raw)


def test_a_missing_section_or_version_stops_the_app() -> None:
    raw = data()
    del raw["events"]
    with pytest.raises(PolicyError, match="events"):
        parse_events_policy(raw)
    with pytest.raises(PolicyError, match="version"):
        parse_events_policy({"version": 2})
