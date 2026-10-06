"""Revision 0011 (REQ-DEV-03): the team rules that need committed transactions, in a database of their own.

- A block and an invitation between the same two never pass each other: both take the pair's advisory lock
  (``team_invitations_open``; ``developer_blocks_0_lock`` and ``app_block_developer``), so an invitation racing a block
  is refused once the block commits, and a block racing an invitation ends it once the invitation commits.
- A message waits for a close or a block in flight: ``team_messages_1_open`` reads the thread FOR SHARE (a close's FOR
  UPDATE and a block's UPDATE both conflict with it), so a message racing either is refused once it commits.
- At most 10 team message reports per reporter in 24 hours holds for concurrent sessions (the per-reporter lock).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
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
from tests.integration.teams.schema_world import (
    BLOCK,
    CLOSE,
    INVITE,
    POST,
    REPORT,
    invitation_params,
    peer,
    post,
    problem,
    team,
)


@pytest.fixture
def url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_race_{uuid4().hex[:12]}"
    database = create_database(admin_url, name)
    try:
        run_alembic(database, lambda config: command.upgrade(config, "0011"))
        yield database
    finally:
        drop_database(admin_url, name)


async def _pair(owner: AsyncEngine, *, thread: bool) -> tuple[UUID, UUID, UUID, UUID | None]:
    """Committed: two developers who opted in, a problem and, when asked, their team's thread."""
    async with owner.begin() as conn:
        amina, brian = await peer(conn, "amina"), await peer(conn, "brian")
        issue = await problem(conn, amina)
        found = (await team(conn, amina, brian, issue))[1] if thread else None
    return amina, brian, issue, found


async def test_an_invitation_racing_a_block_is_refused_once_the_block_commits(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        amina, brian, issue, _ = await _pair(owner, thread=False)
        async with app.connect() as blocker, app.connect() as inviter:
            await blocker.begin()
            await t.act(blocker, amina)
            assert await t.run(blocker, BLOCK, blocked=brian) == 1
            await inviter.begin()
            await t.act(inviter, brian)
            pid = await t.backend_pid(inviter)
            sent = asyncio.create_task(inviter.execute(sa.text(INVITE), invitation_params(brian, amina, issue)))
            await t.wait_until_blocked(blocker, pid, sent)  # the invitation waits for the pair's lock
            await blocker.commit()
            with pytest.raises(DBAPIError, match="a block stands between the two developers"):
                await sent
            await inviter.rollback()
    finally:
        await owner.dispose()
        await app.dispose()


async def test_a_block_racing_an_invitation_ends_it_once_the_invitation_commits(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        amina, brian, issue, _ = await _pair(owner, thread=False)
        for blocking in (
            BLOCK,
            "INSERT INTO developer_blocks (blocker_user_id, blocked_user_id) VALUES (:me, :blocked)",
        ):
            async with app.connect() as inviter, app.connect() as blocker:
                await inviter.begin()
                await t.act(inviter, brian)
                params = invitation_params(brian, amina, issue)
                await t.run(inviter, INVITE, **params)
                await blocker.begin()
                await t.act(blocker, amina)
                pid = await t.backend_pid(blocker)
                block = asyncio.create_task(blocker.execute(sa.text(blocking), {"me": amina, "blocked": brian}))
                await t.wait_until_blocked(inviter, pid, block)  # the block waits for the pair's lock
                await inviter.commit()
                done = await block
                if blocking == BLOCK:  # the function counts what it ended under the lock: the block and the invitation
                    assert done.scalar_one() == 2
                await blocker.commit()
            async with owner.connect() as conn:
                status = "SELECT status FROM team_invitations WHERE id = :id"
                assert (await conn.execute(sa.text(status), {"id": params["id"]})).scalar_one() == "ended", blocking
                await conn.execute(sa.text("DELETE FROM developer_blocks"))
                await conn.commit()
    finally:
        await owner.dispose()
        await app.dispose()


@pytest.mark.parametrize("closing", ["close", "block"])
async def test_a_message_racing_a_close_or_a_block_is_refused_once_it_commits(url: URL, closing: str) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        amina, brian, _, thread = await _pair(owner, thread=True)
        async with app.connect() as closer, app.connect() as poster:
            await closer.begin()
            await t.act(closer, amina)
            if closing == "close":
                await t.run(closer, CLOSE, thread=thread, reason="left")
            else:  # a direct INSERT: the trigger closes the thread with a plain UPDATE
                await t.run(
                    closer,
                    "INSERT INTO developer_blocks (blocker_user_id, blocked_user_id) VALUES (:me, :other)",
                    me=amina,
                    other=brian,
                )
            await poster.begin()
            await t.act(poster, brian)  # its snapshot still sees the thread open
            pid = await t.backend_pid(poster)
            params = {"id": uuid7(), "thread": thread, "sender": brian, "body": "Are you there?"}
            sent = asyncio.create_task(poster.execute(sa.text(POST), params))
            await t.wait_until_blocked(closer, pid, sent)  # the message waits for the thread's update
            await closer.commit()
            with pytest.raises(DBAPIError, match="the thread is closed"):
                await sent
            await poster.rollback()
    finally:
        await owner.dispose()
        await app.dispose()


async def test_two_reports_racing_past_the_ninth_leave_exactly_ten(url: URL) -> None:
    owner, app = role_engine(url, "bridge_owner"), role_engine(url, "bridge_app")
    try:
        async with owner.begin() as conn:
            amina, brian = await peer(conn, "amina"), await peer(conn, "brian")
            _, thread = await team(conn, amina, brian, await problem(conn, amina))
            messages = [await post(conn, brian, thread, f"#{n}") for n in range(11)]
            await t.act(conn, amina)
            for reported in messages[:9]:
                await conn.execute(sa.text(REPORT), {"message": reported, "reasons": ["spam"]})
        async with app.connect() as first, app.connect() as second:
            for session in (first, second):
                await session.begin()
                await t.act(session, amina)
            pid = await t.backend_pid(second)
            filed = await first.execute(sa.text(REPORT), {"message": messages[9], "reasons": ["spam"]})
            assert filed.one().created
            racing = asyncio.create_task(
                second.execute(sa.text(REPORT), {"message": messages[10], "reasons": ["spam"]})
            )
            await t.wait_until_blocked(first, pid, racing)
            await first.commit()
            with pytest.raises(DBAPIError, match="at most 10 team message reports a day"):
                await racing
            await second.rollback()
        async with owner.connect() as conn:
            found = "SELECT subject_id FROM moderation_cases WHERE subject_type = 'team_message' AND reporter_id = :r"
            assert set((await conn.execute(sa.text(found), {"r": amina})).scalars()) == set(messages[:10])
    finally:
        await owner.dispose()
        await app.dispose()
