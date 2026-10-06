"""Revision 0010 (REQ-DEV-02; P22 track B, D-60): ``app_trend_job_state(since)``, the weekly trend job's only reader of
the trend cards, each test in one rolled-back transaction.

The job is bridge_app with no user bound, to which the cards' SELECT policies show nothing. The function tells it, and
only it, two facts in one row: ``recent`` (a card that is not rejected was created at or after ``since``: the job's
6-day rule) and ``cited_refs`` (the distinct excerpt ids, sorted, that the sources of every card that is not rejected
cite: left out of the week's call; an empty array when there is none). No id, title, status or time of any card. A
signed-in session is refused (insufficient_privilege, 42501), and so is a NULL time (invalid_parameter_value, 22023).

Each test first removes the committed cards (the RLS world's) inside its own rolled-back transaction, so "no card"
means none; nothing outside the transaction changes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t
from tests.integration.events.schema_world import CREATE_TREND, DECIDE_TREND, card, clock, people, source

STATE = "SELECT * FROM app_trend_job_state(:since)"
LOOK_BACK = timedelta(days=6)  # the weekly job's rule
JOB_ONLY = "the weekly trend job only, with no user bound"
ADD_OLD_CARD = (
    "INSERT INTO trend_cards (id, title, summary, topic_slug, created_at)"
    " VALUES (:id, 'Last week''s trend', 'Drafted a week ago.', 'last-week', :at)"
)
ADD_OLD_SOURCE = (
    "INSERT INTO trend_card_sources (id, card_id, position, url, publisher, published_date, retrieved_at, quote,"
    " excerpt_ref, support) VALUES (uuid7(), :card, :position, 'https://tech.example.test/old', 'Old Publisher',"
    " DATE '2026-09-01', DATE '2026-09-02', 'A quoted line.', :ref, 'The trend.')"
)


async def state(conn: AsyncConnection, since: datetime) -> tuple[bool, list[str]]:
    """As the job (bridge_app, no user bound): the function's one row, of exactly its two columns."""
    await t.act(conn, None)
    result = await conn.execute(sa.text(STATE), {"since": since})
    assert list(result.keys()) == ["recent", "cited_refs"]
    (row,) = result.all()
    return row.recent, row.cited_refs


async def refusal(conn: AsyncConnection, since: datetime | None, match: str) -> str:
    """The SQLSTATE of the function's refusal (``match`` in its message), the outer transaction left usable."""
    savepoint = await conn.begin_nested()
    with pytest.raises(DBAPIError, match=match) as refused:
        await conn.execute(sa.text(STATE), {"since": since})
    await savepoint.rollback()
    assert isinstance(refused.value.orig, psycopg.Error)
    return str(refused.value.orig.diag.sqlstate)


async def no_cards(conn: AsyncConnection) -> datetime:
    """As the owner, in this rolled-back transaction only: no trend card (the sources cascade). The shared clock."""
    await t.as_owner(conn)
    await t.run(conn, "DELETE FROM trend_cards")
    assert await t.run(conn, "SELECT count(*) FROM trend_card_sources") == 0
    return await clock(conn)


async def drafted(conn: AsyncConnection, refs: list[str]) -> UUID:
    """As the job: a candidate citing ``refs`` (created at the shared clock)."""
    await t.act(conn, None)
    sources = [source(excerpt_ref=ref) for ref in refs]
    found: UUID = await t.run(conn, CREATE_TREND, card=json.dumps(card()), sources=json.dumps(sources))
    return found


async def drafted_at(conn: AsyncConnection, at: datetime, refs: list[str]) -> UUID:
    """As the owner: a candidate created at ``at`` citing ``refs`` (only the owner's INSERT names another time)."""
    await t.as_owner(conn)
    card_id = uuid7()
    await t.run(conn, ADD_OLD_CARD, id=card_id, at=at)
    for position, ref in enumerate(refs, start=1):
        await t.run(conn, ADD_OLD_SOURCE, card=card_id, position=position, ref=ref)
    return card_id


async def decided(conn: AsyncConnection, admin: UUID, card_id: UUID, decision: str) -> None:
    await t.act(conn, admin)
    await t.run(conn, DECIDE_TREND, card=card_id, decision=decision)


async def staff_admin(conn: AsyncConnection) -> UUID:
    return await w.add_user(conn, f"admin-{uuid7().hex}@example.test", "Admin", staff_role="admin")


async def test_with_no_card_nothing_is_recent_and_no_excerpt_is_cited(owner_engine: AsyncEngine) -> None:
    """Given no trend card at all, When the job asks for any time, Then ``recent`` is false and ``cited_refs`` is an
    empty array (never NULL)."""
    async with t.as_app(owner_engine) as conn:
        now = await no_cards(conn)
        for since in (now - LOOK_BACK, now - timedelta(days=3650), now + timedelta(days=1)):
            assert await state(conn, since) == (False, [])


async def test_a_recent_card_is_recent_and_cites_its_excerpts(owner_engine: AsyncEngine) -> None:
    """Given one candidate the job drafted now (two sources, the first citing the later excerpt id), When the job asks
    for the last 6 days, Then ``recent`` is true and ``cited_refs`` are its two excerpt ids, sorted; the same once a
    staff admin published it. ``since`` is inclusive: at the card's creation time it is recent, a microsecond later
    it is not (and its excerpts stay cited)."""
    async with t.as_app(owner_engine) as conn:
        admin = await staff_admin(conn)
        now = await no_cards(conn)
        card_id = await drafted(conn, ["tech:edge.2", "tech:edge.1"])
        assert await state(conn, now - LOOK_BACK) == (True, ["tech:edge.1", "tech:edge.2"])
        await decided(conn, admin, card_id, "publish")
        assert await state(conn, now - LOOK_BACK) == (True, ["tech:edge.1", "tech:edge.2"])
        await t.as_owner(conn)
        created: datetime = await t.run(conn, "SELECT created_at FROM trend_cards WHERE id = :id", id=card_id)
        assert await state(conn, created) == (True, ["tech:edge.1", "tech:edge.2"])
        assert await state(conn, created + timedelta(microseconds=1)) == (False, ["tech:edge.1", "tech:edge.2"])


async def test_an_old_card_is_not_recent_but_its_excerpts_stay_cited(owner_engine: AsyncEngine) -> None:
    """Given one card created 7 days ago (published), When the job asks for the last 6 days, Then ``recent`` is false
    and its excerpts are still cited (8 days back it is recent). When the job then drafts a card citing one of the same
    excerpts and a new one, Then ``recent`` is true and each excerpt id is listed once, sorted."""
    async with t.as_app(owner_engine) as conn:
        admin = await staff_admin(conn)
        now = await no_cards(conn)
        old = await drafted_at(conn, now - timedelta(days=7), ["tech:rust.1", "tech:ai.3"])
        await decided(conn, admin, old, "publish")
        assert await state(conn, now - LOOK_BACK) == (False, ["tech:ai.3", "tech:rust.1"])
        assert await state(conn, now - timedelta(days=8)) == (True, ["tech:ai.3", "tech:rust.1"])
        await drafted(conn, ["tech:rust.1", "tech:wasm.1"])
        assert await state(conn, now - LOOK_BACK) == (True, ["tech:ai.3", "tech:rust.1", "tech:wasm.1"])


async def test_a_rejected_card_is_neither_recent_nor_cited(owner_engine: AsyncEngine) -> None:
    """Given a card drafted now and rejected by a staff admin, When the job asks, Then it is not recent and none of its
    excerpts is cited (they may be drafted again); an old rejected card neither. A live candidate beside them is recent
    and cites only its own excerpts, and an excerpt both a rejected and a live card cite is listed once."""
    async with t.as_app(owner_engine) as conn:
        admin = await staff_admin(conn)
        now = await no_cards(conn)
        rejected = await drafted(conn, ["tech:rejected.1", "tech:shared.1"])
        await decided(conn, admin, rejected, "reject")
        old = await drafted_at(conn, now - timedelta(days=30), ["tech:rejected.2"])
        await decided(conn, admin, old, "reject")
        assert await state(conn, now - LOOK_BACK) == (False, [])
        assert await state(conn, now - timedelta(days=365)) == (False, [])
        await drafted(conn, ["tech:shared.1", "tech:live.1"])
        assert await state(conn, now - LOOK_BACK) == (True, ["tech:live.1", "tech:shared.1"])


async def test_only_a_session_with_no_user_bound_reads_the_job_state(owner_engine: AsyncEngine) -> None:
    """A signed-in session is refused with insufficient_privilege whoever it is: a developer, a staff admin (who reads
    the cards under RLS instead: the manual run), a staff moderator, an organisation's owner and viewer; the job's
    NULL time is invalid_parameter_value."""
    async with t.as_app(owner_engine) as conn:
        p = await people(conn)
        now = await no_cards(conn)
        await drafted(conn, ["tech:edge.1"])
        callers: tuple[tuple[UUID, UUID | None], ...] = (
            (p.developer, None),
            (p.admin, None),
            (p.moderator, None),
            (p.owner, p.org),
            (p.viewer, p.org),
        )
        for user, org in callers:
            await t.act(conn, user, org)
            assert await refusal(conn, now - LOOK_BACK, JOB_ONLY) == "42501", user
        await t.act(conn, None)
        assert await refusal(conn, None, "name the time") == "22023"
        assert await state(conn, now - LOOK_BACK) == (True, ["tech:edge.1"])
