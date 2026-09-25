"""Auth emails are sent after the HTTP response (FastAPI background task), in their own transaction.

Why: the request path must cost the same whether or not an address has an account (no enumeration by timing), and a
slow provider must not hold the request's transaction or its audit-chain lock. Link tokens are created and committed
in the request; only the finished wording travels here and it is never stored.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.emails import Wording
from bridge.db import bind_tenant
from bridge.logging import get_logger
from bridge.notifications.deliveries import send_email
from bridge.notifications.email import EmailMessage, EmailProvider


@dataclass(frozen=True, slots=True)
class PendingEmail:
    user_id: UUID
    address: str
    wording: Wording
    kind: str
    dedupe_key: str | None = None


async def deliver(
    factory: async_sessionmaker[AsyncSession], provider: EmailProvider, pending: list[PendingEmail]
) -> None:
    """Send each pending email through the delivery ledger (REQ-NOT-01); failures are recorded there, never raised."""
    log = get_logger("bridge.auth.mailer")
    for item in pending:
        try:
            async with factory() as db:
                await bind_tenant(db, user_id=item.user_id)
                message = EmailMessage(
                    to=item.address, subject=item.wording.subject, text=item.wording.text, html=None, tag=item.kind
                )
                await send_email(
                    db, provider, message=message, kind=item.kind, user_id=item.user_id, dedupe_key=item.dedupe_key
                )
                await db.commit()
        except DBAPIError as exc:  # DB messages can carry addresses (DETAIL: Key (email)=...): log the constraint only
            constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            log.error("auth.email_not_recorded", kind=item.kind, constraint=constraint)
        except Exception as exc:  # a background task has no caller to report to: log the type and continue
            log.error("auth.email_not_recorded", kind=item.kind, error_type=type(exc).__name__)
