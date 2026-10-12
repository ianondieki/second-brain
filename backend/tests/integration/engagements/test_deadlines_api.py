"""REQ-ENG-13 (docs/platform/tasks/P27.md track A, acceptance 1; D-61, D-70), through the API.

Given a developer with a SUBMITTED engagement, an INFO_REQUESTED one, a Brief they pitched to and an engagement on
hold, their calendar lists exactly the first three, sorted by ``due_at``, the SUBMITTED one the organisation's turn and
the question theirs (the hold contributes nothing: its resume date is not a deadline, on either side or in a feed); the
organisation's calendar lists its stage deadlines, its open Briefs and its published events; each entry's ``.ics``
opens at the right instant (the end of the Nairobi day); a deadline that is not the caller's is 404. A feed URL created
in Settings returns the same entries to an unauthenticated ``GET`` (no cookie, ``private, no-store``, the product's
calendar name, a stable UID per entry, ``last_fetched_at`` stamped), a rotated URL makes the old one 404, a revoked
one 404, a member who leaves takes their organisation feed with them, and the 61st read in an hour is 429 with
``Retry-After``. The feed never carries a note, a message, a Brief's statement or a proposal's text.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.config import get_settings
from bridge.engagements import feeds
from bridge.engagements.calendar import NAIROBI, add_business_days
from bridge.engagements.policy import get_policy
from bridge.events.calendar import public_host
from bridge.models.enums import EngagementState
from bridge.teams import limits
from tests.integration.api import make_client
from tests.integration.engagements import deadline_world as dw
from tests.integration.engagements.api_world import (
    Tracker,
    build,
    clients,
    db_today,
    deals_on,
    holidays_of,
    open_engagement,
    run,
    seats,
    walk_to,
)
from tests.unit.events.ics_parser import instant, parse

QUESTION = "Which depots would the pilot cover, and how many sensors each?"
ANSWER = "Three depots in Kiambu, twelve sensors each, maintained by us."
MESSAGE = "Thank you; our procurement lead will call on Thursday about the pilot budget."
HOLD_DAYS = timedelta(days=20)  # a hold's resume date, inside the default window


def vevents(body: bytes) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for name, value in parse(body):
        if (name, value) == ("BEGIN", "VEVENT"):
            found.append({})
        elif found and name != "END":
            found[-1][name] = value
    return found


async def ok(response: httpx.Response) -> Any:
    assert response.status_code == 200, (response.status_code, response.text)
    return response.json()


async def test_the_developer_and_the_organisation_see_their_deadlines(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    submitted = await open_engagement(app_engine, world)
    today = await db_today(owner_engine)
    holidays = await holidays_of(owner_engine)
    sacco = await dw.add_org(owner_engine)
    brief = await dw.add_brief(owner_engine, sacco.id, sacco.owner, today + timedelta(days=18), title="Cold chain")
    asked = await dw.pitch_to_brief(owner_engine, app_engine, world, sacco, brief)
    telco_brief = await dw.add_brief(owner_engine, world.org, world.owner, today + timedelta(days=30), title="Billing")
    starts = datetime.combine(today + timedelta(days=12), time(9, 0), tzinfo=NAIROBI)
    meetup = await dw.add_event(owner_engine, world.org, world.owner, starts, title="Meetup", staff=world.staff)
    third = await dw.add_org(owner_engine)
    held = await dw.pitch(owner_engine, app_engine, world.developer, third.id)
    settings = get_settings()
    people = (world.developer, world.owner, sacco.reviewer, world.outsider)
    third_people = (third.owner, third.reviewer, third.signatory)
    async with (
        clients(app_engine, settings, *people, *third_people) as (dev, owner, reviewer, outsider, *third_seats),
        make_client(app_engine, settings, ip="127.0.9.5") as anon,
    ):
        third_owner, third_reviewer, third_signatory = third_seats
        question = Tracker(asked)
        await question.ok(reviewer, "start-review")
        await question.ok(reviewer, "request-info", {"question": QUESTION})
        # on hold after the organisation's interest: its resume date is not a deadline (contract A)
        hold = Tracker(held)
        await hold.ok(third_reviewer, "start-review")
        contact = {"contact_user_id": str(third.owner), "contact_channel": "phone", "contact_by": str(today)}
        assert (await hold.ok(third_signatory, "approve", contact))["state"] == "INTEREST_CONFIRMED"
        paused = await hold.ok(dev, "pause", {"reason": "Budget committee", "resume_at": str(today + HOLD_DAYS)})
        assert paused["state"] == "ON_HOLD"

        mine = await ok(await dev.get("/api/me/deadlines"))
        items = mine["items"]
        stage_due = add_business_days(today, get_policy().stage(EngagementState.SUBMITTED).due_bd or 0, holidays)
        answer_due = add_business_days(today, get_policy().info_expire_bd, holidays)
        expected = sorted(
            [
                (f"stage:{submitted}", str(stage_due), False, str(submitted)),
                (f"answer:{asked}", str(answer_due), True, str(asked)),
                (f"brief:{brief}", str(today + timedelta(days=18)), True, None),
            ],
            key=lambda row: (row[1], row[0]),  # by due_at (the end of the Nairobi day), then by key
        )
        assert [(i["key"], i["due_on"], i["mine"], i["engagement_id"]) for i in items] == expected
        assert not [i for i in items if i["engagement_id"] == str(held)]  # on hold: nothing, not its resume date
        assert str(today + HOLD_DAYS) not in {i["due_on"] for i in items}
        by_kind = {i["kind"]: i for i in items}
        assert by_kind["stage"]["title"] == "Proposal submitted: RLS proposal"
        assert by_kind["stage"]["context"] == world.org_name
        assert by_kind["stage"]["href"] == f"/dev/engagements/{submitted}"
        assert by_kind["answer"]["title"] == "Information requested: RLS proposal"
        assert by_kind["brief"]["title"] == "Cold chain"
        assert by_kind["brief"]["context"] == sacco.name
        assert by_kind["brief"]["href"] == f"/problems/{brief}"
        stage_at = datetime.fromisoformat(by_kind["stage"]["due_at"])
        assert stage_at.astimezone(NAIROBI).time() == time(23, 59, 59)  # the end of its Nairobi day
        assert stage_at.astimezone(NAIROBI).date() == stage_due
        assert mine["now"]
        assert [i["key"] for i in items] == [i["key"] for i in sorted(items, key=lambda i: i["due_at"])]

        # a window is what falls due inside it
        window = {"from": str(today + timedelta(days=17)), "to": str(today + timedelta(days=19))}
        assert [i["key"] for i in (await ok(await dev.get("/api/me/deadlines", params=window)))["items"]] == [
            f"brief:{brief}"
        ]
        reversed_window = {"from": str(today), "to": str(today - timedelta(days=1))}
        refused = await dev.get("/api/me/deadlines", params=reversed_window)
        assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "invalid_range")

        # the developer's reminded events join their calendar
        await dw.remind(owner_engine, world.developer, meetup)
        reminded = (await ok(await dev.get("/api/me/deadlines")))["items"]
        [event] = [i for i in reminded if i["kind"] == "event"]
        assert (event["key"], event["href"], event["context"], event["overdue"]) == (
            f"event:{meetup}",
            f"/dev/events/{meetup}",
            world.org_name,
            False,
        )
        assert datetime.fromisoformat(event["due_at"]) == starts.astimezone(UTC)

        # the organisation's calendar: its stage deadlines, its open Briefs and its published events
        theirs = (await ok(await owner.get(f"/api/orgs/{world.org}/deadlines")))["items"]
        assert {i["key"] for i in theirs} == {f"stage:{submitted}", f"brief:{telco_brief}", f"event:{meetup}"}
        assert f"stage:{held}" not in {i["key"] for i in theirs}
        org_stage = next(i for i in theirs if i["kind"] == "stage")
        assert org_stage["mine"] is True  # the organisation starts the review
        assert org_stage["href"] == f"/org/engagements/{submitted}"
        assert org_stage["context"] != ""
        org_brief = next(i for i in theirs if i["kind"] == "brief")
        assert org_brief["href"] == f"/org/problems/{telco_brief}?org={world.org}"
        assert next(i for i in theirs if i["kind"] == "event")["href"] == f"/org/events/{meetup}?org={world.org}"
        sacco_items = (await ok(await reviewer.get(f"/api/orgs/{sacco.id}/deadlines")))["items"]
        assert {i["key"]: i["mine"] for i in sacco_items} == {f"answer:{asked}": False, f"brief:{brief}": True}

        # one entry's .ics opens at its instant
        ics = await dev.get(f"/api/me/deadlines/stage/{submitted}/calendar.ics")
        assert ics.status_code == 200
        assert ics.headers["content-type"].startswith("text/calendar")
        assert ics.headers["cache-control"] == "private, no-store"
        assert "attachment" in ics.headers["content-disposition"]
        [entry] = vevents(ics.content)
        assert instant(entry["DTSTART"]) == stage_at
        assert instant(entry["DTEND"]) - instant(entry["DTSTART"]) == timedelta(minutes=15)
        assert entry["SUMMARY"] == "Proposal submitted: RLS proposal — due"
        assert entry["UID"] == f"stage-{submitted}@{public_host(settings.public_base_url)}"
        assert entry["URL"] == f"{settings.public_base_url.rstrip('/')}/dev/engagements/{submitted}"
        org_ics = await owner.get(f"/api/orgs/{world.org}/deadlines/event/{meetup}/calendar.ics")
        [org_entry] = vevents(org_ics.content)
        assert instant(org_entry["DTSTART"]) == starts.astimezone(UTC)
        assert instant(org_entry["DTEND"]) == (starts + timedelta(hours=2)).astimezone(UTC)

        # the held engagement's organisation lists nothing for it either; nor does either side's feed
        third_items = (await ok(await third_owner.get(f"/api/orgs/{third.id}/deadlines")))["items"]
        assert not [i for i in third_items if i["engagement_id"] == str(held)]
        public = settings.public_base_url.rstrip("/")
        read: dict[str, set[str]] = {}
        for side, client, path in (("dev", dev, "/api/me"), ("third", third_owner, f"/api/orgs/{third.id}")):
            feed = await anon.get((await client.post(f"{path}/calendar-feed")).json()["url"].removeprefix(public))
            assert feed.status_code == 200, feed.text
            read[side] = {entry["UID"].split("@")[0] for entry in vevents(feed.content)}
            assert not {f"stage-{held}", f"answer-{held}"} & read[side]
        assert read["dev"] == {i["key"].replace(":", "-", 1) for i in reminded}  # the list's entries, no more
        assert read["third"] == set()  # its only engagement is on hold

        # not the caller's: 404 (another developer, another organisation, a kind that does not apply, on hold)
        for client, path in (
            (dev, f"/api/me/deadlines/stage/{held}/calendar.ics"),
            (third_owner, f"/api/orgs/{third.id}/deadlines/stage/{held}/calendar.ics"),
            (outsider, f"/api/me/deadlines/stage/{submitted}/calendar.ics"),
            (reviewer, f"/api/orgs/{sacco.id}/deadlines/stage/{submitted}/calendar.ics"),
            (dev, f"/api/me/deadlines/answer/{submitted}/calendar.ics"),
            (dev, f"/api/me/deadlines/brief/{telco_brief}/calendar.ics"),
            (dev, f"/api/me/deadlines/milestone/{submitted}/calendar.ics"),
            (outsider, f"/api/orgs/{world.org}/deadlines"),
        ):
            assert (await client.get(path)).status_code == 404, path
        assert (await outsider.get("/api/me/deadlines")).json()["items"] == []


async def test_a_developer_sees_the_briefs_of_the_organisations_they_pitched_to_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Contract A, "a Brief they pitched to": the Brief's organisation is the one the live engagement or open tag
    names. A Brief of one organisation linked to a proposal pitched to another is not the developer's deadline; nor is
    the Brief of a pitch that ended (its engagement declined, its tag closed)."""
    world = await build(owner_engine)
    today = await db_today(owner_engine)
    linked_elsewhere, pitched_elsewhere, declining = [await dw.add_org(owner_engine) for _ in range(3)]
    soon, later = today + timedelta(days=10), today + timedelta(days=11)
    other_brief = await dw.add_brief(owner_engine, linked_elsewhere.id, linked_elsewhere.owner, soon, title="Water")
    elsewhere = await dw.pitch(owner_engine, app_engine, world.developer, pitched_elsewhere.id, other_brief)
    ended_brief = await dw.add_brief(owner_engine, declining.id, declining.owner, later, title="Grid")
    ended = await dw.pitch(owner_engine, app_engine, world.developer, declining.id, ended_brief)
    settings = get_settings()
    async with clients(app_engine, settings, world.developer, declining.signatory) as (dev, signatory):

        async def briefs() -> set[str]:
            items = (await ok(await dev.get("/api/me/deadlines")))["items"]
            return {i["key"] for i in items if i["kind"] == "brief"}

        assert await briefs() == {f"brief:{ended_brief}"}  # a live pitch to the Brief's own organisation
        assert (await dev.get(f"/api/me/deadlines/brief/{other_brief}/calendar.ics")).status_code == 404
        declined = await Tracker(ended).ok(signatory, "decline", {"reason": "NOT_PRIORITY"})
        assert declined["state"] == "DECLINED"
        assert await briefs() == set()
        assert (await dev.get(f"/api/me/deadlines/brief/{ended_brief}/calendar.ics")).status_code == 404
    closed = "SELECT count(*) FROM tags WHERE developer_id = :d AND org_id = :o AND closed_at IS NOT NULL"
    assert await dw.one(owner_engine, closed, d=world.developer, o=declining.id) == 1  # the tag closed with it
    assert await dw.one(owner_engine, "SELECT ended_at IS NOT NULL FROM engagements WHERE id = :e", e=ended)
    assert await dw.one(owner_engine, "SELECT org_id FROM engagements WHERE id = :e", e=elsewhere) == (
        pitched_elsewhere.id
    )


async def test_a_feed_carries_the_list_to_a_calendar_app_and_nothing_else(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    today = await db_today(owner_engine)
    brief = await dw.add_brief(owner_engine, world.org, world.owner, today + timedelta(days=9), title="Fleet")
    starts = datetime.combine(today + timedelta(days=4), time(10, 0), tzinfo=NAIROBI)
    meetup = await dw.add_event(owner_engine, world.org, world.owner, starts, title="Meetup", staff=world.staff)
    await dw.remind(owner_engine, world.developer, meetup)  # an event entry: its title and times, nothing else
    settings = get_settings()
    async with seats(app_engine, settings, world) as s, make_client(app_engine, settings, ip="127.0.9.1") as anon:
        t = Tracker(engagement)
        await t.ok(s.reviewer, "start-review")
        await t.ok(s.reviewer, "request-info", {"question": QUESTION})
        await t.ok(s.dev, "answer-info", {"answer": ANSWER})
        await walk_to(t, s, world, today, "INTEREST_CONFIRMED")
        posted = await s.owner.post(f"/api/engagements/{engagement}/messages", json={"body": MESSAGE})
        assert posted.status_code == 201, posted.text

        assert (await ok(await s.dev.get("/api/me/calendar-feed")))["active"] is False
        created = await s.dev.post("/api/me/calendar-feed")
        assert created.status_code == 201, created.text
        url = created.json()["url"]
        assert url.startswith(f"{settings.public_base_url.rstrip('/')}/api/calendar/")
        assert url.endswith(".ics")
        path = url.removeprefix(settings.public_base_url.rstrip("/"))

        anon.cookies.clear()
        read = await anon.get(path)
        assert read.status_code == 200, read.text
        assert "set-cookie" not in read.headers
        assert read.headers["cache-control"] == "private, no-store"
        assert read.headers["content-type"].startswith("text/calendar")
        assert "x-app-now" in read.headers
        lines = parse(read.content)
        assert ("X-WR-CALNAME", f"{settings.product_name} deadlines") in lines
        listed = (await ok(await s.dev.get("/api/me/deadlines")))["items"]
        host = public_host(settings.public_base_url)
        assert [e["UID"] for e in vevents(read.content)] == [
            f"{i['kind']}-{i['key'].split(':')[1]}@{host}" for i in listed
        ]
        status = await ok(await s.dev.get("/api/me/calendar-feed"))
        assert status["active"] is True
        assert status["last_fetched_at"] is not None

        org_feed = (await s.owner.post(f"/api/orgs/{world.org}/calendar-feed")).json()["url"]
        org_read = await anon.get(org_feed.removeprefix(settings.public_base_url.rstrip("/")))
        assert org_read.status_code == 200
        # a member's feed of the organisation is named for it; the personal feed is the product's alone
        org_names = [value for name, value in parse(org_read.content) if name == "X-WR-CALNAME"]
        assert org_names == [f"{settings.product_name} deadlines · {world.org_name}"]
        assert [value for name, value in lines if name == "X-WR-CALNAME"] == [f"{settings.product_name} deadlines"]
        assert {e["UID"].split("@")[0] for e in vevents(org_read.content)} == {
            f"stage-{engagement}",
            f"brief-{brief}",
            f"event-{meetup}",
        }

        # titles, dates and names only: an event's entry carries neither its description nor its join address
        texts = (QUESTION, ANSWER, MESSAGE, dw.BRIEF_STATEMENT, dw.EVENT_DESCRIPTION, "What it does", "A problem")
        for body in (read.content, org_read.content):
            [event] = [e for e in vevents(body) if e["UID"].startswith(f"event-{meetup}@")]
            assert (event["SUMMARY"], event["DESCRIPTION"]) == ("Meetup", world.org_name)
            assert "LOCATION" not in event
            for secret in (*texts, dw.JOIN_URL):
                assert secret.encode() not in body, secret
                assert secret[:20].encode() not in body, secret
            assert b"meet.example.test" not in body
            assert b"RLS proposal" in body  # the proposal's title is a title

        # rotate: the old URL is gone at once; revoke: the new one too
        rotated = (await s.dev.post("/api/me/calendar-feed")).json()["url"]
        assert rotated != url
        assert (await anon.get(path)).status_code == 404
        new_path = rotated.removeprefix(settings.public_base_url.rstrip("/"))
        assert (await anon.get(new_path)).status_code == 200
        revoked = await s.dev.delete("/api/me/calendar-feed")
        assert revoked.status_code == 204
        gone = await anon.get(new_path)
        assert gone.status_code == 404
        assert gone.json()["detail"]["code"] == "not_found"
        assert (await s.dev.delete("/api/me/calendar-feed")).status_code == 204  # idempotent
        assert (await ok(await s.dev.get("/api/me/calendar-feed")))["active"] is False

        # malformed or unknown tokens: the same 404
        for bad in ("/api/calendar/nope.ics", f"/api/calendar/{'A' * 43}.ics", f"/api/calendar/{'A' * 42}B.ics"):
            assert (await anon.get(bad)).status_code == 404, bad

        # a member who leaves the organisation takes their feed of it with them
        org_path = org_feed.removeprefix(settings.public_base_url.rstrip("/"))
        async with owner_engine.begin() as conn:
            await run(
                conn,
                "UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u",
                o=world.org,
                u=world.owner,
            )
        assert (await anon.get(org_path)).status_code == 404
        live = "SELECT count(*) FROM calendar_feeds WHERE user_id = :u AND revoked_at IS NULL"
        assert await dw.one(owner_engine, live, u=world.owner) == 0  # revoked by the database, not only unread
        async with owner_engine.begin() as conn:
            await run(
                conn,
                "UPDATE memberships SET status = 'active' WHERE org_id = :o AND user_id = :u",
                o=world.org,
                u=world.owner,
            )
        assert (await anon.get(org_path)).status_code == 404  # coming back does not revive the old URL

        # a suspended account's feeds all die
        personal = (await s.dev.post("/api/me/calendar-feed")).json()["url"]
        personal_path = personal.removeprefix(settings.public_base_url.rstrip("/"))
        assert (await anon.get(personal_path)).status_code == 200
        async with owner_engine.begin() as conn:
            await run(conn, "UPDATE users SET status = 'suspended' WHERE id = :u", u=world.developer)
        assert (await anon.get(personal_path)).status_code == 404
        assert await dw.one(owner_engine, live, u=world.developer) == 0


async def test_a_feed_is_read_at_most_60_times_an_hour(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    await open_engagement(app_engine, world)
    settings = get_settings()
    async with (
        clients(app_engine, settings, world.developer) as (dev,),
        make_client(app_engine, settings, ip="127.0.9.2") as anon,
    ):
        url = (await dev.post("/api/me/calendar-feed")).json()["url"]
        path = url.removeprefix(settings.public_base_url.rstrip("/"))
        for _ in range(60):
            assert (await anon.get(path)).status_code == 200
        refused = await anon.get(path)
        assert refused.status_code == 429
        assert refused.json()["detail"]["code"] == "too_many_fetches"
        assert 1 <= int(refused.headers["retry-after"]) <= 3600
        assert "set-cookie" not in refused.headers
        # a new URL is a new feed with its own count
        fresh = (await dev.post("/api/me/calendar-feed")).json()["url"]
        assert (await anon.get(fresh.removeprefix(settings.public_base_url.rstrip("/")))).status_code == 200


async def test_a_feed_the_bound_read_does_not_confirm_is_404_and_spends_nothing(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bound re-read (``feeds.verify``) is the token's second check: when the lookup's answer is not the row the
    feed's own user reads (another organisation or another user than the row's, or a feed revoked between the two
    reads), the read answers the same 404, records no fetch in the ledger and stamps nothing."""
    world = await build(owner_engine)
    await open_engagement(app_engine, world)
    settings = get_settings()
    async with (
        clients(app_engine, settings, world.developer) as (dev,),
        make_client(app_engine, settings, ip="127.0.9.4") as anon,
    ):
        url = (await dev.post("/api/me/calendar-feed")).json()["url"]
        path = url.removeprefix(settings.public_base_url.rstrip("/"))
        live = "SELECT id FROM calendar_feeds WHERE user_id = :u AND revoked_at IS NULL"
        feed_id = await dw.one(owner_engine, live, u=world.developer)

        def answer(found: feeds.FeedRef) -> None:
            async def lookup(db: AsyncSession, digest: bytes) -> feeds.FeedRef:
                return found

            monkeypatch.setattr(feeds, "lookup", lookup)

        for forged in (
            feeds.FeedRef(feed_id, world.developer, world.org),  # the developer's own feed bound to an organisation
            feeds.FeedRef(feed_id, world.owner, None),  # another user's binding: their RLS hides the row
        ):
            answer(forged)
            refused = await anon.get(path)
            assert (refused.status_code, refused.json()["detail"]["code"]) == (404, "not_found"), forged
            assert "set-cookie" not in refused.headers

        assert (await dev.delete("/api/me/calendar-feed")).status_code == 204
        answer(feeds.FeedRef(feed_id, world.developer, None))  # found live, revoked before the bound read
        gone = await anon.get(path)
        assert (gone.status_code, gone.json()["detail"]["code"]) == (404, "not_found")
    ledger = limits.ledger_keys(settings.secret_key.get_secret_value(), feeds.FETCH_PURPOSE, feed_id).email
    assert await dw.one(owner_engine, "SELECT count(*) FROM login_attempts WHERE email_digest = :d", d=ledger) == 0
    assert await dw.one(owner_engine, "SELECT last_fetched_at FROM calendar_feeds WHERE id = :f", f=feed_id) is None


async def test_feeds_are_audited_by_id_and_need_a_session(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    settings = get_settings()
    async with (
        clients(app_engine, settings, world.developer) as (dev,),
        make_client(app_engine, settings, ip="127.0.9.3") as anon,
    ):
        assert (await anon.post("/api/me/calendar-feed")).status_code == 401
        assert (await anon.get("/api/me/deadlines")).status_code == 401
        await dev.post("/api/me/calendar-feed")
        await dev.post("/api/me/calendar-feed")
        await dev.delete("/api/me/calendar-feed")
    actions = await dw.one(
        owner_engine,
        "SELECT array_agg(action ORDER BY id) FROM audit_events"
        " WHERE actor_user_id = :u AND action LIKE 'calendar_feed.%'",
        u=world.developer,
    )
    assert actions == ["calendar_feed.created", "calendar_feed.created", "calendar_feed.revoked"]
    hashes = await dw.one(
        owner_engine,
        "SELECT count(*) FILTER (WHERE revoked_at IS NULL) FROM calendar_feeds WHERE user_id = :u",
        u=world.developer,
    )
    assert hashes == 0


async def test_milestones_platform_events_and_the_organisation_feed(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """A signed agreement's milestone is the developer's deadline until submitted, then the organisation's review
    date; accepted, it is gone. A platform event names the product. A member's feed of the organisation has a status
    and can be turned off."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    today = await db_today(owner_engine)
    holidays = await holidays_of(owner_engine)
    settings = deals_on()
    starts = datetime.combine(today + timedelta(days=5), time(18, 0), tzinfo=NAIROBI)
    platform = await dw.add_event(owner_engine, None, world.staff, starts, title="Open day", staff=world.staff)
    await dw.remind(owner_engine, world.developer, platform)
    async with seats(app_engine, settings, world) as s:
        t = Tracker(engagement)
        detail = await walk_to(t, s, world, today, "IN_IMPLEMENTATION")
        milestone = detail["agreements"][0]["milestones"][0]["id"]
        key = f"milestone:{milestone}"

        def find(items: list[dict[str, Any]]) -> dict[str, Any]:
            [found] = [i for i in items if i["key"] == key]
            return found

        mine = (await ok(await s.dev.get("/api/me/deadlines")))["items"]
        assert not [i for i in mine if i["kind"] == "stage"]  # implementation: the milestones carry the dates
        working = find(mine)
        assert (working["title"], working["mine"], working["due_on"]) == (
            "Milestone 1: RLS proposal",
            True,
            str(today + timedelta(days=30)),
        )
        assert working["engagement_id"] == str(engagement)
        assert find((await ok(await s.owner.get(f"/api/orgs/{world.org}/deadlines")))["items"])["mine"] is False
        assert (await s.dev.get(f"/api/me/deadlines/milestone/{milestone}/calendar.ics")).status_code == 200
        [event] = [i for i in mine if i["kind"] == "event"]
        assert event["context"] == settings.product_name

        for step in ("start", "submit"):
            await t.ok(s.dev, f"milestones/{milestone}/{step}")
        review_on = add_business_days(today, get_policy().review_window_bd_default, holidays)
        review = find((await ok(await s.dev.get("/api/me/deadlines")))["items"])
        assert (review["title"], review["mine"], review["due_on"]) == (
            "Milestone 1 review: RLS proposal",
            False,
            str(review_on),
        )
        org_review = find((await ok(await s.reviewer.get(f"/api/orgs/{world.org}/deadlines")))["items"])
        assert org_review["mine"] is True
        await t.ok(s.reviewer, f"milestones/{milestone}/accept")
        assert not [i for i in (await ok(await s.dev.get("/api/me/deadlines")))["items"] if i["kind"] == "milestone"]
        assert (await s.dev.get(f"/api/me/deadlines/milestone/{milestone}/calendar.ics")).status_code == 404

        assert (await ok(await s.owner.get(f"/api/orgs/{world.org}/calendar-feed")))["active"] is False
        assert (await s.owner.post(f"/api/orgs/{world.org}/calendar-feed")).status_code == 201
        assert (await ok(await s.owner.get(f"/api/orgs/{world.org}/calendar-feed")))["active"] is True
        assert (await ok(await s.owner.get("/api/me/calendar-feed")))["active"] is False  # one per (user, org)
        assert (await s.owner.delete(f"/api/orgs/{world.org}/calendar-feed")).status_code == 204
        assert (await ok(await s.owner.get(f"/api/orgs/{world.org}/calendar-feed")))["active"] is False
