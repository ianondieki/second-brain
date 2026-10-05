"""Today's five's numbers from ``backend/config/policy.yaml``, section ``quiz`` (REQ-DEV-01; D-59).

Loaded and validated like the other sections (``bridge.problems.brief_policy``): a missing section or value, an
unknown key or a value out of range raises ``PolicyError`` at first use, so a typo never becomes a silent default.
The bounds of a question's text (300, 120 and 600 characters) and the five questions of four options are the card's
rules and revision 0009's CHECKs, so they are constants in ``bridge.quiz.checks``, not policy.
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
    "sources_per_prompt": (8, 12),  # the card: a sample of 8 to 12 pages per call
    "draft_attempts": (1, 3),  # the card: one retry; never more than two retries a night
    "no_repeat_days": (1, 365),
}


@dataclass(frozen=True, slots=True)
class QuizPolicy:
    """``sources_per_prompt``: curated pages sent per call; ``draft_attempts``: calls per night (a discarded draft is
    retried until they are spent); ``no_repeat_days``: the window of the prompt-hash no-repeat rule."""

    sources_per_prompt: int
    draft_attempts: int
    no_repeat_days: int


def parse_quiz_policy(data: Any) -> QuizPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("quiz")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'quiz'")
    if set(section) != set(_RANGES):
        raise PolicyError(f"policy.yaml: quiz must have exactly {sorted(_RANGES)}, got {sorted(section)}")
    values: dict[str, int] = {}
    for key, (low, high) in _RANGES.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: quiz.{key} must be a whole number from {low} to {high}")
        values[key] = value
    return QuizPolicy(**values)


def load_quiz_policy(path: Path = POLICY_FILE) -> QuizPolicy:
    return parse_quiz_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_quiz_policy() -> QuizPolicy:
    """The process-wide quiz policy (read once)."""
    return load_quiz_policy()
