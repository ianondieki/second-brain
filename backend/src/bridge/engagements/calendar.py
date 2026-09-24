"""Kenyan business days (BD) for engagement deadlines and reminders (REQ-BD-01 groundwork).

A business day is Monday to Friday and not a gazetted public holiday. Holidays are passed in as their *observed*
dates (the `holidays.observed_on` column, already moved off a Sunday per the Public Holidays Act); loading them is
the caller's job, so this module never touches the database and every function is pure.

Counting convention: the start day itself is never counted. "n business days after `start`" is the n-th business
day strictly after `start`, and `business_days_between(a, b)` counts the business days `d` with `a < d <= b`, so
`business_days_between(start, add_business_days(start, n)) == n` for every n >= 1.

Deadlines are computed on Nairobi calendar dates: convert a timestamp with `local_date` first. A `datetime` passed
where a `date` is expected raises `TypeError`, because a `datetime` never compares equal to a `date` and would
silently miss every holiday.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import date, datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

NAIROBI: Final = ZoneInfo("Africa/Nairobi")
_ONE_DAY: Final = timedelta(days=1)


def _plain_date(d: date) -> date:
    if isinstance(d, datetime):
        raise TypeError("pass a calendar date, not a datetime (convert timestamps with local_date first)")
    return d


def local_date(ts: datetime) -> date:
    """The Nairobi calendar date of a timezone-aware timestamp. A naive timestamp raises `ValueError`."""
    if ts.tzinfo is None or ts.utcoffset() is None:
        raise ValueError("local_date needs a timezone-aware datetime")
    return ts.astimezone(NAIROBI).date()


def is_business_day(d: date, holidays: Collection[date]) -> bool:
    """True for Monday to Friday unless `d` is one of the observed `holidays`."""
    d = _plain_date(d)
    return d.weekday() < 5 and d not in holidays


def next_business_day(d: date, holidays: Collection[date]) -> date:
    """`d` itself when it is a business day, otherwise the first business day after it."""
    d = _plain_date(d)
    while not is_business_day(d, holidays):
        d += _ONE_DAY
    return d


def add_business_days(start: date, n: int, holidays: Collection[date]) -> date:
    """The n-th business day after `start` (`start` itself is not counted), for n >= 0.

    n = 0 returns `start` when it is a business day, otherwise the next business day, so a result is always a
    business day. From a Saturday, n = 0 and n = 1 therefore both give the following Monday (if it is not a
    holiday). A negative n raises `ValueError`.
    """
    start = _plain_date(start)
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    if n == 0:
        return next_business_day(start, holidays)
    d, counted = start, 0
    while counted < n:
        d += _ONE_DAY
        if is_business_day(d, holidays):
            counted += 1
    return d


def business_days_between(a: date, b: date, holidays: Collection[date]) -> int:
    """Business days `d` with `a < d <= b`; negative (the same count, negated) when `b` is before `a`."""
    a, b = _plain_date(a), _plain_date(b)
    if b < a:
        return -business_days_between(b, a, holidays)
    count, d = 0, a
    while d < b:
        d += _ONE_DAY
        if is_business_day(d, holidays):
            count += 1
    return count
