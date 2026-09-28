"""Attempt throttling on the ``login_attempts`` ledger (docs/spec/08: login 5/min per IP + account).

Keys are HMAC digests of the normalised email and the client IP, never the raw values. Limits per rolling minute:
5 for one (IP, account) pair; 20 for one account from any IP (credential stuffing); 100 for one IP (a shared NAT
must not lock out a whole campus). Magic-link and signup emails reuse the ledger with their own purpose labels, and
the OAuth start and callback routes (REQ-AUTH-02) with per-IP keys only (``ip_keys``, ``ip_blocked``). ``first_use``
records single-use values (the OAuth ``state``) in the same ledger.
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
FIRST_USE_LOCK_CLASS = 0x6F617374  # pg_advisory_xact_lock(int, int) namespace for first_use ("oast")
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


def ip_keys(secret: str, purpose: str, ip: str) -> Keys:
    """Keys for an action throttled per client IP only (no account is known yet)."""
    return keys(secret, purpose, "", ip)


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


async def ip_blocked(db: AsyncSession, k: Keys, *, limit: int, window: timedelta = WINDOW) -> bool:
    """True when this IP made ``limit`` or more attempts (for this purpose) in the window."""
    return await _count(db, LoginAttempt.ip_digest == k.ip, window=window) >= limit


async def account_count(db: AsyncSession, k: Keys, *, window: timedelta) -> int:
    """Attempts for this account (any IP) in the window."""
    return await _count(db, LoginAttempt.email_digest == k.email, window=window)


def record(db: AsyncSession, k: Keys, *, succeeded: bool) -> None:
    db.add(LoginAttempt(email_digest=k.email, ip_digest=k.ip, succeeded=succeeded))


async def first_use(db: AsyncSession, secret: str, purpose: str, value: str, *, window: timedelta) -> bool:
    """Record one use of a single-use ``value`` and say whether it is the first within ``window``. Only an HMAC
    digest is stored (in the ``email_digest`` slot). A transaction-scoped advisory lock on the digest (two-key form,
    so it never meets the audit chain's single-key locks) serialises concurrent uses, so exactly one of them finds
    no earlier row; it is released when the caller commits."""
    digest = keyed_digest(secret, f"{purpose}:value", value)
    slot = int.from_bytes(digest[:4], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(FIRST_USE_LOCK_CLASS, slot)))
    k = Keys(digest, keyed_digest(secret, f"{purpose}:ip", "-"))
    if await account_count(db, k, window=window) > 0:
        return False
    record(db, k, succeeded=True)
    await db.flush()
    return True
