"""Limits on sending invitation emails (REQ-TEN-02; the P28 security review's MAJOR on invitation email abuse).

Every invite and every resend sends an email to an address the caller typed, so each counts, before any invitation
row is written, against three limits on the ``login_attempts`` ledger (HMAC digests only, never an id, address or IP
in clear):

- the caller: ``SENDS_PER_HOUR`` in any hour (``bridge.teams.limits.spend``);
- the organisation: ``ORG_SENDS_PER_DAY`` in any 24 hours, whoever sends;
- the recipient address, across organisations: ``ADDRESS_PER_WINDOW`` from one client IP in ``ADDRESS_WINDOW`` and
  ``ADDRESS_PER_DAY`` from anywhere in 24 hours (the sign-up and link emails' rule, ``bridge.auth.service``).

Past any of them: 429 ``rate_limited`` with ``Retry-After`` (whole seconds until the oldest counted send leaves the
window). The caller commits the counts before the invitation is checked any further, so a send the database refuses
afterwards (an existing member, a second invitation) still counts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.auth import throttle
from bridge.auth.models import LoginAttempt
from bridge.config import Settings
from bridge.teams import limits
from bridge.tenancy.deps import OrgContext

SENDS_PER_HOUR: Final = 10  # per caller, any organisation
ORG_SENDS_PER_DAY: Final = 30  # per organisation, any caller
ADDRESS_PER_WINDOW: Final = 3  # per recipient address and client IP
ADDRESS_WINDOW: Final = timedelta(minutes=15)
ADDRESS_PER_DAY: Final = 20  # per recipient address, from anywhere
CALLER_PURPOSE: Final = "org_invitation_sender"  # the ledger's purpose labels
ORG_PURPOSE: Final = "org_invitation_org"
ADDRESS_PURPOSE: Final = "org_invitation_address"
CODE: Final = "rate_limited"
# [[COPY-REVIEW]]
CALLER_MESSAGE: Final = f"You have sent {SENDS_PER_HOUR} invitations in the last hour. Try again later."
ORG_MESSAGE: Final = f"Your organisation has sent {ORG_SENDS_PER_DAY} invitations today. Try again tomorrow."
ADDRESS_MESSAGE: Final = "This address has had several invitations recently. Try again later."


async def _spend_address(db: AsyncSession, secret: str, address: str, ip: str) -> None:
    keys = throttle.keys(secret, ADDRESS_PURPOSE, address, ip)
    await limits.lock(db, f"{ADDRESS_PURPOSE}:{keys.email.hex()}")
    now = clock.utcnow()
    for window, limit, same_ip in ((ADDRESS_WINDOW, ADDRESS_PER_WINDOW, True), (limits.DAY, ADDRESS_PER_DAY, False)):
        where = and_(LoginAttempt.email_digest == keys.email, LoginAttempt.created_at > now - window)
        if same_ip:
            where = and_(where, LoginAttempt.ip_digest == keys.ip)
        count, oldest = (await db.execute(select(func.count(), func.min(LoginAttempt.created_at)).where(where))).one()
        if int(count) >= limit:
            raise limits.too_many(CODE, ADDRESS_MESSAGE, limits.retry_after(oldest, window, now))
    throttle.record(db, keys, succeeded=True)


async def spend_send(db: AsyncSession, settings: Settings, org: OrgContext, address: str, ip: str) -> None:
    """Count one invitation email from the caller of ``org`` to ``address`` (see the module docstring), or raise 429
    ``rate_limited``. The records join the caller's transaction (commit them before going on)."""
    secret = settings.secret_key.get_secret_value()
    await limits.spend(
        db,
        secret,
        purpose=CALLER_PURPOSE,
        user_id=org.live.user.id,
        limit=SENDS_PER_HOUR,
        window=limits.HOUR,
        code=CODE,
        message=CALLER_MESSAGE,
    )
    await limits.spend(
        db,
        secret,
        purpose=ORG_PURPOSE,
        user_id=org.org_id,
        limit=ORG_SENDS_PER_DAY,
        window=limits.DAY,
        code=CODE,
        message=ORG_MESSAGE,
    )
    await _spend_address(db, secret, address, ip)
