"""REQ-SCOUT-02: the deterministic score, the selection and the code's "Matched on" line (pure code, no database)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from bridge.matching.config import get_weights
from bridge.matching.pipeline import Candidate, Filters, excluded, final_score, matched_on, score, select_top
from bridge.models.enums import ProposalMaturity

T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
W = get_weights()


def candidate(**overrides: object) -> Candidate:
    base = Candidate(
        proposal_id=uuid4(),
        version_id=uuid4(),
        owner_id=uuid4(),
        published_at=T0,
        title="Mobile money savings for SACCOs",
        problem_statement="Members cannot save small amounts",
        summary="A USSD savings wallet",
        impact_claims="Pilot with 3 SACCOs",
        niche_id=uuid4(),
        niche_name="Microfinance & SACCOs",
        parent_name="Finance",
        county_code="KE-47",
        county_name="Nairobi",
        maturity=ProposalMaturity.MVP,
        ask=None,
        niche_exact=True,
        tagged=False,
        has_problem=True,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def filters(**overrides: object) -> Filters:
    base = Filters(org_id=uuid4(), niches=(uuid4(),), include_keywords=("savings", "ussd", "insurance"))
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_points_follow_the_weights() -> None:
    s = score(candidate(), filters(), W)
    # 2 of 3 keywords found (saturation 2): 50; exact niche: 30; no tag: 0; impact claims and a problem: 10.
    assert s.points == {"keywords": 50.0, "niche": 30.0, "tagged": 0.0, "evidence": 10.0}
    assert s.score == 90
    assert s.keywords_found == ("savings", "ussd")
    assert s.breakdown()["deterministic"] == 90


def test_each_rule_moves_the_score() -> None:
    assert score(candidate(niche_exact=False), filters(), W).score == 50 + 21 + 10  # via the parent niche: 0.7
    assert score(candidate(tagged=True), filters(), W).score == 100
    assert score(candidate(impact_claims=None), filters(), W).score == 85
    assert score(candidate(has_problem=False, impact_claims="  "), filters(), W).score == 80
    one_keyword = filters(include_keywords=("savings", "tractor"))
    assert score(candidate(), one_keyword, W).score == 25 + 30 + 10  # 1 of the 2 needed
    assert score(candidate(), filters(include_keywords=("tractor",)), W).score == 40
    assert score(candidate(), filters(include_keywords=()), W).score == 90  # none listed: the niche decides


def test_keywords_match_case_insensitively_as_substrings() -> None:
    s = score(candidate(title="SAVINGS groups"), filters(include_keywords=("Savings",)), W)
    assert s.keywords_found == ("Savings",)
    assert excluded("A crypto-currency wallet", ["CRYPTO"])
    assert not excluded("A wallet", ["crypto"])


def test_selection_keeps_min_fit_and_orders_by_score_then_age() -> None:
    old, new = candidate(published_at=T0), candidate(published_at=T0 + timedelta(days=1))
    low = candidate(title="Unrelated", summary="", problem_statement="", impact_claims=None, has_problem=False)
    scored = [score(c, filters(), W) for c in (new, low, old)]
    picked = select_top(scored, 60, 10)
    assert [s.candidate for s in picked] == [old, new]  # the low one (30) is under 60; ties: older first
    assert select_top(scored, 60, 1)[0].candidate == old
    assert [s.candidate for s in select_top(scored, 0, 10)] == [old, new, low]
    same = [score(candidate(proposal_id=UUID(int=i), published_at=T0), filters(), W) for i in (2, 1)]
    assert [s.candidate.proposal_id for s in select_top(same, 0, 10)] == [UUID(int=1), UUID(int=2)]


def test_the_final_score_mixes_the_model_in_only_when_it_answered() -> None:
    assert final_score(80, None, W) == 80
    assert final_score(80, 40, W) == 64  # 0.6*80 + 0.4*40
    assert final_score(81, 100, W) == 89  # 88.6 rounds half up
    assert final_score(0, 0, W) == 0
    assert final_score(100, 100, W) == 100


def test_the_code_line_names_the_rules_that_fired() -> None:
    line = matched_on(score(candidate(tagged=True), filters(), W))
    assert line == (
        'Matched on niche Finance › Microfinance & SACCOs; keywords "savings", "ussd"; county Nairobi; maturity mvp;'
        " the developer tagged your organisation."
    )
    bare = candidate(niche_name=None, county_code=None, county_name=None, maturity=None)
    assert matched_on(score(bare, filters(include_keywords=()), W)) == "Matched on your niches."
    assert len(matched_on(score(candidate(), filters(include_keywords=tuple("k" * 60 for _ in range(1))), W))) <= 600
