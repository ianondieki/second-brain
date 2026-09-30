"""The "what to pursue" ranker, hybrid version 1 (REQ-PERS-01; docs/spec/06 6.7), in code only.

Items are only approved research cards and verified organisations' published Briefs (AC-PERS-7: never a candidate,
never a developer's own problem). Each gets the features f1-f10 normalised to [0, 1] and
``score = 100 · Σ w·f / Σ|w|`` over the features that apply (weights in ``config/ranking/weights_v1.yaml``), plus
the new-card boost for 7 days. Then MMR (λ 0.7, similarity by niche) with at most 3 cards per niche in the top 10 and
one exploration slot outside the liked niches, labelled "Exploring". Labels: Strong fit, Good fit, Stretch.

The pursuit recommendation, Pursue / Consider / Not now, is decided here from fit, market pull, trend, crowding and
evidence confidence, always with at least one reason: a card with 10 or more proposals and no market pull is never
Pursue (AC-PERS-2). Why chips are the top positive contributions and the Why-not chip the main drawback, all
written in code; nothing here predicts revenue or profit.

Prototype (prototype-m2-plan.md §6): no embeddings, so f1 is the share of keywords the card shares with the
developer's profile and recent proposals (Tier 1); f4 (skill coverage) has no data and never applies. f1 and f9 use
the developer's own history and apply only with the ``profiling`` consent (AC-PERS-3); without it the ranking uses
the liked niches, the county the developer gave and public facts only.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Final, Literal
from uuid import UUID

from bridge.matching.ranking_config import RankerConfig, TrendConfig
from bridge.matching.trend_facts import ProblemFact, ProblemSignals
from bridge.matching.trending import Trend, nairobi_day

RECOMMENDABLE: Final = frozenset({"research_agent", "org_brief"})
Decision = Literal["pursue", "consider", "not_now"]
DECISION_LABELS: Final[Mapping[Decision, str]] = {"pursue": "Pursue", "consider": "Consider", "not_now": "Not now"}
_WORD: Final = re.compile(r"[a-z0-9]+")
# Words too common in problem statements to say anything about fit.
STOPWORDS: Final = frozenset(
    {
        "about", "after", "also", "been", "between", "cannot", "could", "each", "from", "have", "into", "kenya",
        "more", "most", "need", "needs", "only", "other", "over", "people", "same", "small", "some", "such", "than",
        "that", "their", "them", "then", "there", "these", "they", "this", "those", "through", "time", "until",
        "very", "want", "what", "when", "where", "which", "while", "with", "without", "would", "year", "years",
    }
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Developer:
    liked: frozenset[UUID]
    liked_parents: frozenset[UUID]  # the parents of the liked niches
    county_code: str | None
    personalised: bool  # the profiling consent
    keywords: frozenset[str] = frozenset()  # profile and recent proposals (profiling only)
    track: Mapping[UUID, tuple[int, int]] = field(default_factory=dict)  # niche -> (started, done) (profiling only)
    proposal_keywords: frozenset[str] = frozenset()  # the part of ``keywords`` from their proposals (the chip's word)


@dataclass(frozen=True, slots=True)
class Card:
    fact: ProblemFact
    trend: Trend
    signals: ProblemSignals


@dataclass(frozen=True, slots=True)
class Feature:
    raw: float | None
    value: float | None
    weight: float
    applies: bool


@dataclass(frozen=True, slots=True)
class Ranked:
    card: Card
    score: int
    label: str
    features: Mapping[str, Feature]
    decision: Decision
    reasons: tuple[str, ...]
    why: tuple[str, ...]
    why_not: str | None
    exploring: bool = False


def keywords(text: str, min_length: int) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) >= min_length and w not in STOPWORDS}


def _log_share(x: float, cap: int) -> float:
    return min(1.0, math.log1p(max(x, 0.0)) / math.log1p(cap))


def niche_match(card: Card, dev: Developer, cfg: RankerConfig) -> float:
    niche, parent = card.fact.niche_id, card.fact.parent_id
    if niche is None:
        return 0.0
    if niche in dev.liked:
        return cfg.niche_liked
    if niche in dev.liked_parents or (parent is not None and (parent in dev.liked or parent in dev.liked_parents)):
        return cfg.niche_adjacent
    return 0.0


def market_pull(card: Card) -> int:
    """Scouting organisations (counted from 3) + tenders (no data yet) + verified organisations' Briefs."""
    return (card.signals.orgs_scouting or 0) + int(card.signals.brief)


def age_days(card: Card, now: datetime) -> float:
    """Whole Africa/Nairobi days since publication: the same answer all day (the trends are per day too)."""
    published = card.fact.published_at or now
    return float(max(0, (nairobi_day(now) - nairobi_day(published)).days))


def features(card: Card, dev: Developer, cfg: RankerConfig, now: datetime) -> dict[str, Feature]:
    w = cfg.weights

    def f(name: str, raw: float | None, value: float | None, applies: bool = True) -> tuple[str, Feature]:
        return name, Feature(raw, value if applies else None, w[name], applies)

    shared = len(keywords(f"{card.fact.title} {card.fact.statement}", cfg.min_keyword_length) & dev.keywords)
    if card.fact.county_code is None:
        region = cfg.region_national
    else:
        region = cfg.region_same_county if card.fact.county_code == dev.county_code else 0.0
    z = card.trend.z
    clipped = None if z is None else (max(-cfg.z_clip, min(cfg.z_clip, z)) + cfg.z_clip) / (2 * cfg.z_clip)
    if card.fact.source == "org_brief":
        confidence: float | None = cfg.brief_confidence
    else:
        confidence = None if card.fact.confidence is None else float(card.fact.confidence)
    started, done = dev.track.get(card.fact.niche_id, (0, 0)) if card.fact.niche_id else (0, 0)
    record = (done + 1) / (started + 2)
    age = age_days(card, now)
    return dict(
        (
            f(
                "semantic_fit",
                shared,
                min(1.0, shared / cfg.semantic_saturation),
                dev.personalised and bool(dev.keywords),
            ),
            f("niche_match", None, niche_match(card, dev, cfg)),
            f("region_match", None, region, dev.county_code is not None),
            f("skill_coverage", None, None, False),  # no skills data in the prototype
            f("trend", z, clipped, z is not None),
            f("evidence_confidence", confidence, confidence, confidence is not None),
            f("market_pull", market_pull(card), _log_share(market_pull(card), cfg.market_pull_cap)),
            f("crowding", card.signals.proposals, _log_share(card.signals.proposals, cfg.crowding_cap)),
            f("track_record", record, record, dev.personalised),
            f("freshness", age, 2.0 ** (-age / cfg.freshness_half_life_days)),
        )
    )


def score(feats: Mapping[str, Feature], cfg: RankerConfig, *, new_card: bool) -> int:
    applied = [ft for ft in feats.values() if ft.applies and ft.value is not None]
    denominator = sum(abs(ft.weight) for ft in applied)
    base = sum(ft.weight * (ft.value or 0.0) for ft in applied) / denominator if denominator else 0.0
    total = 100 * (base + (cfg.new_card_boost if new_card else 0.0))
    return max(0, min(100, round(total)))


def fit_label(value: int, cfg: RankerConfig) -> str:
    if value >= cfg.label_strong:
        return "Strong fit"
    return "Good fit" if value >= cfg.label_good else "Stretch"


def pursuit(card: Card, feats: Mapping[str, Feature], value: int, cfg: RankerConfig) -> tuple[Decision, list[str]]:
    """Pursue / Consider / Not now with at least one reason ([[COPY-REVIEW]] the reasons)."""
    p = cfg.pursuit
    proposals = card.signals.proposals
    crowded = proposals >= p.crowded_proposals
    pull = market_pull(card) > 0
    z = card.trend.z
    rising = z is not None and z >= p.pursue_trend_z
    confidence = feats["evidence_confidence"].raw or 0.0
    if crowded and not pull:
        return "not_now", [f"{proposals} proposals already and no organisation is looking for this yet"]
    if value < p.not_now_below_score:
        return "not_now", ["A weak fit with your niches and county"]
    if confidence < p.not_now_below_confidence:
        return "not_now", ["The evidence behind this problem is still thin"]
    if value >= p.pursue_min_score and confidence >= p.pursue_min_confidence and (pull or rising) and not crowded:
        reasons = ["Organisations are looking for this"] if pull else []
        reasons += ["Trending in its niche"] if rising else []
        return "pursue", [*reasons, f"{fit_label(value, cfg)} for you"]
    reasons = [] if pull or rising else ["No organisation demand yet"]
    reasons += [f"Crowded: {proposals} proposals already"] if crowded else []
    reasons += ["A partial fit for you"] if value < p.pursue_min_score else []
    reasons += ["The evidence is still building"] if confidence < p.pursue_min_confidence else []
    return "consider", reasons or ["Worth a closer look"]


def why_chips(
    card: Card, feats: Mapping[str, Feature], cfg: RankerConfig, trend: TrendConfig, dev: Developer
) -> list[str]:
    """The top positive contributions, each only when its fact holds ([[COPY-REVIEW]] the chips). f1's chip names its
    source: the developer's past proposals when a shared keyword comes from one, else their profile."""
    card_words = keywords(f"{card.fact.title} {card.fact.statement}", cfg.min_keyword_length)
    fit = "Close to your past proposals" if card_words & dev.proposal_keywords else "Close to your profile"
    v = {name: (ft.value or 0.0) if ft.applies else 0.0 for name, ft in feats.items()}
    orgs = card.signals.orgs_scouting
    brief = card.signals.brief
    candidates = {
        "semantic_fit": (fit, v["semantic_fit"] > 0),
        "niche_match": (
            "In a niche you like" if v["niche_match"] >= cfg.niche_liked else "Next to a niche you like",
            v["niche_match"] > 0,
        ),
        "region_match": (
            "In your county" if card.fact.county_code else "Nationwide",
            v["region_match"] > 0,
        ),
        "trend": ("Trending in its niche", (card.trend.z or 0.0) >= trend.z_trending),
        "evidence_confidence": (
            "Posted by a verified organisation" if brief else "Backed by cited sources",
            v["evidence_confidence"] >= cfg.pursuit.pursue_min_confidence,
        ),
        "market_pull": (
            f"{orgs} companies scouting" if orgs else "A verified organisation is asking",
            v["market_pull"] > 0,
        ),
        "track_record": (
            "Your past projects",
            (feats["track_record"].raw or 0.0) > 0.5 and feats["track_record"].applies,
        ),
        "freshness": ("New this week", (feats["freshness"].raw or 0.0) <= cfg.new_card_days),
    }
    held = [(feats[n].weight * v[n], n) for n, (_, ok) in candidates.items() if ok]
    held.sort(key=lambda item: (-item[0], item[1]))
    chips = [candidates[n][0] for _, n in held[: cfg.why_chips]]
    return chips or ["Verified organisation brief" if brief else "Research card with cited sources"]


def why_not(card: Card, feats: Mapping[str, Feature], dev: Developer, cfg: RankerConfig) -> str | None:
    proposals = card.signals.proposals
    if proposals:
        return f"{proposals} {'proposal' if proposals == 1 else 'proposals'} already"
    if dev.liked and (feats["niche_match"].value or 0.0) == 0:
        return "Outside your liked niches"
    if (feats["evidence_confidence"].raw or 0.0) < cfg.pursuit.pursue_min_confidence:
        return "The evidence is still building"
    return None


def _similarity(a: ProblemFact, b: ProblemFact) -> float:
    if a.niche_id is not None and a.niche_id == b.niche_id:
        return 1.0
    family_a = {x for x in (a.niche_id, a.parent_id) if x is not None}
    family_b = {x for x in (b.niche_id, b.parent_id) if x is not None}
    return 0.5 if family_a & family_b else 0.0


def _mmr(pool: Sequence[Ranked], slots: int, cfg: RankerConfig, taken: Counter[UUID | None]) -> list[Ranked]:
    chosen: list[Ranked] = []
    remaining = list(pool)
    while remaining and len(chosen) < slots:
        best, best_value = None, -math.inf
        for r in remaining:
            if taken[r.card.fact.niche_id] >= cfg.per_niche_cap and r.card.fact.niche_id is not None:
                continue
            overlap = max((_similarity(r.card.fact, c.card.fact) for c in chosen), default=0.0)
            value = cfg.mmr_lambda * r.score / 100 - (1 - cfg.mmr_lambda) * overlap
            if value > best_value:
                best, best_value = r, value
        if best is None:
            break
        chosen.append(best)
        remaining.remove(best)
        taken[best.card.fact.niche_id] += 1
    return chosen


def rank(cards: Sequence[Card], dev: Developer, cfg: RankerConfig, trend: TrendConfig, now: datetime) -> list[Ranked]:
    """The top ``top_n`` recommendations, deterministic for the same facts."""
    scored = []
    for card in cards:
        if card.fact.source not in RECOMMENDABLE:
            continue
        feats = features(card, dev, cfg, now)
        new_card = age_days(card, now) <= cfg.new_card_days
        value = score(feats, cfg, new_card=new_card)
        decision, reasons = pursuit(card, feats, value, cfg)
        scored.append(
            Ranked(
                card=card,
                score=value,
                label=fit_label(value, cfg),
                features=feats,
                decision=decision,
                reasons=tuple(reasons),
                why=tuple(why_chips(card, feats, cfg, trend, dev)),
                why_not=why_not(card, feats, dev, cfg),
            )
        )
    published = {r.card.fact.id: (r.card.fact.published_at or now).timestamp() for r in scored}
    scored.sort(key=lambda r: (-r.score, -published[r.card.fact.id], str(r.card.fact.id)))
    explore: list[Ranked] = []
    if dev.liked and cfg.exploration_slots:
        outside = [r for r in scored if (r.features["niche_match"].value or 0.0) == 0]
        explore = [replace(r, exploring=True) for r in outside[: cfg.exploration_slots]]
    explored = {r.card.fact.id for r in explore}
    taken: Counter[UUID | None] = Counter(r.card.fact.niche_id for r in explore)
    main = _mmr([r for r in scored if r.card.fact.id not in explored], cfg.top_n - len(explore), cfg, taken)
    return [*main, *explore]
