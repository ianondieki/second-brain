"""REQ-ENG-11: read markers follow the commit order of the thread, interleaved deterministically through the post lock.

Given a post in flight (it holds the engagement's post lock and has inserted its message, not yet committed), When the
other party marks the thread read and posts too, Then the mark stops at the newest committed message, the second post
waits for the first to commit and is timed after it, and the in-flight message, once committed, is unread.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.engagements import messages
from bridge.ids import uuid7
from tests.integration.engagements import tracker as t
from tests.integration.engagements.thread_world import posted, read, thread_at, thread_path


async def wait_for_an_advisory_wait(observer: AsyncConnection, task: asyncio.Task[Any]) -> None:
    """Wait until some session waits for an advisory lock (pg_locks, read live); fails if ``task`` ends first."""
    waiting = sa.text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")
    deadline = time.monotonic() + 30
    while not (await observer.execute(waiting)).scalar_one():
        assert not task.done(), "the post did not wait for the post in flight"
        assert time.monotonic() < deadline, "the post never waited"
        await asyncio.sleep(0.01)  # a poll interval: the order comes from the lock, not from a delay


async def test_a_post_in_flight_stays_unread_and_the_next_post_waits_for_it(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        first = await posted(s.owner, e, "Welcome.")
        in_flight = uuid7()
        async with app_engine.connect() as poster, owner_engine.connect() as observer:
            await poster.begin()
            await t.act(poster, world.owner, world.org)
            await poster.execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": messages.post_lock_key(e)}
            )
            await poster.execute(
                sa.text(
                    "INSERT INTO engagement_messages (id, engagement_id, sender_user_id, sender_party, body)"
                    " VALUES (:id, :e, :u, 'org', 'Sent while you were reading.')"
                ),
                {"id": in_flight, "e": e, "u": world.owner},
            )
            marked = await s.dev.post(thread_path(e, "/read"), json={})
            assert marked.status_code == 200, marked.text
            assert datetime.fromisoformat(marked.json()["last_read_at"]) == datetime.fromisoformat(first["created_at"])
            reply: asyncio.Task[Any] = asyncio.create_task(posted(s.dev, e, "Thanks!"))
            await wait_for_an_advisory_wait(observer, reply)
            await poster.commit()
            answered = await reply
        thread_now = await read(s.dev, e)
        times = {m["id"]: datetime.fromisoformat(m["created_at"]) for m in thread_now["items"]}
        assert times[answered["id"]] > times[str(in_flight)] > times[first["id"]]
        assert thread_now["unread"] == 1  # the message committed after the mark
