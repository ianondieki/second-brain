"""Revision 0008 (REQ-PERS-03, REQ-TREND-02; P21 track C, D-57 (7)): saved Discover searches and their alert job.

- A saved search is its owner's only (read, insert, rename, mute, delete); its name, view, words, niche and county are
  checked; ``created_at`` is the database's and ``last_alerted_at`` the alert job's (bound to the owner).
- At most 10 per user (``saved_searches_cap``: check_violation, constraint ``saved_searches_at_most_10``), counted
  after RLS, so a row for another user is refused by the policy and tells nothing about that user's searches.
- ``app_saved_searches_due(now)`` lists, to a session with no user bound only, the (user, saved search) ids with alerts
  on, of active users, not alerted since 00:00 Africa/Nairobi of ``now``'s day; bound to the owner, the job advances
  ``last_alerted_at`` and the search leaves the day's list.

Every test runs in one rolled-back transaction (``tracker.as_app``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t

SAVE = (
    "INSERT INTO saved_searches (id, user_id, name, view, niche_slug, county_code, words, alerts)"
    " VALUES (:id, :u, :name, :view, :niche, :county, :words, :alerts)"
)
MINE = "SELECT count(*) FROM saved_searches"
DUE = "SELECT * FROM app_saved_searches_due(:now)"
RLS = "row-level security"
DENIED = "permission denied"
# 07:05 in Nairobi on 5 October 2026 (the job's cron, 04:05 UTC); the Nairobi day began at 21:00 UTC the day before.
NOW = datetime(2026, 10, 5, 4, 5, tzinfo=UTC)
NAIROBI_MIDNIGHT = datetime(2026, 10, 4, 21, 0, tzinfo=UTC)


def search(user: UUID, **overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "id": uuid7(),
        "u": user,
        "name": "Agriculture in Nakuru",
        "view": "problems",
        "niche": None,
        "county": None,
        "words": None,
        "alerts": True,
    }
    return params | overrides


async def save(conn: AsyncConnection, user: UUID, **overrides: Any) -> UUID:
    """Save a search as ``user`` (the connection already acts for them); returns its id."""
    params = search(user, **overrides)
    await t.run(conn, SAVE, **params)
    return UUID(str(params["id"]))


async def people(conn: AsyncConnection) -> tuple[UUID, UUID, str, str]:
    """As the owner: two developers, a niche slug and a county code (the test database has no seed regions)."""
    first = await w.add_user(conn, f"saver-{uuid7().hex}@example.test", "Saver")
    second = await w.add_user(conn, f"other-{uuid7().hex}@example.test", "Other")
    slug = f"agri-{uuid7().hex[-8:]}"
    await t.run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (uuid7(), :s, 'Agriculture')", s=slug)
    await t.run(conn, "INSERT INTO regions (code, kind, name) VALUES ('KE', 'country', 'Kenya') ON CONFLICT DO NOTHING")
    county = f"XS-{uuid7().hex[-4:]}"
    await t.run(
        conn, "INSERT INTO regions (code, parent_code, kind, name) VALUES (:c, 'KE', 'county', 'Nakuru')", c=county
    )
    return first, second, slug, county


async def test_a_saved_search_is_its_owners_only_and_its_query_is_checked(owner_engine: AsyncEngine) -> None:
    """Given two developers, When one saves a search, Then only they read, rename, mute and delete it; the other and an
    unbound session read and change nothing and cannot save in their name; the query's fields are checked; the app
    never writes the owner, query or creation time after the insert, nor dates the search or its last alert."""
    async with t.as_app(owner_engine) as conn:
        first, second, slug, county = await people(conn)
        await t.act(conn, first)
        saved = await save(conn, first, niche=slug, county=county, words="drip irrigation")
        await save(conn, first, view="briefs", name="Any Brief")
        assert await t.run(conn, MINE) == 2
        for assignment in ("name = 'Renamed'", "alerts = false", "last_alerted_at = now()"):
            assert await t.rowcount(conn, f"UPDATE saved_searches SET {assignment} WHERE id = :id", id=saved) == 1
        for assignment in (
            "view = 'briefs'",
            "words = 'x'",
            "niche_slug = NULL",
            "user_id = :other",
            "created_at = now()",
        ):
            await t.expect(
                conn, f"UPDATE saved_searches SET {assignment} WHERE id = :id", DENIED, id=saved, other=second
            )
        for column in ("last_alerted_at", "created_at"):  # the job's and the database's
            dated = (
                f"INSERT INTO saved_searches (id, user_id, name, view, {column})"
                " VALUES (uuid7(), :u, 'x', 'problems', now())"
            )
            await t.expect(conn, dated, DENIED, u=first)
        for params, constraint in (
            (search(first, name=""), "ck_saved_searches_name_length"),
            (search(first, name=" \t "), "ck_saved_searches_name_length"),
            (search(first, name="n" * 61), "ck_saved_searches_name_length"),
            (search(first, view="proposals"), "ck_saved_searches_view_known"),
            (search(first, words=""), "ck_saved_searches_words_length"),
            (search(first, words="w" * 101), "ck_saved_searches_words_length"),
            (search(first, niche="no-such-niche"), "fk_saved_searches_niche_slug_niches"),
            (search(first, county="XX-000"), "fk_saved_searches_county_code_regions"),
        ):
            await t.expect(conn, SAVE, constraint, **params)
        await save(conn, first, name="n" * 60, words="w" * 100)
        for by in (second, None):
            await t.act(conn, by)
            assert await t.run(conn, MINE) == 0
            await t.expect(conn, SAVE, RLS, **search(first))
            assert await t.rowcount(conn, "UPDATE saved_searches SET alerts = true WHERE id = :id", id=saved) == 0
            assert await t.rowcount(conn, "DELETE FROM saved_searches WHERE id = :id", id=saved) == 0
        await t.act(conn, first)
        assert await t.rowcount(conn, "DELETE FROM saved_searches WHERE id = :id", id=saved) == 1
        assert await t.run(conn, MINE) == 2


async def test_at_most_ten_saved_searches_per_user(owner_engine: AsyncEngine) -> None:
    """Ten saved searches each, then the eleventh is refused (one at a time or two in one statement), per user; a
    deleted one frees a place; and a row in another user's name is refused by the policy before the cap counts, so it
    never reveals how many searches that user has."""
    async with t.as_app(owner_engine) as conn:
        first, second, _, _ = await people(conn)
        for user in (first, second):
            await t.act(conn, user)
            kept = [await save(conn, user, name=f"Search {n}") for n in range(10)]
        savepoint = await conn.begin_nested()
        with pytest.raises(DBAPIError, match="at most 10 per user") as refused:
            await conn.execute(sa.text(SAVE), search(second))
        await savepoint.rollback()
        assert isinstance(refused.value.orig, psycopg.Error)
        assert refused.value.orig.diag.constraint_name == "saved_searches_at_most_10"
        await t.act(conn, first)
        await t.expect(conn, SAVE, RLS, **search(second))  # the policy, not the cap
        two = (
            "INSERT INTO saved_searches (id, user_id, name, view) VALUES (uuid7(), :u, 'One', 'problems'),"
            " (uuid7(), :u, 'Two', 'briefs')"
        )
        await t.run(conn, "DELETE FROM saved_searches WHERE name = 'Search 0'")
        await t.expect(conn, two, "at most 10 per user", u=first)
        await save(conn, first, name="In its place")
        await t.expect(conn, SAVE, "at most 10 per user", **search(first))
        assert await t.run(conn, MINE) == 10
        await t.act(conn, second)
        assert await t.run(conn, MINE) == len(kept) == 10


async def test_the_alert_job_lists_due_searches_by_id_with_no_user_bound(owner_engine: AsyncEngine) -> None:
    """The job's list holds the searches with alerts on, of active users, not alerted since the start of the Nairobi
    day, as (user, search) ids only; a signed-in session and a missing time are refused; bound to the owner the job
    advances last_alerted_at and the search leaves that day's list; another user cannot advance it."""
    async with t.as_app(owner_engine) as conn:
        first, second, slug, _ = await people(conn)
        await t.act(conn, first)
        fresh = await save(conn, first, niche=slug)
        muted = await save(conn, first, alerts=False)
        yesterday = await save(conn, first, view="briefs")
        today = await save(conn, first, words="water")
        advance = "UPDATE saved_searches SET last_alerted_at = :at WHERE id = :id"
        await t.run(conn, advance, at=NAIROBI_MIDNIGHT - timedelta(minutes=1), id=yesterday)
        await t.run(conn, advance, at=NAIROBI_MIDNIGHT, id=today)
        await t.act(conn, second)
        suspended = await save(conn, second)
        await t.as_owner(conn)
        await t.run(conn, "UPDATE users SET status = 'suspended' WHERE id = :id", id=second)
        mine = {fresh, muted, yesterday, today, suspended}
        await t.act(conn, None)
        result = await conn.execute(sa.text(DUE), {"now": NOW})
        assert list(result.keys()) == ["user_id", "saved_search_id"]  # ids only
        due = {(row.user_id, row.saved_search_id) for row in result if row.saved_search_id in mine}
        assert due == {(first, fresh), (first, yesterday)}
        await t.expect(conn, DUE, "name the time", now=None)
        for by in (first, second):
            await t.act(conn, by)
            await t.expect(conn, DUE, "the saved-search alert job only, with no user bound", now=NOW)
        assert await t.rowcount(conn, advance, at=NOW, id=fresh) == 0  # bound to another user
        await t.act(conn, first)  # the job, bound to the owner, in the notification's transaction
        assert await t.rowcount(conn, advance, at=NOW, id=fresh) == 1
        await t.act(conn, None)
        listed = {row.saved_search_id for row in await conn.execute(sa.text(DUE), {"now": NOW})}
        assert listed & mine == {yesterday}  # a re-run the same day lists nothing the first run advanced
