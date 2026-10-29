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
from tests.integration.engagements.api_world import moved_clock
from tests.integration.engagements.thread_world import end, posted, thread_at, thread_path, uploaded


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


async def test_a_failed_object_delete_rolls_the_purge_back_for_the_next_run(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given two unsendable uploads and a store that refuses one file, When the purge runs, Then nothing commits (the
    rows stay, the refused file too) and the next run, with the store back, deletes both rows and both files."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        first, second = await uploaded(s.dev, e), await uploaded(s.dev, e)
        await end(owner_engine, world, e, "WITHDRAWN")
        store = thread.store
        original = store.delete
        refused = message_files.object_key(e, first)

        async def delete(bucket: str, object_key: str) -> None:
            if object_key == refused:
                raise OSError("object store unavailable")
            await original(bucket, object_key)  # type: ignore[arg-type]

        monkeypatch.setattr(store, "delete", delete)
        factory = create_session_factory(app_engine)
        assert await message_files.purge_stale_uploads(factory, store) == 0
        assert await staged_ids(owner_engine, e) == {first, second}  # kept for the next run
        assert key(e, first) in store.objects
        monkeypatch.undo()
        assert await message_files.purge_stale_uploads(factory, store) >= 2
        assert await staged_ids(owner_engine, e) == set()
        assert key(e, first) not in store.objects
        assert key(e, second) not in store.objects


async def test_a_staged_file_whose_object_cannot_be_deleted_stays_staged(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Given a staged file and a store that refuses to delete, When its uploader removes it, Then 503
    storage_unavailable, and the row and its file both stay (removable again once the store is back)."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        file_id = await uploaded(s.dev, e)

        async def refuse(bucket: str, object_key: str) -> None:
            raise OSError("object store unavailable")

        monkeypatch.setattr(thread.store, "delete", refuse)
        refused = await s.dev.delete(thread_path(e, f"/attachments/{file_id}"))
        assert (refused.status_code, refused.json()["detail"]["code"]) == (503, "storage_unavailable")
        assert await staged_ids(owner_engine, e) == {file_id}
        assert key(e, file_id) in thread.store.objects
        monkeypatch.undo()
        assert (await s.dev.delete(thread_path(e, f"/attachments/{file_id}"))).status_code == 204
        assert key(e, file_id) not in thread.store.objects
