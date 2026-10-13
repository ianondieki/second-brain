"""The organisation's board numbers from ``backend/config/policy.yaml``, section ``pipeline`` (REQ-ENG-14;
docs/platform/tasks/P27.md track B).

``stalled_after_bd``: an active engagement that is not on hold and has had no tracker event for this many Kenyan
business days or more is marked "no movement" on the board (``bridge.engagements.pipeline``). Loaded and validated as
the events' section is (``bridge.events.policy``): a missing section or value, an unknown key or a value out of range
raises ``PolicyError`` at first use, so a typo never becomes a silent default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError

_RANGES: Final[Mapping[str, tuple[int, int]]] = {"stalled_after_bd": (1, 60)}


@dataclass(frozen=True, slots=True)
class PipelinePolicy:
    stalled_after_bd: int


def parse_pipeline_policy(data: Any) -> PipelinePolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("pipeline")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'pipeline'")
    if set(section) != set(_RANGES):
        raise PolicyError(f"policy.yaml: pipeline must have exactly {sorted(_RANGES)}, got {sorted(section)}")
    values: dict[str, int] = {}
    for key, (low, high) in _RANGES.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: pipeline.{key} must be a whole number from {low} to {high}")
        values[key] = value
    return PipelinePolicy(**values)


def load_pipeline_policy(path: Path = POLICY_FILE) -> PipelinePolicy:
    return parse_pipeline_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_pipeline_policy() -> PipelinePolicy:
    """The process-wide pipeline policy (read once; a bad value stops the first board read that needs it)."""
    return load_pipeline_policy()
