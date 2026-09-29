"""The scout's numbers from ``backend/config/matching/weights_v1.yaml`` (REQ-SCOUT-02; docs/spec/06 6.8).

The pipeline (``bridge.matching.pipeline``), the scan (``bridge.matching.scan``), Preview and the digest read these
values; nothing else defines them. Loading validates every value and fails closed (``WeightsError``): a missing or
unknown key, deterministic weights that do not sum to 100, or a number out of range never becomes a silent default.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.config import BACKEND_DIR

WEIGHTS_FILE: Final = BACKEND_DIR / "config" / "matching" / "weights_v1.yaml"
BAND_CODE: Final = re.compile(r"[a-z0-9_-]{1,32}")  # scout_agents.budget_band's CHECK
_TIME: Final = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_SECTIONS: Final = {
    "deterministic": {"keywords", "niche", "tagged", "evidence"},
    "keywords": {"saturation", "none_listed"},
    "niche": {"exact", "via_parent"},
    "final": {"model_weight"},
    "limits": {
        "scan_per_run",
        "matches_per_run",
        "model_top_n",
        "digest_items",
        "top_3_items",
        "first_run_days",
        "preview_items",
    },
    "schedule": {"scan_after"},
}
_LIMIT_RANGES: Final = {
    "scan_per_run": (1, 5000),
    "matches_per_run": (1, 500),
    "model_top_n": (0, 15),  # docs/spec/06 6.8: the rubric call covers at most 15
    "digest_items": (1, 10),  # docs/spec/06 6.8: a digest has at most 10 items
    "top_3_items": (1, 10),
    "first_run_days": (1, 90),
    "preview_items": (1, 50),
}


class WeightsError(ValueError):
    """weights_v1.yaml is missing a value, has an unknown key or a value out of range."""


@dataclass(frozen=True, slots=True)
class BudgetBand:
    code: str
    label: str


@dataclass(frozen=True, slots=True)
class Weights:
    """``keywords``, ``niche``, ``tagged`` and ``evidence`` are points (summing to 100); the shares are 0-1."""

    keywords: int
    niche: int
    tagged: int
    evidence: int
    keyword_saturation: int
    keywords_none_listed: float
    niche_exact: float
    niche_via_parent: float
    model_weight: float
    scan_per_run: int
    matches_per_run: int
    model_top_n: int
    digest_items: int
    top_3_items: int
    first_run_days: int
    preview_items: int
    scan_after: time
    budget_bands: tuple[BudgetBand, ...]

    def band(self, code: str) -> BudgetBand | None:
        return next((b for b in self.budget_bands if b.code == code), None)

    def digest_size(self, scout_digest: object) -> int:
        """The plan's digest size (``plans.yaml`` ``scout_digest``): ``top_3`` or ``full``; anything else is the
        smallest (fail safe)."""
        return self.digest_items if scout_digest == "full" else self.top_3_items


def _section(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    section = data.get(name)
    if not isinstance(section, Mapping) or set(section) != _SECTIONS[name]:
        raise WeightsError(f"weights_v1.yaml: {name} must have exactly {sorted(_SECTIONS[name])}")
    return section


def _int(value: Any, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise WeightsError(f"weights_v1.yaml: {where} must be a whole number from {low} to {high}, got {value!r}")
    return value


def _share(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
        raise WeightsError(f"weights_v1.yaml: {where} must be a number from 0 to 1, got {value!r}")
    return float(value)


def _bands(raw: Any) -> tuple[BudgetBand, ...]:
    if not isinstance(raw, list) or not raw:
        raise WeightsError("weights_v1.yaml: budget_bands must be a non-empty list")
    bands = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"code", "label"}:
            raise WeightsError("weights_v1.yaml: each budget band has exactly a code and a label")
        code, label = item["code"], item["label"]
        if not isinstance(code, str) or not BAND_CODE.fullmatch(code) or not isinstance(label, str) or not label:
            raise WeightsError(f"weights_v1.yaml: budget band {code!r} needs a code [a-z0-9_-] and a label")
        bands.append(BudgetBand(code, label))
    if len({b.code for b in bands}) != len(bands):
        raise WeightsError("weights_v1.yaml: budget band codes must be distinct")
    return tuple(bands)


def parse_weights(data: Any) -> Weights:
    if not isinstance(data, Mapping) or data.get("version") != 1:
        raise WeightsError("weights_v1.yaml: version 1 expected")
    unknown = set(data) - {"version", "budget_bands", *_SECTIONS}
    if unknown:
        raise WeightsError(f"weights_v1.yaml: unknown sections {sorted(unknown)}")
    points = _section(data, "deterministic")
    det = {name: _int(points[name], f"deterministic.{name}", 0, 100) for name in _SECTIONS["deterministic"]}
    if sum(det.values()) != 100:
        raise WeightsError("weights_v1.yaml: the deterministic points must sum to 100")
    keywords, niche = _section(data, "keywords"), _section(data, "niche")
    limits = _section(data, "limits")
    scan_after = _section(data, "schedule")["scan_after"]
    match = _TIME.fullmatch(scan_after) if isinstance(scan_after, str) else None
    if match is None:
        raise WeightsError("weights_v1.yaml: schedule.scan_after must be HH:MM (EAT)")
    values = {name: _int(limits[name], f"limits.{name}", *_LIMIT_RANGES[name]) for name in _SECTIONS["limits"]}
    if values["preview_items"] < values["digest_items"]:
        raise WeightsError("weights_v1.yaml: limits.preview_items must cover a whole digest")
    return Weights(
        keywords=det["keywords"],
        niche=det["niche"],
        tagged=det["tagged"],
        evidence=det["evidence"],
        keyword_saturation=_int(keywords["saturation"], "keywords.saturation", 1, 20),
        keywords_none_listed=_share(keywords["none_listed"], "keywords.none_listed"),
        niche_exact=_share(niche["exact"], "niche.exact"),
        niche_via_parent=_share(niche["via_parent"], "niche.via_parent"),
        model_weight=_share(_section(data, "final")["model_weight"], "final.model_weight"),
        scan_after=time(int(match.group(1)), int(match.group(2))),
        budget_bands=_bands(data.get("budget_bands")),
        **values,
    )


def load_weights(path: Path = WEIGHTS_FILE) -> Weights:
    return parse_weights(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_weights() -> Weights:
    """The process-wide weights (read once)."""
    return load_weights()
