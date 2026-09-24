"""Server-side sessions (docs/spec/08 Auth): the cookie carries a random token, the table only its SHA-256."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.crypto import new_token, token_hash
from bridge.auth.models import Session, User
from bridge.clock import utcnow
from bridge.models.enums import UserStatus

TOUCH_EVERY = timedelta(minutes=5)


@dataclass(slots=True)
class LiveSession:
    token: str
    row: Session
    user: User


async def create(
    db: AsyncSession, user: User, *, ttl: timedelta, mfa_pending: bool, user_agent: str | None
) -> LiveSession:
    now = utcnow()
    token = new_token()
    row = Session(
        user_id=user.id,
        token_hash=token_hash(token),
        expires_at=now + ttl,
        last_seen_at=now,
        mfa_pending=mfa_pending,
        mfa_verified_at=None,
        user_agent=(user_agent or "")[:200] or None,
    )
    db.add(row)
    await db.flush()
    return LiveSession(token, row, user)


async def lookup(db: AsyncSession, token: str) -> LiveSession | None:
    """The live session for a cookie token, or None (unknown, revoked, expired or suspended user)."""
    now = utcnow()
    result = await db.execute(
        select(Session, User)
        .join(User, User.id == Session.user_id)
        .where(Session.token_hash == token_hash(token), Session.revoked_at.is_(None), Session.expires_at > now)
    )
    found = result.first()
    if found is None:
        return None
    row, user = found
    if user.status != UserStatus.ACTIVE:
        return None
    if now - row.last_seen_at > TOUCH_EVERY:
        row.last_seen_at = now
    return LiveSession(token, row, user)


async def revoke(db: AsyncSession, row: Session) -> None:
    row.revoked_at = utcnow()


async def revoke_all(db: AsyncSession, user_id: object, *, except_id: object | None = None) -> None:
    stmt = update(Session).where(Session.user_id == user_id, Session.revoked_at.is_(None))
    if except_id is not None:
        stmt = stmt.where(Session.id != except_id)
    await db.execute(stmt.values(revoked_at=utcnow()))


def mfa_fresh(row: Session, max_age: timedelta, now: datetime | None = None) -> bool:
    """True when the session completed MFA within ``max_age`` (the step-up rule, ADR-002: 12 h)."""
    if row.mfa_verified_at is None:
        return False
    return (now or utcnow()) - row.mfa_verified_at <= max_age
