"""REQ-ENG-11: the thread's file operations that race a send, interleaved deterministically through row locks.

- Removing a staged file while its uploader's send of it is in flight: the removal waits for the send's row lock and,
  once the send commits, finds no staged row: 404, and the object of the now-sent attachment is never deleted.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import message_files
from bridge.engagements import state_machine as sm
from bridge.engagements.service import Party
from bridge.errors import ApiError
from bridge.ids import uuid7
from bridge.models.enums import EngagementParty
from tests.integration.engagements import tracker as t
from tests.integration.engagements.thread_world import read, thread_at, uploaded


class _Live:
    def __init__(self, user_id: UUID) -> None:
        self.user = type("User", (), {"id": user_id})()


def developer_party(engagement: UUID, developer: UUID, org: UUID) -> Party:
    actor = sm.Actor(EngagementParty.DEVELOPER, sm.DEVELOPER)
    return Party(engagement, _Live(developer), actor, org)  # type: ignore[arg-type]


async def test_removing_a_file_that_its_send_is_taking_never_deletes_the_sent_object(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        world, e = thread.world, thread.engagement
        file_id = await uploaded(thread.seats.dev, e)
        key = ("uploads", message_files.object_key(e, file_id))
        message_id = uuid7()
        factory = create_session_factory(app_engine)
        async with app_engine.connect() as sender, app_engine.connect() as observer:
            await sender.begin()
            await t.act(sender, world.developer)
            await sender.execute(
                sa.text(
                    "INSERT INTO engagement_messages (id, engagement_id, sender_user_id, sender_party, body)"
                    " VALUES (:id, :e, :u, 'developer', 'The plan, attached.')"
                ),
                {"id": message_id, "e": e, "u": world.developer},
            )
            await sender.execute(
                sa.text("UPDATE engagement_message_attachments SET message_id = :m WHERE id = :a"),
                {"m": message_id, "a": file_id},
            )  # the send holds the upload's row lock until it commits
            async with factory() as db:
                await bind_tenant(db, user_id=world.developer)
                pid = int((await db.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one())
                party = developer_party(e, world.developer, world.org)
                removal: asyncio.Task[Any] = asyncio.create_task(
                    message_files.remove_staged(db, thread.store, party, file_id)
                )
                await t.wait_until_blocked(observer, pid, removal)
                await sender.commit()
                with pytest.raises(ApiError) as refused:
                    await removal
                assert refused.value.status_code == 404
        assert key in thread.store.objects  # the sent attachment's file is still there
        [sent] = (await read(thread.seats.owner, e))["items"]
        assert [a["id"] for a in sent["attachments"]] == [str(file_id)]
