"""REQ-PERS-01, REQ-PERS-02 (P23-1): the ranker's f1 is the cosine of the developer's profile embedding and the card's,
``max(0, cosine)`` in [0, 1], when both vectors exist (same model and version, the profiling consent granted: the
card's ``similarity``), else today's keyword share; the Why chip says "Similar to your profile" on the vector path and
keeps today's words on the keyword path; each row records which path f1 took (``f1_source``). Vectors are pinned in
the fake embedder, so the ranking is deterministic."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from bridge.llm.embeddings import FakeEmbedder, cosine, hashed_vector, vector_with_similarity
from bridge.matching.ranker import SIMILAR_WORDS, Card, Developer, features, rank
from bridge.matching.ranking_config import get_ranking
from bridge.matching.trend_facts import ProblemFact, ProblemSignals
from bridge.matching.trending import Trend

CFG = get_ranking()
R, T = CFG.ranker, CFG.trending
NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
LIKED = uuid4()
PROFILE = "Solar pumps for smallholder irrigation"
NEAR, FAR = "Irrigation scheduling for small farms", "Hospital queue management"
WORDS = frozenset({"solar", "pumps", "smallholder", "irrigation"})


def embedder() -> FakeEmbedder:
    """The profile's vector, a card's at cosine 0.9 and another's at 0.05: pinned, not hashed."""
    base = hashed_vector("profile anchor")
    fake = FakeEmbedder({PROFILE: base})
    fake.pin(NEAR, vector_with_similarity(base, 0.9, seed="near"))
    fake.pin(FAR, vector_with_similarity(base, 0.05, seed="far"))
    return fake


def card(title: str, similarity: float | None = None) -> Card:
    fact = ProblemFact(
        id=uuid4(),
        source="research_agent",
        title=title,
        statement="A problem statement.",
        niche_id=LIKED,
        parent_id=None,
        country="KE",
        country_name="Kenya",
        county_code="KE-30",
        county_name=None,
        created_by=None,
        published_at=NOW - timedelta(days=30),
        confidence=Decimal("0.8"),
        status="published",
    )
    trend = Trend(score=1.0, z=0.0, trending=False, new_this_week=False, actors=3)
    return Card(fact, trend, ProblemSignals(proposals=0, orgs_scouting=None, brief=False), similarity)


def near_to_profile(title: str, fake: FakeEmbedder) -> float:
    return cosine(fake.vector_for(PROFILE), fake.vector_for(title))


def dev(personalised: bool = True, keywords: frozenset[str] = WORDS) -> Developer:
    base = Developer(frozenset({LIKED}), frozenset(), "KE-30", personalised)
    return replace(base, keywords=keywords if personalised else frozenset())


def test_f1_is_the_cosine_when_both_vectors_exist() -> None:
    fake = embedder()
    near = near_to_profile(NEAR, fake)
    assert near == pytest.approx(0.9)
    fit = features(card(NEAR, near), dev(), R, NOW)["semantic_fit"]
    assert (fit.applies, fit.source) == (True, "embedding")
    assert fit.raw == near
    assert fit.value == pytest.approx(0.9)


def test_a_negative_cosine_counts_as_no_fit_and_says_nothing() -> None:
    fit = features(card(NEAR, -0.4), dev(), R, NOW)["semantic_fit"]
    assert (fit.applies, fit.raw, fit.value, fit.source) == (True, -0.4, 0.0, "embedding")
    [row] = rank([card(NEAR, -0.4)], dev(), R, T, NOW)
    assert SIMILAR_WORDS not in row.why


def test_a_card_close_to_the_profile_ranks_above_a_far_one_and_says_why() -> None:
    fake = embedder()
    near, far = card(NEAR, near_to_profile(NEAR, fake)), card(FAR, near_to_profile(FAR, fake))
    rows = rank([far, near], dev(), R, T, NOW)
    assert [r.card.fact.title for r in rows] == [NEAR, FAR]
    assert rows[0].score > rows[1].score
    assert SIMILAR_WORDS == "Similar to your profile"
    assert SIMILAR_WORDS in rows[0].why
    assert "Close to your profile" not in rows[0].why
    assert all(r.features["semantic_fit"].source == "embedding" for r in rows)
    again = rank([near, far], dev(), R, T, NOW)
    assert [r.card.fact.id for r in again] == [r.card.fact.id for r in rows]  # deterministic


def test_without_a_card_vector_f1_is_the_keyword_share_as_today() -> None:
    fit = features(card("Solar irrigation pumps break down"), dev(), R, NOW)["semantic_fit"]
    assert (fit.applies, fit.raw, fit.source) == (True, 3, "keywords")
    assert fit.value == min(1.0, 3 / R.semantic_saturation)
    [row] = rank([card("Solar irrigation pumps break down")], dev(), R, T, NOW)
    assert "Close to your profile" in row.why
    assert SIMILAR_WORDS not in row.why


def test_without_the_consent_neither_path_applies() -> None:
    """AC-PERS-3: a card's similarity is never used without the profiling consent (the route does not even read it)."""
    fit = features(card(NEAR, 0.9), dev(personalised=False), R, NOW)["semantic_fit"]
    assert (fit.applies, fit.value, fit.source) == (False, None, None)
    keywords_only = features(card(NEAR), dev(keywords=frozenset()), R, NOW)["semantic_fit"]
    assert (keywords_only.applies, keywords_only.source) == (False, None)


def test_a_similarity_that_is_not_a_number_falls_back_to_keywords() -> None:
    """A zero vector has no cosine (revision 0012's writers refuse one): f1 never reads NaN as a perfect fit."""
    fit = features(card("Solar irrigation pumps break down", float("nan")), dev(), R, NOW)["semantic_fit"]
    assert (fit.applies, fit.raw, fit.source) == (True, 3, "keywords")
