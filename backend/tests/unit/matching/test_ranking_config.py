"""REQ-TREND-01, REQ-PERS-01: every trending and ranker number comes from config/ranking/weights_v1.yaml, validated
and failing closed (a missing or unknown key, an unknown kind or a value out of range is refused)."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
import yaml

from bridge.matching.ranking_config import RANKING_FILE, RankingConfigError, get_ranking, parse_ranking


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(RANKING_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def test_the_real_file_loads_with_the_spec_values() -> None:
    cfg = get_ranking()
    t, r = cfg.trending, cfg.ranker
    assert (t.problems.half_life_days, t.projects.half_life_days) == (14, 7)  # docs/spec/06 6.6
    assert dict(t.problems.weights) == {
        "verified_org_brief": 6,
        "official_source": 5,
        "independent_source": 3,
        "proposal_submitted": 2,
        "scout_match": 2,
    }
    assert dict(t.projects.weights) == {"org_interest": 12}
    assert (t.baseline_days, t.min_actors, t.young_share, t.young_days) == (90, 3, 0.5, 7)
    assert (r.weights["semantic_fit"], r.weights["crowding"]) == (0.25, -0.07)  # docs/spec/06 6.7
    assert round(sum(v for v in r.weights.values() if v > 0), 6) == 1.0
    assert (r.mmr_lambda, r.top_n, r.per_niche_cap, r.exploration_slots) == (0.7, 10, 3, 1)
    assert (r.label_strong, r.label_good) == (80, 60)
    assert r.pursuit.crowded_proposals == 10
    assert (cfg.discover.gap_decile, cfg.discover.gap_fewer_than) == (0.1, 3)
    assert (cfg.liked_min, cfg.liked_max) == (3, 5)


BROKEN: list[tuple[Callable[[dict[str, Any]], object], str]] = [
    (lambda d: d.update(version=2), "version 1"),
    (lambda d: d.update(extra={}), "exactly"),
    (lambda d: d["trending"].pop("min_actors"), "exactly"),
    (lambda d: d["trending"].update(min_actors=2), "from 3 to 100"),  # never below the definer's floor
    (lambda d: d["trending"].update(window_days=401), "from 1 to 400"),
    (lambda d: d["trending"].update(baseline_days=200), "inside window_days"),
    (lambda d: d["trending"]["problems"]["weights"].update(developer_save=1), "must name exactly"),
    (lambda d: d["trending"]["projects"]["weights"].update(verified_view=3), "must name exactly"),
    (lambda d: d["trending"]["problems"]["weights"].pop("scout_match"), "must name exactly"),  # no silent zero
    (lambda d: d["trending"].update(baseline_days=14, baseline_step_days=21), "must not exceed baseline_days"),
    (lambda d: d.update(version=True), "version 1"),
    (lambda d: d.update(version=1.0), "version 1"),
    (lambda d: d["trending"]["problems"].update(half_life_days=0), "from 1 to 365"),
    (lambda d: d["trending"].update(young_share=1.5), "from 0 to 1"),
    (lambda d: d["discover"]["opportunity_gap"].update(decile=0), "from 0.01 to 1"),
    (lambda d: d["ranker"]["weights"].update(crowding=0.07), "only negative"),
    (lambda d: d["ranker"]["weights"].update(trend=-0.1), "only negative"),
    (lambda d: d["ranker"]["weights"].pop("freshness"), "exactly"),
    (lambda d: d["ranker"]["labels"].update(good=80), "below labels.strong"),
    (lambda d: d["ranker"].update(per_niche_cap=11), "from 1 to 10"),
    (lambda d: d["ranker"].update(version=""), "short name"),
    (lambda d: d["ranker"]["pursuit"].update(crowded_proposals=True), "whole number"),
    (lambda d: d["liked_niches"].update(min=6), "must not exceed"),
]


@pytest.mark.parametrize(("breaks", "message"), BROKEN)
def test_a_broken_file_is_refused(breaks: Callable[[dict[str, Any]], object], message: str) -> None:
    data = raw()
    breaks(data)
    with pytest.raises(RankingConfigError, match=message):
        parse_ranking(data)
