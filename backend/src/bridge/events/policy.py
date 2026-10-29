"""This week's events' numbers from ``backend/config/policy.yaml``, section ``events`` (REQ-DEV-02; D-60).

Loaded and validated like the Briefs' section (``bridge.problems.brief_policy``): a missing section or value, an unknown
key or a value out of range raises ``PolicyError`` at first use, so a typo never becomes a silent default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError

_RANGES: Final[Mapping[str, tuple[int, int]]] = {"daily_posts": (1, 200)}


@dataclass(frozen=True, slots=True)
class EventsPolicy:
    """``daily_posts``: events one organisation posts per Nairobi day before 429 (each waits on the staff queue)."""

    daily_posts: int


def parse_events_policy(data: Any) -> EventsPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("events")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'events'")
    if set(section) != set(_RANGES):
        raise PolicyError(f"policy.yaml: events must have exactly {sorted(_RANGES)}, got {sorted(section)}")
    values: dict[str, int] = {}
    for key, (low, high) in _RANGES.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: events.{key} must be a whole number from {low} to {high}")
        values[key] = value
    return EventsPolicy(**values)


def load_events_policy(path: Path = POLICY_FILE) -> EventsPolicy:
    return parse_events_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_events_policy() -> EventsPolicy:
    """The process-wide events policy (read once; a bad value stops the first post that needs it)."""
    return load_events_policy()
