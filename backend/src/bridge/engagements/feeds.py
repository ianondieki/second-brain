"""Private calendar feeds (REQ-ENG-13; D-70: capability URLs; revision 0013's ``calendar_feeds``).

A feed URL carries a token of ``TOKEN_BYTES`` random bytes (``secrets.token_bytes``) in base64url without padding;
only its SHA-256 is stored (``calendar_feeds.token_hash``), computed from the raw bytes alike at creation and at
lookup. One live feed per user (``org_id`` NULL: their deadlines as a developer) and per user and organisation (a
member's: the organisation's deadlines). Creating one rotates: in one transaction, under a transaction advisory lock
per (user, organisation) so two requests at once rotate one after the other, the live feed is revoked (the database
stamps ``revoked_at`` with its clock) and the new hash inserted; the old URL answers 404 at once. Revoking is the same
UPDATE alone. The URL is shown once (the response to the POST): it cannot be rebuilt from the hash.

The unauthenticated read (``GET /api/calendar/{token}.ics``): a token that is not canonical base64url of 32 bytes is
refused before the database is asked; otherwise ``app_calendar_feed_lookup(sha256)`` (SECURITY DEFINER: the session is
bound to nobody, so no feed row is readable to it) finds the live feed of an active user (and, for an organisation's
feed, a still-active member). The request then binds that user (and organisation) for Row-Level Security, re-reads its
own feed row and compares the stored hash with the computed one in constant time (``hmac.compare_digest``), counts the
fetch against ``FETCHES_PER_HOUR`` per feed (the ``login_attempts`` ledger, keyed by an HMAC of the feed's id), reads
the deadlines as that person and stamps ``last_fetched_at`` through ``app_calendar_feed_touch``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.config import Settings
from bridge.engagements.models import CalendarFeed
from bridge.engagements.schemas import CalendarFeedStatus
from bridge.ids import uuid7
from bridge.teams import limits

TOKEN_BYTES: Final = 32
_TOKEN: Final = re.compile(r"[A-Za-z0-9_-]{43}")  # base64url of 32 bytes, no padding
FETCHES_PER_HOUR: Final = 60
FETCH_WINDOW: Final = timedelta(hours=1)
FETCH_PURPOSE: Final = "calendar_feed_fetch"  # the ledger's purpose label
TOO_MANY_FETCHES: Final = "This calendar feed was read too often. Try again later."  # [[COPY-REVIEW]]
FEED_PATH: Final = "/api/calendar/{token}.ics"
_LOCK: Final = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_LOOKUP: Final = text("SELECT feed_id, user_id, org_id FROM app_calendar_feed_lookup(:token_hash)")
_TOUCH: Final = text("SELECT app_calendar_feed_touch(:feed)")


@dataclass(frozen=True, slots=True)
class FeedRef:
    """A live feed found by its token: whose deadlines it carries."""

    feed_id: UUID
    user_id: UUID
    org_id: UUID | None


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def new_token() -> tuple[str, bytes]:
    """(the URL's token, the SHA-256 of its raw bytes: the only thing stored)."""
    raw = secrets.token_bytes(TOKEN_BYTES)
    return _encode(raw), hashlib.sha256(raw).digest()


def token_hash(token: str) -> bytes | None:
    """The SHA-256 a canonical token stands for; None for anything else (no database read for it)."""
    if not _TOKEN.fullmatch(token):
        return None
    try:
        raw = base64.urlsafe_b64decode(token + "=")
    except (binascii.Error, ValueError):  # pragma: no cover - the pattern admits only the alphabet
        return None
    if len(raw) != TOKEN_BYTES or _encode(raw) != token:  # one spelling per token: the unused low bits are zero
        return None
    return hashlib.sha256(raw).digest()


def feed_url(base_url: str, token: str) -> str:
    """The absolute address a calendar app subscribes to (the web app's public origin, which serves ``/api``)."""
    return f"{base_url.rstrip('/')}{FEED_PATH.format(token=token)}"


def _live(user_id: UUID, org_id: UUID | None) -> list[ColumnElement[bool]]:
    return [
        CalendarFeed.user_id == user_id,
        CalendarFeed.org_id.is_(None) if org_id is None else CalendarFeed.org_id == org_id,
        CalendarFeed.revoked_at.is_(None),
    ]


async def _lock(db: AsyncSession, user_id: UUID, org_id: UUID | None) -> None:
    await db.execute(_LOCK, {"key": f"calendar_feed:{user_id}:{org_id or '-'}"})


async def revoke(db: AsyncSession, user_id: UUID, org_id: UUID | None) -> UUID | None:
    """Revoke the live feed, if any (idempotent; the database stamps the time); returns its id. The caller commits."""
    await _lock(db, user_id, org_id)
    revoked = await db.execute(
        update(CalendarFeed)
        .where(*_live(user_id, org_id))
        .values(revoked_at=text("app_clock_now()"))
        .returning(CalendarFeed.id)
        .execution_options(synchronize_session=False)
    )
    found: UUID | None = revoked.scalar_one_or_none()
    return found


@dataclass(frozen=True, slots=True)
class Created:
    token: str  # shown once, in the URL
    feed_id: UUID
    replaced: UUID | None  # the feed it revoked


async def rotate(db: AsyncSession, user_id: UUID, org_id: UUID | None) -> Created:
    """Revoke the caller's live feed (for ``org_id``, or their own) and create the next, inserting only the columns
    bridge_app may write. The caller commits."""
    replaced = await revoke(db, user_id, org_id)
    token, digest = new_token()
    feed_id = uuid7()
    await db.execute(insert(CalendarFeed).values(id=feed_id, user_id=user_id, org_id=org_id, token_hash=digest))
    return Created(token, feed_id, replaced)


async def status(db: AsyncSession, user_id: UUID, org_id: UUID | None) -> CalendarFeedStatus:
    found = (
        await db.execute(select(CalendarFeed.created_at, CalendarFeed.last_fetched_at).where(*_live(user_id, org_id)))
    ).one_or_none()
    if found is None:
        return CalendarFeedStatus(active=False, created_at=None, last_fetched_at=None)
    return CalendarFeedStatus(active=True, created_at=found.created_at, last_fetched_at=found.last_fetched_at)


async def lookup(db: AsyncSession, digest: bytes) -> FeedRef | None:
    """The live feed whose token hashes to ``digest`` (any session: the hash is the capability)."""
    row = (await db.execute(_LOOKUP, {"token_hash": digest})).one_or_none()
    return None if row is None else FeedRef(row.feed_id, row.user_id, row.org_id)


async def verify(db: AsyncSession, feed: FeedRef, digest: bytes) -> bool:
    """With the session bound to the feed's user: their own live row still holds ``digest`` (constant time)."""
    stored = await db.scalar(
        select(CalendarFeed.token_hash).where(CalendarFeed.id == feed.feed_id, CalendarFeed.revoked_at.is_(None))
    )
    return stored is not None and hmac.compare_digest(stored, digest)


async def spend_fetch(db: AsyncSession, settings: Settings, feed: FeedRef) -> None:
    """Count one read of ``feed``, or 429 ``too_many_fetches`` (with ``Retry-After``) beyond ``FETCHES_PER_HOUR``."""
    await limits.spend(
        db,
        settings.secret_key.get_secret_value(),
        purpose=FETCH_PURPOSE,
        user_id=feed.feed_id,
        limit=FETCHES_PER_HOUR,
        window=FETCH_WINDOW,
        code="too_many_fetches",
        message=TOO_MANY_FETCHES,
    )


async def touch(db: AsyncSession, feed: FeedRef) -> bool:
    """Stamp the feed's ``last_fetched_at`` (the database's clock)."""
    stamped: bool = bool(await db.scalar(_TOUCH, {"feed": feed.feed_id}))
    return stamped
