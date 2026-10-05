"""REQ-DEV-01: Today's five's numbers in ``config/policy.yaml`` (section ``quiz``), validated strictly."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.engagements.policy import POLICY_FILE, PolicyError
from bridge.quiz.policy import QuizPolicy, load_quiz_policy, parse_quiz_policy


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def test_the_real_policy() -> None:
    assert load_quiz_policy() == QuizPolicy(sources_per_prompt=10, draft_attempts=2, no_repeat_days=60)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(version=2), "version 1"),
        (lambda d: d.pop("quiz"), "missing section"),
        (lambda d: d["quiz"].update(extra=1), "exactly"),
        (lambda d: d["quiz"].pop("draft_attempts"), "exactly"),
        (lambda d: d["quiz"].update(sources_per_prompt=7), "8 to 12"),
        (lambda d: d["quiz"].update(sources_per_prompt=13), "8 to 12"),
        (lambda d: d["quiz"].update(draft_attempts=0), "1 to 3"),
        (lambda d: d["quiz"].update(draft_attempts=True), "1 to 3"),
        (lambda d: d["quiz"].update(no_repeat_days="60"), "1 to 365"),
    ],
)
def test_a_bad_value_is_refused(mutate: Any, message: str) -> None:
    data = raw()
    mutate(data)
    with pytest.raises(PolicyError, match=message):
        parse_quiz_policy(data)
