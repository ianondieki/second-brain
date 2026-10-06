"""Peers and team up's numbers from ``backend/config/policy.yaml``, section ``teams`` (REQ-DEV-03; D-58).

Loaded and validated like the other sections (``bridge.events.policy``): a missing section or value, an unknown key or
a value out of range raises ``PolicyError`` at first use, so a typo never becomes a silent default. The 0011 security
review's MINOR 5 is why the peers page and the profile changes are limited: without the limits the opted-in set could
be harvested by rotating the county and the liked niches and paging through ``app_peers``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError

_RANGES: Final[Mapping[str, tuple[int, int]]] = {
    "invitations_per_day": (1, 100),
    "posts_per_hour": (1, 600),
    "peers_pages_per_hour": (1, 1000),
    "profile_changes_per_day": (1, 100),
}


@dataclass(frozen=True, slots=True)
class TeamsPolicy:
    """``invitations_per_day``: invitations a developer sends in any 24 hours; ``posts_per_hour``: messages a developer
    writes in one team thread in any hour; ``peers_pages_per_hour``: peers pages a developer who opted in reads in any
    hour; ``profile_changes_per_day``: changes of the county or the liked niches in any 24 hours."""

    invitations_per_day: int
    posts_per_hour: int
    peers_pages_per_hour: int
    profile_changes_per_day: int


def parse_teams_policy(data: Any) -> TeamsPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("teams")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'teams'")
    if set(section) != set(_RANGES):
        raise PolicyError(f"policy.yaml: teams must have exactly {sorted(_RANGES)}, got {sorted(section)}")
    values: dict[str, int] = {}
    for key, (low, high) in _RANGES.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: teams.{key} must be a whole number from {low} to {high}")
        values[key] = value
    return TeamsPolicy(**values)


def load_teams_policy(path: Path = POLICY_FILE) -> TeamsPolicy:
    return parse_teams_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_teams_policy() -> TeamsPolicy:
    """The process-wide teams policy (read once; a bad value stops the first request that needs it)."""
    return load_teams_policy()
