"""Today's five: a developer's streak, kept in code when an attempt finishes (REQ-DEV-01; D-59; P22 card A).

A streak counts consecutive Nairobi days played. ``after_playing`` is what finishing an attempt on ``day`` makes of the
stored ``quiz_profiles`` row: the day after the last one played adds one, any other day starts again at one (a missed
day resets), and the best streak is never below the current one (the table's CHECK). ``shown`` is what a person sees
on ``today``: the stored streak while it is still alive (they played today or yesterday), else 0; the best is kept.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True, slots=True)
class Streak:
    """A ``quiz_profiles`` row's streak columns."""

    current: int = 0
    best: int = 0
    last_played_on: date | None = None


def after_playing(stored: Streak | None, day: date) -> Streak:
    """The streak once an attempt on the Nairobi day ``day`` finished (one attempt a day: ``day`` is new)."""
    before = stored or Streak()
    if before.last_played_on == day:
        return before
    current = before.current + 1 if before.last_played_on == day - timedelta(days=1) else 1
    return Streak(current=current, best=max(before.best, current), last_played_on=day)


def shown(stored: Streak | None, today: date) -> tuple[int, int]:
    """(current, best) on the Nairobi day ``today``: a streak whose last day is before yesterday is over."""
    if stored is None:
        return 0, 0
    alive = stored.last_played_on is not None and today - timedelta(days=1) <= stored.last_played_on <= today
    return (stored.current if alive else 0), stored.best
