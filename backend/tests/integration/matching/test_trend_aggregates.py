"""REQ-TREND-01 (schema half; revision 0005): ``app_trend_aggregates``, the cross-organisation read of signal_events.

Only the listed kinds (``proposal_published``, ``proposal_version_published``, ``scout_match``, ``org_interest``), only
for published proposals clear of moderation holds, and only for an item and kind with at least 3 distinct actors in the
window (fewer: no row). Per item, kind and Africa/Nairobi day over [since, now): ``events`` counts each actor once per
item and day (AC-TREND-1: five by one account in one day count as one; actor-less signals once per day); ``actors``
counts the item and kind's distinct actors over the window; ``orgs`` its distinct organisations only when there are 3
or more. No hash and no organisation id is ever returned; any signed-in user (or none) gets the same platform-wide
counts, whatever their organisation; the window is bounded.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.schema_v4 import act, add_niche, add_user, as_app, as_owner, expect, run, seats

NAIROBI = ZoneInfo("Africa/Nairobi")
MONDAY = datetime(2026, 10, 5, 9, 0, tzinfo=NAIROBI)
SINCE, NOW = MONDAY - timedelta(days=1), MONDAY + timedelta(days=2)
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


async def _aggregates(
    conn: AsyncConnection, items: list[UUID], since: datetime = SINCE, now: datetime = NOW
) -> dict[Any, Any]:
    found = await conn.execute(sa.text(AGGREGATES), {"since": since, "now": now, "items": items})
    return {(row.item_id, row.kind, row.day): (row.events, row.actors, row.orgs) for row in found.all()}


async def _proposal(conn: AsyncConnection, **kwargs: Any) -> UUID:
    """As the owner: a proposal (published and clear unless told otherwise) of a new developer."""
    niche = await add_niche(conn)
    developer = await add_user(conn, "developer")
    problem = await w.add_problem(conn, developer, niche)
    proposal, _version = await w.add_proposal(conn, developer, niche, problem, **kwargs)
    return proposal


async def test_events_count_each_actor_once_per_item_and_day(owner_engine: AsyncEngine) -> None:
    """AC-TREND-1 (database half): five interests by one account in one Nairobi day are one event; two other accounts
    add one each; the next day counts again; signals without an actor count once a day (and are no actor)."""
    async with as_app(owner_engine) as conn:
        item = await _proposal(conn)
        for minutes in range(5):
            await _signal(conn, item, "org_interest", MONDAY + timedelta(minutes=minutes), "a1")
        await _signal(conn, item, "org_interest", MONDAY + timedelta(hours=14, minutes=59), "a2")  # 23:59 Monday
        await _signal(conn, item, "org_interest", MONDAY, "a3")
        await _signal(conn, item, "org_interest", MONDAY + timedelta(hours=15), "a1")  # 00:00 Tuesday Nairobi
        for hours in (0, 1):
            await _signal(conn, item, "org_interest", MONDAY + timedelta(days=1, hours=hours), None)
        viewer = await add_user(conn, "viewer")
        await act(conn, viewer)
        monday, tuesday = MONDAY.date(), MONDAY.date() + timedelta(days=1)
        assert await _aggregates(conn, [item]) == {
            (item, "org_interest", monday): (3, 3, None),
            (item, "org_interest", tuesday): (2, 3, None),  # a1 and the actor-less signals, once
        }


async def test_an_item_and_kind_below_three_distinct_actors_returns_nothing(owner_engine: AsyncEngine) -> None:
    """No count ever describes one or two accounts: an item and kind with fewer than 3 distinct actors in the window
    has no row (however many events they made), and appears once a third account acts."""
    async with as_app(owner_engine) as conn:
        item = await _proposal(conn)
        for n in range(6):
            await _signal(conn, item, "scout_match", MONDAY + timedelta(minutes=n), f"r{n % 2}", f"o{n % 2}")
        await _signal(conn, item, "scout_match", MONDAY, None)  # actor-less signals are nobody
        await act(conn, None)
        assert await _aggregates(conn, [item]) == {}
        await as_owner(conn)
        await _signal(conn, item, "scout_match", MONDAY, "r2", "o2")
        await act(conn, None)
        assert await _aggregates(conn, [item]) == {(item, "scout_match", MONDAY.date()): (4, 3, 3)}


async def test_organisations_are_counted_only_from_three(owner_engine: AsyncEngine) -> None:
    """A badge may say "4 companies scouting" but never "2 companies": fewer than 3 distinct organisations is NULL."""
    async with as_app(owner_engine) as conn:
        item = await _proposal(conn)
        await _signal(conn, item, "scout_match", MONDAY, "r1", "o1")
        await _signal(conn, item, "scout_match", MONDAY, "r2", "o2")
        await _signal(conn, item, "scout_match", MONDAY, "r3", "o2")
        await act(conn, None)
        assert await _aggregates(conn, [item]) == {(item, "scout_match", MONDAY.date()): (3, 3, None)}
        await as_owner(conn)
        await _signal(conn, item, "scout_match", MONDAY + timedelta(minutes=5), "r4", "o3")
        await act(conn, None)
        assert await _aggregates(conn, [item]) == {(item, "scout_match", MONDAY.date()): (4, 4, 3)}


@pytest.mark.parametrize(
    ("proposal", "kind"),
    [
        pytest.param({}, "developer_save", id="unlisted_kind"),
        pytest.param({}, "proposal_viewed", id="another_unlisted_kind"),
        pytest.param({"moderation_state": "held"}, "org_interest", id="held_proposal"),
        pytest.param({"status": "hidden"}, "org_interest", id="hidden_proposal"),
        pytest.param({"registered": False}, "org_interest", id="draft_proposal"),
        pytest.param(None, "org_interest", id="not_a_proposal"),
    ],
)
async def test_only_listed_kinds_of_published_clear_proposals_are_aggregated(
    owner_engine: AsyncEngine, proposal: dict[str, Any] | None, kind: str
) -> None:
    """Each case has five distinct actors, so only the kind allowlist and the item's visibility leave it out; the same
    signals on a published, clear proposal with a listed kind are counted."""
    async with as_app(owner_engine) as conn:
        item = await _proposal(conn, **proposal) if proposal is not None else uuid7()
        control = await _proposal(conn)
        for n in range(5):
            await _signal(conn, item, kind, MONDAY, f"a{n}")
            await _signal(conn, control, "org_interest", MONDAY, f"a{n}")
        await act(conn, None)
        assert await _aggregates(conn, [item, control]) == {(control, "org_interest", MONDAY.date()): (5, 5, None)}


async def test_the_window_is_since_inclusive_now_exclusive_and_bounded(owner_engine: AsyncEngine) -> None:
    async with as_app(owner_engine) as conn:
        item = await _proposal(conn)
        for n in range(3):
            await _signal(conn, item, "org_interest", MONDAY, f"at_since_{n}")
        await _signal(conn, item, "org_interest", MONDAY + timedelta(hours=2), "at_now")
        await act(conn, None)
        found = await _aggregates(conn, [item], MONDAY, MONDAY + timedelta(hours=2))
        assert found == {(item, "org_interest", MONDAY.date()): (3, 3, None)}  # the one at now is left out
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
        item = await _proposal(conn)
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
            answers.append(await _aggregates(conn, [item]))
        assert answers[0] == answers[1] == answers[2] == {(item, "org_interest", MONDAY.date()): (3, 3, None)}
        values = [value for key, counts in answers[0].items() for value in (*key, *counts)]
        assert a.org not in values
        assert b.org not in values
        assert not any(isinstance(value, bytes | memoryview) for value in values)
