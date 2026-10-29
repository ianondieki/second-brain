"""REQ-PERS-01 (docs/spec/06 6.7): the hybrid ranker in code. AC-PERS-2: every row carries its feature vector, the
pursuit decision with a reason and at least one Why chip; a card with 10 or more proposals and no market pull is never
Pursue; nothing mentions profit or revenue. Also: normalisation, the score formula, labels, MMR with at most 3 cards
per niche, the exploration slot, the new-card boost, and the profiling consent gating f1 and f9 (AC-PERS-3)."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from bridge.matching.ranker import Card, Developer, features, fit_label, rank, score
from bridge.matching.ranking_config import get_ranking
from bridge.matching.trend_facts import ProblemFact, ProblemSignals
from bridge.matching.trending import Trend

CFG = get_ranking()
R, T = CFG.ranker, CFG.trending
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
PARENT, LIKED, SIBLING, ELSEWHERE = uuid4(), uuid4(), uuid4(), uuid4()
PARENTS = {LIKED: PARENT, SIBLING: PARENT, ELSEWHERE: None}


def card(
    *,
    niche: UUID = LIKED,
    source: str = "research_agent",
    proposals: int = 0,
    orgs: int | None = None,
    z: float | None = 0.0,
    confidence: str | None = "0.8",
    county: str | None = "KE-30",
    age_days: float = 30,
    title: str = "Farmers lose harvests to drought",
) -> Card:
    fact = ProblemFact(
        id=uuid4(),
        source=source,
        title=title,
        statement="Grain farmers cannot plan planting after dry spells.",
        niche_id=niche,
        parent_id=PARENTS.get(niche),
        country="KE",
        country_name="Kenya",
        county_code=county,
        county_name=None,
        created_by=None,
        published_at=NOW - timedelta(days=age_days),
        confidence=None if confidence is None else Decimal(confidence),
        status="published",
    )
    signals = ProblemSignals(proposals=proposals, orgs_scouting=orgs, brief=source == "org_brief")
    trend = Trend(score=1.0, z=z, trending=z is not None and z >= T.z_trending, new_this_week=age_days <= 7, actors=3)
    return Card(fact, trend, signals)


def dev(**changes: object) -> Developer:
    base = Developer(
        liked=frozenset({LIKED}), liked_parents=frozenset({PARENT}), county_code="KE-30", personalised=False
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_features_are_normalised_and_the_score_follows_the_formula() -> None:
    c = card(z=6.0, orgs=3, proposals=2)
    feats = features(c, dev(), R, NOW)
    assert all(ft.value is None or 0 <= ft.value <= 1 for ft in feats.values())
    assert feats["trend"].value == 1.0  # z clipped to +3
    assert feats["trend"].raw == 6.0
    assert (feats["niche_match"].value, feats["region_match"].value) == (1.0, 1.0)
    assert not feats["skill_coverage"].applies
    assert not feats["semantic_fit"].applies  # no profiling consent
    assert not feats["track_record"].applies
    applied = [ft for ft in feats.values() if ft.applies]
    expected = 100 * sum(ft.weight * (ft.value or 0) for ft in applied) / sum(abs(ft.weight) for ft in applied)
    assert score(feats, R, new_card=False) == round(expected)
    assert score(feats, R, new_card=True) == round(expected + 100 * R.new_card_boost)


def test_niche_and_region_matches() -> None:
    assert features(card(niche=SIBLING), dev(), R, NOW)["niche_match"].value == R.niche_adjacent
    assert features(card(niche=ELSEWHERE), dev(), R, NOW)["niche_match"].value == 0
    assert features(card(county=None), dev(), R, NOW)["region_match"].value == R.region_national
    assert features(card(county="KE-01"), dev(), R, NOW)["region_match"].value == 0
    assert not features(card(), dev(county_code=None), R, NOW)["region_match"].applies


def test_labels() -> None:
    assert (fit_label(80, R), fit_label(79, R), fit_label(60, R), fit_label(59, R)) == (
        "Strong fit",
        "Good fit",
        "Good fit",
        "Stretch",
    )


def test_every_row_has_its_features_a_pursuit_reason_and_a_why_chip() -> None:
    """AC-PERS-2 (row half)."""
    cards = [card(), card(niche=ELSEWHERE, confidence="0.45"), card(source="org_brief", confidence=None, proposals=12)]
    for row in rank(cards, dev(), R, T, NOW):
        assert set(row.features) == {
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
        }
        assert row.decision in {"pursue", "consider", "not_now"}
        assert row.reasons
        assert row.why


@pytest.mark.parametrize("orgs", [None, 0])
def test_a_crowded_card_without_market_pull_is_never_pursue(orgs: int | None) -> None:
    """AC-PERS-2: crowding >= 10 proposals and market_pull 0 is never Pursue, whatever else is strong."""
    crowded = card(proposals=10, orgs=orgs, z=3.0, confidence="1.0", age_days=1)
    [row] = rank([crowded], dev(), R, T, NOW)
    assert row.decision == "not_now"
    assert "10 proposals" in row.reasons[0]
    pulled = replace(crowded, signals=replace(crowded.signals, orgs_scouting=3))
    [row] = rank([pulled], dev(), R, T, NOW)
    assert row.decision != "not_now"  # pulled, so not dismissed; still not Pursue while crowded
    assert row.decision == "consider"


def test_a_strong_pulled_card_is_pursue_with_its_reasons() -> None:
    [row] = rank([card(orgs=4, z=2.0, confidence="0.9", age_days=2)], dev(), R, T, NOW)
    assert row.decision == "pursue"
    assert row.reasons[0] == "Organisations are looking for this"
    assert "Trending in its niche" in row.reasons
    # The top positive contributions: niche 0.15, trend 0.10 x 0.83 (already a pursuit reason, so not repeated as a
    # chip), county 0.08, confidence 0.08 x 0.9; market pull 0.10 x 0.67 comes next.
    assert row.why == ("In a niche you like", "In your county", "Backed by cited sources")
    [row] = rank([card(orgs=4, z=2.0, confidence="0.7", county="KE-01")], dev(), R, T, NOW)  # pull now 3rd
    assert "4 companies scouting" in row.why


def test_nothing_mentions_profit_or_revenue() -> None:
    cards = [card(orgs=o, proposals=p, z=z) for o in (None, 3) for p in (0, 12) for z in (None, 0.0, 2.5)]
    words = json.dumps([asdict(r) for r in rank(cards, dev(), R, T, NOW)], default=str).lower()
    for banned in ("profit", "revenue", "income", "kes ", "ksh"):
        assert banned not in words


def test_at_most_three_per_niche_in_the_top_ten_and_one_exploration_slot() -> None:
    others = [uuid4() for _ in range(3)]
    cards = [card(z=2.0, orgs=3) for _ in range(8)] + [card(niche=SIBLING) for _ in range(8)]
    cards += [card(niche=niche, z=-1.0, confidence="0.5") for niche in (ELSEWHERE, *others) for _ in range(4)]
    rows = rank(cards, dev(liked=frozenset({LIKED, *others})), R, T, NOW)
    assert len(rows) == 10
    by_niche: dict[UUID | None, int] = {}
    for row in rows:
        by_niche[row.card.fact.niche_id] = by_niche.get(row.card.fact.niche_id, 0) + 1
    assert max(by_niche.values()) <= 3
    [explore] = [row for row in rows if row.exploring]
    assert explore.card.fact.niche_id == ELSEWHERE
    assert rows[-1] is explore


def test_mmr_spreads_niches_before_repeating_one() -> None:
    liked = [card(z=2.0, orgs=4) for _ in range(3)]
    sibling = card(niche=SIBLING, z=2.0, orgs=3)  # a point or two below the liked niche's cards
    rows = rank([*liked, sibling], dev(liked=frozenset({LIKED, SIBLING})), R, T, NOW)
    assert rows[0].score > rows[1].score
    assert rows[0].card in liked
    assert rows[1].card is sibling  # a close second from another niche beats the same niche's equal cards
    without_mmr = rank([*liked, sibling], dev(liked=frozenset({LIKED, SIBLING})), replace(R, mmr_lambda=1.0), T, NOW)
    assert without_mmr[3].card is sibling  # by score alone it would come last


def test_only_research_cards_and_briefs_are_recommended() -> None:
    rows = rank([card(source="developer"), card(source="org_brief", confidence=None)], dev(), R, T, NOW)
    assert [r.card.fact.source for r in rows] == ["org_brief"]
    assert rows[0].features["evidence_confidence"].raw == R.brief_confidence


def test_profiling_consent_gates_f1_and_f9() -> None:
    """AC-PERS-3 (ranker half): without the consent, f1 and f9 do not apply, whatever history is known."""
    history = {"keywords": frozenset({"farmers", "drought", "harvests"}), "track": {LIKED: (2, 2)}}
    off = features(card(), dev(**history), R, NOW)
    on = features(card(), dev(personalised=True, **history), R, NOW)
    assert (off["semantic_fit"].applies, off["track_record"].applies) == (False, False)
    assert (on["semantic_fit"].applies, on["track_record"].applies) == (True, True)
    assert on["semantic_fit"].raw == 3
    assert on["track_record"].raw == pytest.approx(0.75)
    [row] = rank([card()], dev(personalised=True, **history), R, T, NOW)
    assert "Your past projects" in row.why or "Close to your profile" in row.why  # keywords of the profile only


def test_the_ranking_is_deterministic() -> None:
    cards = [card(z=z, orgs=o) for z in (0.5, 1.5, None) for o in (None, 3)]
    first = [r.card.fact.id for r in rank(cards, dev(), R, T, NOW)]
    assert first == [r.card.fact.id for r in rank(list(reversed(cards)), dev(), R, T, NOW)]


def test_a_brand_new_developer_gets_an_explained_list() -> None:
    """AC-PERS-1 (ranker half): liked niches and a county, no history, no consent: every card explained."""
    rows = rank([card(age_days=2), card(niche=SIBLING), card(niche=ELSEWHERE)], dev(), R, T, NOW)
    assert rows
    assert all(r.why and r.reasons for r in rows)


def test_the_fit_chip_names_where_the_shared_words_come_from() -> None:
    """f1's chip says "past proposals" only when a shared keyword comes from one ([[COPY-REVIEW]])."""
    words = frozenset({"farmers", "drought", "harvests"})
    profile_only = dev(personalised=True, keywords=words)
    from_proposals = dev(personalised=True, keywords=words, proposal_keywords=frozenset({"drought"}))
    [row] = rank([card(niche=ELSEWHERE, county=None)], profile_only, R, T, NOW)
    assert "Close to your profile" in row.why
    assert "Close to your past proposals" not in row.why
    [row] = rank([card(niche=ELSEWHERE, county=None)], from_proposals, R, T, NOW)
    assert "Close to your past proposals" in row.why


def test_trending_wording_only_where_discover_says_trending() -> None:
    """Round-2 MAJOR 2: a high z-score without Discover's actor or score floors is "Rising", never "Trending", in the
    chips and the pursuit reasons alike; and no reason is repeated as a chip."""
    high = card(z=2.714, orgs=4, confidence="0.9", age_days=2)
    rising = replace(high, trend=replace(high.trend, trending=False))
    for c, words, other in ((rising, "Rising in its niche", "Trending"), (high, "Trending in its niche", "Rising")):
        [row] = rank([c], dev(), R, T, NOW)
        assert words in (*row.why, *row.reasons)
        assert not any(other in text for text in (*row.why, *row.reasons))
        assert not set(row.why) & set(row.reasons)
    quiet = replace(rising, signals=replace(rising.signals, orgs_scouting=None))
    [row] = rank([quiet], dev(), R, T, NOW)
    assert "Rising in its niche" in (*row.why, *row.reasons)
    assert all("Trending" not in text for text in (*row.why, *row.reasons))
