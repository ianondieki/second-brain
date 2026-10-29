"""REQ-DEV-02: the trends' numbers in ``config/policy.yaml`` (section ``trends``), validated strictly; the task
``trend_synthesis`` is registered as the card says (Sonnet 5, no tools, Tier 1 only, not confidential, no fallback)."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
import yaml

from bridge.config import get_settings
from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.llm import registry
from bridge.llm.registry import Purpose
from bridge.problems.research.policy import get_research_policy
from bridge.problems.trends.policy import TrendsPolicy, load_trends_policy, parse_trends_policy

TASK = "trend_synthesis"  # bridge.problems.trends.synthesis.TASK


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def test_the_real_policy() -> None:
    assert load_trends_policy() == TrendsPolicy(
        max_excerpts=12,
        max_cards_per_run=3,
        min_support_words=4,
        stale_after_months=6,
        archive_after_months=12,
        draft_attempts=2,
        discard_below=Decimal("0.40"),
    )


def test_scoring_keeps_the_research_weights_with_the_trends_ages() -> None:
    research = get_research_policy()
    scoring = load_trends_policy().scoring(research)
    assert (scoring.weights, scoring.source_quality) == (research.weights, research.source_quality)
    assert (scoring.stale_after_months, scoring.archive_after_months) == (6, 12)
    assert (scoring.min_support_words, scoring.discard_below) == (4, Decimal("0.40"))
    assert (research.stale_after_months, research.archive_after_months) == (12, 18)  # the research policy unchanged


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(version=2), "version 1"),
        (lambda d: d.pop("trends"), "missing section"),
        (lambda d: d["trends"].update(extra=1), "exactly"),
        (lambda d: d["trends"].pop("max_excerpts"), "exactly"),
        (lambda d: d["trends"].update(max_excerpts=0), "1 to 20"),
        (lambda d: d["trends"].update(max_cards_per_run=6), "1 to 5"),
        (lambda d: d["trends"].update(min_support_words=True), "1 to 20"),
        (lambda d: d["trends"].update(draft_attempts=3), "2 to 2"),
        (lambda d: d["trends"].update(stale_after_months=12), "below archive_after_months"),
        (lambda d: d["trends"].update(discard_below="high"), "must be a number"),
        (lambda d: d["trends"].update(discard_below="1.5"), "from 0 to 1"),
        (lambda d: d["trends"].update(discard_below=True), "must be a number"),
    ],
)
def test_a_bad_value_is_refused(mutate: Any, message: str) -> None:
    data = raw()
    mutate(data)
    with pytest.raises(PolicyError, match=message):
        parse_trends_policy(data)


def test_the_task_is_registered_as_the_card_says() -> None:
    reg = registry.load(get_settings().llm_models_file)
    task = reg.task(TASK)
    assert (task.model, task.effort) == (reg.task("research_synthesis").model, "medium")
    assert "sonnet" in task.model
    assert (task.confidential, task.batchable, task.max_tokens) == (False, False, 2048)
    assert task.purpose is Purpose.TIER1_ONLY
    assert task.allowed_tools == ()
    assert (task.fallback_model, task.fallback_effort) == (None, None)
    assert task.free_slots == (1, 2, 3)
    assert TASK in reg.tasks
