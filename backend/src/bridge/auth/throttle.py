"""Attempt throttling on the ``login_attempts`` ledger (docs/spec/08: login 5/min per IP + account).

Keys are HMAC digests of the normalised email and the client IP, never the raw values. Limits per rolling minute:
5 for one (IP, account) pair; 20 for one account from any IP (credential stuffing); 100 for one IP (a shared NAT
must not lock out a whole campus). Magic-link and signup emails reuse the ledger with their own purpose labels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.auth.crypto import keyed_digest
from bridge.auth.models import LoginAttempt

WINDOW = timedelta(minutes=1)
PER_ACCOUNT_ANY_IP = 20
PER_IP_ANY_ACCOUNT = 100


@dataclass(frozen=True, slots=True)
class Keys:
    email: bytes
    ip: bytes


def keys(secret: str, purpose: str, email: str, ip: str) -> Keys:
    return Keys(
        keyed_digest(secret, f"{purpose}:email", email.strip().lower()), keyed_digest(secret, f"{purpose}:ip", ip)
    )


async def _count(db: AsyncSession, *conditions: object, window: timedelta) -> int:
    since = clock.utcnow() - window
    stmt = select(func.count()).select_from(LoginAttempt).where(and_(LoginAttempt.created_at > since, *conditions))  # type: ignore[arg-type]
    return int((await db.execute(stmt)).scalar_one())


async def blocked(
    db: AsyncSession,
    k: Keys,
    *,
    pair_limit: int,
    window: timedelta = WINDOW,
    account_limit: int = PER_ACCOUNT_ANY_IP,
    ip_limit: int = PER_IP_ANY_ACCOUNT,
) -> bool:
    if (
        await _count(db, LoginAttempt.email_digest == k.email, LoginAttempt.ip_digest == k.ip, window=window)
        >= pair_limit
    ):
        return True
    if await _count(db, LoginAttempt.email_digest == k.email, window=window) >= account_limit:
        return True
    return await _count(db, LoginAttempt.ip_digest == k.ip, window=window) >= ip_limit


async def account_count(db: AsyncSession, k: Keys, *, window: timedelta) -> int:
    """Attempts for this account (any IP) in the window."""
    return await _count(db, LoginAttempt.email_digest == k.email, window=window)


def record(db: AsyncSession, k: Keys, *, succeeded: bool) -> None:
    db.add(LoginAttempt(email_digest=k.email, ip_digest=k.ip, succeeded=succeeded))
