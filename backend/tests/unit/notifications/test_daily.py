"""REQ-NOT-06 (AC-MAIL-3, unit half): a daily message's dedupe key is built from exactly (user, kind, Nairobi date,
channel), so the table's unique ``dedupe_key`` allows one row, hence one message, per tuple; and ``attempt_limit``
caps the attempts of one message across every call (retries <= 3), ending it ``failed`` (a dead letter) when they are
spent. PostgreSQL half: ``integration/notifications/test_daily_uniqueness.py``."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import pytest
from structlog.testing import capture_logs

from bridge.ids import uuid7
from bridge.models.enums import DeliveryStatus, NotificationChannel
from bridge.notifications.deliveries import (
    MAX_ATTEMPTS,
    MAX_DEDUPE_KEY_CHARS,
    InMemoryDeliveryStore,
    daily_key,
    send_email,
)
from bridge.notifications.email import DeliveryError, EmailMessage, FakeEmailProvider
from bridge.notifications.models import NotificationDelivery

EMAIL, IN_APP = NotificationChannel.EMAIL, NotificationChannel.IN_APP
DAY = date(2026, 10, 5)
USER, OTHER, ORG = uuid7(), uuid7(), uuid7()
NOW = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)


async def _no_sleep(_seconds: float) -> None:
    return None


def transient() -> DeliveryError:
    return DeliveryError("SMTP 451 try later", transient=True, code=451)


async def send(store: InMemoryDeliveryStore, provider: FakeEmailProvider, **kwargs: Any) -> NotificationDelivery:
    values: dict[str, Any] = {
        "message": EmailMessage(to="dev@example.com", subject="Today", text="Needs you: 1"),
        "kind": "em7",
        "user_id": USER,
        "dedupe_key": daily_key("em7", EMAIL, USER, DAY),
        "local_date": DAY,
    }
    values.update(kwargs)
    return await send_email(store, provider, sleep=_no_sleep, clock=lambda: NOW, **values)


def test_a_daily_key_names_the_kind_channel_user_and_nairobi_date() -> None:
    assert daily_key("em7", EMAIL, USER, DAY) == f"em7:email:{USER}:2026-10-05"
    assert daily_key("em7_org", EMAIL, USER, DAY, org_id=ORG) == f"em7_org:email:{USER}:{ORG}:2026-10-05"
    keys = {
        daily_key("em7", EMAIL, USER, DAY),
        daily_key("em7", IN_APP, USER, DAY),
        daily_key("em7", EMAIL, OTHER, DAY),
        daily_key("em7", EMAIL, USER, date(2026, 10, 6)),
        daily_key("em7_org", EMAIL, USER, DAY),
        daily_key("em7_org", EMAIL, USER, DAY, org_id=ORG),
    }
    assert len(keys) == 6
    longest = daily_key("k" * 40, NotificationChannel.WHATSAPP, USER, DAY, org_id=ORG)
    assert len(longest) <= MAX_DEDUPE_KEY_CHARS


@pytest.mark.parametrize("kind", ["", "k" * 41, "em7:x", "EM7"])
def test_a_daily_key_refuses_a_malformed_kind(kind: str) -> None:
    with pytest.raises(ValueError, match="kind"):
        daily_key(kind, EMAIL, USER, DAY)


async def test_two_sends_for_one_user_day_and_channel_send_one_message() -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider()
    first = await send(store, provider)
    second = await send(store, provider)
    assert second is first
    assert len(provider.outbox) == 1
    assert [row.local_date for row in store.rows] == [DAY]
    await send(store, provider, dedupe_key=daily_key("em7", EMAIL, USER, date(2026, 10, 6)))
    assert len(provider.outbox) == 2  # the next day is a new message


async def test_the_attempt_limit_spans_calls_and_ends_in_a_dead_letter() -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider([transient() for _ in range(6)])
    first = await send(store, provider, attempt_limit=MAX_ATTEMPTS, max_attempts=2)
    assert (first.status, first.attempts) == (DeliveryStatus.QUEUED, 2)
    with capture_logs() as logs:
        second = await send(store, provider, attempt_limit=MAX_ATTEMPTS, max_attempts=2)
    assert second is first
    assert (second.status, second.attempts, second.last_error_transient) == (DeliveryStatus.FAILED, 3, True)
    assert [entry["event"] for entry in logs] == ["email.resumed", "email.dead_letter"]
    third = await send(store, provider, attempt_limit=MAX_ATTEMPTS)
    assert (third.status, third.attempts) == (DeliveryStatus.FAILED, 3)
    assert provider.attempts == 3  # never a fourth attempt
    assert provider.outbox == []


async def test_three_transient_failures_in_one_call_are_a_dead_letter_under_the_limit() -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider([transient() for _ in range(3)])
    row = await send(store, provider, attempt_limit=MAX_ATTEMPTS)
    assert (row.status, row.attempts) == (DeliveryStatus.FAILED, 3)
    without_limit = await send(
        InMemoryDeliveryStore(), FakeEmailProvider([transient() for _ in range(3)]), attempt_limit=None
    )
    assert without_limit.status is DeliveryStatus.QUEUED  # REQ-NOT-01 behaviour unchanged without a limit


async def test_a_queued_row_already_at_its_limit_is_dead_lettered_without_sending() -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider([transient() for _ in range(3)])
    queued = await send(store, provider)  # REQ-NOT-01: three attempts, still queued
    assert (queued.status, queued.attempts) == (DeliveryStatus.QUEUED, 3)
    with capture_logs() as logs:
        row = await send(store, provider, attempt_limit=MAX_ATTEMPTS)
    assert (row.status, row.attempts) == (DeliveryStatus.FAILED, 3)
    assert provider.attempts == 3
    assert [entry["event"] for entry in logs] == ["email.dead_letter"]


async def test_a_permanent_failure_is_final_at_once_under_the_limit() -> None:
    store = InMemoryDeliveryStore()
    provider = FakeEmailProvider([DeliveryError("550 no such user", transient=False, code=550)])
    row = await send(store, provider, attempt_limit=MAX_ATTEMPTS)
    assert (row.status, row.attempts, row.last_error_transient) == (DeliveryStatus.FAILED, 1, False)
    assert (await send(store, provider, attempt_limit=MAX_ATTEMPTS)).attempts == 1


async def test_a_resumed_row_succeeds_within_its_limit() -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider([transient(), transient()])
    queued = await send(store, provider, attempt_limit=MAX_ATTEMPTS, max_attempts=2)
    assert queued.status is DeliveryStatus.QUEUED
    row = await send(store, provider, attempt_limit=MAX_ATTEMPTS)
    assert (row.status, row.attempts) == (DeliveryStatus.SENT, 3)
    assert len(provider.outbox) == 1


@pytest.mark.parametrize("limit", [0, MAX_ATTEMPTS + 1])
async def test_an_attempt_limit_outside_one_to_three_is_refused(limit: int) -> None:
    store = InMemoryDeliveryStore()
    with pytest.raises(ValueError, match="attempt_limit"):
        await send(store, FakeEmailProvider(), attempt_limit=limit)
    assert store.rows == []
