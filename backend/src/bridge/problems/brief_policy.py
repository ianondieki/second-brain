"""Problem Briefs' numbers from ``backend/config/policy.yaml``, section ``briefs`` (REQ-DIR-05).

Loaded and validated like the other sections (``bridge.proposals.assistant_policy``): a missing section or value, an
unknown key or a value out of range raises ``PolicyError`` at first use, so a typo never becomes a silent default.
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
class BriefsPolicy:
    """``daily_posts``: Briefs one organisation posts per Nairobi day before 429 (each files a moderation case)."""

    daily_posts: int


def parse_briefs_policy(data: Any) -> BriefsPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("briefs")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'briefs'")
    if set(section) != set(_RANGES):
        raise PolicyError(f"policy.yaml: briefs must have exactly {sorted(_RANGES)}, got {sorted(section)}")
    values: dict[str, int] = {}
    for key, (low, high) in _RANGES.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: briefs.{key} must be a whole number from {low} to {high}")
        values[key] = value
    return BriefsPolicy(**values)


def load_briefs_policy(path: Path = POLICY_FILE) -> BriefsPolicy:
    return parse_briefs_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_briefs_policy() -> BriefsPolicy:
    """The process-wide Briefs policy (read once; a bad value stops the first post that needs it)."""
    return load_briefs_policy()
