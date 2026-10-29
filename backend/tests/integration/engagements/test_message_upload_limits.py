"""REQ-ENG-11: what an upload to the thread must pass, and when.

- Before the body is read: the stage gate, the posting role, the type allow-list and the ten unsent files; no file
  byte is pulled for an upload refused there, and no transaction is open (nothing idle in transaction, no lock) while
  an accepted body streams in.
- Every attempt refused counts toward the 30 attempts an hour, so refusals cannot be retried without bound.
- At most 200 MB scanned per user and engagement in 24 hours: 429 upload_quota with Retry-After.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bridge.audit.service import record as audit
from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import message_files
from tests.integration.engagements.thread_world import PDF, code, end, thread_at, thread_path, upload, uploaded

IDLE = (
    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() AND state = 'idle in transaction'"
    " AND pid <> pg_backend_pid()"
)


class Body:
    """A request body that records whether it was read, and can run a check between its two chunks."""

    def __init__(self, data: bytes, between: object = None) -> None:
        self.data, self.between, self.pulled = data, between, 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.pulled += 1
        yield self.data[:5]
        if callable(self.between):
            await self.between()
        self.pulled += 1
        yield self.data[5:]


async def send(client: httpx.AsyncClient, engagement: UUID, body: Body, content_type: str) -> httpx.Response:
    return await client.post(
        thread_path(engagement, "/attachments"),
        content=body,
        headers={"Content-Type": content_type, "X-File-Name": quote("plan.pdf")},
    )


async def test_refusals_that_need_no_body_come_before_it_is_read(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        unsupported = Body(b"MZ\x90\x00 an executable")
        assert code(await send(s.dev, e, unsupported, "application/x-msdownload")) == (422, "unsupported_file")
        viewer = Body(PDF)
        assert code(await send(thread.viewer, e, viewer, "application/pdf")) == (403, "cannot_post")
        for _ in range(message_files.STAGED_PER_ENGAGEMENT):
            await uploaded(s.owner, e)
        full = Body(PDF)
        assert code(await send(s.owner, e, full, "application/pdf")) == (409, "too_many_staged")
        await end(owner_engine, thread.world, e, "WITHDRAWN")
        ended = Body(PDF)
        assert code(await send(s.dev, e, ended, "application/pdf")) == (409, "thread_read_only")
        assert [b.pulled for b in (unsupported, viewer, full, ended)] == [0, 0, 0, 0]


async def test_no_transaction_is_open_while_the_body_streams_in(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, database_url: URL
) -> None:
    observer = create_async_engine(database_url)  # the superuser: it reads every session's state
    seen: list[int] = []
    try:

        async def look() -> None:
            async with observer.connect() as conn:
                seen.append(int((await conn.execute(text(IDLE))).scalar_one()))

        async with thread_at(owner_engine, app_engine) as thread:
            body = Body(PDF, look)
            accepted = await send(thread.seats.dev, thread.engagement, body, "application/pdf")
            assert accepted.status_code == 201, accepted.text
    finally:
        await observer.dispose()
    assert seen == [0]


async def test_refused_attempts_count_toward_the_hourly_limit(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e = thread.seats, thread.engagement
        for _ in range(message_files.UPLOADS_PER_HOUR):
            assert code(await upload(s.dev, e, b"not a pdf")) == (422, "unsupported_file")
        limited = await upload(s.dev, e)
        assert code(limited) == (429, "too_many_uploads")
        assert 1 <= int(limited.headers["Retry-After"]) <= 3600


async def test_two_hundred_megabytes_a_day_then_429_upload_quota(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given 200 MB already scanned for the developer on this engagement today (ten 20 MB uploads, as their audit
    events record them), When they upload one more byte's worth, Then 429 upload_quota until the first of those
    leaves the 24 hours; the organisation's quota is its own."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        factory = create_session_factory(app_engine)
        async with factory() as db:
            await bind_tenant(db, user_id=world.developer)
            for _ in range(10):
                await audit(
                    db,
                    message_files.STAGED,
                    actor_user_id=world.developer,
                    subject_type="engagement",
                    subject_id=e,
                    payload={"size_bytes": 20 * 1024 * 1024},
                )
            await db.commit()
        limited = await upload(s.dev, e)
        assert code(limited) == (429, "upload_quota")
        assert 23 * 3600 < int(limited.headers["Retry-After"]) <= 24 * 3600
        assert (await upload(s.owner, e)).status_code == 201
