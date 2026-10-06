"""This week as developers read it (REQ-DEV-02; D-60, D-61; P22 card B, defaults (2) to (4)).

- ``week_events(db, limit)``: published events starting from Monday 00:00 of the current ISO week to the end of
  Sunday of the next (Africa/Nairobi, on the shared clock), not yet ended, in the caller's county or online, soonest
  first, with whether the caller asked to be reminded: one statement. A developer without a county sees online events
  only. An organisation's event shows only while the organisation is neither suspended nor delisted (a delisted
  organisation is not readable by developers at all, so the join drops it).
- ``event_page(db, id)``: one published event of such an organisation, with its description, for a developer or a
  member of its organisation (the ``.ics`` and the event page); None for anyone else (staff included) and for an event
  that is not published.
- ``can_remind(db, id)``: the event is published, has not ended and its organisation is available; the reminder's
  INSERT policy repeats the first two.
- ``email_state(...)``: what the day-before email's gate (``bridge.reminders.dispatch.email_block``, EM7's) would say
  for the caller: ``on``, ``no_consent`` or ``unverified``.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.sessions import LiveSession
from bridge.events.calendar import CalendarEvent, calendar_path, google_calendar_url
from bridge.events.schemas import EmailState, EventPageOut, WeekEventOut
from bridge.events.service import PLATFORM
from bridge.reminders.dispatch import Recipient, email_block

N26: Final = "n26"  # the day-before email's kind (REQUIREMENTS.md §5 N26)
STRIP_SIZE: Final = 3
# Every statement: a published event of an available organisation (or the platform), with its organiser, county and
# whether the caller asked to be reminded.
_WEEK: Final = text(
    "WITH clock AS (SELECT app_clock_now() AS now, date_trunc('week', app_clock_now() AT TIME ZONE"
    " 'Africa/Nairobi') AS monday) "
    "SELECT e.id, e.org_id, o.legal_name AS org_name, e.title, e.description, e.starts_at, e.ends_at, e.online,"
    " e.venue, e.county_code, r.name AS county_name, e.join_url, e.link, e.updated_at,"
    " EXISTS (SELECT 1 FROM event_reminders m WHERE m.event_id = e.id AND m.user_id = app_user_id()) AS reminder"
    " FROM events e LEFT JOIN organizations o ON o.id = e.org_id LEFT JOIN regions r ON r.code = e.county_code"
    " WHERE e.status = 'published'"
    " AND (e.org_id IS NULL OR (o.id IS NOT NULL AND o.suspended_at IS NULL AND o.delisted_at IS NULL))"
    " AND e.ends_at > (SELECT now FROM clock)"
    " AND e.starts_at >= ((SELECT monday FROM clock) AT TIME ZONE 'Africa/Nairobi')"
    " AND e.starts_at < (((SELECT monday FROM clock) + interval '14 days') AT TIME ZONE 'Africa/Nairobi')"
    " AND (e.online OR e.county_code = (SELECT d.county_code FROM developer_profiles d"
    " WHERE d.user_id = app_user_id()))"
    " ORDER BY e.starts_at, e.id LIMIT :limit"
)
_PAGE: Final = text(
    "SELECT e.id, e.org_id, o.legal_name AS org_name, e.title, e.description, e.starts_at, e.ends_at, e.online,"
    " e.venue, e.county_code, r.name AS county_name, e.join_url, e.link, e.updated_at,"
    " EXISTS (SELECT 1 FROM event_reminders m WHERE m.event_id = e.id AND m.user_id = app_user_id()) AS reminder"
    " FROM events e LEFT JOIN organizations o ON o.id = e.org_id LEFT JOIN regions r ON r.code = e.county_code"
    " WHERE e.status = 'published'"
    " AND (e.org_id IS NULL OR (o.id IS NOT NULL AND o.suspended_at IS NULL AND o.delisted_at IS NULL))"
    " AND e.id = :id AND (app_is_developer() OR (e.org_id IS NOT NULL AND app_is_member(e.org_id)))"
)
_REMINDABLE: Final = text(
    "SELECT e.id FROM events e LEFT JOIN organizations o ON o.id = e.org_id WHERE e.status = 'published'"
    " AND (e.org_id IS NULL OR (o.id IS NOT NULL AND o.suspended_at IS NULL AND o.delisted_at IS NULL))"
    " AND e.id = :id AND e.ends_at > app_clock_now() AND app_is_developer()"
)


def calendar_event(row: Any) -> CalendarEvent:
    return CalendarEvent(
        id=row.id,
        title=row.title,
        description=row.description,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        updated_at=row.updated_at,
        online=row.online,
        venue=row.venue,
        county_name=row.county_name,
        join_url=row.join_url,
        link=row.link,
    )


def _week_event(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "organiser": PLATFORM if row.org_id is None else row.org_name,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "online": row.online,
        "venue": row.venue,
        "county_code": row.county_code,
        "county_name": row.county_name,
        "join_url": row.join_url,
        "link": row.link,
        "reminder": row.reminder,
        "calendar_url": calendar_path(row.id),
        "google_calendar_url": google_calendar_url(calendar_event(row)),
    }


async def week_events(db: AsyncSession, *, limit: int | None = STRIP_SIZE) -> list[WeekEventOut]:
    """This week's and next week's events for the caller (see the module docstring); ``limit`` None: all of them."""
    rows = (await db.execute(_WEEK, {"limit": limit})).all()
    return [WeekEventOut(**_week_event(row)) for row in rows]


async def page_row(db: AsyncSession, event_id: UUID) -> Any | None:
    """The event page's row (see the module docstring), or None."""
    return (await db.execute(_PAGE, {"id": event_id})).one_or_none()


async def event_page(db: AsyncSession, event_id: UUID) -> EventPageOut | None:
    row = await page_row(db, event_id)
    return None if row is None else EventPageOut(**_week_event(row), description=row.description)


async def can_remind(db: AsyncSession, event_id: UUID) -> bool:
    return (await db.execute(_REMINDABLE, {"id": event_id})).one_or_none() is not None


async def email_state(db: AsyncSession, live: LiveSession) -> EmailState:
    """What the day-before email's gate says for the caller (``preference_off`` cannot happen for N26: it is not a
    settable kind, so a stray preference row reads as no consent)."""
    user = live.user
    block = await email_block(db, Recipient(user.id, user.email, user.email_verified_at is not None), N26)
    if block is None:
        return "on"
    return "unverified" if block == "unverified" else "no_consent"
