"""The submission assistant's numbers from ``backend/config/policy.yaml``, section ``assistant`` (REQ-PROP-05).

Loaded and validated like the tracker's and the reminders' sections (``bridge.engagements.policy``,
``bridge.reminders.thresholds``): a missing section or value, an unknown key or a value out of range raises
``PolicyError`` at first use, so a typo never becomes a silent default.
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
    "max_calls_per_user_day": (1, 1000),
    "max_in_flight_per_user": (1, 10),
    "tier2_overlap_words": (3, 50),
    "max_reason_chars": (40, 2000),
}


@dataclass(frozen=True, slots=True)
class AssistantPolicy:
    """``max_calls_per_user_day``: a user's ``submission_assistant`` ledger rows today before 429;
    ``max_in_flight_per_user``: suggestions running at once per user (per process); ``tier2_overlap_words``: the
    shingle length that marks a suggestion as copying confidential text; ``max_reason_chars``: a hint's reason cap."""

    max_calls_per_user_day: int
    max_in_flight_per_user: int
    tier2_overlap_words: int
    max_reason_chars: int


def parse_assistant_policy(data: Any) -> AssistantPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("assistant")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'assistant'")
    if set(section) != set(_RANGES):
        raise PolicyError(f"policy.yaml: assistant must have exactly {sorted(_RANGES)}, got {sorted(section)}")
    values: dict[str, int] = {}
    for key, (low, high) in _RANGES.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: assistant.{key} must be a whole number from {low} to {high}")
        values[key] = value
    return AssistantPolicy(**values)


def load_assistant_policy(path: Path = POLICY_FILE) -> AssistantPolicy:
    return parse_assistant_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_assistant_policy() -> AssistantPolicy:
    """The process-wide assistant policy (read once)."""
    return load_assistant_policy()
