"""REQ-NOT-01: the delivery ledger around every send. Each send is one ``notification_deliveries`` row; at most 3
attempts with the transient/permanent classification ported from ``reminder/notify.py``; ``email_suppressions`` is
checked before every send; a ``dedupe_key`` makes a send idempotent. AC-MAIL-3 closes with REQ-NOT-06 (Phase 3)
against PostgreSQL; here the ledger runs on ``InMemoryDeliveryStore``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from bridge.ids import uuid7
from bridge.models.enums import DeliveryStatus, NotificationChannel
from bridge.notifications.deliveries import MAX_ATTEMPTS, InMemoryDeliveryStore, send_email
from bridge.notifications.email import DeliveryError, EmailMessage, FakeEmailProvider
from bridge.notifications.models import NotificationDelivery

ADDRESS = "dev@example.com"
NOW = datetime(2026, 9, 24, 7, 0, tzinfo=UTC)
USER_ID = uuid7()


class Sleeps:
    """An instant ``asyncio.sleep`` that records the delays asked for."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def message(**overrides: Any) -> EmailMessage:
    values: dict[str, Any] = {"to": ADDRESS, "subject": "Your proposal", "text": "Private body text"}
    values.update(overrides)
    return EmailMessage(**values)


def transient(text: str = "Postmark HTTP 503") -> DeliveryError:
    return DeliveryError(text, transient=True)


def permanent(text: str = "Postmark HTTP 422, code 406") -> DeliveryError:
    return DeliveryError(text, transient=False, code=406)


async def send(
    store: InMemoryDeliveryStore, provider: FakeEmailProvider, sleeps: Sleeps | None = None, **kwargs: Any
) -> NotificationDelivery:
    values: dict[str, Any] = {"message": message(), "kind": "em2", "user_id": USER_ID}
    values.update(kwargs)
    return await send_email(store, provider, sleep=sleeps or Sleeps(), clock=lambda: NOW, **values)


async def test_success_on_the_first_attempt() -> None:
    store, provider, sleeps = InMemoryDeliveryStore(), FakeEmailProvider(), Sleeps()
    local = date(2026, 9, 24)
    org_id = uuid7()
    row = await send(store, provider, sleeps, org_id=org_id, dedupe_key="em2:e1", local_date=local)

    assert row.status is DeliveryStatus.SENT
    assert row.attempts == 1
    assert row.provider == "fake"
    assert row.provider_message_id == "fake-1"
    assert row.sent_at == NOW
    assert row.last_error is None
    assert row.last_error_transient is None
    assert (row.kind, row.channel, row.to_address) == ("em2", NotificationChannel.EMAIL, ADDRESS)
    assert (row.user_id, row.org_id, row.dedupe_key, row.local_date) == (USER_ID, org_id, "em2:e1", local)
    assert isinstance(row.id, UUID)
    assert store.rows == [row]
    assert provider.outbox == [message()]
    assert sleeps.calls == []


async def test_a_transient_failure_is_retried_then_sent() -> None:
    store, provider, sleeps = InMemoryDeliveryStore(), FakeEmailProvider(failures=[transient()]), Sleeps()
    row = await send(store, provider, sleeps)

    assert row.status is DeliveryStatus.SENT
    assert row.attempts == 2
    assert row.sent_at == NOW
    assert row.last_error == "Postmark HTTP 503"  # kept: explains why it took two attempts
    assert row.last_error_transient is True
    assert provider.attempts == 2
    assert len(provider.outbox) == 1
    assert sleeps.calls == [0.5]


async def test_three_transient_failures_give_up_as_failed() -> None:
    store = InMemoryDeliveryStore()
    provider = FakeEmailProvider(failures=[transient("a"), transient("b"), transient("c")])
    sleeps = Sleeps()
    row = await send(store, provider, sleeps)

    assert row.status is DeliveryStatus.FAILED
    assert row.attempts == 3 == MAX_ATTEMPTS
    assert row.last_error == "c"
    assert row.last_error_transient is True
    assert row.sent_at is None
    assert row.provider_message_id is None
    assert provider.attempts == 3
    assert provider.outbox == []
    assert sleeps.calls == [0.5, 2.0]  # no sleep after the last attempt


async def test_a_permanent_failure_stops_at_once() -> None:
    store, provider, sleeps = InMemoryDeliveryStore(), FakeEmailProvider(failures=[permanent()]), Sleeps()
    row = await send(store, provider, sleeps)

    assert row.status is DeliveryStatus.FAILED
    assert row.attempts == 1
    assert row.last_error == "Postmark HTTP 422, code 406"
    assert row.last_error_transient is False
    assert provider.attempts == 1
    assert sleeps.calls == []


async def test_a_permanent_failure_after_a_transient_one_stops_there() -> None:
    store = InMemoryDeliveryStore()
    provider = FakeEmailProvider(failures=[transient(), permanent(), transient()])
    row = await send(store, provider)

    assert row.status is DeliveryStatus.FAILED
    assert row.attempts == 2
    assert row.last_error_transient is False
    assert provider.attempts == 2


async def test_a_short_backoff_repeats_its_last_delay() -> None:
    provider = FakeEmailProvider(failures=[transient(), transient(), transient()])
    sleeps = Sleeps()
    await send(InMemoryDeliveryStore(), provider, sleeps, backoff=(1.0,))
    assert sleeps.calls == [1.0, 1.0]


async def test_max_attempts_one_never_retries() -> None:
    provider = FakeEmailProvider(failures=[transient()])
    row = await send(InMemoryDeliveryStore(), provider, max_attempts=1)
    assert (row.status, row.attempts, provider.attempts) == (DeliveryStatus.FAILED, 1, 1)
