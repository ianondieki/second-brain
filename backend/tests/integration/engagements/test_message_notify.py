"""N18 (REQ-ENG-11; P21-A7; D-57 (2)): each message tells the other party's people in-app, always, and by a status
email that is mutable, at most one per recipient and engagement in any 30 minutes, and never carries the text.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.db import create_session_factory
from bridge.engagements import message_notify
from bridge.ids import uuid7
from bridge.notifications.email import DeliveryError, FakeEmailProvider
from tests.integration.engagements.api_world import moved_clock
from tests.integration.engagements.thread_world import (
    email_of,
    in_app,
    message_jobs,
    posted,
    run_message_jobs,
    thread_at,
)

SECRET = "Our budget is KES 2.4M and the pilot sites are Thika and Ruiru."


async def _mute(owner_engine: AsyncEngine, user: UUID) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO notification_preferences (user_id, kind, channel, enabled) VALUES (:u, :k, 'email', false)"
            ),
            {"u": user, "k": message_notify.KIND},
        )


async def test_the_developers_message_tells_the_organisations_people_once_by_email_per_half_hour(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given an open thread (the reviewer started the review, the signatory approved naming the owner), When the
    developer writes twice in a row, Then the owner, the signatory and the reviewer each get two in-app notices
    linking to the organisation's Messages tab and one email between them; the finance member and the viewer, who
    never acted, and the developer get nothing. A day later the next message emails again."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        provider = FakeEmailProvider()
        await posted(s.dev, e, SECRET)
        await posted(s.dev, e, "And a second thought.")
        assert await run_message_jobs(owner_engine, app_engine, e, provider) == 2
        people = (world.owner, world.signatory, world.reviewer)
        for person in people:
            notices = await in_app(owner_engine, person)
            assert len(notices) == 2
            assert {n["link"] for n in notices} == {f"/org/engagements/{e}?tab=messages"}
            assert all(n["org_id"] == world.org for n in notices)
            assert all(SECRET not in f"{n['title']} {n['body']}" for n in notices)
        for nobody in (world.finance, world.viewer, world.developer):
            assert await in_app(owner_engine, nobody) == []
        assert sorted(m.to for m in provider.outbox) == sorted([await email_of(owner_engine, p) for p in people])
        for email in provider.outbox:
            assert SECRET not in email.text
            assert SECRET not in (email.html or "")
            assert "KES 2.4M" not in email.subject

        async with moved_clock(owner_engine) as advance:
            await advance(1)
            await posted(s.dev, e, "Back again tomorrow.")
            await run_message_jobs(owner_engine, app_engine, e, provider)
        assert len(provider.outbox) == 6


async def test_the_organisations_message_tells_the_developer_and_a_muted_email_stays_in_app(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given the developer turned N18 emails off, When the owner writes, Then the developer gets the in-app notice
    and no email; the owner's colleagues get nothing (they are not the other party)."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        await _mute(owner_engine, world.developer)
        provider = FakeEmailProvider()
        await posted(s.owner, e, SECRET)
        await run_message_jobs(owner_engine, app_engine, e, provider)
        [notice] = await in_app(owner_engine, world.developer)
        assert notice["title"].startswith(f"New message from {world.org_name}")
        assert notice["link"] == f"/dev/engagements/{e}?tab=messages"
        assert provider.outbox == []
        for colleague in (world.signatory, world.reviewer, world.owner):
            assert await in_app(owner_engine, colleague) == []


async def test_a_retry_tells_nobody_twice_and_resumes_a_queued_email(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given the email provider fails transiently three times, When the job runs, Then it reports the email still
    queued; run again, it sends that one email and writes no second in-app notice."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        await posted(s.owner, e, "Hello from the organisation.")
        [(_, args)] = await message_jobs(owner_engine, e)
        provider = FakeEmailProvider([DeliveryError("busy", transient=True)] * 3)
        factory = create_session_factory(app_engine)
        kwargs = {
            "engagement_id": UUID(args["engagement_id"]),
            "message_id": UUID(args["message_id"]),
            "developer_id": UUID(args["developer_id"]),
        }
        assert await message_notify.deliver(factory, provider, get_settings(), **kwargs) is False
        assert await message_notify.deliver(factory, provider, get_settings(), **kwargs) is True
        assert await message_notify.deliver(factory, provider, get_settings(), **kwargs) is True
        assert len(provider.outbox) == 1
        assert len(await in_app(owner_engine, world.developer)) == 1


async def test_an_unknown_message_or_a_departed_member_is_skipped(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        factory = create_session_factory(app_engine)
        provider = FakeEmailProvider()
        missing = {"engagement_id": e, "message_id": uuid7(), "developer_id": world.developer}
        assert await message_notify.deliver(factory, provider, get_settings(), **missing) is True
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE memberships SET status = 'removed' WHERE org_id = :o AND user_id = :u"),
                {"o": world.org, "u": world.reviewer},
            )
            await conn.execute(text("UPDATE users SET email_verified_at = NULL WHERE id = :u"), {"u": world.owner})
        await posted(s.dev, e, "Hello all.")
        await run_message_jobs(owner_engine, app_engine, e, provider)
        assert await in_app(owner_engine, world.reviewer) == []  # no longer a member
        assert len(await in_app(owner_engine, world.owner)) == 1  # in-app, but no email: unverified address
        assert [m.to for m in provider.outbox] == [await email_of(owner_engine, world.signatory)]


def test_the_bells_title_fits_its_column() -> None:
    title = message_notify.title_for("Telco A", "A" * 400)
    assert len(title) == 200
    assert title.startswith('New message from Telco A on "AAA')
    assert title.endswith('…"')
    assert message_notify.title_for("Telco  A\n", "Pilot") == 'New message from Telco A on "Pilot"'


@asynccontextmanager
async def minutes_clock(owner_engine: AsyncEngine) -> AsyncIterator[Callable[[int], Awaitable[None]]]:
    """The shared test clock moved forward by whole minutes on demand, and put back as it was at the end."""
    async with owner_engine.connect() as conn:
        enabled, offset = (await conn.execute(text("SELECT enabled, clock_offset FROM test_clock"))).one()
    moved = [offset]

    async def advance(minutes: int) -> None:
        moved[0] += timedelta(minutes=minutes)
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE test_clock SET enabled = true, clock_offset = :o"), {"o": moved[0]})

    try:
        yield advance
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE test_clock SET enabled = :e, clock_offset = :o"), {"e": enabled, "o": offset}
            )


async def test_the_email_gap_is_thirty_minutes_on_the_messages_clock(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    """Given the owner's message emailed to the developer, When the owner writes again 29 minutes later, Then the
    developer gets the in-app notice but no email; When they write 31 minutes after the first, Then an email again."""
    async with thread_at(owner_engine, app_engine) as thread:
        s, e, world = thread.seats, thread.engagement, thread.world
        provider = FakeEmailProvider()
        async with minutes_clock(owner_engine) as advance:
            await posted(s.owner, e, "First.")
            await run_message_jobs(owner_engine, app_engine, e, provider)
            assert len(provider.outbox) == 1
            await advance(29)
            await posted(s.owner, e, "Twenty-nine minutes on.")
            await run_message_jobs(owner_engine, app_engine, e, provider)
            assert len(provider.outbox) == 1
            await advance(2)
            await posted(s.owner, e, "Thirty-one minutes on.")
            await run_message_jobs(owner_engine, app_engine, e, provider)
            assert len(provider.outbox) == 2
        assert len(await in_app(owner_engine, world.developer)) == 3
