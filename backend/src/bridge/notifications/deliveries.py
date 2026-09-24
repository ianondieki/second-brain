"""The delivery ledger around every email (REQ-NOT-01; AC-MAIL-3 closes with REQ-NOT-06 in Phase 3).

``send_email`` keeps one ``notification_deliveries`` row per message:

1. ``sent``, ``failed`` and ``suppressed`` are terminal: a call with the same ``dedupe_key`` returns the row and sends
   nothing (idempotent).
2. An address in ``email_suppressions`` is never sent to: its row ends ``suppressed``. The check runs before every
   send, including a resumed one.
3. Otherwise the row is ``queued`` (newly inserted, or found under the same ``dedupe_key``) and one call makes at most
   ``MAX_ATTEMPTS`` (3) attempts (AC-MAIL-3). A transient ``DeliveryError`` is retried after the backoff; a permanent
   one ends the row ``failed`` at once; success ends it ``sent``. When one call's attempts run out on transient errors,
   the row stays ``queued`` with ``last_error`` and ``last_error_transient=True``, so a later call with the same
   ``dedupe_key`` resumes it; ``attempts`` keeps counting across calls. A resuming call must name the same recipient.
   Any other exception from a provider is a bug and propagates (the caller's transaction then drops the row).

The caller owns the transaction: rows are flushed, never committed, on a session the caller has already scoped to a
tenant (``bridge.db.bind_tenant``). Storage sits behind the narrow ``DeliveryStore`` seam: ``SqlDeliveryStore`` for
PostgreSQL and ``InMemoryDeliveryStore`` for unit tests. Logs carry the delivery id and kind, never the address,
subject or body (docs/spec/08 Observability).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.models.enums import DeliveryStatus, NotificationChannel
from bridge.notifications.email import DeliveryError, EmailMessage, EmailProvider, redact_addresses
from bridge.notifications.models import EmailSuppression, NotificationDelivery

MAX_ATTEMPTS = 3
DEFAULT_BACKOFF: tuple[float, ...] = (0.5, 2.0)  # seconds before attempts 2 and 3
MAX_KIND_CHARS = 40  # notification_deliveries.kind
MAX_DEDUPE_KEY_CHARS = 200  # notification_deliveries.dedupe_key

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], datetime]


class DeliveryStore(Protocol):
    """Where ``send_email`` keeps its rows."""

    async def find_by_dedupe_key(self, dedupe_key: str) -> NotificationDelivery | None: ...

    async def is_suppressed(self, address: str) -> bool: ...

    async def add(self, delivery: NotificationDelivery) -> bool:
        """Insert ``delivery``. False, with nothing inserted, when its dedupe key is already taken."""
        ...

    async def save(self, delivery: NotificationDelivery) -> None:
        """Persist changes to a row returned by ``add`` or ``find_by_dedupe_key``."""
        ...


class SqlDeliveryStore:
    """``DeliveryStore`` on the caller's tenant-scoped ``AsyncSession``. Flushes; never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_dedupe_key(self, dedupe_key: str) -> NotificationDelivery | None:
        # FOR UPDATE: a concurrent send of the same key waits here until this transaction ends and then reads the row's
        # final state, so a queued row is never resumed by two senders at once. populate_existing refreshes an instance
        # this session already holds.
        row: NotificationDelivery | None = await self._session.scalar(
            select(NotificationDelivery)
            .where(NotificationDelivery.dedupe_key == dedupe_key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return row

    async def is_suppressed(self, address: str) -> bool:
        # email_suppressions.email is citext, so the comparison ignores case.
        found = await self._session.scalar(
            select(EmailSuppression.id).where(EmailSuppression.email == address).limit(1)
        )
        return found is not None

    async def add(self, delivery: NotificationDelivery) -> bool:
        await self._session.flush()  # the caller's own pending changes fail here, outside the savepoint
        try:
            async with self._session.begin_nested():
                self._session.add(delivery)
        except IntegrityError:
            # A concurrent send inserted the same dedupe key after our lookup; any other violation is re-raised.
            if delivery.dedupe_key is not None and await self.find_by_dedupe_key(delivery.dedupe_key) is not None:
                return False
            raise
        return True

    async def save(self, delivery: NotificationDelivery) -> None:
        await self._session.flush()


class InMemoryDeliveryStore:
    """``DeliveryStore`` for unit tests. Suppressions match case-insensitively, like ``citext`` in PostgreSQL."""

    def __init__(self, suppressed: Iterable[str] = ()) -> None:
        self.rows: list[NotificationDelivery] = []
        self._suppressed = {address.casefold() for address in suppressed}

    async def find_by_dedupe_key(self, dedupe_key: str) -> NotificationDelivery | None:
        return next((row for row in self.rows if row.dedupe_key == dedupe_key), None)

    async def is_suppressed(self, address: str) -> bool:
        return address.casefold() in self._suppressed

    def suppress(self, address: str) -> None:
        """Add ``address`` to the suppression list (as a bounce or unsubscribe would)."""
        self._suppressed.add(address.casefold())

    async def add(self, delivery: NotificationDelivery) -> bool:
        if delivery.dedupe_key is not None and await self.find_by_dedupe_key(delivery.dedupe_key) is not None:
            return False
        self.rows.append(delivery)
        return True

    async def save(self, delivery: NotificationDelivery) -> None:
        if not any(row is delivery for row in self.rows):
            raise LookupError("save() called for a delivery that was never added")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check_arguments(
    *,
    kind: str,
    user_id: UUID | None,
    org_id: UUID | None,
    dedupe_key: str | None,
    max_attempts: int,
    backoff: Sequence[float],
) -> None:
    if not 1 <= max_attempts <= MAX_ATTEMPTS:
        raise ValueError(f"max_attempts must be between 1 and {MAX_ATTEMPTS}")
    if any(delay < 0 for delay in backoff):
        raise ValueError("backoff delays must not be negative")
    if user_id is None and org_id is None:
        raise ValueError("a delivery needs a user_id or org_id (check constraint has_recipient_scope)")
    if not kind or len(kind) > MAX_KIND_CHARS:
        raise ValueError(f"kind must be 1-{MAX_KIND_CHARS} characters")
    if dedupe_key is not None and not 0 < len(dedupe_key) <= MAX_DEDUPE_KEY_CHARS:
        raise ValueError(f"dedupe_key must be 1-{MAX_DEDUPE_KEY_CHARS} characters")


async def send_email(
    session: AsyncSession | DeliveryStore,
    provider: EmailProvider,
    *,
    message: EmailMessage,
    kind: str,
    user_id: UUID | None = None,
    org_id: UUID | None = None,
    dedupe_key: str | None = None,
    local_date: date | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    backoff: Sequence[float] = DEFAULT_BACKOFF,
    sleep: Sleep = asyncio.sleep,
    clock: Clock = _utcnow,
) -> NotificationDelivery:
    """Send ``message`` once through ``provider`` and return its ledger row (see the module docstring).

    ``session`` is the caller's tenant-scoped ``AsyncSession`` (or any ``DeliveryStore``). ``backoff[i]`` is the
    wait before attempt ``i + 2``; the last value repeats. ``sleep`` and ``clock`` are injectable for tests.
    """
    _check_arguments(
        kind=kind, user_id=user_id, org_id=org_id, dedupe_key=dedupe_key, max_attempts=max_attempts, backoff=backoff
    )
    store: DeliveryStore = SqlDeliveryStore(session) if isinstance(session, AsyncSession) else session
    log = get_logger(__name__)  # per call, so a logger cached under an earlier configuration is never reused

    delivery = await store.find_by_dedupe_key(dedupe_key) if dedupe_key is not None else None
    if delivery is not None:
        if delivery.status != DeliveryStatus.QUEUED:  # sent, failed and suppressed are terminal
            log.info("email.duplicate", kind=kind, delivery_id=str(delivery.id), status=str(delivery.status))
            return delivery
        if delivery.to_address.casefold() != message.to.casefold():
            raise ValueError("this dedupe_key is already recorded for a different recipient")

    suppressed = await store.is_suppressed(message.to)
    if delivery is None:
        delivery = NotificationDelivery(
            id=uuid7(),
            user_id=user_id,
            org_id=org_id,
            kind=kind,
            channel=NotificationChannel.EMAIL,
            to_address=message.to,
            dedupe_key=dedupe_key,
            local_date=local_date,
            status=DeliveryStatus.SUPPRESSED if suppressed else DeliveryStatus.QUEUED,
            attempts=0,
            provider=None if suppressed else provider.name,
        )
        if not await store.add(delivery):
            # A concurrent send inserted the same dedupe key between our lookup and our insert. Its row is left alone,
            # even when queued (that send may still be under way); a later call resumes it.
            winner = await store.find_by_dedupe_key(dedupe_key) if dedupe_key is not None else None
            if winner is None:
                raise RuntimeError("the delivery store refused an insert without a dedupe-key conflict")
            log.info("email.duplicate", kind=kind, delivery_id=str(winner.id), status=str(winner.status))
            return winner
    elif suppressed:
        delivery.status = DeliveryStatus.SUPPRESSED
        await store.save(delivery)
    else:
        log.info("email.resumed", kind=kind, delivery_id=str(delivery.id), attempts=delivery.attempts)
        delivery.provider = provider.name
    if suppressed:
        log.info("email.suppressed", kind=kind, delivery_id=str(delivery.id))
        return delivery

    delays = tuple(backoff) or (0.0,)
    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            await sleep(delays[min(attempt - 2, len(delays) - 1)])
        delivery.attempts += 1  # counts across calls when a queued row is resumed
        try:
            result = await provider.send(message)
        except DeliveryError as exc:
            delivery.last_error = redact_addresses(str(exc))
            delivery.last_error_transient = exc.transient
            if not exc.transient:
                delivery.status = DeliveryStatus.FAILED  # terminal: never resent under this dedupe key
                event = "email.failed"
            elif attempt < max_attempts:
                event = "email.retry"
            else:
                event = "email.deferred"  # stays queued: a later call with the same dedupe key resumes it
            await store.save(delivery)
            log.warning(
                event,
                kind=kind,
                delivery_id=str(delivery.id),
                attempts=delivery.attempts,
                transient=exc.transient,
                error=delivery.last_error,
            )
            if event == "email.retry":
                continue
            return delivery
        delivery.status = DeliveryStatus.SENT
        delivery.provider = result.provider
        delivery.provider_message_id = result.message_id
        delivery.sent_at = clock()
        await store.save(delivery)
        log.info(
            "email.sent", kind=kind, delivery_id=str(delivery.id), attempts=delivery.attempts, provider=result.provider
        )
        return delivery
    raise AssertionError("unreachable: max_attempts is at least 1")
