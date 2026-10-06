"""REQ-DEV-03 (D-58): the teams' limits come from policy.yaml's ``teams`` section, validated strictly."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.teams.policy import TeamsPolicy, get_teams_policy, load_teams_policy, parse_teams_policy


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(loaded)


def test_the_shipped_values() -> None:
    assert load_teams_policy() == TeamsPolicy(
        invitations_per_day=10,
        reinvite_after_days=30,
        posts_per_hour=60,
        peers_pages_per_hour=60,
        profile_changes_per_day=10,
    )
    assert get_teams_policy() is get_teams_policy()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("invitations_per_day", 0),
        ("reinvite_after_days", 366),
        ("posts_per_hour", True),
        ("peers_pages_per_hour", 1001),
        ("profile_changes_per_day", "10"),
        ("unknown", 1),
    ],
)
def test_a_bad_or_unknown_value_stops_the_app(key: str, value: object) -> None:
    raw = data()
    raw["teams"][key] = value
    with pytest.raises(PolicyError, match="teams"):
        parse_teams_policy(raw)


def test_a_missing_section_or_version_stops_the_app() -> None:
    raw = data()
    del raw["teams"]
    with pytest.raises(PolicyError, match="teams"):
        parse_teams_policy(raw)
    with pytest.raises(PolicyError, match="version"):
        parse_teams_policy({"version": 2})
