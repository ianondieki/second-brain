"""REQ-RES-01: the research agent's numbers live in ``config/policy.yaml`` (docs/spec/06 6.5), parsed strictly."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.problems.research.policy import get_research_policy, parse_research_policy


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def test_the_real_file_has_the_spec_numbers() -> None:
    policy = get_research_policy()
    assert (policy.max_searches, policy.max_fetches, policy.max_input_tokens) == (25, 40, 400_000)  # AC-RES-3
    assert policy.discard_below == Decimal("0.40")
    assert policy.weights == {
        "source_quality": Decimal("0.35"),
        "corroboration": Decimal("0.25"),
        "freshness": Decimal("0.20"),
        "extraction_agreement": Decimal("0.20"),
    }
    assert policy.source_quality == {
        "official": Decimal("1.0"),
        "filing": Decimal("0.9"),
        "news": Decimal("0.8"),
        "ngo": Decimal("0.8"),
        "blog": Decimal("0.4"),
        "social": Decimal("0.3"),
    }
    assert (policy.stale_after_months, policy.archive_after_months) == (12, 18)
    assert (policy.min_excerpts, policy.max_excerpts) == (3, 5)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r.pop("max_fetches"), "research must have exactly"),
        (lambda r: r.update(unknown=1), "research must have exactly"),
        (lambda r: r.update(max_searches=26), "max_searches must be a whole number from 0 to 25"),
        (lambda r: r.update(max_fetches=41), "max_fetches must be a whole number from 0 to 40"),
        (lambda r: r.update(min_excerpts=6), "min_excerpts exceeds max_excerpts"),
        (lambda r: r.update(stale_after_months=18), "stale_after_months must be below"),
        (lambda r: r.update(discard_below="1.5"), "discard_below must be from 0 to 1"),
        (lambda r: r.update(discard_below="nope"), "discard_below must be a number"),
        (lambda r: r["weights"].update(freshness="0.30"), "weights must add up to 1"),
        (lambda r: r["weights"].pop("freshness"), "weights must have exactly"),
        (lambda r: r["source_quality"].update(official="2"), "source_quality.official must be from 0 to 1"),
        (lambda r: r.update(max_cards_per_run=True), "max_cards_per_run must be a whole number"),
    ],
)
def test_a_bad_research_section_is_refused(change: Any, message: str) -> None:
    data = raw()
    change(data["research"])
    with pytest.raises(PolicyError, match=message):
        parse_research_policy(data)


def test_a_missing_section_is_refused() -> None:
    data = raw()
    del data["research"]
    with pytest.raises(PolicyError, match="missing section 'research'"):
        parse_research_policy(data)
