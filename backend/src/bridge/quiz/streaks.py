"""Today's five: a developer's streak, kept in code when an attempt finishes (REQ-DEV-01; D-59; P22 card A).

A streak counts consecutive days *that had an approved set* played: a Nairobi day with no approved set (staff
rejected its draft, or never approved one) is skipped and breaks nobody's streak, while a day with a set the developer
did not play ends it. So Monday to Wednesday played, no set on Thursday, Friday played: a streak of 4.

``after_playing`` is what finishing an attempt on ``day`` makes of the stored ``quiz_profiles`` row: it goes on (one
more) when no approved set is dated after the last day played and before ``day`` (``missed`` 0), and starts again at
one otherwise; the best is never below the current (the table's CHECK). ``shown`` is what a person sees on ``today``:
the stored streak while it is still alive (no approved set dated after their last day played and before today: they
can still play today's), else 0; the best is kept. ``missed_sets`` counts those sets; the caller reads it under its
own role (a developer reads the approved sets up to today, the seed's owner role every set).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

_MISSED: Final = text(
    "SELECT count(*) FROM quiz_sets WHERE status = 'approved' AND quiz_date > :since AND quiz_date < :until"
)


@dataclass(frozen=True, slots=True)
class Streak:
    """A ``quiz_profiles`` row's streak columns."""

    current: int = 0
    best: int = 0
    last_played_on: date | None = None


def after_playing(stored: Streak | None, day: date, *, missed: int) -> Streak:
    """The streak once an attempt on the Nairobi day ``day`` finished (one attempt a day: ``day`` is new).
    ``missed``: approved sets dated after the last day played and before ``day``."""
    before = stored or Streak()
    if before.last_played_on == day:
        return before
    goes_on = before.last_played_on is not None and before.last_played_on < day and missed == 0
    current = before.current + 1 if goes_on else 1
    return Streak(current=current, best=max(before.best, current), last_played_on=day)


def shown(stored: Streak | None, today: date, *, missed: int) -> tuple[int, int]:
    """(current, best) on the Nairobi day ``today``. ``missed``: approved sets dated after the last day played and
    before today (a set the developer did not play ends the streak)."""
    if stored is None:
        return 0, 0
    alive = stored.last_played_on is not None and stored.last_played_on <= today and missed == 0
    return (stored.current if alive else 0), stored.best


async def missed_sets(db: AsyncSession | AsyncConnection, stored: Streak | None, day: date) -> int:
    """The approved sets dated after ``stored``'s last day played and before ``day`` (no query when there can be
    none: never played, or played the day before or on ``day``)."""
    last = None if stored is None else stored.last_played_on
    if last is None or last >= day - timedelta(days=1):
        return 0
    return int(await db.scalar(_MISSED, {"since": last, "until": day}) or 0)
