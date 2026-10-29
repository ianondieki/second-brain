"""REQ-NOT-02: ``em1.deliver`` runs after the Pitch committed, so it never raises: a provider bug or a database error is
logged without the address (the ledger keeps what it can), and a delivered EM1 is sent once per dedupe key."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

from bridge.db import create_session_factory
from bridge.ids import uuid7
from bridge.notifications import em1
from bridge.notifications.email import EmailMessage, FakeEmailProvider, SendResult
from tests.integration import world as w
from tests.integration.proposals.helpers import rows

PARTS = em1.EmailParts("Your proposal", "Plain text", "<p>HTML</p>")


class BrokenProvider:
    name = "broken"

    async def send(self, message: EmailMessage) -> SendResult:
        raise RuntimeError("a provider bug")


async def test_a_provider_bug_is_logged_not_raised(app_engine: AsyncEngine, owner_engine: AsyncEngine) -> None:
    address = f"em1-{uuid4().hex[:10]}@example.test"
    async with owner_engine.begin() as conn:
        user_id = await w.add_user(conn, address, "Dev")
    pending = em1.PendingEm1(user_id, address, PARTS, f"em1:{uuid7()}:{uuid7()}")
    with capture_logs() as logs:
        await em1.deliver(create_session_factory(app_engine), BrokenProvider(), pending)
    assert [(e["event"], e.get("error_type")) for e in logs if e["event"] == "em1.not_recorded"] == [
        ("em1.not_recorded", "RuntimeError")
    ]
    assert address not in repr(logs)
    # The transaction rolled back: no ledger row claims a send.
    assert await rows(owner_engine, "SELECT id FROM notification_deliveries WHERE user_id = :u", u=user_id) == []


async def test_a_database_error_is_logged_by_constraint_only(
    app_engine: AsyncEngine, owner_engine: AsyncEngine
) -> None:
    ghost = uuid7()  # no such user: the ledger row's foreign key fails
    address = f"ghost-{uuid4().hex[:10]}@example.test"
    provider = FakeEmailProvider()
    with capture_logs() as logs:
        await em1.deliver(
            create_session_factory(app_engine), provider, em1.PendingEm1(ghost, address, PARTS, "em1:x:y")
        )
    [event] = [e for e in logs if e["event"] == "em1.not_recorded"]
    assert event["constraint"] == "fk_notification_deliveries_user_id_users"
    assert address not in repr(logs)
    assert provider.outbox == []


async def test_one_email_per_dedupe_key(app_engine: AsyncEngine, owner_engine: AsyncEngine) -> None:
    address = f"em1-{uuid4().hex[:10]}@example.test"
    async with owner_engine.begin() as conn:
        user_id = await w.add_user(conn, address, "Dev")
    provider = FakeEmailProvider()
    pending = em1.PendingEm1(user_id, address, PARTS, f"em1:{uuid7()}:{uuid7()}")
    for _ in range(3):
        await em1.deliver(create_session_factory(app_engine), provider, pending)
    assert len(provider.outbox) == 1
    assert (provider.outbox[0].to, provider.outbox[0].html, provider.outbox[0].tag) == (address, "<p>HTML</p>", "em1")
    [row] = await rows(owner_engine, "SELECT kind, status FROM notification_deliveries WHERE user_id = :u", u=user_id)
    assert (row.kind, row.status) == ("em1", "sent")
