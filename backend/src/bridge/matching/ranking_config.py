"""Trending and ranker numbers from ``backend/config/ranking/weights_v1.yaml`` (REQ-TREND-01, REQ-TREND-02,
REQ-PERS-01; docs/spec/06 6.6, 6.7).

``bridge.matching.trending``, ``discover`` and ``ranker`` read these values; nothing else defines them. Loading
validates every value and fails closed (``RankingConfigError``): a missing or unknown key, a kind the code does not
know, or a number out of range never becomes a silent default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

import yaml

from bridge.config import BACKEND_DIR

RANKING_FILE: Final = BACKEND_DIR / "config" / "ranking" / "weights_v1.yaml"
AGGREGATE_MAX_DAYS: Final = 400  # app_trend_aggregates refuses a longer window (revision 0005)
PROBLEM_KINDS: Final = frozenset(
    {"verified_org_brief", "official_source", "independent_source", "proposal_submitted", "scout_match"}
)
PROJECT_KINDS: Final = frozenset({"org_interest"})
FEATURES: Final = (
    "semantic_fit",
    "niche_match",
    "region_match",
    "skill_coverage",
    "trend",
    "evidence_confidence",
    "market_pull",
    "crowding",
    "track_record",
    "freshness",
)
_TRENDING = {
    "window_days",
    "baseline_days",
    "baseline_step_days",
    "min_baseline_samples",
    "sd_floor",
    "z_trending",
    "min_score",
    "min_actors",
    "min_orgs",
    "young_share",
    "young_days",
    "new_days",
    "badge_days",
    "problems",
    "projects",
}
_RANKER = {
    "version",
    "weights",
    "niche",
    "region",
    "z_clip",
    "market_pull_cap",
    "crowding_cap",
    "freshness_half_life_days",
    "new_card_days",
    "new_card_boost",
    "brief_confidence",
    "semantic_saturation",
    "min_keyword_length",
    "recent_proposals",
    "top_n",
    "per_niche_cap",
    "mmr_lambda",
    "exploration_slots",
    "why_chips",
    "labels",
    "pursuit",
}
_PURSUIT = {
    "crowded_proposals",
    "pursue_min_score",
    "pursue_min_confidence",
    "pursue_trend_z",
    "not_now_below_score",
    "not_now_below_confidence",
}


class RankingConfigError(ValueError):
    """weights_v1.yaml (ranking) is missing a value, has an unknown key or a value out of range."""


@dataclass(frozen=True, slots=True)
class Decay:
    half_life_days: float
    weights: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class TrendConfig:
    window_days: int
    baseline_days: int
    baseline_step_days: int
    min_baseline_samples: int
    sd_floor: float
    z_trending: float
    min_score: float
    min_actors: int
    min_orgs: int
    young_share: float
    young_days: int
    new_days: int
    badge_days: int
    problems: Decay
    projects: Decay


@dataclass(frozen=True, slots=True)
class DiscoverConfig:
    items: int
    sources_per_problem: int
    projects_per_problem: int
    gap_decile: float
    gap_fewer_than: int


@dataclass(frozen=True, slots=True)
class Pursuit:
    crowded_proposals: int
    pursue_min_score: int
    pursue_min_confidence: float
    pursue_trend_z: float
    not_now_below_score: int
    not_now_below_confidence: float


@dataclass(frozen=True, slots=True)
class RankerConfig:
    version: str
    weights: Mapping[str, float]
    niche_liked: float
    niche_adjacent: float
    region_same_county: float
    region_national: float
    z_clip: float
    market_pull_cap: int
    crowding_cap: int
    freshness_half_life_days: float
    new_card_days: int
    new_card_boost: float
    brief_confidence: float
    semantic_saturation: int
    min_keyword_length: int
    recent_proposals: int
    top_n: int
    per_niche_cap: int
    mmr_lambda: float
    exploration_slots: int
    why_chips: int
    label_strong: int
    label_good: int
    pursuit: Pursuit


@dataclass(frozen=True, slots=True)
class RankingConfig:
    trending: TrendConfig
    discover: DiscoverConfig
    ranker: RankerConfig
    liked_min: int
    liked_max: int


def _section(data: Any, where: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(data, Mapping) or set(data) != keys:
        raise RankingConfigError(f"ranking weights: {where} must have exactly {sorted(keys)}")
    return data


def _int(value: Any, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise RankingConfigError(f"ranking weights: {where} must be a whole number from {low} to {high}, got {value!r}")
    return value


def _num(value: Any, where: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= value <= high:
        raise RankingConfigError(f"ranking weights: {where} must be a number from {low} to {high}, got {value!r}")
    return float(value)


def _decay(data: Any, where: str, kinds: frozenset[str]) -> Decay:
    section = _section(data, where, {"half_life_days", "weights"})
    weights = section["weights"]
    if not isinstance(weights, Mapping) or set(weights) != kinds:
        raise RankingConfigError(f"ranking weights: {where}.weights must name exactly {sorted(kinds)}")
    return Decay(
        half_life_days=_num(section["half_life_days"], f"{where}.half_life_days", 1, 365),
        weights={str(k): _num(v, f"{where}.weights.{k}", 0, 100) for k, v in weights.items()},
    )


def _trending(data: Any) -> TrendConfig:
    t = _section(data, "trending", _TRENDING)
    ints = {
        "window_days": (1, AGGREGATE_MAX_DAYS),
        "baseline_days": (7, AGGREGATE_MAX_DAYS),
        "baseline_step_days": (1, 90),
        "min_baseline_samples": (1, 1000),
        "min_actors": (3, 100),  # never below the definer's floor
        "min_orgs": (3, 100),
        "young_days": (1, 90),
        "new_days": (1, 90),
        "badge_days": (1, 365),
    }
    values: dict[str, Any] = {k: _int(t[k], f"trending.{k}", *bounds) for k, bounds in ints.items()}
    if values["baseline_days"] > values["window_days"]:
        raise RankingConfigError("ranking weights: trending.baseline_days must fit inside window_days")
    if values["baseline_step_days"] > values["baseline_days"]:
        raise RankingConfigError("ranking weights: trending.baseline_step_days must not exceed baseline_days")
    return TrendConfig(
        sd_floor=_num(t["sd_floor"], "trending.sd_floor", 0.01, 100),
        z_trending=_num(t["z_trending"], "trending.z_trending", 0, 10),
        min_score=_num(t["min_score"], "trending.min_score", 0, 1000),
        young_share=_num(t["young_share"], "trending.young_share", 0, 1),
        problems=_decay(t["problems"], "trending.problems", PROBLEM_KINDS),
        projects=_decay(t["projects"], "trending.projects", PROJECT_KINDS),
        **values,
    )


def _discover(data: Any) -> DiscoverConfig:
    d = _section(data, "discover", {"items", "sources_per_problem", "projects_per_problem", "opportunity_gap"})
    gap = _section(d["opportunity_gap"], "discover.opportunity_gap", {"decile", "fewer_than"})
    return DiscoverConfig(
        items=_int(d["items"], "discover.items", 1, 100),
        sources_per_problem=_int(d["sources_per_problem"], "discover.sources_per_problem", 0, 10),
        projects_per_problem=_int(d["projects_per_problem"], "discover.projects_per_problem", 0, 10),
        gap_decile=_num(gap["decile"], "discover.opportunity_gap.decile", 0.01, 1),
        gap_fewer_than=_int(gap["fewer_than"], "discover.opportunity_gap.fewer_than", 1, 100),
    )


def _ranker(data: Any) -> RankerConfig:
    r = _section(data, "ranker", _RANKER)
    weights = _section(r["weights"], "ranker.weights", set(FEATURES))
    w = {k: _num(weights[k], f"ranker.weights.{k}", -1, 1) for k in FEATURES}
    if w["crowding"] > 0 or any(v < 0 for k, v in w.items() if k != "crowding"):
        raise RankingConfigError("ranking weights: crowding is the only negative weight")
    niche = _section(r["niche"], "ranker.niche", {"liked", "adjacent"})
    region = _section(r["region"], "ranker.region", {"same_county", "national"})
    labels = _section(r["labels"], "ranker.labels", {"strong", "good"})
    p = _section(r["pursuit"], "ranker.pursuit", _PURSUIT)
    version = r["version"]
    if not isinstance(version, str) or not version or len(version) > 40:
        raise RankingConfigError("ranking weights: ranker.version must be a short name")
    strong, good = _int(labels["strong"], "labels.strong", 1, 100), _int(labels["good"], "labels.good", 0, 100)
    if good >= strong:
        raise RankingConfigError("ranking weights: labels.good must be below labels.strong")
    top_n = _int(r["top_n"], "ranker.top_n", 1, 50)
    return RankerConfig(
        version=version,
        weights=w,
        niche_liked=_num(niche["liked"], "ranker.niche.liked", 0, 1),
        niche_adjacent=_num(niche["adjacent"], "ranker.niche.adjacent", 0, 1),
        region_same_county=_num(region["same_county"], "ranker.region.same_county", 0, 1),
        region_national=_num(region["national"], "ranker.region.national", 0, 1),
        z_clip=_num(r["z_clip"], "ranker.z_clip", 0.5, 10),
        market_pull_cap=_int(r["market_pull_cap"], "ranker.market_pull_cap", 1, 1000),
        crowding_cap=_int(r["crowding_cap"], "ranker.crowding_cap", 1, 1000),
        freshness_half_life_days=_num(r["freshness_half_life_days"], "ranker.freshness_half_life_days", 1, 365),
        new_card_days=_int(r["new_card_days"], "ranker.new_card_days", 0, 90),
        new_card_boost=_num(r["new_card_boost"], "ranker.new_card_boost", 0, 0.2),
        brief_confidence=_num(r["brief_confidence"], "ranker.brief_confidence", 0, 1),
        semantic_saturation=_int(r["semantic_saturation"], "ranker.semantic_saturation", 1, 50),
        min_keyword_length=_int(r["min_keyword_length"], "ranker.min_keyword_length", 2, 10),
        recent_proposals=_int(r["recent_proposals"], "ranker.recent_proposals", 0, 20),
        top_n=top_n,
        per_niche_cap=_int(r["per_niche_cap"], "ranker.per_niche_cap", 1, top_n),
        mmr_lambda=_num(r["mmr_lambda"], "ranker.mmr_lambda", 0, 1),
        exploration_slots=_int(r["exploration_slots"], "ranker.exploration_slots", 0, top_n),
        why_chips=_int(r["why_chips"], "ranker.why_chips", 1, 5),
        label_strong=strong,
        label_good=good,
        pursuit=Pursuit(
            crowded_proposals=_int(p["crowded_proposals"], "pursuit.crowded_proposals", 1, 1000),
            pursue_min_score=_int(p["pursue_min_score"], "pursuit.pursue_min_score", 0, 100),
            pursue_min_confidence=_num(p["pursue_min_confidence"], "pursuit.pursue_min_confidence", 0, 1),
            pursue_trend_z=_num(p["pursue_trend_z"], "pursuit.pursue_trend_z", -10, 10),
            not_now_below_score=_int(p["not_now_below_score"], "pursuit.not_now_below_score", 0, 100),
            not_now_below_confidence=_num(p["not_now_below_confidence"], "pursuit.not_now_below_confidence", 0, 1),
        ),
    )


def parse_ranking(data: Any) -> RankingConfig:
    if not isinstance(data, Mapping) or type(data.get("version")) is not int or data.get("version") != 1:
        raise RankingConfigError("ranking weights: version 1 expected")
    top = _section(data, "the file", {"version", "trending", "discover", "ranker", "liked_niches"})
    liked = _section(top["liked_niches"], "liked_niches", {"min", "max"})
    liked_min, liked_max = _int(liked["min"], "liked_niches.min", 1, 20), _int(liked["max"], "liked_niches.max", 1, 20)
    if liked_min > liked_max:
        raise RankingConfigError("ranking weights: liked_niches.min must not exceed max")
    return RankingConfig(
        trending=_trending(top["trending"]),
        discover=_discover(top["discover"]),
        ranker=_ranker(top["ranker"]),
        liked_min=liked_min,
        liked_max=liked_max,
    )


def load_ranking(path: Path = RANKING_FILE) -> RankingConfig:
    return parse_ranking(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def get_ranking() -> RankingConfig:
    """The process-wide ranking configuration (read once)."""
    return load_ranking()
