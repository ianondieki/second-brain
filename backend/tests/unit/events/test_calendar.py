"""REQ-DEV-02 (D-61; card test B3, the pure half): the ``.ics`` file is a valid, deterministic VCALENDAR with one
VEVENT (VERSION, PRODID, a stable UID, DTSTART/DTEND the event's UTC instants, text escaped, lines folded at 75 octets
with CRLF) and the Google Calendar link round-trips the times."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from bridge.events import calendar
from bridge.events.calendar import CalendarEvent
from tests.unit.events.ics_parser import instant, one, parse

EAT = timezone(timedelta(hours=3))
EVENT_ID = UUID("01927f00-0000-7000-8000-000000000001")


def event(**changes: object) -> CalendarEvent:
    values: dict[str, object] = {
        "id": EVENT_ID,
        "title": "Rust, Go; and \\ friends",
        "description": "Talks and a workshop.\nBring a laptop, a charger; and questions.",
        "starts_at": datetime(2026, 10, 14, 18, 0, tzinfo=EAT),
        "ends_at": datetime(2026, 10, 14, 20, 30, tzinfo=EAT),
        "updated_at": datetime(2026, 10, 6, 9, 15, 2, tzinfo=UTC),
        "online": False,
        "venue": "iHub, Senteu Plaza",
        "county_name": "Nairobi City",
        "join_url": None,
        "link": "https://events.example.test/rust-go?ref=wazo",
    }
    values.update(changes)
    return CalendarEvent(**values)  # type: ignore[arg-type]


def test_the_file_is_a_valid_vcalendar_with_one_vevent() -> None:
    body = calendar.ics(event(), host="wazo.example", product="Wazo")
    lines = parse(body)
    names = [name for name, _ in lines]
    assert names[:6] == ["BEGIN", "VERSION", "PRODID", "CALSCALE", "METHOD", "BEGIN"]
    assert names[-2:] == ["END", "END"]
    assert (one(lines, "VERSION"), one(lines, "METHOD"), one(lines, "STATUS")) == ("2.0", "PUBLISH", "CONFIRMED")
    assert one(lines, "PRODID") == "-//Wazo//This week//EN"
    assert one(lines, "UID") == f"event-{EVENT_ID}@wazo.example"
    assert instant(one(lines, "DTSTART")) == datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
    assert instant(one(lines, "DTEND")) == datetime(2026, 10, 14, 17, 30, tzinfo=UTC)
    assert instant(one(lines, "DTSTAMP")) == datetime(2026, 10, 6, 9, 15, 2, tzinfo=UTC)
    assert one(lines, "SUMMARY") == "Rust, Go; and \\ friends"
    assert one(lines, "LOCATION") == "iHub, Senteu Plaza, Nairobi City"
    assert one(lines, "DESCRIPTION") == "Talks and a workshop.\nBring a laptop, a charger; and questions."
    assert one(lines, "URL") == "https://events.example.test/rust-go?ref=wazo"
    assert b"SUMMARY:Rust\\, Go\\; and \\\\ friends\r\n" in body  # escaped as RFC 5545 asks


def test_the_file_is_byte_stable_and_the_uid_names_only_the_event() -> None:
    first = calendar.ics(event(), host="wazo.example", product="Wazo")
    assert calendar.ics(event(), host="wazo.example", product="Wazo") == first
    moved = calendar.ics(event(title="Another title"), host="wazo.example", product="Wazo")
    assert one(parse(moved), "UID") == one(parse(first), "UID")


def test_long_lines_fold_at_75_octets_without_splitting_a_character() -> None:
    long_title = "Kiswahili na teknolojia " + chr(0xE9) * 120  # two octets each
    body = calendar.ics(event(title=long_title, description="d" * 900), host="h.example", product="Wazo")
    lines = parse(body)  # refuses any physical line over 75 octets
    assert one(lines, "SUMMARY") == long_title
    assert one(lines, "DESCRIPTION") == "d" * 900
    assert body.count(b"\r\n ") > 10


def test_an_online_event_is_located_at_its_join_address_and_has_no_url_without_a_link() -> None:
    online = event(online=True, venue=None, county_name=None, join_url="https://meet.example.test/abc", link=None)
    lines = parse(calendar.ics(online, host="h.example", product="Wazo"))
    assert one(lines, "LOCATION") == "https://meet.example.test/abc"
    assert "URL" not in [name for name, _ in lines]


def test_the_google_link_round_trips_the_times_and_encodes_every_value() -> None:
    url = calendar.google_calendar_url(event())
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "calendar.google.com", "/calendar/render")
    query = parse_qs(parts.query, strict_parsing=True)
    start, end = query["dates"][0].split("/")
    assert (instant(start), instant(end)) == (
        datetime(2026, 10, 14, 15, 0, tzinfo=UTC),
        datetime(2026, 10, 14, 17, 30, tzinfo=UTC),
    )
    assert query["action"] == ["TEMPLATE"]
    assert query["text"] == ["Rust, Go; and \\ friends"]
    assert query["location"] == ["iHub, Senteu Plaza, Nairobi City"]
    assert query["ctz"] == ["Africa/Nairobi"]
    assert query["details"][0].endswith("\n\nhttps://events.example.test/rust-go?ref=wazo")
    assert not {" ", "\n", ";"} & set(url)


def test_paths_and_host() -> None:
    assert calendar.calendar_path(EVENT_ID) == f"/api/events/{EVENT_ID}/calendar.ics"
    assert calendar.filename(EVENT_ID) == f"event-{EVENT_ID}.ics"
    assert calendar.public_host("https://Wazo.Example:8443/app") == "wazo.example"
    assert calendar.public_host("not a url") == "localhost"
