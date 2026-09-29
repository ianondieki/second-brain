"""The research agent's numbers from ``backend/config/policy.yaml``, section ``research`` (REQ-RES-01; spec 06 6.5).

Loaded and validated like the tracker's, the reminders' and the assistant's sections: a missing section or value, an
unknown key or a value out of range raises ``PolicyError`` at first use, so a typo never becomes a silent default. The
confidence weights and quality tiers are decimals written as strings (exact arithmetic); the four weights add up to 1.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError

SOURCE_TYPES: Final = ("official", "filing", "news", "ngo", "blog", "social")  # docs/spec/06 6.5 quality tiers
WEIGHT_KEYS: Final = ("source_quality", "corroboration", "freshness", "extraction_agreement")
# The research_runs CHECK (revision 0005) bounds the caps: a policy above it could never be recorded.
_INTS: Final[Mapping[str, tuple[int, int]]] = {
    "max_searches": (0, 25),
    "max_fetches": (0, 40),
    "max_input_tokens": (1_000, 400_000),
    "min_excerpts": (1, 10),
    "max_excerpts": (1, 10),
    "max_cards_per_run": (1, 10),
    "max_quote_words": (10, 200),
    "min_support_words": (1, 20),
    "stale_after_months": (1, 120),
    "archive_after_months": (1, 240),
    "corroboration_publishers": (1, 10),
}
_KEYS: Final = frozenset({*_INTS, "discard_below", "weights", "source_quality"})


@dataclass(frozen=True, slots=True)
class ResearchPolicy:
    max_searches: int
    max_fetches: int
    max_input_tokens: int
    min_excerpts: int
    max_excerpts: int
    max_cards_per_run: int
    max_quote_words: int
    min_support_words: int
    stale_after_months: int
    archive_after_months: int
    corroboration_publishers: int
    discard_below: Decimal
    weights: Mapping[str, Decimal]
    source_quality: Mapping[str, Decimal]


def _decimal(value: Any, where: str, *, low: Decimal = Decimal(0), high: Decimal = Decimal(1)) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise PolicyError(f"policy.yaml: research.{where} must be a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise PolicyError(f"policy.yaml: research.{where} must be a number") from None
    if not number.is_finite() or not low <= number <= high:
        raise PolicyError(f"policy.yaml: research.{where} must be from {low} to {high}")
    return number


def _table(section: Mapping[str, Any], name: str, keys: tuple[str, ...]) -> dict[str, Decimal]:
    table = section.get(name)
    if not isinstance(table, Mapping) or set(table) != set(keys):
        raise PolicyError(f"policy.yaml: research.{name} must have exactly {sorted(keys)}")
    return {key: _decimal(table[key], f"{name}.{key}") for key in keys}


def parse_research_policy(data: Any) -> ResearchPolicy:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise PolicyError("policy.yaml: version 1 expected")
    section = data.get("research")
    if not isinstance(section, Mapping):
        raise PolicyError("policy.yaml: missing section 'research'")
    if set(section) != _KEYS:
        raise PolicyError(f"policy.yaml: research must have exactly {sorted(_KEYS)}, got {sorted(section)}")
    ints: dict[str, int] = {}
    for key, (low, high) in _INTS.items():
        value = section[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise PolicyError(f"policy.yaml: research.{key} must be a whole number from {low} to {high}")
        ints[key] = value
    if ints["min_excerpts"] > ints["max_excerpts"]:
        raise PolicyError("policy.yaml: research.min_excerpts exceeds max_excerpts")
    if ints["stale_after_months"] >= ints["archive_after_months"]:
        raise PolicyError("policy.yaml: research.stale_after_months must be below archive_after_months")
    weights = _table(section, "weights", WEIGHT_KEYS)
    if sum(weights.values()) != 1:
        raise PolicyError("policy.yaml: research.weights must add up to 1")
    return ResearchPolicy(
        **ints,
        discard_below=_decimal(section["discard_below"], "discard_below"),
        weights=weights,
        source_quality=_table(section, "source_quality", SOURCE_TYPES),
    )


def load_research_policy(path: Path = POLICY_FILE) -> ResearchPolicy:
    return parse_research_policy(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_research_policy() -> ResearchPolicy:
    """The process-wide research policy (read once)."""
    return load_research_policy()
