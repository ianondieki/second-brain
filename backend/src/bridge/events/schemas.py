"""This week's API shapes (REQ-DEV-02; D-60, D-61; docs/platform/tasks/P22.md section B).

Three readers, three shapes, none of them carrying who posted an event (``created_by``) or who decided it
(``decided_by``: never selected): an organisation's members and staff read ``EventOut`` (every status, the decision
and cancellation times, ``updated_at`` as the version a reviewer read); developers read ``WeekEventOut`` (published
events only, with their own "Remind me" and the two calendar links) and ``EventPageOut`` (the same with the
description). A trend card is ``TrendCardOut`` on Home and ``TrendCardDetailOut`` (with its sources) on its page.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

EventStatus = Literal["draft", "published", "rejected", "cancelled"]
EmailState = Literal["on", "no_consent", "unverified"]
EMAIL_STATE_HELP = (
    "Whether the day-before email (N26) would go to the caller: on, no_consent (the reminders consent is not granted)"
    " or unverified (the address is not confirmed). The morning-of in-app notice (N27) comes either way."
)
# Raw bounds, checked before cleaning (a huge body is refused unread); the stored bounds are bridge.events.text's.
_RAW_LINE, _RAW_BLOCK, _RAW_URL = 600, 5000, 2000


class EventIn(BaseModel):
    """An event as its poster writes it: plain text, times with their offset (stored in UTC), online with a join
    address, or at a venue in a county."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=_RAW_LINE, description="1 to 120 characters, one line")
    description: str = Field(max_length=_RAW_BLOCK, description="1 to 1,000 characters of plain text")
    starts_at: AwareDatetime = Field(description="ISO 8601 with an offset; not in the past")
    ends_at: AwareDatetime = Field(description="After the start and at most 3 days later")
    online: bool
    venue: str | None = Field(default=None, max_length=_RAW_LINE, description="At a venue: 1 to 160 characters")
    county_code: str | None = Field(default=None, max_length=8, description="At a venue: the county's code (KE-30)")
    join_url: str | None = Field(default=None, max_length=_RAW_URL, description="Online: an https address")
    link: str | None = Field(default=None, max_length=_RAW_URL, description="The event's own page: an https address")


class EventOut(BaseModel):
    """An event as its organisation's members and staff read it (any status)."""

    id: UUID
    org_id: UUID | None = Field(description="Null for a platform event (posted by staff)")
    organiser: str | None = Field(
        description='"Platform" for a platform event, else the organisation\'s name (null when it is not listed)'
    )
    title: str
    description: str
    starts_at: datetime
    ends_at: datetime
    online: bool
    venue: str | None
    county_code: str | None
    county_name: str | None
    join_url: str | None
    link: str | None
    status: EventStatus
    decided_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime = Field(description="The version read: a staff decision sends it back as seen")


class EventList(BaseModel):
    items: list[EventOut]


class WeekEventOut(BaseModel):
    """A published event as a developer reads it."""

    id: UUID
    title: str
    organiser: str = Field(description='"Platform" or the organisation\'s name')
    starts_at: datetime
    ends_at: datetime
    online: bool
    venue: str | None
    county_code: str | None
    county_name: str | None
    join_url: str | None
    link: str | None
    reminder: bool = Field(description="The caller asked to be reminded of it")
    calendar_url: str = Field(description="The .ics file (GET, signed in)")
    google_calendar_url: str = Field(description="Google Calendar's template link (no OAuth)")


class EventPageOut(WeekEventOut):
    description: str


class TrendCardOut(BaseModel):
    """A published trend card, labelled "Trend · AI-drafted, human-reviewed on {reviewed_on}"."""

    id: UUID
    title: str
    summary: str
    topic_slug: str
    published_at: datetime
    reviewed_on: date = Field(description="The Nairobi day staff published it (the label's date)")
    seeded_example: bool = Field(
        description="Written by hand for the demo, not by the model: never labelled AI-drafted (no generating call)"
    )


class TrendSourceOut(BaseModel):
    url: str
    publisher: str
    published_date: date
    retrieved_at: date
    quote: str


class TrendCardDetailOut(TrendCardOut):
    named_orgs: list[str]
    sources: list[TrendSourceOut]


class WeekOut(BaseModel):
    events: list[WeekEventOut] = Field(
        description="At most 3: published, in the caller's county or online, starting from Monday of this ISO week to"
        " Sunday of the next (Nairobi), not ended, soonest first"
    )
    trend: TrendCardOut | None = Field(description="The trend of the day (rotates daily); null when none is published")
    reminders_email: EmailState = Field(description=EMAIL_STATE_HELP)


class WeekEventsOut(BaseModel):
    items: list[WeekEventOut]
    reminders_email: EmailState = Field(description=EMAIL_STATE_HELP)


class ReminderOut(BaseModel):
    reminder: bool
    email: EmailState = Field(description=EMAIL_STATE_HELP)


class EventDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["publish", "reject"]
    seen: AwareDatetime = Field(description="The event's updated_at as the reviewer read it")
