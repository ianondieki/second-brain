"""REQ-DIR-03 queue (REQ-ADM-01; docs/spec/06 6.2 "SLA 2 BD"): the claim review SLA comes from policy.yaml's
``claims`` section, validated strictly, and counts Kenyan business days from the claim's Nairobi submission date to
the end of the due day."""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime
from typing import Any

import pytest
import yaml

from bridge.admin.claims import ClaimSla, ClaimsPolicy, load_claims_policy, parse_claims_policy, review_sla
from bridge.engagements.policy import POLICY_FILE, PolicyError


def data() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(POLICY_FILE.read_text(encoding="utf-8"))
    return copy.deepcopy(loaded)


def test_the_shipped_value_is_two_business_days() -> None:
    assert load_claims_policy() == ClaimsPolicy(review_sla_bd=2)


@pytest.mark.parametrize(
    ("key", "value"), [("review_sla_bd", 0), ("review_sla_bd", 21), ("review_sla_bd", True), ("review_sla_bd", "2")]
)
def test_a_bad_value_stops_the_app(key: str, value: object) -> None:
    raw = data()
    raw["claims"][key] = value
    with pytest.raises(PolicyError, match=r"claims\.review_sla_bd"):
        parse_claims_policy(raw)


def test_an_unknown_key_a_missing_section_or_another_version_stops_the_app() -> None:
    unknown = data()
    unknown["claims"]["dispute_sla_bd"] = 10
    with pytest.raises(PolicyError, match="claims must have exactly"):
        parse_claims_policy(unknown)
    missing = data()
    del missing["claims"]
    with pytest.raises(PolicyError, match="missing section 'claims'"):
        parse_claims_policy(missing)
    with pytest.raises(PolicyError, match="version 1"):
        parse_claims_policy({**data(), "version": 2})
    with pytest.raises(PolicyError, match="version 1"):
        parse_claims_policy(["claims"])


TUESDAY_MORNING = datetime(2026, 3, 3, 7, 0, tzinfo=UTC)  # 10:00 in Nairobi


def sla(due_on: date, business_days_left: int, overdue: bool) -> ClaimSla:
    return ClaimSla(due_on=due_on, business_days_left=business_days_left, overdue=overdue)


@pytest.mark.parametrize(
    ("now", "holidays", "expected"),
    [
        # Two business days after Tuesday: Thursday, due until 23:59:59 in Nairobi.
        (datetime(2026, 3, 3, 9, 0, tzinfo=UTC), frozenset(), sla(date(2026, 3, 5), 2, False)),
        (datetime(2026, 3, 5, 20, 59, 59, tzinfo=UTC), frozenset(), sla(date(2026, 3, 5), 0, False)),
        (datetime(2026, 3, 5, 21, 0, 0, tzinfo=UTC), frozenset(), sla(date(2026, 3, 5), -1, True)),
        # A holiday on the Wednesday moves the due day to Friday.
        (datetime(2026, 3, 3, 9, 0, tzinfo=UTC), frozenset({date(2026, 3, 4)}), sla(date(2026, 3, 6), 2, False)),
        # Overdue a week later: the count goes negative in business days (the weekend does not count).
        (datetime(2026, 3, 12, 9, 0, tzinfo=UTC), frozenset(), sla(date(2026, 3, 5), -5, True)),
    ],
)
def test_the_review_sla_counts_business_days_from_the_nairobi_submission_date(
    now: datetime, holidays: frozenset[date], expected: ClaimSla
) -> None:
    assert review_sla(TUESDAY_MORNING, now, holidays, 2) == expected


def test_the_submission_day_is_the_nairobi_date_not_the_utc_date() -> None:
    """Nairobi is UTC+3: between 21:00 and midnight UTC a claim is already filed on the next day there."""
    # 00:30 on Thursday in Nairobi is 21:30 on Wednesday in UTC: Thursday + 2 BD is Monday (Wednesday + 2 is Friday).
    after_midnight = datetime(2026, 3, 4, 21, 30, tzinfo=UTC)
    assert review_sla(after_midnight, after_midnight, frozenset(), 2) == sla(date(2026, 3, 9), 2, False)
    # 23:30 on Wednesday in Nairobi (20:30 UTC) is Wednesday either way: due Friday.
    before_midnight = datetime(2026, 3, 4, 20, 30, tzinfo=UTC)
    assert review_sla(before_midnight, before_midnight, frozenset(), 2) == sla(date(2026, 3, 6), 2, False)
    # "Today" is Nairobi's too: at 00:30 on Friday there (Thursday in UTC) the claim is due today (0 left, not 1).
    friday = datetime(2026, 3, 5, 21, 30, tzinfo=UTC)
    assert review_sla(before_midnight, friday, frozenset(), 2) == sla(date(2026, 3, 6), 0, False)
