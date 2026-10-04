"""The originality check's numbers from ``backend/config/policy.yaml``, section ``originality`` (REQ-PROP-04).

Loaded and validated like the assistant's section (``bridge.proposals.assistant_policy``): a missing section or value,
an unknown key, a value of the wrong type or out of range, or ``cosine_some`` not below ``cosine_high`` raises
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

_RATIOS: Final = ("jaccard_high", "cosine_high", "cosine_some")
_COUNTS: Final[Mapping[str, tuple[int, int]]] = {
    "daily_limit": (1, 1000),
    "max_candidates": (1, 5000),
    "max_explained": (1, 10),
    "explanation_max_chars": (40, 2000),
}


@dataclass(frozen=True, slots=True)
class OriginalityPolicy:
    """``jaccard_high``: the shingle-set Jaccard that makes ``high_overlap``; ``cosine_high`` and ``cosine_some``: the
    teaser-embedding cosines of ``high_overlap`` and ``some_overlap``; ``daily_limit``: checks per developer per
    Nairobi day; ``max_candidates``: LSH candidates read per check; ``max_explained``: matched teasers the explainer
    sees; ``explanation_max_chars``: the longest explainer sentence shown."""

    jaccard_high: float
    cosine_high: float
    cosine_some: float
    daily_limit: int
    max_candidates: int
    max_explained: int
    explanation_max_chars: int


def parse_originality_policy(data: Any) -> OriginalityPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("originality")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'originality'")
    expected = {*_RATIOS, *_COUNTS}
    if set(section) != expected:
        raise PolicyError(f"policy.yaml: originality must have exactly {sorted(expected)}, got {sorted(section)}")
    values: dict[str, Any] = {}
    for key in _RATIOS:
        value = section[key]
        if not isinstance(value, float) or not 0.0 < value <= 1.0:
            raise PolicyError(f"policy.yaml: originality.{key} must be a decimal number above 0 and at most 1")
        values[key] = value
    for key, (low, high) in _COUNTS.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: originality.{key} must be a whole number from {low} to {high}")
        values[key] = value
    if values["cosine_some"] >= values["cosine_high"]:
        raise PolicyError("policy.yaml: originality.cosine_some must be below cosine_high")
    return OriginalityPolicy(**values)


def load_originality_policy(path: Path = POLICY_FILE) -> OriginalityPolicy:
    return parse_originality_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_originality_policy() -> OriginalityPolicy:
    """The process-wide originality policy (read once)."""
    return load_originality_policy()
