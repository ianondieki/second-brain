"""REQ-TRACK-03 (P27 UX fix round, principle 7 "one truth"), through the API on the test clock.

Given a SUBMITTED engagement whose stage deadline has passed, with a holiday on a business day between the due day
and today (the test clock moved a week past it), every surface that shows the deadline counts the same business days
late, the holiday left out: the developer's and the organisation's lists, the tracker on both sides, the board and
both calendars (``/api/me/deadlines``, ``/api/orgs/{org}/deadlines``). Before the fix the lists, the tracker and the
board read the holidays from today forward only, so they counted the past holiday as a working day: one more than
the calendar.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements.calendar import add_business_days, business_days_between
from bridge.ids import uuid7
from tests.integration.engagements.api_world import (
    Tracker,
    build,
    db_today,
    deals_on,
    holidays_of,
    moved_clock,
    open_engagement,
    seats,
)

DAYS_PAST_THE_HOLIDAY = 7


async def _get(client: httpx.AsyncClient, path: str) -> Any:
    response = await client.get(path)
    assert response.status_code == 200, (path, response.status_code, response.text)
    return response.json()


def _listed(items: list[dict[str, Any]], engagement: UUID) -> dict[str, Any]:
    found = [i for i in items if i["id"] == str(engagement)]
    assert len(found) == 1, engagement
    return found[0]


def _on_board(board: dict[str, Any], engagement: UUID) -> dict[str, Any]:
    return _listed([i for column in board["columns"] for i in column["items"]], engagement)


def _dated(deadlines: dict[str, Any], engagement: UUID) -> dict[str, Any]:
    found = [i for i in deadlines["items"] if i["key"] == f"stage:{engagement}"]
    assert len(found) == 1, engagement
    return cast(dict[str, Any], found[0])


async def test_a_past_holiday_is_left_out_of_the_overdue_count_everywhere(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    tracker = Tracker(engagement)
    holiday = uuid7()
    async with seats(app_engine, deals_on(), world) as s, moved_clock(owner_engine) as advance:
        due_on = date.fromisoformat((await tracker.detail(s.dev))["due"]["due_on"])
        known = await holidays_of(owner_engine)
        day_off = add_business_days(due_on, 1, known)  # the first business day after the deadline
        async with owner_engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO holidays (id, country, holiday_on, observed_on, name)"
                    " VALUES (:id, 'KE', :day, :day, 'P27 one-truth fixture')"
                ),
                {"id": holiday, "day": day_off},
            )
        try:
            await advance((day_off - await db_today(owner_engine)).days + DAYS_PAST_THE_HOLIDAY)
            today = await db_today(owner_engine)
            assert due_on < day_off < today
            expected = business_days_between(today, due_on, await holidays_of(owner_engine))
            assert expected < 0
            assert expected == business_days_between(today, due_on, known) + 1  # the fixture day is left out

            org = f"/api/orgs/{world.org}"
            counts = {
                "developer list": _listed((await _get(s.dev, "/api/me/engagements"))["items"], engagement)["due"],
                "organisation list": _listed((await _get(s.owner, f"{org}/engagements"))["items"], engagement)["due"],
                "developer tracker": (await tracker.detail(s.dev))["due"],
                "organisation tracker": (await tracker.detail(s.reviewer))["due"],
                "board": _on_board(await _get(s.owner, f"{org}/pipeline"), engagement)["due"],
                "developer calendar": _dated(await _get(s.dev, "/api/me/deadlines"), engagement),
                "organisation calendar": _dated(await _get(s.owner, f"{org}/deadlines"), engagement),
            }
        finally:
            async with owner_engine.begin() as conn:
                await conn.execute(text("DELETE FROM holidays WHERE id = :id"), {"id": holiday})
    shown = {where: (d["due_on"], d["business_days_left"], d["overdue"]) for where, d in counts.items()}
    assert shown == dict.fromkeys(counts, (str(due_on), expected, True))
