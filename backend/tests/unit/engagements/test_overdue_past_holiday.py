"""REQ-TRACK-03 (P27 UX fix round, principle 7 "one truth"): an overdue count skips the holidays between the due day
and today, so the tracker's ``due`` (``history.due_out``: the lists, the detail, the board) and the calendar's entry
(``deadlines.build``) give the same number of business days for one deadline. The count is only right when the
holidays it is given reach back to the due day: a set that starts today counts a past holiday as a working day.
"""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from bridge.engagements import deadlines
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import NAIROBI
from bridge.engagements.deadlines import Item
from bridge.engagements.history import due_out
from bridge.engagements.schemas import DeadlineKind

ENGAGEMENT = UUID("01927f00-0000-7000-8000-0000000000f1")
DUE_ON = date(2026, 10, 16)  # a Friday
MASHUJAA = date(2026, 10, 20)  # the Tuesday after: an observed holiday, before today
JAMHURI = date(2026, 12, 12)  # after today: a forward-only set has it as well
TODAY = date(2026, 10, 23)  # the Friday after
HOLIDAYS = frozenset({MASHUJAA, JAMHURI})
NOW = datetime.combine(TODAY, time(9, 0), tzinfo=NAIROBI)


def test_an_overdue_count_skips_a_holiday_between_the_due_day_and_today() -> None:
    late = due_out(sm.end_of_day(DUE_ON), NOW, HOLIDAYS)
    # Mon 19, Wed 21, Thu 22, Fri 23: four business days late (Tuesday 20 is Mashujaa Day)
    assert (late.due_on, late.business_days_left, late.overdue) == (DUE_ON, -4, True)


def test_holidays_from_today_on_count_a_past_holiday_as_a_working_day() -> None:
    """The cause of the two numbers: the holidays loaded from today forward leave Mashujaa Day out."""
    forward_only = frozenset(h for h in HOLIDAYS if h >= TODAY)
    assert due_out(sm.end_of_day(DUE_ON), NOW, forward_only).business_days_left == -5


def test_the_tracker_and_the_calendar_agree_on_one_deadline() -> None:
    deadline = sm.end_of_day(DUE_ON)
    item = Item(
        kind=DeadlineKind.STAGE,
        item_id=ENGAGEMENT,
        title="Under review: Smart irrigation",
        context="Telco A",
        href=f"/dev/engagements/{ENGAGEMENT}",
        due_at=deadline,
        mine=False,
        engagement_id=ENGAGEMENT,
    )
    calendar = deadlines.build(item, now=NOW, holidays=HOLIDAYS).out
    tracker = due_out(deadline, NOW, HOLIDAYS)
    assert (calendar.due_on, calendar.due_at, calendar.business_days_left, calendar.overdue) == (
        tracker.due_on,
        tracker.due_at,
        tracker.business_days_left,
        tracker.overdue,
    )
