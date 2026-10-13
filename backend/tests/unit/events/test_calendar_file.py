"""REQ-ENG-13 (D-70; docs/platform/tasks/P27.md track A): the hand-written RFC 5545 writer of This week's events takes
a list of entries and a calendar name, for the deadlines' files and feeds. An event's own file is unchanged; a calendar
of several entries is one VCALENDAR with one VEVENT each (a stable UID each), ``X-WR-CALNAME`` when it is named, every
line folded at 75 octets with CRLF; a deadline is transparent (it never blocks time) and an entry without a location
or a description carries neither line."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from bridge.events import calendar
from bridge.events.calendar import CalendarEvent, Entry
from tests.unit.events.ics_parser import instant, parse

STAMP = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
EAT = timezone(timedelta(hours=3))
DUE = datetime(2026, 10, 16, 20, 59, 59, tzinfo=UTC)  # the end of 16 Oct 2026 in Nairobi


def entry(n: int, **changes: object) -> Entry:
    values: dict[str, object] = {
        "uid": f"stage-{n}@wazo.example",
        "stamp": STAMP,
        "starts_at": DUE + timedelta(days=n),
        "ends_at": DUE + timedelta(days=n, minutes=15),
        "summary": f"Proposal {n} — due",
        "description": "Telco A",
        "url": f"https://wazo.example/dev/engagements/{n}",
        "transparent": True,
    }
    values.update(changes)
    return Entry(**values)  # type: ignore[arg-type]


def vevents(body: bytes) -> list[dict[str, str]]:
    """Each VEVENT's properties, in order."""
    found: list[dict[str, str]] = []
    for name, value in parse(body):
        if (name, value) == ("BEGIN", "VEVENT"):
            found.append({})
        elif found and (name, value) != ("END", "VEVENT") and name not in ("END",):
            found[-1][name] = value
    return found


def test_a_named_calendar_of_several_entries() -> None:
    body = calendar.calendar_file([entry(1), entry(2)], product="Wazo", section="Deadlines", name="Wazo deadlines")
    lines = parse(body)
    names = [name for name, _ in lines]
    assert names[:7] == ["BEGIN", "VERSION", "PRODID", "CALSCALE", "METHOD", "X-WR-CALNAME", "X-PUBLISHED-TTL"]
    assert dict(lines[:7])["PRODID"] == "-//Wazo//Deadlines//EN"
    assert ("X-WR-CALNAME", "Wazo deadlines") in lines
    assert lines[-1] == ("END", "VCALENDAR")
    first, second = vevents(body)
    assert first["UID"] == "stage-1@wazo.example"
    assert second["UID"] == "stage-2@wazo.example"
    assert instant(first["DTSTART"]) == DUE + timedelta(days=1)
    assert instant(first["DTEND"]) - instant(first["DTSTART"]) == timedelta(minutes=15)
    assert instant(first["DTSTAMP"]) == STAMP
    assert first["SUMMARY"] == "Proposal 1 — due"
    assert first["DESCRIPTION"] == "Telco A"
    assert first["URL"] == "https://wazo.example/dev/engagements/1"
    assert first["TRANSP"] == "TRANSPARENT"
    assert "LOCATION" not in first  # none given: no empty line either


def test_an_unnamed_calendar_has_no_name_and_no_refresh_hint() -> None:
    body = calendar.calendar_file([entry(1)], product="Wazo", section="Deadlines")
    names = [name for name, _ in parse(body)]
    assert "X-WR-CALNAME" not in names
    assert "X-PUBLISHED-TTL" not in names


def test_an_empty_calendar_is_still_a_calendar() -> None:
    body = calendar.calendar_file([], product="Wazo", section="Deadlines", name="Wazo deadlines")
    lines = parse(body)
    assert lines[0] == ("BEGIN", "VCALENDAR")
    assert lines[-1] == ("END", "VCALENDAR")
    assert ("BEGIN", "VEVENT") not in lines


def test_text_is_escaped_and_folded_in_every_entry() -> None:
    long = "Kiswahili; na, teknolojia " + chr(0xE9) * 80
    body = calendar.calendar_file(
        [entry(1, summary=long, description=None)], product="Wazo", section="Deadlines", name="A, B; C"
    )
    [only] = vevents(body)
    assert only["SUMMARY"] == long
    assert "DESCRIPTION" not in only
    assert b"X-WR-CALNAME:A\\, B\\; C\r\n" in body


# Two pinned events and the bytes the writer gave them before it took a list of entries (the event writer of
# claude/fervent-mccarthy-0zyqn2, run on these events): a venue with a link, and an online event whose title folds
# just before a two-octet character, whose join address is its location and which has no link.
IN_PERSON = CalendarEvent(
    id=UUID("01927f00-0000-7000-8000-0000000000a1"),
    title="Rust, Go; and \\ friends",
    description="Talks and a workshop.\nBring a laptop, a charger; and questions.",
    starts_at=datetime(2026, 10, 14, 18, 0, tzinfo=EAT),
    ends_at=datetime(2026, 10, 14, 20, 30, tzinfo=EAT),
    updated_at=datetime(2026, 10, 6, 9, 15, 2, tzinfo=UTC),
    online=False,
    venue="iHub, Senteu Plaza",
    county_name="Nairobi City",
    join_url=None,
    link="https://events.example.test/rust-go?ref=wazo",
)
ONLINE = CalendarEvent(
    id=UUID("01927f00-0000-7000-8000-0000000000a2"),
    title="Wasanidi wa programu " * 3 + "abc" + "\u00e9" * 40,  # 74 octets with "SUMMARY:", then a 2-octet character
    description="Line one.\r\nLine two; with a comma, and a backslash \\ " + "x" * 90,
    starts_at=datetime(2026, 11, 2, 9, 30, tzinfo=EAT),
    ends_at=datetime(2026, 11, 2, 11, 0, tzinfo=EAT),
    updated_at=datetime(2026, 10, 7, 23, 59, 59, tzinfo=UTC),
    online=True,
    venue=None,
    county_name=None,
    join_url="https://meet.example.test/abc-defg-hij?pwd=" + "z" * 60,
    link=None,
)
IN_PERSON_ICS = (
    b"BEGIN:VCALENDAR\r\n"
    b"VERSION:2.0\r\n"
    b"PRODID:-//Wazo//This week//EN\r\n"
    b"CALSCALE:GREGORIAN\r\n"
    b"METHOD:PUBLISH\r\n"
    b"BEGIN:VEVENT\r\n"
    b"UID:event-01927f00-0000-7000-8000-0000000000a1@wazo.example\r\n"
    b"DTSTAMP:20261006T091502Z\r\n"
    b"DTSTART:20261014T150000Z\r\n"
    b"DTEND:20261014T173000Z\r\n"
    b"SUMMARY:Rust\\, Go\\; and \\\\ friends\r\n"
    b"LOCATION:iHub\\, Senteu Plaza\\, Nairobi City\r\n"
    b"DESCRIPTION:Talks and a workshop.\\nBring a laptop\\, a charger\\; and questio\r\n"
    b" ns.\r\n"
    b"URL:https://events.example.test/rust-go?ref=wazo\r\n"
    b"STATUS:CONFIRMED\r\n"
    b"TRANSP:OPAQUE\r\n"
    b"END:VEVENT\r\n"
    b"END:VCALENDAR\r\n"
)
ONLINE_ICS = (
    b"BEGIN:VCALENDAR\r\n"
    b"VERSION:2.0\r\n"
    b"PRODID:-//Wazo//This week//EN\r\n"
    b"CALSCALE:GREGORIAN\r\n"
    b"METHOD:PUBLISH\r\n"
    b"BEGIN:VEVENT\r\n"
    b"UID:event-01927f00-0000-7000-8000-0000000000a2@wazo.example\r\n"
    b"DTSTAMP:20261007T235959Z\r\n"
    b"DTSTART:20261102T063000Z\r\n"
    b"DTEND:20261102T080000Z\r\n"
    b"SUMMARY:Wasanidi wa programu Wasanidi wa programu Wasanidi wa programu abc\r\n"
    b" \xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9"
    b"\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9"
    b"\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9"
    b"\xc3\xa9\r\n"
    b" \xc3\xa9\xc3\xa9\xc3\xa9\r\n"
    b"LOCATION:https://meet.example.test/abc-defg-hij?pwd=zzzzzzzzzzzzzzzzzzzzzzz\r\n"
    b" zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz\r\n"
    b"DESCRIPTION:Line one.\\nLine two\\; with a comma\\, and a backslash \\\\ xxxxxxx\r\n"
    b" xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\r\n"
    b" xxxxxxxxx\r\n"
    b"STATUS:CONFIRMED\r\n"
    b"TRANSP:OPAQUE\r\n"
    b"END:VEVENT\r\n"
    b"END:VCALENDAR\r\n"
)


@pytest.mark.parametrize(("pinned", "golden"), [(IN_PERSON, IN_PERSON_ICS), (ONLINE, ONLINE_ICS)])
def test_an_events_file_is_the_same_bytes_as_before(pinned: CalendarEvent, golden: bytes) -> None:
    """``ics`` is now one entry through ``calendar_file``: an event's file is byte for byte what the old writer gave
    (every line, its order, escaping, folding and CRLF)."""
    assert calendar.ics(pinned, host="wazo.example", product="Wazo") == golden
