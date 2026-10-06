"""The application's limits of peers and team up (REQ-DEV-03; ``teams`` in policy.yaml; the 0011 security review's
MINOR 5), each a 429 with ``Retry-After`` (whole seconds until the oldest counted action leaves the window).

- Invitations (``invitations_per_day``) and team messages (``posts_per_hour``) count their own rows on the database's
  clock (``created_at`` is ``app_clock_now()``), under a transaction advisory lock per sender (invitations) or per
  thread (messages, the engagement thread's pattern), so concurrent requests count one after another.
- Peers pages (``peers_pages_per_hour``) and changes of the county or the liked niches (``profile_changes_per_day``)
  leave no row of their own, so each is recorded in the ``login_attempts`` ledger (``bridge.auth.throttle``: an HMAC
  digest of a purpose and the user's id, never the raw id) and counted there, under a per-user advisory lock. A refused
  request records nothing; the caller commits the record with the change it allowed.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.auth import throttle
from bridge.auth.models import LoginAttempt
from bridge.config import Settings
from bridge.errors import ApiError
from bridge.teams.policy import get_teams_policy

HOUR: Final = timedelta(hours=1)
DAY: Final = timedelta(hours=24)
PEERS_PAGE: Final = "teams_peers_page"  # the ledger's purpose labels
PROFILE_CHANGE: Final = "teams_profile_change"
_LOCK: Final = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
# [[COPY-REVIEW]]
TOO_MANY_CHANGES: Final = "You have changed your county or niches many times today. Try again tomorrow."


def retry_after(oldest: datetime, window: timedelta, now: datetime) -> int:
    """Whole seconds until ``oldest`` leaves the window that ends at ``now`` (at least 1)."""
    return max(1, math.ceil((oldest + window - now).total_seconds()))


def too_many(code: str, message: str, seconds: int) -> ApiError:
    error = ApiError(429, code, message, retry_after_seconds=seconds)
    error.headers = {"Retry-After": str(seconds)}
    return error


async def lock(db: AsyncSession, key: str) -> None:
    """A transaction advisory lock on ``key`` (released at commit or rollback)."""
    await db.execute(_LOCK, {"key": key})


def ledger_keys(secret: str, purpose: str, user_id: UUID) -> throttle.Keys:
    return throttle.keys(secret, purpose, str(user_id), "-")


async def spend(
    db: AsyncSession,
    secret: str,
    *,
    purpose: str,
    user_id: UUID,
    limit: int,
    window: timedelta,
    code: str,
    message: str,
) -> None:
    """Count one ``purpose`` action of ``user_id`` in the ledger, or answer 429 ``code`` when ``limit`` of them fall
    within ``window`` already. The record joins the caller's transaction (commit it with the change)."""
    keys = ledger_keys(secret, purpose, user_id)
    await lock(db, f"{purpose}:{user_id}")
    now = clock.utcnow()
    count, oldest = (
        await db.execute(
            select(func.count(), func.min(LoginAttempt.created_at)).where(
                LoginAttempt.email_digest == keys.email, LoginAttempt.created_at > now - window
            )
        )
    ).one()
    if int(count) >= limit:
        raise too_many(code, message, retry_after(oldest, window, now))
    throttle.record(db, keys, succeeded=True)


async def spend_profile_change(db: AsyncSession, settings: Settings, user_id: UUID) -> None:
    """Count one change of the county or the liked niches (``PATCH /api/me/profile``, ``PUT /api/me/niches``), or
    answer 429 ``too_many_profile_changes`` beyond ``teams.profile_changes_per_day`` in any 24 hours."""
    await spend(
        db,
        settings.secret_key.get_secret_value(),
        purpose=PROFILE_CHANGE,
        user_id=user_id,
        limit=get_teams_policy().profile_changes_per_day,
        window=DAY,
        code="too_many_profile_changes",
        message=TOO_MANY_CHANGES,
    )
