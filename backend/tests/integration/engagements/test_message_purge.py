"""REQ-ENG-11: the hourly purge of staged thread uploads that can never be sent (``message_files.purge_stale_uploads``
over revision 0008's ``app_purge_stale_message_uploads``): an upload left unsent for more than 24 hours, or on an
engagement that ended, goes with its file; a fresh staged upload and every sent file stay; a signed-in session can
purge nothing.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import message_files
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.engagements.api_world import moved_clock
from tests.integration.engagements.thread_world import end, posted, thread_at, uploaded


def key(engagement: UUID, attachment: UUID) -> tuple[str, str]:
    return ("uploads", message_files.object_key(engagement, attachment))


async def staged_ids(owner_engine: AsyncEngine, engagement: UUID) -> set[UUID]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT id FROM engagement_message_attachments WHERE engagement_id = :e"), {"e": engagement}
        )
        return {UUID(str(row)) for row in rows.scalars()}


async def test_stale_and_ended_uploads_go_with_their_files_and_sent_ones_stay(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        factory = create_session_factory(app_engine)
        sent_file = await uploaded(s.dev, e)
        await posted(s.dev, e, "The plan, attached.", attachments=[sent_file])
        stale = await uploaded(s.dev, e)
        async with moved_clock(owner_engine) as advance:
            await advance(2)
            fresh = await uploaded(s.owner, e)
            # the purge is database-wide (other tests' uploads may go too): this engagement's rows and files tell
            assert await message_files.purge_stale_uploads(factory, thread.store) >= 1
            assert await staged_ids(owner_engine, e) == {sent_file, fresh}
            assert key(e, stale) not in thread.store.objects
            assert key(e, fresh) in thread.store.objects
            assert key(e, sent_file) in thread.store.objects
            await message_files.purge_stale_uploads(factory, thread.store)
            assert await staged_ids(owner_engine, e) == {sent_file, fresh}

            await end(owner_engine, world, e, "WITHDRAWN")
            assert await message_files.purge_stale_uploads(factory, thread.store) >= 1
            assert await staged_ids(owner_engine, e) == {sent_file}
            assert key(e, fresh) not in thread.store.objects
            assert key(e, sent_file) in thread.store.objects


async def test_a_signed_in_session_purges_nothing(owner_engine: AsyncEngine, app_engine: AsyncEngine) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        await uploaded(thread.seats.dev, thread.engagement)
        factory = create_session_factory(app_engine)
        async with factory() as db:
            await bind_tenant(db, user_id=thread.world.developer)
            with pytest.raises(DBAPIError, match="no user bound"):
                await db.execute(text("SELECT * FROM app_purge_stale_message_uploads(app_clock_now())"))


async def test_a_key_outside_the_thread_or_a_failed_delete_does_not_stop_the_purge(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The objects go after the rows are committed: a delete that fails is logged and the next key still goes."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        first, second = await uploaded(s.dev, e), await uploaded(s.dev, e)
        await end(owner_engine, world, e, "WITHDRAWN")
        failing = InMemoryObjectStore()
        failing.objects = dict(thread.store.objects)
        calls: list[str] = []
        original = failing.delete

        async def delete(bucket: str, object_key: str) -> None:  # the first delete fails, the second goes
            calls.append(object_key)
            if len(calls) == 1:
                raise OSError("object store unavailable")
            await original(bucket, object_key)  # type: ignore[arg-type]

        monkeypatch.setattr(failing, "delete", delete)
        factory = create_session_factory(app_engine)
        assert await message_files.purge_stale_uploads(factory, failing) >= 2
        ours = {message_files.object_key(e, a) for a in (first, second)}
        assert ours <= set(calls)
        assert len(calls) >= 2
        left = {object_key for _, object_key in failing.objects}
        assert calls[0] in left or calls[0] not in ours  # the failed delete left its object behind
        assert not left & set(calls[1:])  # every later one went
        assert await staged_ids(owner_engine, e) == set()
