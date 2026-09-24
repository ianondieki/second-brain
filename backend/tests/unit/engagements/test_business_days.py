"""Kenyan business-day calendar (REQ-BD-01 groundwork, task REQ-REM-00).

Fixed cases use the real 2026 observed holidays from backend/seed/reference.yaml (the rows the `holidays` table is
seeded from); the Hypothesis properties use the same set plus random extra holidays.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from bridge.engagements.calendar import (
    NAIROBI,
    add_business_days,
    business_days_between,
    is_business_day,
    local_date,
    next_business_day,
)

REFERENCE = Path(__file__).resolve().parents[3] / "seed" / "reference.yaml"


def _observed_holidays() -> frozenset[date]:
    rows = yaml.safe_load(REFERENCE.read_text(encoding="utf-8"))["holidays"]
    return frozenset(row["observed"] for row in rows)


HOLIDAYS = _observed_holidays()
NO_HOLIDAYS: frozenset[date] = frozenset()
PROPS = settings(max_examples=300, database=None, deadline=None)

days_2026_27 = st.dates(min_value=date(2026, 1, 1), max_value=date(2027, 12, 31))
extra_holidays = st.frozensets(days_2026_27, max_size=40)


def test_reference_holidays_are_the_2026_observed_dates() -> None:
    assert date(2026, 6, 1) in HOLIDAYS  # Madaraka Day, a Monday
    assert date(2026, 10, 20) in HOLIDAYS  # Mashujaa Day, a Tuesday
    assert date(2026, 4, 3) in HOLIDAYS  # Good Friday
    assert date(2026, 4, 6) in HOLIDAYS  # Easter Monday
    assert all(isinstance(d, date) and not isinstance(d, datetime) for d in HOLIDAYS)


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 9, 24), True),  # an ordinary Thursday
        (date(2026, 9, 26), False),  # Saturday
        (date(2026, 9, 27), False),  # Sunday
        (date(2026, 6, 1), False),  # Madaraka Day
        (date(2026, 10, 20), False),  # Mashujaa Day
        (date(2026, 10, 21), True),
        (date(2026, 10, 10), False),  # Mazingira Day falls on a Saturday (not moved): a weekend anyway
    ],
)
def test_is_business_day(day: date, expected: bool) -> None:
    assert is_business_day(day, HOLIDAYS) is expected


@pytest.mark.parametrize(
    ("start", "n", "expected"),
    [
        (date(2026, 5, 29), 1, date(2026, 6, 2)),  # Fri + 1 BD skips the weekend and Madaraka Day (Mon)
        (date(2026, 10, 19), 1, date(2026, 10, 21)),  # Mon + 1 BD skips Mashujaa Day (Tue)
        (date(2026, 4, 2), 1, date(2026, 4, 7)),  # Thu + 1 BD skips Good Friday, the weekend, Easter Monday
        (date(2026, 5, 26), 5, date(2026, 6, 4)),  # Idd-ul-Azha (Wed 27 May) and Madaraka Day in one window
        (date(2026, 12, 24), 1, date(2026, 12, 28)),  # Christmas (Fri); Boxing Day is a Saturday
        (date(2026, 9, 24), 20, date(2026, 10, 23)),  # SUBMITTED expiry window (20 BD) across Mashujaa Day
        (date(2026, 9, 24), 10, date(2026, 10, 8)),
        (date(2026, 9, 26), 1, date(2026, 9, 28)),  # from a Saturday: the next business day is day 1
        (date(2026, 9, 24), 0, date(2026, 9, 24)),  # n = 0 on a business day: the day itself
        (date(2026, 9, 26), 0, date(2026, 9, 28)),  # n = 0 on a Saturday: the next business day
        (date(2026, 5, 30), 0, date(2026, 6, 2)),  # n = 0 on a Saturday before Madaraka Day
    ],
)
def test_add_business_days_2026(start: date, n: int, expected: date) -> None:
    assert add_business_days(start, n, HOLIDAYS) == expected


def test_add_business_days_without_holidays_counts_weekdays_only() -> None:
    assert add_business_days(date(2026, 5, 29), 1, NO_HOLIDAYS) == date(2026, 6, 1)
    assert add_business_days(date(2026, 9, 21), 5, NO_HOLIDAYS) == date(2026, 9, 28)


def test_add_business_days_rejects_a_negative_count() -> None:
    with pytest.raises(ValueError, match="n must be >= 0"):
        add_business_days(date(2026, 9, 24), -1, HOLIDAYS)


def test_a_datetime_is_refused_where_a_date_is_expected() -> None:
    # datetime(...) == date(...) is always False, so a datetime would never match a holiday: refuse it.
    moment = datetime(2026, 6, 1, 9, 0, tzinfo=NAIROBI)
    with pytest.raises(TypeError, match="local_date"):
        is_business_day(moment, HOLIDAYS)
    with pytest.raises(TypeError, match="local_date"):
        add_business_days(moment, 1, HOLIDAYS)
    with pytest.raises(TypeError, match="local_date"):
        business_days_between(date(2026, 6, 1), moment, HOLIDAYS)


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (date(2026, 9, 24), date(2026, 9, 24), 0),
        (date(2026, 9, 24), date(2026, 9, 25), 1),
        (date(2026, 9, 25), date(2026, 9, 28), 1),  # Fri -> Mon: only Monday counts
        (date(2026, 9, 26), date(2026, 9, 27), 0),  # Sat -> Sun
        (date(2026, 5, 29), date(2026, 6, 2), 1),  # Madaraka Day is not counted
        (date(2026, 9, 24), date(2026, 10, 23), 20),
        (date(2026, 10, 23), date(2026, 9, 24), -20),  # reversed arguments give the negative count
        (date(2026, 12, 24), date(2027, 1, 4), 5),  # 28-31 Dec and 4 Jan; 25 Dec and 1 Jan are holidays
    ],
)
def test_business_days_between_2026(a: date, b: date, expected: int) -> None:
    assert business_days_between(a, b, HOLIDAYS) == expected


def test_next_business_day_is_on_or_after() -> None:
    assert next_business_day(date(2026, 9, 24), HOLIDAYS) == date(2026, 9, 24)
    assert next_business_day(date(2026, 10, 17), HOLIDAYS) == date(2026, 10, 19)
    assert next_business_day(date(2026, 4, 3), HOLIDAYS) == date(2026, 4, 7)


def test_nairobi_is_the_platform_zone() -> None:
    assert str(NAIROBI) == "Africa/Nairobi"
    assert datetime(2026, 9, 24, 12, 0, tzinfo=NAIROBI).utcoffset() == timedelta(hours=3)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 9, 23, 20, 59, tzinfo=UTC), date(2026, 9, 23)),  # 23:59 EAT
        (datetime(2026, 9, 23, 21, 0, tzinfo=UTC), date(2026, 9, 24)),  # midnight EAT
        (datetime(2026, 9, 24, 0, 30, tzinfo=NAIROBI), date(2026, 9, 24)),
        (datetime(2026, 9, 24, 1, 0, tzinfo=timezone(timedelta(hours=5))), date(2026, 9, 23)),  # 23:00 EAT
    ],
)
def test_local_date_is_the_nairobi_calendar_day(moment: datetime, expected: date) -> None:
    assert local_date(moment) == expected


def test_local_date_refuses_a_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        local_date(datetime(2026, 9, 24, 12, 0))  # noqa: DTZ001 - the naive value is the point of the test


# ----------------------------------------------------------------------------- properties


@PROPS
@given(start=days_2026_27, n=st.integers(min_value=0, max_value=300), extra=extra_holidays)
def test_result_is_always_a_business_day(start: date, n: int, extra: frozenset[date]) -> None:
    holidays = HOLIDAYS | extra
    assert is_business_day(add_business_days(start, n, holidays), holidays)


@PROPS
@given(start=days_2026_27, n=st.integers(min_value=0, max_value=300), extra=extra_holidays)
def test_monotonic_in_n(start: date, n: int, extra: frozenset[date]) -> None:
    holidays = HOLIDAYS | extra
    now, later = add_business_days(start, n, holidays), add_business_days(start, n + 1, holidays)
    assert now <= later
    if n >= 1 or is_business_day(start, holidays):
        assert now < later  # only n = 0 from a non-business day shares its answer with n = 1


@PROPS
@given(start=days_2026_27, n=st.integers(min_value=1, max_value=300), extra=extra_holidays)
def test_between_inverts_add(start: date, n: int, extra: frozenset[date]) -> None:
    holidays = HOLIDAYS | extra
    end = add_business_days(start, n, holidays)
    assert end > start
    assert business_days_between(start, end, holidays) == n
    assert business_days_between(end, start, holidays) == -n


@PROPS
@given(a=days_2026_27, b=days_2026_27, c=days_2026_27)
def test_between_adds_up_across_a_midpoint(a: date, b: date, c: date) -> None:
    total = business_days_between(a, b, HOLIDAYS) + business_days_between(b, c, HOLIDAYS)
    assert total == business_days_between(a, c, HOLIDAYS)


@PROPS
@given(day=days_2026_27, extra=extra_holidays)
def test_business_day_means_weekday_and_not_a_holiday(day: date, extra: frozenset[date]) -> None:
    holidays = HOLIDAYS | extra
    assert is_business_day(day, holidays) == (day.weekday() < 5 and day not in holidays)
    nxt = next_business_day(day, holidays)
    assert nxt >= day
    assert is_business_day(nxt, holidays)
    assert all(not is_business_day(day + timedelta(days=i), holidays) for i in range((nxt - day).days))
