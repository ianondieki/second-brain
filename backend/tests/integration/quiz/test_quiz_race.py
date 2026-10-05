"""Revision 0009 (REQ-DEV-01): the quiz's rules that need committed transactions, in a database of its own.

- A pull and an attempt never miss each other: ``quiz_attempts_score`` reads the set FOR KEY SHARE before it scores,
  and every pull, restore and rescore locks the set FOR UPDATE first. An attempt made while a pull is in flight waits
  and is scored without the pulled question; a pull made while an attempt is in flight waits and rescores it.
- Ten flags a day holds for concurrent sessions: ``app_flag_question`` serialises a developer's flags (an advisory
  lock), so of two racing past the ninth exactly one is taken.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import date
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.engagements import tracker as t
from tests.integration.quiz.schema_world import (
    ATTEMPT,
    FLAG,
    KEY,
    SET_STATUS,
    People,
    approved,
    flag,
    owner_attempt,
    owner_set,
    people,
    scores,
)


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_quizrace_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "head"))
        yield database
    finally:
        drop_database(admin_url, name)


async def _committed_set(owner: AsyncEngine) -> tuple[People, date, UUID, list[UUID]]:
    """Committed: the people and today's approved set (a database of its own: the day is free)."""
    async with owner.begin() as conn:
        p = await people(conn)
        today: date = await t.run(conn, "SELECT app_nairobi_today()")
        set_id, questions = await approved(conn, today, p.admin)
    return p, today, set_id, questions


async def test_an_attempt_waits_for_a_pull_in_flight_and_is_scored_without_it(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        p, _, set_id, questions = await _committed_set(owner)
        async with app.connect() as staff, app.connect() as player:
            await staff.begin()
            await t.act(staff, p.admin)
            await t.run(staff, SET_STATUS, question=questions[0], status="pulled", reason="The key is wrong.")
            await player.begin()
            await t.act(player, p.developer)
            pid = await t.backend_pid(player)
            params = {"id": uuid7(), "set": set_id, "user": p.developer, "answers": list(KEY), "ms": 1000}
            playing = asyncio.create_task(player.execute(sa.text(ATTEMPT), params))
            await t.wait_until_blocked(staff, pid, playing)  # the attempt waits for the pull
            await staff.commit()
            assert (await playing).scalar_one() == 4  # the pulled question counts for nobody
            await player.commit()
        async with owner.connect() as conn:
            assert await scores(conn, set_id) == {p.developer: 4}
    finally:
        await owner.dispose()
        await app.dispose()


async def test_a_pull_waits_for_an_attempt_in_flight_and_rescores_it(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        p, _, set_id, questions = await _committed_set(owner)
        async with app.connect() as staff, app.connect() as player:
            await player.begin()
            await t.act(player, p.developer)
            params = {"id": uuid7(), "set": set_id, "user": p.developer, "answers": list(KEY), "ms": 1000}
            assert (await player.execute(sa.text(ATTEMPT), params)).scalar_one() == 5
            await staff.begin()
            await t.act(staff, p.admin)
            pid = await t.backend_pid(staff)
            pull = {"question": questions[0], "status": "pulled", "reason": "The key is wrong."}
            pulling = asyncio.create_task(staff.execute(sa.text(SET_STATUS), pull))
            await t.wait_until_blocked(player, pid, pulling)  # the pull waits for the attempt
            await player.commit()
            assert (await pulling).scalar_one() == 1  # and rescores it once it is committed
            await staff.commit()
        async with owner.connect() as conn:
            assert await scores(conn, set_id) == {p.developer: 4}
    finally:
        await owner.dispose()
        await app.dispose()


async def test_two_flags_racing_past_the_ninth_leave_exactly_ten(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        p, today, set_id, questions = await _committed_set(owner)
        async with owner.begin() as conn:
            await owner_attempt(conn, set_id, p.developer)
            for back in (1, 2):
                past, ids = await owner_set(conn, date.fromordinal(today.toordinal() - back))
                await owner_attempt(conn, past, p.developer)  # a developer flags only what they played
                questions += ids
            for question_id in questions[:9]:
                assert await flag(conn, p.developer, question_id) is False
        async with app.connect() as first, app.connect() as second:
            for session in (first, second):
                await session.begin()
                await t.act(session, p.developer)
            pid = await t.backend_pid(second)
            taken = await first.execute(sa.text(FLAG), {"question": questions[9], "reason": "other", "note": None})
            assert taken.one().pulled is False
            racing = asyncio.create_task(
                second.execute(sa.text(FLAG), {"question": questions[10], "reason": "other", "note": None})
            )
            await t.wait_until_blocked(first, pid, racing)
            await first.commit()
            with pytest.raises(DBAPIError, match="at most 10 flags a day"):
                await racing
            await second.rollback()
        async with owner.connect() as conn:
            count = "SELECT count(*) FROM quiz_flags WHERE user_id = :u"
            assert await t.run(conn, count, u=p.developer) == 10
    finally:
        await owner.dispose()
        await app.dispose()
