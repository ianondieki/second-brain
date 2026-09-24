"""REQ-NOT-01: the delivery ledger around every send. Each send is one ``notification_deliveries`` row; at most 3
attempts with the transient/permanent classification ported from ``reminder/notify.py``; ``email_suppressions`` is
checked before every send; a ``dedupe_key`` makes a send idempotent. AC-MAIL-3 closes with REQ-NOT-06 (Phase 3)
against PostgreSQL; here the ledger runs on ``InMemoryDeliveryStore``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

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


@pytest.mark.parametrize("address", [ADDRESS, "DEV@Example.COM"])
async def test_a_suppressed_address_is_recorded_and_never_sent(address: str) -> None:
    store = InMemoryDeliveryStore(suppressed=["Dev@Example.com"])  # citext in Postgres: case-insensitive
    provider = FakeEmailProvider()
    row = await send(store, provider, message=message(to=address), dedupe_key="em2:e1")

    assert row.status is DeliveryStatus.SUPPRESSED
    assert row.attempts == 0
    assert row.provider is None
    assert row.sent_at is None
    assert store.rows == [row]
    assert provider.attempts == 0

    again = await send(store, provider, message=message(to=address), dedupe_key="em2:e1")
    assert again is row
    assert provider.attempts == 0


async def test_a_duplicate_dedupe_key_sends_nothing_more() -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider()
    first = await send(store, provider, dedupe_key="em2:engagement-1")
    second = await send(store, provider, dedupe_key="em2:engagement-1")

    assert second is first
    assert second.status is DeliveryStatus.SENT
    assert provider.attempts == 1
    assert len(provider.outbox) == 1
    assert store.rows == [first]


async def test_a_failed_row_is_not_resent_under_the_same_dedupe_key() -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider(failures=[permanent()])
    first = await send(store, provider, dedupe_key="em7:user:2026-09-24")
    second = await send(store, provider, dedupe_key="em7:user:2026-09-24")
    assert second is first
    assert first.status is DeliveryStatus.FAILED
    assert provider.attempts == 1


async def test_different_dedupe_keys_each_send() -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider()
    await send(store, provider, dedupe_key="em2:engagement-1")
    await send(store, provider, dedupe_key="em2:engagement-2")
    await send(store, provider)
    await send(store, provider)  # no key: not deduplicated
    assert provider.attempts == 4
    assert len(store.rows) == 4


class RacingStore(InMemoryDeliveryStore):
    """A concurrent sender inserts the same dedupe key between our lookup and our insert."""

    def __init__(self, winner: NotificationDelivery) -> None:
        super().__init__()
        self._winner = winner
        self._lookups = 0

    async def find_by_dedupe_key(self, dedupe_key: str) -> NotificationDelivery | None:
        self._lookups += 1
        if self._lookups == 1:
            self.rows.append(self._winner)  # lands after our lookup
            return None
        return await super().find_by_dedupe_key(dedupe_key)


async def test_losing_an_insert_race_returns_the_winner_and_sends_nothing() -> None:
    winner = NotificationDelivery(
        id=uuid7(),
        user_id=USER_ID,
        kind="em2",
        channel=NotificationChannel.EMAIL,
        to_address=ADDRESS,
        dedupe_key="em2:engagement-1",
        status=DeliveryStatus.QUEUED,
        attempts=0,
    )
    store, provider = RacingStore(winner), FakeEmailProvider()
    row = await send(store, provider, dedupe_key="em2:engagement-1")
    assert row is winner
    assert provider.attempts == 0
    assert store.rows == [winner]


async def test_no_log_line_carries_the_address_subject_or_body() -> None:
    failing = f"Postmark HTTP 422: Invalid 'To' address: '{ADDRESS}'"
    provider = FakeEmailProvider(failures=[transient(), DeliveryError(failing, code=300)])
    store = InMemoryDeliveryStore(suppressed=["blocked@example.com"])
    with capture_logs() as logs:
        await send(store, provider)
        await send(store, FakeEmailProvider(), message=message(to="blocked@example.com"))
        await send(store, FakeEmailProvider())

    assert {entry["event"] for entry in logs} >= {"email.retry", "email.failed", "email.suppressed", "email.sent"}
    flat = repr(logs)
    for secret in (ADDRESS, "blocked@example.com", "Your proposal", "Private body text"):
        assert secret not in flat
    assert ADDRESS not in (store.rows[0].last_error or "")  # addresses are redacted from the stored error too


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        pytest.param({"max_attempts": 0}, "max_attempts", id="zero-attempts"),
        pytest.param({"max_attempts": 4}, "max_attempts", id="more-than-three"),
        pytest.param({"backoff": (-1.0,)}, "backoff", id="negative-backoff"),
        pytest.param({"user_id": None, "org_id": None}, "user_id or org_id", id="no-recipient-scope"),
        pytest.param({"kind": ""}, "kind", id="empty-kind"),
        pytest.param({"kind": "k" * 41}, "kind", id="kind-too-long"),
        pytest.param({"dedupe_key": "d" * 201}, "dedupe_key", id="dedupe-key-too-long"),
    ],
)
async def test_bad_arguments_are_refused_before_anything_is_written(kwargs: dict[str, Any], match: str) -> None:
    store, provider = InMemoryDeliveryStore(), FakeEmailProvider()
    with pytest.raises(ValueError, match=match):
        await send(store, provider, **kwargs)
    assert store.rows == []
    assert provider.attempts == 0


async def test_an_org_scoped_send_needs_no_user() -> None:
    row = await send(InMemoryDeliveryStore(), FakeEmailProvider(), user_id=None, org_id=uuid7())
    assert row.status is DeliveryStatus.SENT
    assert row.user_id is None
