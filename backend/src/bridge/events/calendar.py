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
"""

from __future__ import annotations

from collections.abc import Iterator
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


def ics(event: CalendarEvent, *, host: str, product: str) -> bytes:
    """The event as an iCalendar file (see the module docstring)."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//{escape(product)}//This week//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:event-{event.id}@{host}",
        f"DTSTAMP:{utc_stamp(event.updated_at)}",
        f"DTSTART:{utc_stamp(event.starts_at)}",
        f"DTEND:{utc_stamp(event.ends_at)}",
        f"SUMMARY:{escape(event.title)}",
        f"LOCATION:{escape(place(event))}",
        f"DESCRIPTION:{escape(event.description)}",
    ]
    if event.link:
        lines.append(f"URL:{event.link}")  # a URI value (https, no whitespace): not TEXT, so not escaped
    lines += ["STATUS:CONFIRMED", "TRANSP:OPAQUE", "END:VEVENT", "END:VCALENDAR"]
    return "".join(fold(line) + CRLF for line in lines).encode("utf-8")


def google_calendar_url(event: CalendarEvent) -> str:
    """Google Calendar's template link for the event (see the module docstring)."""
    details = event.description if not event.link else f"{event.description}\n\n{event.link}"
    params = [
        ("action", "TEMPLATE"),
        ("text", event.title),
        ("dates", f"{utc_stamp(event.starts_at)}/{utc_stamp(event.ends_at)}"),
        ("details", details),
        ("location", place(event)),
        ("ctz", NAIROBI_TZ),
    ]
    return f"{GOOGLE_TEMPLATE}?{urlencode(params, quote_via=quote, safe='')}"
