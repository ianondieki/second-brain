"""REQ-ENG-14 (docs/platform/tasks/P27.md track B, the unit half): the board's plain rules. A side state sits in the
column of the stage it left (as the stepper shows it); the stage's age counts from its entry from the main path (a
question or a hold does not restart it); "no movement" is an active engagement, not on hold, with no tracker event for
``stalled_after_bd`` Kenyan business days or more (a weekend and a holiday do not count); the column's median age
leaves CLOSED out; the funnel counts each engagement once per group, at its first entry, inside the window."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest

from bridge.engagements import pipeline
from bridge.engagements.pipeline import Change
from bridge.models.enums import EngagementState as S

MASHUJAA = date(2026, 10, 20)
E1, E2, E3 = (UUID(f"01927f00-0000-7000-8000-00000000000{n}") for n in (1, 2, 3))


def at(day: date, hour: int = 9) -> datetime:
    return datetime(day.year, day.month, day.day, hour - 3, tzinfo=UTC)  # hour in Nairobi


@pytest.mark.parametrize(
    ("state", "paused_from", "group"),
    [
        (S.SUBMITTED, None, "review"),
        (S.INFO_REQUESTED, S.UNDER_REVIEW, "review"),
        (S.ON_HOLD, S.CONTACT_MADE, "contact_nda"),
        (S.PROCUREMENT_ROUTE, None, "contact_nda"),
        (S.NEGOTIATION, None, "agreement"),
        (S.DELIVERED, None, "implementation"),
        (S.CLOSED, None, "close"),
        (S.DECLINED, None, None),
        (S.ON_HOLD, None, None),
    ],
)
def test_the_column_of_a_state(state: S, paused_from: S | None, group: str | None) -> None:
    assert pipeline.board_group(state, paused_from) == group


def test_a_side_state_does_not_restart_the_stage() -> None:
    changes = [
        Change(None, S.SUBMITTED, at(date(2026, 10, 1))),
        Change(S.SUBMITTED, S.UNDER_REVIEW, at(date(2026, 10, 2))),
        Change(S.UNDER_REVIEW, S.INFO_REQUESTED, at(date(2026, 10, 5))),
        Change(S.INFO_REQUESTED, S.UNDER_REVIEW, at(date(2026, 10, 7))),
    ]
    fallback = at(date(2026, 10, 9))
    assert pipeline.stage_start(changes, S.UNDER_REVIEW, fallback) == at(date(2026, 10, 2))
    assert pipeline.stage_start(changes[:3], S.UNDER_REVIEW, fallback) == at(date(2026, 10, 2))  # still asking
    assert pipeline.stage_start([], S.UNDER_REVIEW, fallback) == fallback


def test_no_movement_counts_business_days_from_the_last_event() -> None:
    last = at(date(2026, 10, 16))  # Friday
    holidays = frozenset({MASHUJAA})
    # Mon 19, (Tue 20 holiday), Wed 21, Thu 22, Fri 23: 4 business days; Mon 26: 5
    assert pipeline.stalled(S.UNDER_REVIEW, last, at(date(2026, 10, 23)), holidays, 5) is False
    assert pipeline.stalled(S.UNDER_REVIEW, last, at(date(2026, 10, 26)), holidays, 5) is True
    assert pipeline.stalled(S.UNDER_REVIEW, last, at(date(2026, 10, 23)), frozenset(), 5) is True
    assert pipeline.stalled(S.INFO_REQUESTED, last, at(date(2026, 10, 30)), holidays, 5) is True
    assert pipeline.stalled(S.ON_HOLD, last, at(date(2026, 10, 30)), holidays, 5) is False
    assert pipeline.stalled(S.CLOSED, last, at(date(2026, 10, 30)), holidays, 5) is False


def test_the_day_boundary_is_nairobi_s() -> None:
    last = datetime(2026, 10, 16, 20, 30, tzinfo=UTC)  # 23:30 on Friday in Nairobi
    saturday = datetime(2026, 10, 16, 21, 30, tzinfo=UTC)  # 00:30 on Saturday in Nairobi, still Friday in UTC
    assert pipeline.days_since(last, saturday) == 1
    assert pipeline.days_since(last, last) == 0
    assert pipeline.stalled(S.SUBMITTED, last, saturday, frozenset(), 1) is False  # a Saturday is no business day


def test_the_median_age_leaves_closed_out() -> None:
    assert pipeline.median([]) is None
    assert pipeline.median([3]) == 3
    assert pipeline.median([1, 4]) == 2.5
    assert pipeline.median([9, 1, 5]) == 5


def test_the_funnel_counts_first_entries_inside_the_window() -> None:
    now = at(date(2026, 10, 30))
    old = now - timedelta(days=120)
    recent = now - timedelta(days=10)
    changes = {
        # entered review long ago, came back to review recently (a returned question), then contact: counted once
        E1: [
            Change(None, S.SUBMITTED, old),
            Change(S.SUBMITTED, S.UNDER_REVIEW, old),
            Change(S.UNDER_REVIEW, S.INFO_REQUESTED, recent),
            Change(S.INFO_REQUESTED, S.UNDER_REVIEW, recent),
            Change(S.UNDER_REVIEW, S.INTEREST_CONFIRMED, recent),
        ],
        # all inside: review, contact, agreement, implementation, close, CLOSED
        E2: [
            Change(None, S.SUBMITTED, recent),
            Change(S.SUBMITTED, S.UNDER_REVIEW, recent),
            Change(S.UNDER_REVIEW, S.INTEREST_CONFIRMED, recent),
            Change(S.INTEREST_CONFIRMED, S.NEGOTIATION, recent),
            Change(S.NEGOTIATION, S.IN_IMPLEMENTATION, recent),
            Change(S.IN_IMPLEMENTATION, S.SIGN_OFF, recent),
            Change(S.SIGN_OFF, S.CLOSED, recent),
        ],
        # declined inside the window
        E3: [Change(None, S.SUBMITTED, recent), Change(S.SUBMITTED, S.DECLINED, recent)],
    }
    found = pipeline.funnel(changes, now, 90)
    assert found.window_days == 90
    assert found.entered.model_dump() == {
        "review": 2,
        "contact_nda": 2,
        "agreement": 1,
        "implementation": 1,
        "close": 1,
    }
    assert (found.closed, found.ended) == (1, 1)
    assert pipeline.funnel(changes, now + timedelta(days=200), 90).entered.review == 0
