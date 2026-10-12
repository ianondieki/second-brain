"""REQ-ENG-14 (docs/platform/tasks/P27.md track B, the unit half): the board's plain rules. A side state sits in the
column of the stage it left (as the stepper shows it); the stage's age counts from its entry from the main path (a
question or a hold does not restart it); "no movement" is an active engagement, not on hold, with no tracker event for
``stalled_after_bd`` Kenyan business days or more (a weekend and a holiday do not count); the column's median age
leaves CLOSED out; the funnel counts what falls inside the window: each engagement's first entry per group and its
ending."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from bridge.engagements import pipeline
from bridge.engagements.calendar import NAIROBI
from bridge.engagements.pipeline import Change
from bridge.engagements.schemas import StageGroup
from bridge.models.enums import EngagementState as S

MASHUJAA = date(2026, 10, 20)


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


def test_the_funnel_counts_first_entries_and_endings_inside_the_window() -> None:
    """The database returns each engagement's first entry per group (``min(created_at)``, tested through the API in
    tests/integration/engagements/test_pipeline_api.py) and each ended engagement's terminal state; the window decides,
    its two ends included."""
    now = at(date(2026, 10, 30))
    start = pipeline.window_start(now, 90)
    # Whole Nairobi days: the window opens at midnight EAT 90 days before now's Nairobi day (security re-check MINOR).
    assert start == datetime(2026, 8, 1, 0, 0, tzinfo=NAIROBI)
    assert start == pipeline.window_start(now + timedelta(hours=10), 90)  # the same all day
    recent = now - timedelta(days=10)
    firsts: list[tuple[StageGroup, datetime]] = [
        ("review", start - timedelta(seconds=1)),  # first entered just before the window: not counted
        ("review", start),  # the window's first instant
        ("contact_nda", recent),
        ("agreement", recent),
        ("implementation", recent),
        ("close", now),  # the window's last instant
        ("close", now + timedelta(seconds=1)),  # after now (a moved clock): not counted
    ]
    endings = [
        (S.CLOSED, recent),
        (S.CLOSED, start - timedelta(days=1)),  # closed before the window
        (S.DECLINED, recent),
        (S.WITHDRAWN, start),
        (S.EXPIRED, now),
        (S.TERMINATED, now + timedelta(days=1)),
    ]
    found = pipeline.funnel(firsts, endings, now, 90)
    assert found.window_days == 90
    assert found.entered.model_dump() == {
        "review": 1,
        "contact_nda": 1,
        "agreement": 1,
        "implementation": 1,
        "close": 1,
    }
    assert (found.closed, found.ended) == (1, 3)
    later = pipeline.funnel(firsts, endings, now + timedelta(days=200), 90)
    assert later.entered.model_dump() == dict.fromkeys(pipeline.GROUPS, 0)
    assert (later.closed, later.ended) == (0, 0)
    empty = pipeline.funnel([], [], now, 90)
    assert (empty.entered.review, empty.closed, empty.ended) == (0, 0, 0)


def test_only_the_five_stepper_groups_are_columns() -> None:
    assert pipeline.GROUPS == ("review", "contact_nda", "agreement", "implementation", "close")
    assert pipeline.as_group("agreement") == "agreement"
    with pytest.raises(ValueError, match="stage group"):
        pipeline.as_group("elsewhere")
