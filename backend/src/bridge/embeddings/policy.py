"""The embedding job's numbers from ``backend/config/policy.yaml``, section ``embeddings`` (REQ-PERS-02, REQ-EMB-01;
P23-1).

Loaded and validated like the other sections (``bridge.events.policy``): a missing section or value, an unknown key or
a value out of range raises ``PolicyError`` at first use, so a typo never becomes a silent default. The batch size is
the model's (``ai/models.yaml`` ``embeddings.reembed_batch_size``), not policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError

_RANGES: Final[Mapping[str, tuple[int, int]]] = {"max_rows_per_run": (1, 5000)}


@dataclass(frozen=True, slots=True)
class EmbeddingsPolicy:
    """``max_rows_per_run``: rows of each table (developer profiles, problems) one run of ``embeddings.reembed`` tries
    at most, refused writes included; the rest wait for the next run."""

    max_rows_per_run: int


def parse_embeddings_policy(data: Any) -> EmbeddingsPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("embeddings")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'embeddings'")
    if set(section) != set(_RANGES):
        raise PolicyError(f"policy.yaml: embeddings must have exactly {sorted(_RANGES)}, got {sorted(section)}")
    values: dict[str, int] = {}
    for key, (low, high) in _RANGES.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: embeddings.{key} must be a whole number from {low} to {high}")
        values[key] = value
    return EmbeddingsPolicy(**values)


def load_embeddings_policy(path: Path = POLICY_FILE) -> EmbeddingsPolicy:
    return parse_embeddings_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_embeddings_policy() -> EmbeddingsPolicy:
    """The process-wide embeddings policy (read once; a bad value stops the first run)."""
    return load_embeddings_policy()
