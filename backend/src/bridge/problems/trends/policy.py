"""The trends' numbers from ``backend/config/policy.yaml``, section ``trends`` (REQ-DEV-02; D-60; P22 card B).

Loaded and validated like the research section (``bridge.problems.research.policy``): a missing section or value, an
unknown key or a value out of range raises ``PolicyError`` at first use, so a typo never becomes a silent default.
The confidence weights and quality tiers are the research section's (one formula for both card types); ``scoring``
gives the research checks a ``ResearchPolicy`` carrying the trends' own support length, discard threshold and ages.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.problems.research.policy import ResearchPolicy

_INTS: Final[Mapping[str, tuple[int, int]]] = {
    "max_excerpts": (1, 20),
    "max_cards_per_run": (1, 5),
    "min_support_words": (1, 20),
    "stale_after_months": (1, 120),
    "archive_after_months": (1, 240),
    "draft_attempts": (2, 2),  # the card: one retry on a refused draft, then the week has none
}
_KEYS: Final = frozenset({*_INTS, "discard_below"})


@dataclass(frozen=True, slots=True)
class TrendsPolicy:
    max_excerpts: int
    max_cards_per_run: int
    min_support_words: int
    stale_after_months: int
    archive_after_months: int
    draft_attempts: int
    discard_below: Decimal

    def scoring(self, research: ResearchPolicy) -> ResearchPolicy:
        """The research policy with the trends' support length, discard threshold and ages: what the shared checks
        (``bridge.problems.research.checks``) and freshness (``bridge.problems.research.sources``) read."""
        return dataclasses.replace(
            research,
            min_support_words=self.min_support_words,
            discard_below=self.discard_below,
            stale_after_months=self.stale_after_months,
            archive_after_months=self.archive_after_months,
        )


def parse_trends_policy(data: Any) -> TrendsPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("trends")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'trends'")
    if set(section) != _KEYS:
        raise PolicyError(f"policy.yaml: trends must have exactly {sorted(_KEYS)}, got {sorted(section)}")
    ints: dict[str, int] = {}
    for key, (low, high) in _INTS.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: trends.{key} must be a whole number from {low} to {high}")
        ints[key] = value
    if ints["stale_after_months"] >= ints["archive_after_months"]:
        raise PolicyError("policy.yaml: trends.stale_after_months must be below archive_after_months")
    raw = section["discard_below"]
    try:
        if isinstance(raw, bool) or not isinstance(raw, int | float | str):
            raise InvalidOperation
        threshold = Decimal(str(raw))
    except InvalidOperation:
        raise PolicyError("policy.yaml: trends.discard_below must be a number") from None
    if not threshold.is_finite() or not Decimal(0) <= threshold <= Decimal(1):
        raise PolicyError("policy.yaml: trends.discard_below must be from 0 to 1")
    return TrendsPolicy(**ints, discard_below=threshold)


def load_trends_policy(path: Path = POLICY_FILE) -> TrendsPolicy:
    return parse_trends_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_trends_policy() -> TrendsPolicy:
    """The process-wide trends policy (read once)."""
    return load_trends_policy()
