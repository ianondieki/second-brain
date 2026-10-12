"""REQ-ENG-14 (docs/platform/tasks/P27.md track B, acceptance 2, the API half), on the test clock.

Given an organisation with engagements at every point of the path (SUBMITTED; a question asked in review; on hold
after approval; in negotiation; CLOSED; declined), its board shows each in the right column (a side state under the
stage it left, CLOSED in Close, the declined one nowhere) with counts and median ages, the age of a stage counted from
its main-path entry; with no event for 6 business days on the test clock the active ones are marked stalled (not after
4; never one on hold or closed); the funnel's ``entered`` counts match the events in the 90-day window, and fall to
zero once the window has passed them. Members only (a viewer reads it; anyone else 404); ``team`` is null here.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.engagements import deadline_world as dw
from tests.integration.engagements.api_world import (
    Tracker,
    build,
    business_days_later,
    clients,
    db_today,
    deals_on,
    moved_clock,
    open_engagement,
    seats,
    walk_to,
)
from tests.integration.query_counts import LARGE, SMALL, counted

GROUPS = ["review", "contact_nda", "agreement", "implementation", "close"]


def columns(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {column["group"]: column for column in board["columns"]}


def ids(column: dict[str, Any]) -> set[str]:
    return {item["id"] for item in column["items"]}


def item(board: dict[str, Any], engagement: UUID) -> dict[str, Any]:
    [found] = [i for c in board["columns"] for i in c["items"] if i["id"] == str(engagement)]
    return found


async def test_the_board_columns_ageing_stalls_and_funnel(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    world = await build(owner_engine)
    settings = deals_on()
    submitted = await open_engagement(app_engine, world)
    developers: dict[str, tuple[UUID, UUID]] = {}
    for name in ("asked", "held", "agreement", "closed", "declined"):
        developers[name] = await dw.another_developer(owner_engine, app_engine, world.org)
    today = await db_today(owner_engine)
    people = [developer for developer, _ in developers.values()]
    async with seats(app_engine, settings, world) as s, clients(app_engine, settings, *people, world.viewer) as signed:
        dev = dict(zip(developers, signed, strict=False))
        viewer, outsider_check = signed[-1], s.dev
        engagement = {name: e for name, (_, e) in developers.items()}

        asked = Tracker(engagement["asked"])
        await asked.ok(s.reviewer, "start-review")
        await asked.ok(s.reviewer, "request-info", {"question": "Which depots would the pilot cover?"})
        held = Tracker(engagement["held"])
        await walk_to(held, replace(s, dev=dev["held"]), world, today, "INTEREST_CONFIRMED")
        hold = {"reason": "Budget committee", "resume_at": str(today + timedelta(days=20))}
        await held.ok(dev["held"], "pause", hold)
        await walk_to(Tracker(engagement["agreement"]), replace(s, dev=dev["agreement"]), world, today, "NEGOTIATION")
        await walk_to(Tracker(engagement["closed"]), replace(s, dev=dev["closed"]), world, today, "CLOSED")
        await Tracker(engagement["declined"]).ok(s.signatory, "decline", {"reason": "NOT_PRIORITY"})

        response = await viewer.get(f"/api/orgs/{world.org}/pipeline")
        assert response.status_code == 200, response.text
        assert "x-app-now" in response.headers
        board = response.json()
        assert [c["group"] for c in board["columns"]] == GROUPS
        by_group = columns(board)
        assert ids(by_group["review"]) == {str(submitted), str(engagement["asked"])}
        assert ids(by_group["contact_nda"]) == {str(engagement["held"])}
        assert ids(by_group["agreement"]) == {str(engagement["agreement"])}
        assert ids(by_group["implementation"]) == set()
        assert ids(by_group["close"]) == {str(engagement["closed"])}
        assert [c["count"] for c in board["columns"]] == [2, 1, 1, 0, 1]
        assert by_group["review"]["median_days_in_stage"] == 0
        assert by_group["implementation"]["median_days_in_stage"] is None
        assert by_group["close"]["median_days_in_stage"] is None  # CLOSED does not age in a stage
        assert board["stalled_after_bd"] == 5
        question = item(board, engagement["asked"])
        assert (question["state"], question["paused_from"]) == ("INFO_REQUESTED", "UNDER_REVIEW")
        review_entry = [
            e["created_at"]
            for e in (await viewer.get(f"/api/engagements/{engagement['asked']}/history")).json()["events"]
            if e["to_state"] == "UNDER_REVIEW"
        ]
        assert datetime.fromisoformat(question["stage_entered_at"]) == datetime.fromisoformat(review_entry[0])
        assert item(board, engagement["held"])["state"] == "ON_HOLD"
        for card in (i for c in board["columns"] for i in c["items"]):
            assert card["stalled"] is False
            assert card["days_in_stage"] == 0
            assert "team" in card
            assert card["team"] is None
            assert card["last_event_at"] >= card["stage_entered_at"]
        assert board["funnel"] == {
            "window_days": 90,
            "entered": {"review": 6, "contact_nda": 3, "agreement": 2, "implementation": 1, "close": 1},
            "closed": 1,
            "ended": 1,
        }
        # the organisation's list never names a developer the board reveals: the same summary rule
        assert item(board, submitted)["developer_named"] is False

        async with moved_clock(owner_engine) as advance:
            await business_days_later(owner_engine, advance, 4)
            later = (await viewer.get(f"/api/orgs/{world.org}/pipeline")).json()
            assert not [i["id"] for c in later["columns"] for i in c["items"] if i["stalled"]]
            await business_days_later(owner_engine, advance, 2)
            stalled = (await viewer.get(f"/api/orgs/{world.org}/pipeline")).json()
            assert {i["id"] for c in stalled["columns"] for i in c["items"] if i["stalled"]} == {
                str(submitted),
                str(engagement["asked"]),
                str(engagement["agreement"]),
            }
            assert all(i["days_in_stage"] >= 6 for c in stalled["columns"] for i in c["items"])
            assert columns(stalled)["review"]["median_days_in_stage"] >= 6
            await advance(91)
            gone = (await viewer.get(f"/api/orgs/{world.org}/pipeline")).json()
            assert gone["funnel"]["entered"] == dict.fromkeys(GROUPS, 0)
            assert (gone["funnel"]["closed"], gone["funnel"]["ended"]) == (0, 0)
            assert [c["count"] for c in gone["columns"]] == [2, 1, 1, 0, 1]

        assert (await outsider_check.get(f"/api/orgs/{world.org}/pipeline")).status_code == 404


async def test_the_board_and_the_calendar_send_as_many_statements_for_many_engagements(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """P16-E1 item 5's rule for the new reads: one query per kind of row, however many engagements."""
    world = await build(owner_engine)
    await open_engagement(app_engine, world)
    await dw.another_developer(owner_engine, app_engine, world.org)
    settings = deals_on()
    async with clients(app_engine, settings, world.viewer) as (viewer,):
        urls = (f"/api/orgs/{world.org}/pipeline", f"/api/orgs/{world.org}/deadlines")
        small = [await counted(viewer, app_engine, url) for url in urls]
        assert len(small[0][1]["columns"][0]["items"]) == SMALL  # both SUBMITTED, in Review
        assert len(small[1][1]["items"]) == SMALL
        for _ in range(LARGE - SMALL):
            await dw.another_developer(owner_engine, app_engine, world.org)
        large = [await counted(viewer, app_engine, url) for url in urls]
        assert len(large[0][1]["columns"][0]["items"]) == LARGE
        assert len(large[1][1]["items"]) == LARGE
        assert [n for n, _ in large] == [n for n, _ in small]


async def test_an_organisation_with_no_engagement_has_an_empty_board(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    org = await dw.add_org(owner_engine)
    async with clients(app_engine, deals_on(), org.owner) as (owner,):
        board = (await owner.get(f"/api/orgs/{org.id}/pipeline")).json()
    assert [(c["group"], c["count"], c["median_days_in_stage"], c["items"]) for c in board["columns"]] == [
        (group, 0, None, []) for group in GROUPS
    ]
    assert board["funnel"]["entered"] == dict.fromkeys(GROUPS, 0)
