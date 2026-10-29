"""Add to calendar, without OAuth or an agent (REQ-DEV-02; D-61; docs/platform/tasks/P22.md section B, "Calendar").

``ics(event)`` writes one event as an iCalendar file (RFC 5545) by hand: no new dependency, and deterministic, so the
same event gives the same bytes every time (``DTSTAMP`` is the event's ``updated_at``, which changes only when its
content or status does). ``VERSION:2.0``, a ``PRODID`` from the product name, ``METHOD:PUBLISH`` and one ``VEVENT``
whose ``UID`` (``event-<uuid>@<the public host>``) never changes, so a calendar that imports the file twice keeps one
entry. Times are UTC (``Z``): unambiguous in every calendar, which shows them in its own zone (Nairobi for the
developers, UTC+3 all year). Text is escaped (backslash, semicolon, comma, line break) and every line is folded at 75
octets with CRLF, never inside a UTF-8 character. ``LOCATION`` is the venue and county, or the join address of an
online event; ``URL`` the event's own link when it has one; the description is the poster's plain text.

``google_calendar_url(event)`` is Google Calendar's template link (``action=TEMPLATE``), every value percent-encoded,
the times as ``<start>Z/<end>Z`` and ``ctz=Africa/Nairobi``: the developer's own browser opens it and they save it
themselves. Both are served for published events only (``bridge.events.router``).

``calendar_file(entries, ...)`` is the same writer for any list of ``Entry`` (REQ-ENG-13, D-70: the deadlines' files and
private feeds, ``bridge.engagements.deadlines``): one ``VEVENT`` per entry in the order given, ``X-WR-CALNAME`` and an
hourly ``X-PUBLISHED-TTL`` when the calendar is named (a subscribed feed), no ``LOCATION`` or ``DESCRIPTION`` line for
an entry without one, and ``TRANSP:TRANSPARENT`` for an entry that marks a moment rather than busy time (a deadline).
``ics(event)`` is one entry through it, byte for byte the file it always was. A calendar with no entry is still a
``VCALENDAR`` (an empty feed): calendar apps read it as a calendar with nothing in it.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID

CRLF: Final = "\r\n"
FOLD_OCTETS: Final = 75
NAIROBI_TZ: Final = "Africa/Nairobi"
GOOGLE_TEMPLATE: Final = "https://calendar.google.com/calendar/render"
MEDIA_TYPE: Final = "text/calendar; charset=utf-8"
FEED_TTL: Final = "PT1H"  # how often a subscribed calendar should look again (X-PUBLISHED-TTL)


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """What a calendar entry carries of a published event."""

    id: UUID
    title: str
    description: str
    starts_at: datetime
    ends_at: datetime
    updated_at: datetime
    online: bool
    venue: str | None
    county_name: str | None
    join_url: str | None
    link: str | None


def calendar_path(event_id: UUID) -> str:
    """The API path of the event's ``.ics`` file."""
    return f"/api/events/{event_id}/calendar.ics"


def filename(event_id: UUID) -> str:
    return f"event-{event_id}.ics"


def public_host(base_url: str) -> str:
    """The host of the web app's public address (``PUBLIC_BASE_URL``): the UID's domain."""
    return (urlsplit(base_url).hostname or "localhost").lower()


def place(event: CalendarEvent) -> str:
    """Where it happens: the venue and county, or the join address of an online event."""
    if event.online:
        return event.join_url or ""
    return ", ".join(part for part in (event.venue, event.county_name) if part)


def utc_stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def escape(value: str) -> str:
    """RFC 5545 TEXT: backslash, semicolon and comma escaped, a line break as ``\\n``."""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return text.replace("\n", "\\n")


def _chunks(line: str) -> Iterator[str]:
    """``line`` in pieces of at most 75 octets (74 after the first: a continuation starts with a space), never
    splitting a character."""
    limit, piece, size = FOLD_OCTETS, "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > limit:
            yield piece
            limit, piece, size = FOLD_OCTETS - 1, "", 0
        piece += char
        size += width
    yield piece


def fold(line: str) -> str:
    """One content line folded at 75 octets: CRLF and a space before each continuation."""
    return (CRLF + " ").join(_chunks(line))


@dataclass(frozen=True, slots=True)
class Entry:
    """One ``VEVENT``: a stable ``uid`` (``<kind>-<id>@<host>``), its ``stamp`` (DTSTAMP), its span, the summary and,
    when set, a location, a description and a URL (an https address: a URI value, not TEXT). ``transparent``: the
    entry marks a moment (a deadline) and never makes the person busy."""

    uid: str
    stamp: datetime
    starts_at: datetime
    ends_at: datetime
    summary: str
    location: str | None = None
    description: str | None = None
    url: str | None = None
    transparent: bool = False


def _vevent(entry: Entry) -> list[str]:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{entry.uid}",
        f"DTSTAMP:{utc_stamp(entry.stamp)}",
        f"DTSTART:{utc_stamp(entry.starts_at)}",
        f"DTEND:{utc_stamp(entry.ends_at)}",
        f"SUMMARY:{escape(entry.summary)}",
    ]
    if entry.location is not None:
        lines.append(f"LOCATION:{escape(entry.location)}")
    if entry.description is not None:
        lines.append(f"DESCRIPTION:{escape(entry.description)}")
    if entry.url:
        lines.append(f"URL:{entry.url}")
    transparency = "TRANSPARENT" if entry.transparent else "OPAQUE"
    return [*lines, "STATUS:CONFIRMED", f"TRANSP:{transparency}", "END:VEVENT"]


def calendar_file(entries: Sequence[Entry], *, product: str, section: str, name: str | None = None) -> bytes:
    """``entries`` as one iCalendar file (see the module docstring); ``section`` names the product's part in the
    ``PRODID`` and ``name`` the calendar a subscription shows."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{escape(product)}//{escape(section)}//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    if name is not None:
        lines += [f"X-WR-CALNAME:{escape(name)}", f"X-PUBLISHED-TTL:{FEED_TTL}"]
    for entry in entries:
        lines += _vevent(entry)
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + CRLF for line in lines).encode("utf-8")


def ics(event: CalendarEvent, *, host: str, product: str) -> bytes:
    """The event as an iCalendar file (see the module docstring)."""
    entry = Entry(
        uid=f"event-{event.id}@{host}",
        stamp=event.updated_at,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        summary=event.title,
        location=place(event),
        description=event.description,
        url=event.link,  # a URI value (https, no whitespace): not TEXT, so not escaped
    )
    return calendar_file([entry], product=product, section="This week")


def google_calendar_url(event: CalendarEvent, *, location: str | None = None, details: bool = True) -> str:
    """Google Calendar's template link for the event (see the module docstring). ``location`` replaces the event's
    place (an email passes the place for people, never the poster's join address) and ``details=False`` leaves out
    the description and the poster's link: an email carries neither (N26)."""
    params = [
        ("action", "TEMPLATE"),
        ("text", event.title),
        ("dates", f"{utc_stamp(event.starts_at)}/{utc_stamp(event.ends_at)}"),
    ]
    if details:
        params.append(("details", event.description if not event.link else f"{event.description}\n\n{event.link}"))
    params += [("location", place(event) if location is None else location), ("ctz", NAIROBI_TZ)]
    return f"{GOOGLE_TEMPLATE}?{urlencode(params, quote_via=quote, safe='')}"
