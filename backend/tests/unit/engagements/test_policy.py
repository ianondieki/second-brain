"""REQ-ENG-01, REQ-BD-01: ``backend/config/policy.yaml`` holds every tracker deadline, and loading it fails closed."""

from __future__ import annotations

import copy
from typing import Any

import pytest
import yaml

from bridge.engagements import policy as p
from bridge.models.enums import EngagementState


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(p.POLICY_FILE.read_text(encoding="utf-8"))
    return data


def test_the_shipped_policy_has_the_spec_deadlines() -> None:
    """docs/spec/06 6.9 "Due rule": stage by stage, in business days."""
    policy = p.get_policy()
    assert p.get_policy() is policy  # read once
    due = {state: policy.stage(state).due_bd for state in p.STAGE_KEYS}
    assert due == {
        EngagementState.ORG_INTEREST: 5,
        EngagementState.SUBMITTED: 10,
        EngagementState.UNDER_REVIEW: 15,
        EngagementState.INTEREST_CONFIRMED: 5,
        EngagementState.CONTACT_MADE: 5,
        EngagementState.NDA_PENDING: 5,
        EngagementState.NDA_SIGNED: 10,
        EngagementState.NEGOTIATION: 7,
        EngagementState.AGREEMENT_SIGNING: 5,
        EngagementState.IN_IMPLEMENTATION: None,
        EngagementState.DELIVERED: 10,
        EngagementState.SIGN_OFF: 5,
        EngagementState.PAYMENT_FINAL: 5,
    }
    assert policy.stage(EngagementState.SUBMITTED).expire_bd == 20
    assert policy.stage(EngagementState.UNDER_REVIEW).expire_bd == 30
    confirmed = policy.stage(EngagementState.INTEREST_CONFIRMED)
    assert (confirmed.escalate_bd, confirmed.expire_bd) == (3, 10)
    assert policy.stage(EngagementState.NDA_PENDING).remind_bd == (2, 4)
    assert policy.stage(EngagementState.CLOSED) == p.StagePolicy()
    assert policy.contact_by_max_bd == 5
    assert policy.decline_other_min_chars == 20
    assert policy.deemed_acceptance_days_max == 90


def _broken(change: str) -> dict[str, Any]:
    data = copy.deepcopy(raw())
    if change == "version":
        data["version"] = 2
    elif change == "stage_missing":
        del data["stages"]["SUBMITTED"]
    elif change == "stage_not_mapping":
        data["stages"]["SUBMITTED"] = 10
    elif change == "stage_unknown_key":
        data["stages"]["SUBMITTED"]["due_days"] = 3
    elif change == "stage_zero":
        data["stages"]["SUBMITTED"]["due_bd"] = 0
    elif change == "stage_bool":
        data["stages"]["SUBMITTED"]["due_bd"] = True
    elif change == "stage_text":
        data["stages"]["SUBMITTED"]["due_bd"] = "10"
    elif change == "remind_not_list":
        data["stages"]["NDA_PENDING"]["remind_bd"] = 2
    elif change == "remind_bad":
        data["stages"]["NDA_PENDING"]["remind_bd"] = [2, 99]
    elif change == "due_missing":
        del data["stages"]["NEGOTIATION"]["due_bd"]
    elif change == "section_missing":
        del data["decline"]
    elif change == "section_keys":
        data["contact"]["extra"] = 1
    elif change == "window":
        data["milestones"]["review_window_bd_default"] = 61
    elif change == "window_order":
        data["milestones"]["review_window_bd_default"] = 30
        data["milestones"]["review_window_bd_max"] = 20
    elif change == "decline_order":
        data["decline"]["other_min_chars"] = 200
        data["decline"]["other_max_chars"] = 100
    elif change == "deemed":
        data["agreement"]["deemed_acceptance_days_max"] = 91
    return data


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "stage_missing",
        "stage_not_mapping",
        "stage_unknown_key",
        "stage_zero",
        "stage_bool",
        "stage_text",
        "remind_not_list",
        "remind_bad",
        "due_missing",
        "section_missing",
        "section_keys",
        "window",
        "window_order",
        "decline_order",
        "deemed",
    ],
)
def test_a_broken_policy_is_refused(change: str) -> None:
    with pytest.raises(p.PolicyError):
        p.parse_policy(_broken(change))


def test_a_policy_that_is_not_a_mapping_is_refused() -> None:
    with pytest.raises(p.PolicyError):
        p.parse_policy(["version", 1])
