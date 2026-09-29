"""REQ-TREND-01 (schema half; revision 0005): ``app_trend_aggregates``, the cross-organisation read of signal_events.

Per item, kind and Africa/Nairobi day over [since, now): ``events`` counts each actor once per item and day (AC-TREND-1:
five saves by one account in one day count as one; actor-less signals once per day); ``actors`` counts the item and
kind's distinct actors over the window; ``orgs`` its distinct organisations only when there are 3 or more. No hash
and no organisation id is ever returned; any signed-in user (or none) gets the same platform-wide counts, whatever
their organisation; the window is bounded.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration.schema_v4 import act, add_user, as_app, expect, run, seats

NAIROBI = ZoneInfo("Africa/Nairobi")
MONDAY = datetime(2026, 10, 5, 9, 0, tzinfo=NAIROBI)
SIGNAL = (
    "INSERT INTO signal_events (id, item_id, kind, actor_hash, org_hash, ts) VALUES (:id, :item, :kind, :actor, :org,"
    " :ts)"
)
AGGREGATES = "SELECT * FROM app_trend_aggregates(:since, :now) WHERE item_id = ANY (:items)"


def digest(label: str) -> bytes:
    return label.encode().ljust(32, b"\0")


async def _signal(
    conn: AsyncConnection, item: UUID, kind: str, at: datetime, actor: str | None, org: str | None = None
) -> None:
    await run(
        conn,
        SIGNAL,
        id=uuid7(),
        item=item,
        kind=kind,
        actor=digest(actor) if actor else None,
        org=digest(org) if org else None,
        ts=at,
    )


async def _aggregates(conn: AsyncConnection, items: list[UUID], since: datetime, now: datetime) -> dict[Any, Any]:
    found = await conn.execute(sa.text(AGGREGATES), {"since": since, "now": now, "items": items})
    return {(row.item_id, row.kind, row.day): (row.events, row.actors, row.orgs) for row in found.all()}


async def test_events_count_each_actor_once_per_item_and_day(owner_engine: AsyncEngine) -> None:
    """AC-TREND-1 (database half): five saves by one account in one Nairobi day are one event; another account adds
    one; the next day counts again; signals without an actor count once a day; actors are distinct over the window."""
    async with as_app(owner_engine) as conn:
        item, other = uuid7(), uuid7()
        for minutes in range(5):
            await _signal(conn, item, "developer_save", MONDAY + timedelta(minutes=minutes), "a1")
        await _signal(conn, item, "developer_save", MONDAY + timedelta(hours=14, minutes=59), "a2")  # 23:59 Monday
        await _signal(conn, item, "developer_save", MONDAY + timedelta(hours=15), "a1")  # 00:00 Tuesday Nairobi
        await _signal(conn, item, "proposal_published", MONDAY, None)
        await _signal(conn, item, "proposal_published", MONDAY + timedelta(hours=1), None)
        await _signal(conn, other, "developer_save", MONDAY, "a1")
        viewer = await add_user(conn, "viewer")
        await act(conn, viewer)
        found = await _aggregates(conn, [item, other], MONDAY - timedelta(days=1), MONDAY + timedelta(days=2))
        monday, tuesday = MONDAY.date(), MONDAY.date() + timedelta(days=1)
        assert found == {
            (item, "developer_save", monday): (2, 2, None),
            (item, "developer_save", tuesday): (1, 2, None),
            (item, "proposal_published", monday): (1, 0, None),
            (other, "developer_save", monday): (1, 1, None),
        }


async def test_organisations_are_counted_only_from_three(owner_engine: AsyncEngine) -> None:
    """A badge may say "4 companies scouting" but never "1 company": fewer than 3 distinct organisations is NULL."""
    async with as_app(owner_engine) as conn:
        item = uuid7()
        since, now = MONDAY - timedelta(days=1), MONDAY + timedelta(days=1)
        await _signal(conn, item, "scout_match", MONDAY, "r1", "o1")
        await _signal(conn, item, "scout_match", MONDAY, "r2", "o2")
        await _signal(conn, item, "scout_match", MONDAY, "r3", "o2")
        await act(conn, None)
        assert await _aggregates(conn, [item], since, now) == {(item, "scout_match", MONDAY.date()): (3, 3, None)}
        await _as_owner_signal(conn, item, "o3")
        await act(conn, None)
        assert await _aggregates(conn, [item], since, now) == {(item, "scout_match", MONDAY.date()): (4, 4, 3)}


async def _as_owner_signal(conn: AsyncConnection, item: UUID, org: str) -> None:
    await conn.execute(sa.text("SET LOCAL ROLE bridge_owner"))
    await _signal(conn, item, "scout_match", MONDAY + timedelta(minutes=5), "r4", org)


async def test_the_window_is_since_inclusive_now_exclusive_and_bounded(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        item = uuid7()
        await _signal(conn, item, "developer_save", MONDAY, "at_since")
        await _signal(conn, item, "developer_save", MONDAY + timedelta(hours=2), "at_now")
        await act(conn, None)
        found = await _aggregates(conn, [item], MONDAY, MONDAY + timedelta(hours=2))
        assert found == {(item, "developer_save", MONDAY.date()): (1, 1, None)}  # the one at now is left out
        call = "SELECT count(*) FROM app_trend_aggregates(:since, :now)"
        for since, now in (
            (None, MONDAY),
            (MONDAY, None),
            (MONDAY, MONDAY - timedelta(seconds=1)),
            (MONDAY - timedelta(days=401), MONDAY),
        ):
            await expect(conn, call, "a window \\[since, now\\) of at most 400 days", since=since, now=now)
        assert await run(conn, call, since=MONDAY - timedelta(days=400), now=MONDAY) >= 0


async def test_aggregates_never_return_hashes_or_organisation_ids_and_ignore_the_callers_tenancy(
    owner_engine: AsyncEngine,
) -> None:
    """The result's columns are ids of items, kinds, days and counts only; members of two organisations, and a
    request with no user, read the same platform-wide counts."""
    async with as_app(owner_engine) as conn:
        a, b = await seats(conn), await seats(conn)
        item = uuid7()
        for n, org in enumerate((a.org, b.org, a.org)):
            await _signal(conn, item, "org_interest", MONDAY + timedelta(minutes=n), f"m{n}", org.hex)
        result = await run(
            conn,
            "SELECT pg_get_function_result(to_regprocedure("
            "'app_trend_aggregates(timestamp with time zone, timestamp with time zone)'))",
        )
        assert result == (
            "TABLE(item_id uuid, kind character varying, day date, events integer, actors integer, orgs integer)"
        )
        answers = []
        callers: tuple[tuple[UUID | None, UUID | None], ...] = ((a.reviewer, a.org), (b.owner, b.org), (None, None))
        for caller, context in callers:
            await act(conn, caller, context)
            answers.append(await _aggregates(conn, [item], MONDAY - timedelta(days=1), MONDAY + timedelta(days=1)))
        assert answers[0] == answers[1] == answers[2] == {(item, "org_interest", MONDAY.date()): (3, 3, None)}
        values = [value for key, counts in answers[0].items() for value in (*key, *counts)]
        assert a.org not in values
        assert b.org not in values
        assert not any(isinstance(value, bytes | memoryview) for value in values)
