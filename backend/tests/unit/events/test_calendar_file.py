"""REQ-ENG-13 (D-70; docs/platform/tasks/P27.md track A): the hand-written RFC 5545 writer of This week's events takes
a list of entries and a calendar name, for the deadlines' files and feeds. An event's own file is unchanged; a calendar
of several entries is one VCALENDAR with one VEVENT each (a stable UID each), ``X-WR-CALNAME`` when it is named, every
line folded at 75 octets with CRLF; a deadline is transparent (it never blocks time) and an entry without a location
or a description carries neither line."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bridge.events import calendar
from bridge.events.calendar import Entry
from tests.unit.events.ics_parser import instant, parse
from tests.unit.events.test_calendar import event

STAMP = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
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


def test_an_events_file_is_the_same_bytes_as_before() -> None:
    """``ics`` is now one entry through ``calendar_file``: the event's file keeps every line in its old order."""
    body = calendar.ics(event(), host="wazo.example", product="Wazo")
    names = [name for name, _ in parse(body)]
    assert names == [
        "BEGIN",
        "VERSION",
        "PRODID",
        "CALSCALE",
        "METHOD",
        "BEGIN",
        "UID",
        "DTSTAMP",
        "DTSTART",
        "DTEND",
        "SUMMARY",
        "LOCATION",
        "DESCRIPTION",
        "URL",
        "STATUS",
        "TRANSP",
        "END",
        "END",
    ]
    assert b"TRANSP:OPAQUE\r\n" in body
