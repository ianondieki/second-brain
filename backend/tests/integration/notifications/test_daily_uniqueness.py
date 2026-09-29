"""AC-MAIL-3 (REQ-NOT-06, REQ-NOT-01) against PostgreSQL, as ``bridge_app`` under RLS: ``notification_deliveries``
holds at most one EM7 per (user, kind, Nairobi date, channel), through the unique ``dedupe_key`` that ``daily_key``
builds from exactly that tuple, also when two sends race; a failing provider is tried at most 3 times per message
across runs, transient errors retried and permanent ones final, and a spent message ends ``failed`` (dead letter).
In-app summaries are written once per key with their ledger row; email preferences default on. The dispatcher's own
once-a-day behaviour is in ``integration/reminders/test_dispatch.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import bridge.models.all  # noqa: F401  # registers every table (foreign keys resolve at flush)
from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.models.enums import DeliveryStatus, NotificationChannel
from bridge.notifications.deliveries import MAX_ATTEMPTS, daily_key, send_email
from bridge.notifications.email import DeliveryError, EmailMessage, FakeEmailProvider
from bridge.notifications.in_app import post_in_app
from bridge.notifications.models import InAppNotification, NotificationDelivery, NotificationPreference
from bridge.notifications.preferences import channel_enabled

EMAIL, IN_APP = NotificationChannel.EMAIL, NotificationChannel.IN_APP
DAY = date(2026, 10, 5)
Factory = async_sessionmaker[AsyncSession]


async def _no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture(scope="module")
def factory(app_engine: AsyncEngine) -> Factory:
    return create_session_factory(app_engine)


@pytest.fixture
async def user(owner_engine: AsyncEngine) -> tuple[UUID, str]:
    user_id = uuid7()
    address = f"not06-{user_id.hex[-12:]}@example.test"
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Daily')"),
            {"id": user_id, "email": address},
        )
    return user_id, address


async def _em7(
    factory: Factory, provider: FakeEmailProvider, user_id: UUID, address: str, **kwargs: object
) -> NotificationDelivery:
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        row = await send_email(
            db,
            provider,
            message=EmailMessage(to=address, subject="Today on Bridge", text="Needs you: 1"),
            kind="em7",
            user_id=user_id,
            dedupe_key=daily_key("em7", EMAIL, user_id, DAY),
            local_date=DAY,
            attempt_limit=MAX_ATTEMPTS,
            sleep=_no_sleep,
            **kwargs,  # type: ignore[arg-type]
        )
        await db.commit()
        return row


async def _rows(factory: Factory, user_id: UUID) -> list[NotificationDelivery]:
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        return list(
            (await db.scalars(select(NotificationDelivery).where(NotificationDelivery.user_id == user_id))).all()
        )


async def test_two_em7_sends_for_one_user_day_and_channel_leave_one_row_and_one_email(
    factory: Factory, user: tuple[UUID, str]
) -> None:
    user_id, address = user
    provider = FakeEmailProvider()
    first = await _em7(factory, provider, user_id, address)
    second = await _em7(factory, provider, user_id, address)
    assert second.id == first.id
    assert len(provider.outbox) == 1
    (row,) = await _rows(factory, user_id)
    assert (row.kind, row.channel, row.local_date, row.status) == ("em7", EMAIL, DAY, DeliveryStatus.SENT)


async def test_two_racing_em7_sends_deliver_one_message(factory: Factory, user: tuple[UUID, str]) -> None:
    user_id, address = user
    provider = FakeEmailProvider()
    rows = await asyncio.gather(*(_em7(factory, provider, user_id, address) for _ in range(2)))
    assert rows[0].id == rows[1].id
    assert len(provider.outbox) == 1
    assert len(await _rows(factory, user_id)) == 1


async def test_the_database_refuses_a_second_row_for_the_same_daily_key(
    factory: Factory, user: tuple[UUID, str]
) -> None:
    user_id, address = user
    await _em7(factory, FakeEmailProvider(), user_id, address)
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        db.add(
            NotificationDelivery(
                id=uuid7(),
                user_id=user_id,
                kind="em7",
                channel=EMAIL,
                to_address=address,
                dedupe_key=daily_key("em7", EMAIL, user_id, DAY),
                local_date=DAY,
            )
        )
        with pytest.raises(IntegrityError, match="uq_notification_deliveries_dedupe_key"):
            await db.flush()


async def test_a_failing_provider_is_tried_at_most_three_times_across_runs(
    factory: Factory, user: tuple[UUID, str]
) -> None:
    user_id, address = user
    provider = FakeEmailProvider([DeliveryError("SMTP 451", transient=True, code=451) for _ in range(5)])
    first = await _em7(factory, provider, user_id, address, max_attempts=2)
    assert (first.status, first.attempts) == (DeliveryStatus.QUEUED, 2)
    second = await _em7(factory, provider, user_id, address)
    assert (second.status, second.attempts) == (DeliveryStatus.FAILED, 3)
    third = await _em7(factory, provider, user_id, address)
    assert (third.status, third.attempts) == (DeliveryStatus.FAILED, 3)
    assert provider.attempts == 3
    assert provider.outbox == []


async def test_a_permanent_failure_is_final_after_one_attempt(factory: Factory, user: tuple[UUID, str]) -> None:
    user_id, address = user
    provider = FakeEmailProvider([DeliveryError("SMTP 550 no such user", transient=False, code=550)])
    row = await _em7(factory, provider, user_id, address)
    assert (row.status, row.attempts, row.last_error_transient) == (DeliveryStatus.FAILED, 1, False)
    await _em7(factory, provider, user_id, address)
    assert provider.attempts == 1


async def test_an_in_app_summary_is_written_once_per_key(factory: Factory, user: tuple[UUID, str]) -> None:
    user_id, _ = user
    key = daily_key("em7", IN_APP, user_id, DAY)
    written = []
    for _ in range(2):
        async with factory() as db:
            await bind_tenant(db, user_id=user_id)
            written.append(
                await post_in_app(
                    db,
                    user_id=user_id,
                    kind="em7",
                    title="Your daily update",
                    body="Needs you: 1",
                    link="/engagements",
                    dedupe_key=key,
                    local_date=DAY,
                )
            )
            await db.commit()
    assert written == [True, False]
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        count = await db.scalar(select(func.count()).where(InAppNotification.user_id == user_id))
        assert count == 1
    (row,) = await _rows(factory, user_id)
    assert (row.channel, row.status, row.to_address, row.dedupe_key) == (IN_APP, DeliveryStatus.SENT, "in-app", key)


async def test_an_in_app_title_is_one_to_two_hundred_characters(factory: Factory, user: tuple[UUID, str]) -> None:
    user_id, _ = user
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        for title in ("  ", "t" * 201):
            with pytest.raises(ValueError, match="title"):
                await post_in_app(
                    db, user_id=user_id, kind="em7", title=title, body=None, link=None, dedupe_key=f"k:{uuid7()}"
                )


@pytest.mark.parametrize("link", ["https://evil.example/x", "//evil.example", "engagements"])
async def test_an_in_app_link_is_a_platform_path(factory: Factory, user: tuple[UUID, str], link: str) -> None:
    user_id, _ = user
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        with pytest.raises(ValueError, match="platform path"):
            await post_in_app(
                db, user_id=user_id, kind="em7", title="T", body=None, link=link, dedupe_key=f"k:{uuid7()}"
            )


async def test_email_preferences_default_on_and_an_explicit_choice_wins(
    factory: Factory, user: tuple[UUID, str]
) -> None:
    user_id, _ = user
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        assert await channel_enabled(db, user_id, "em7", EMAIL) is True
        db.add(NotificationPreference(user_id=user_id, kind="em7", channel=EMAIL, enabled=False))
        await db.commit()
    async with factory() as db:
        await bind_tenant(db, user_id=user_id)
        assert await channel_enabled(db, user_id, "em7", EMAIL) is False
        assert await channel_enabled(db, user_id, "em7_org", EMAIL) is True
