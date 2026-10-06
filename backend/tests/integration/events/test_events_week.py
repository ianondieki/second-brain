"""REQ-DEV-02 (D-60, D-61; P22 card B tests B1, B3, B5 and the tenancy rules, the developer's half).

- B1: a draft, rejected or cancelled event never appears on ``/api/me/week``, ``/api/me/week/events``,
  ``/api/events/{id}`` or its ``.ics``; nor does an event of a suspended or delisted organisation.
- B5: the strip shows the developer's county or online, never another county, soonest first, at most 3, from Monday of
  this week to Sunday of the next, not ended; ``reminder`` is true after Remind me; the trend of the day rotates.
- B3 (the route): the ``.ics`` is served as an attachment, ``text/calendar``, ``private, no-store``, byte-stable across
  two reads, its times the event's UTC instants; the Google link's dates round-trip.
- Remind me: 201 and idempotent, what the email gate says (on, no_consent, unverified), 404 for an event that is not
  published or has ended; Decline 204, idempotent.
- Tenancy: ``/api/me/week`` 404 for an organisation-only account and for staff; the event page and ``.ics`` for a
  developer or a member of the event's organisation only; no read carries who posted or who decided.
"""

from __future__ import annotations

from datetime import UTC, time, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from tests.integration.events.api_world import (
    MOMBASA,
    NAIROBI_CITY,
    WEEK,
    WEEK_EVENTS,
    Clients,
    WeekDb,
    at,
    cancel,
    cast,
    code,
    consent,
    decide,
    nairobi,
    owner_rows,
    owner_run,
    post,
    published,
    trend_card,
)
from tests.integration.events.test_events_org import keys
from tests.unit.events.ics_parser import instant, one, parse


def ids(items: list[dict[str, object]]) -> list[str]:
    return [str(item["id"]) for item in items]


async def test_nothing_unmoderated_or_unavailable_is_shown(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=2), time(18, 0))
    live = await published(week, p, starts)
    draft = await post(week, p.org.reviewer, p.org.id, starts)
    rejected = await post(week, p.org.reviewer, p.org.id, starts)
    await decide(week, rejected, p.moderator, "reject")
    cancelled = await published(week, p, starts)
    await cancel(week, cancelled, p.org.owner)
    developer = await as_user(p.developer)
    assert ids((await developer.get(WEEK)).json()["events"]) == [str(live)]
    assert ids((await developer.get(WEEK_EVENTS)).json()["items"]) == [str(live)]
    for hidden in (draft, rejected, cancelled):
        assert (await developer.get(f"/api/events/{hidden}")).status_code == 404
        assert (await developer.get(f"/api/events/{hidden}/calendar.ics")).status_code == 404
        assert code(await developer.post(f"/api/me/events/{hidden}/reminder")) == (404, "not_found")
    for change in ("suspended_at = now()", "delisted_at = now()"):
        await owner_run(week, f"UPDATE organizations SET {change} WHERE id = :o", o=p.org.id)
        assert (await developer.get(WEEK)).json()["events"] == []
        assert (await developer.get(f"/api/events/{live}")).status_code == 404
        assert (await developer.get(f"/api/events/{live}/calendar.ics")).status_code == 404
        assert (await developer.post(f"/api/me/events/{live}/reminder")).status_code == 404
        await owner_run(
            week, "UPDATE organizations SET suspended_at = NULL, delisted_at = NULL WHERE id = :o", o=p.org.id
        )
    assert ids((await developer.get(WEEK)).json()["events"]) == [str(live)]


async def test_the_strip_picks_the_county_or_online_soonest_first_this_week_and_next(
    week: WeekDb, as_user: Clients
) -> None:
    monday = week.monday()
    await at(week, monday + timedelta(days=2), time(12, 0))  # Wednesday noon
    p = await cast(week)
    day = monday + timedelta(days=2)
    running = await published(week, p, nairobi(day, time(10, 0)), hours=3, county=NAIROBI_CITY)  # not ended
    soon = await published(week, p, nairobi(day, time(18, 0)), platform=True)  # online, the platform's
    later = await published(week, p, nairobi(day + timedelta(days=3), time(9, 0)), county=NAIROBI_CITY)
    last = await published(week, p, nairobi(monday + timedelta(days=13), time(20, 0)))  # Sunday of next week
    await published(week, p, nairobi(day, time(13, 0)), county=MOMBASA)  # another county
    await published(week, p, nairobi(monday + timedelta(days=14), time(9, 0)))  # the week after next
    await at(week, monday, time(8, 0))  # publish an event of Monday morning before it starts, then end it
    ended = await post(week, p.org.reviewer, p.org.id, nairobi(monday, time(9, 0)))
    await decide(week, ended, p.moderator)
    await at(week, day, time(12, 0))
    developer, other, nowhere = await as_user(p.developer), await as_user(p.other), await as_user(p.nowhere)
    strip = (await developer.get(WEEK)).json()
    assert ids(strip["events"]) == [str(running), str(soon), str(later)]  # at most 3, soonest first
    assert ids((await developer.get(WEEK_EVENTS)).json()["items"]) == [
        str(running),
        str(soon),
        str(later),
        str(last),
    ]
    first = strip["events"][0]
    assert (first["organiser"], first["county_name"], first["online"], first["reminder"]) == (
        p.org.name,
        "Nairobi City",
        False,
        False,
    )
    assert strip["events"][1]["organiser"] == "Platform"
    assert first["calendar_url"] == f"/api/events/{running}/calendar.ics"
    assert not {"created_by", "decided_by", "description"} & keys(strip)
    mombasa = ids((await other.get(WEEK_EVENTS)).json()["items"])
    assert str(running) not in mombasa
    assert str(soon) in mombasa
    assert ids((await nowhere.get(WEEK_EVENTS)).json()["items"]) == [str(soon), str(last)]  # online only
    assert (await developer.post(f"/api/me/events/{later}/reminder")).status_code == 201
    marked = (await developer.get(WEEK)).json()["events"]
    assert [event["reminder"] for event in marked] == [False, False, True]


async def test_the_trend_of_the_day_rotates(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    developer = await as_user(p.developer)
    await trend_card(week, p.admin, title="First trend of the rotation")
    await trend_card(week, p.admin, title="Second trend of the rotation")
    await trend_card(week, p.admin, title="A candidate never shown", decision=None)
    await trend_card(week, p.admin, title="A rejected one never shown", decision="reject")
    cards = await owner_rows(
        week, "SELECT id, title FROM trend_cards WHERE status = 'published' ORDER BY published_at, id"
    )
    shown = []
    for offset in (0, 1):
        day = monday + timedelta(days=offset)
        await at(week, day)
        trend = (await developer.get(WEEK)).json()["trend"]
        expected = cards[day.toordinal() % len(cards)]
        assert (trend["id"], trend["title"]) == (str(expected.id), expected.title)
        assert trend["reviewed_on"] == monday.isoformat()
        shown.append(trend["id"])
    assert shown[0] != shown[1]


async def test_the_calendar_file_and_the_google_link(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    starts = nairobi(monday + timedelta(days=1), time(18, 30))
    event_id = await published(week, p, starts, county=NAIROBI_CITY, title="Rust, Go; and friends")
    developer = await as_user(p.developer)
    first = await developer.get(f"/api/events/{event_id}/calendar.ics")
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "text/calendar; charset=utf-8"
    assert first.headers["content-disposition"] == f'attachment; filename="event-{event_id}.ics"'
    assert (first.headers["cache-control"], first.headers["x-content-type-options"]) == ("private, no-store", "nosniff")
    lines = parse(first.content)
    assert (one(lines, "VERSION"), one(lines, "METHOD")) == ("2.0", "PUBLISH")
    assert one(lines, "PRODID").startswith("-//")
    assert one(lines, "UID") == f"event-{event_id}@localhost"
    assert instant(one(lines, "DTSTART")) == starts.astimezone(UTC)
    assert instant(one(lines, "DTEND")) == (starts + timedelta(hours=2)).astimezone(UTC)
    assert one(lines, "SUMMARY") == "Rust, Go; and friends"
    assert one(lines, "LOCATION") == "iHub, Senteu Plaza, Nairobi City"
    assert b"SUMMARY:Rust\\, Go\\; and friends\r\n" in first.content
    assert (await developer.get(f"/api/events/{event_id}/calendar.ics")).content == first.content  # byte-stable
    [event] = (await developer.get(WEEK)).json()["events"]
    query = parse_qs(urlsplit(event["google_calendar_url"]).query)
    start, end = query["dates"][0].split("/")
    assert (instant(start), instant(end)) == (starts.astimezone(UTC), (starts + timedelta(hours=2)).astimezone(UTC))
    page = (await developer.get(f"/api/events/{event_id}")).json()
    assert (page["description"], page["google_calendar_url"]) == (
        "Talks and a workshop.\nBring a laptop.",
        event["google_calendar_url"],
    )


async def test_remind_me_and_decline_and_what_the_email_gate_says(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    event_id = await published(week, p, nairobi(monday + timedelta(days=1), time(18, 0)))
    developer, other = await as_user(p.developer), await as_user(p.other)
    path = f"/api/me/events/{event_id}/reminder"
    for _ in range(2):  # idempotent
        response = await developer.post(path)
        assert (response.status_code, response.json()) == (201, {"reminder": True, "email": "on"})
    rows = await owner_rows(week, "SELECT user_id FROM event_reminders WHERE event_id = :e", e=event_id)
    assert [r.user_id for r in rows] == [p.developer]
    async with week.owner.begin() as conn:
        await consent(conn, p.other, granted=False)
    assert (await other.post(path)).json() == {"reminder": True, "email": "no_consent"}
    await owner_run(week, "UPDATE users SET email_verified_at = NULL WHERE id = :u", u=p.other)
    assert (await other.get(WEEK)).json()["reminders_email"] == "unverified"
    for _ in range(2):
        assert (await developer.delete(path)).status_code == 204
    assert await owner_rows(week, "SELECT 1 FROM event_reminders WHERE user_id = :u", u=p.developer) == []
    await at(week, monday + timedelta(days=1), time(20, 30))  # it ended at 20:00
    assert code(await developer.post(path)) == (404, "not_found")
    assert (await developer.post(f"/api/me/events/{UUID(int=7)}/reminder")).status_code == 404


async def test_who_reads_this_week(week: WeekDb, as_user: Clients) -> None:
    monday = week.monday()
    await at(week, monday)
    p = await cast(week)
    event_id = await published(week, p, nairobi(monday + timedelta(days=1), time(18, 0)))
    trend = await trend_card(week, p.admin)
    candidate = await trend_card(week, p.admin, decision=None)
    for user in (p.org.owner, p.org.viewer, p.admin, p.moderator):
        client = await as_user(user)
        for path in (WEEK, WEEK_EVENTS, f"/api/me/trends/{trend}", f"/api/me/events/{event_id}/reminder"):
            assert (await client.get(path) if "reminder" not in path else await client.post(path)).status_code == 404
    member = await as_user(p.org.viewer)
    assert (await member.get(f"/api/events/{event_id}")).status_code == 200  # its organisation's event page
    assert (await member.get(f"/api/events/{event_id}/calendar.ics")).status_code == 200
    for stranger in (p.rival.owner, p.admin, p.moderator):
        client = await as_user(stranger)
        assert (await client.get(f"/api/events/{event_id}")).status_code == 404
        assert (await client.get(f"/api/events/{event_id}/calendar.ics")).status_code == 404
    developer = await as_user(p.developer)
    card = (await developer.get(f"/api/me/trends/{trend}")).json()
    assert (card["id"], card["reviewed_on"], [s["publisher"] for s in card["sources"]]) == (
        str(trend),
        monday.isoformat(),
        ["GitHub"],
    )
    assert not {"decided_by", "decided_at", "llm_trace_id", "confidence"} & keys(card)
    assert card["seeded_example"] is True  # no generating call: never labelled AI-drafted
    assert code(await developer.get(f"/api/me/trends/{candidate}")) == (404, "not_found")
    assert (await developer.get(f"/api/events/{event_id}")).status_code == 200
