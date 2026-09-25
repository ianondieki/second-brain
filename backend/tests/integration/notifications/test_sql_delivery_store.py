"""REQ-NOT-01: ``send_email`` on ``SqlDeliveryStore`` against PostgreSQL, as ``bridge_app`` under Row-Level Security.

Every session is an RLS-bound ``AsyncSession`` (``bridge.db.bind_tenant``), exactly as a request or job would use it.
Covers the persisted ``sent`` row, a case-variant address in ``email_suppressions`` (citext), two sessions racing on one
dedupe key (the unique index, the savepoint and ``SELECT ... FOR UPDATE``), resuming a keyed row left ``queued`` after
transient exhaustion, and tenant isolation of the ledger. The email provider is the in-memory fake (AC-SEC-5).
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import bridge.models.all  # noqa: F401  # registers every table (foreign keys resolve at flush)
from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.models.enums import DeliveryStatus, NotificationChannel
from bridge.notifications.deliveries import SqlDeliveryStore, send_email
from bridge.notifications.email import DeliveryError, EmailMessage, FakeEmailProvider
from bridge.notifications.models import NotificationDelivery


async def _no_sleep(_seconds: float) -> None:
    return None


def _tag() -> str:
    return uuid7().hex[-12:]


def _message(to: str) -> EmailMessage:
    return EmailMessage(to=to, subject="Your proposal", text="Hello from the integration test")


@pytest.fixture(scope="module")
async def users(owner_engine: AsyncEngine) -> tuple[UUID, UUID]:
    """Users A and B, written as the owner role (RLS does not apply to the table owner)."""
    a, b = uuid7(), uuid7()
    async with owner_engine.begin() as conn:
        for user_id, label in ((a, "a"), (b, "b")):
            await conn.execute(
                text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, :name)"),
                {"id": user_id, "email": f"not01-{label}-{user_id.hex[-12:]}@example.test", "name": label.upper()},
            )
    return a, b


@pytest.fixture(scope="module")
def factory(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(app_engine)


async def _session_for(factory: async_sessionmaker[AsyncSession], user_id: UUID) -> AsyncSession:
    session = factory()
    await bind_tenant(session, user_id=user_id)
    return session


async def _reload(factory: async_sessionmaker[AsyncSession], user_id: UUID, row_id: UUID) -> NotificationDelivery:
    async with factory() as session:
        await bind_tenant(session, user_id=user_id)
        row = await session.get(NotificationDelivery, row_id)
        assert row is not None
        return row


async def test_a_sent_row_is_persisted_with_provider_and_message_id(
    factory: async_sessionmaker[AsyncSession], users: tuple[UUID, UUID]
) -> None:
    user_a, _ = users
    provider = FakeEmailProvider()
    to = f"dev-{_tag()}@example.test"
    async with await _session_for(factory, user_a) as session:
        row = await send_email(session, provider, message=_message(to), kind="em2", user_id=user_a)
        await session.commit()

    stored = await _reload(factory, user_a, row.id)
    assert stored.status is DeliveryStatus.SENT
    assert (stored.provider, stored.provider_message_id, stored.attempts) == ("fake", "fake-1", 1)
    assert stored.sent_at is not None
    assert (stored.kind, stored.channel, stored.to_address, stored.user_id) == (
        "em2",
        NotificationChannel.EMAIL,
        to,
        user_a,
    )
    assert len(provider.outbox) == 1


async def test_a_case_variant_suppressed_address_is_recorded_and_never_sent(
    factory: async_sessionmaker[AsyncSession], owner_engine: AsyncEngine, users: tuple[UUID, UUID]
) -> None:
    user_a, _ = users
    tag = _tag()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO email_suppressions (id, email, reason, source) VALUES (:id, :email, 'bounce', 'test')"),
            {"id": uuid7(), "email": f"Bounced.User-{tag}@Example.TEST"},
        )
    provider = FakeEmailProvider()
    async with await _session_for(factory, user_a) as session:
        row = await send_email(
            session, provider, message=_message(f"bounced.user-{tag}@example.test"), kind="em2", user_id=user_a
        )
        await session.commit()

    assert provider.attempts == 0
    stored = await _reload(factory, user_a, row.id)
    assert stored.status is DeliveryStatus.SUPPRESSED
    assert (stored.attempts, stored.provider, stored.sent_at) == (0, None, None)


async def test_two_sessions_racing_on_one_dedupe_key_send_once(
    factory: async_sessionmaker[AsyncSession], users: tuple[UUID, UUID]
) -> None:
    """The first session holds its uncommitted row; the second blocks on the unique index, loses the insert inside
    its savepoint and returns the winner's row without sending."""
    user_a, _ = users
    provider = FakeEmailProvider()
    key, to = f"em2:race:{_tag()}", f"race-{_tag()}@example.test"
    async with await _session_for(factory, user_a) as first, await _session_for(factory, user_a) as second:
        winner = await send_email(first, provider, message=_message(to), kind="em2", user_id=user_a, dedupe_key=key)
        loser_task = asyncio.create_task(
            send_email(second, provider, message=_message(to), kind="em2", user_id=user_a, dedupe_key=key)
        )
        await asyncio.sleep(0.5)
        assert not loser_task.done()  # it cannot finish while the first transaction holds the key
        await first.commit()
        loser = await asyncio.wait_for(loser_task, timeout=60)
        await second.commit()

    assert loser.id == winner.id
    assert loser.status is DeliveryStatus.SENT
    assert provider.attempts == 1
    assert len(provider.outbox) == 1


async def test_sessions_started_together_on_one_dedupe_key_send_once(
    factory: async_sessionmaker[AsyncSession], users: tuple[UUID, UUID]
) -> None:
    user_a, _ = users
    provider = FakeEmailProvider()
    key, to = f"em2:gather:{_tag()}", f"gather-{_tag()}@example.test"

    async def send_and_commit() -> UUID:
        async with await _session_for(factory, user_a) as session:
            row = await send_email(session, provider, message=_message(to), kind="em2", user_id=user_a, dedupe_key=key)
            await session.commit()
            return row.id

    ids = await asyncio.wait_for(asyncio.gather(send_and_commit(), send_and_commit()), timeout=60)
    assert ids[0] == ids[1]
    assert provider.attempts == 1


async def test_a_keyed_row_left_queued_by_transient_errors_is_resumed_later(
    factory: async_sessionmaker[AsyncSession], users: tuple[UUID, UUID]
) -> None:
    user_a, _ = users
    provider = FakeEmailProvider(failures=[DeliveryError(f"HTTP 503 ({n})", transient=True) for n in range(3)])
    key, to = f"em7:resume:{_tag()}", f"resume-{_tag()}@example.test"
    async with await _session_for(factory, user_a) as session:
        first = await send_email(
            session, provider, message=_message(to), kind="em7", user_id=user_a, dedupe_key=key, sleep=_no_sleep
        )
        await session.commit()
    queued = await _reload(factory, user_a, first.id)
    assert (queued.status, queued.attempts, queued.last_error_transient) == (DeliveryStatus.QUEUED, 3, True)

    async with await _session_for(factory, user_a) as session:
        later = await send_email(
            session, provider, message=_message(to), kind="em7", user_id=user_a, dedupe_key=key, sleep=_no_sleep
        )
        await session.commit()
    assert later.id == first.id
    stored = await _reload(factory, user_a, first.id)
    assert (stored.status, stored.attempts, stored.provider_message_id) == (DeliveryStatus.SENT, 4, "fake-1")
    assert provider.attempts == 4


async def test_concurrent_resumes_of_one_queued_row_send_once(
    factory: async_sessionmaker[AsyncSession], users: tuple[UUID, UUID]
) -> None:
    """SELECT ... FOR UPDATE serialises the resumers: the second waits, then reads the row as sent."""
    user_a, _ = users
    key, to = f"em7:resume-race:{_tag()}", f"resume-race-{_tag()}@example.test"
    flaky = FakeEmailProvider(failures=[DeliveryError("HTTP 503", transient=True)])
    async with await _session_for(factory, user_a) as session:
        queued = await send_email(
            session, flaky, message=_message(to), kind="em7", user_id=user_a, dedupe_key=key, max_attempts=1
        )
        await session.commit()
    assert queued.status is DeliveryStatus.QUEUED

    provider = FakeEmailProvider()

    async def resume_and_commit() -> UUID:
        async with await _session_for(factory, user_a) as session:
            row = await send_email(session, provider, message=_message(to), kind="em7", user_id=user_a, dedupe_key=key)
            await session.commit()
            return row.id

    ids = await asyncio.wait_for(asyncio.gather(resume_and_commit(), resume_and_commit()), timeout=60)
    assert set(ids) == {queued.id}
    assert provider.attempts == 1
    stored = await _reload(factory, user_a, queued.id)
    assert (stored.status, stored.attempts) == (DeliveryStatus.SENT, 2)


async def test_the_ledger_row_is_invisible_to_another_user(
    factory: async_sessionmaker[AsyncSession], users: tuple[UUID, UUID]
) -> None:
    user_a, user_b = users
    key, to = f"em2:rls:{_tag()}", f"rls-{_tag()}@example.test"
    async with await _session_for(factory, user_a) as session:
        row = await send_email(
            session, FakeEmailProvider(), message=_message(to), kind="em2", user_id=user_a, dedupe_key=key
        )
        await session.commit()

    async with await _session_for(factory, user_a) as session:
        found = await SqlDeliveryStore(session).find_by_dedupe_key(key)  # FOR UPDATE also passes the UPDATE policy
        assert found is not None
        assert found.id == row.id
        await session.rollback()

    async with await _session_for(factory, user_b) as session:
        assert await SqlDeliveryStore(session).find_by_dedupe_key(key) is None
        assert await session.get(NotificationDelivery, row.id) is None
        visible = await session.scalars(select(NotificationDelivery.id).where(NotificationDelivery.user_id == user_a))
        assert visible.all() == []
        await session.rollback()


async def test_another_user_cannot_reuse_a_foreign_dedupe_key(
    factory: async_sessionmaker[AsyncSession], users: tuple[UUID, UUID]
) -> None:
    """Dedupe keys are unique across tenants; a key taken by user A is invisible to user B, so B's insert fails on the
    unique index and nothing is sent. Callers therefore build keys that include the tenant."""
    user_a, user_b = users
    key = f"em2:foreign:{_tag()}"
    async with await _session_for(factory, user_a) as session:
        await send_email(
            session,
            FakeEmailProvider(),
            message=_message(f"a-{_tag()}@example.test"),
            kind="em2",
            user_id=user_a,
            dedupe_key=key,
        )
        await session.commit()

    provider = FakeEmailProvider()
    async with await _session_for(factory, user_b) as session:
        with pytest.raises(IntegrityError):
            await send_email(
                session,
                provider,
                message=_message(f"b-{_tag()}@example.test"),
                kind="em2",
                user_id=user_b,
                dedupe_key=key,
            )
        await session.rollback()
    assert provider.attempts == 0
