"""The bell's API (docs/spec/07 §1; REQ-NOT-03, the in-app channel; task P19-C): a signed-in person's own in-app
notifications, whichever portal they use (one set of endpoints for a developer and an organisation's member alike).

- ``GET /api/me/notifications``: newest first (``created_at``, then ``id``), 20 a page with ``limit``, ``cursor`` and
  ``next_cursor`` (``bridge.pagination``); ``unread=1`` keeps the unread ones.
- ``GET /api/me/notifications/unread-count``: ``{count}``, the bell's badge.
- ``POST /api/me/notifications/{id}/read``: marks one read and answers it. Idempotent: the first moment stays.
- ``POST /api/me/notifications/read-all``: marks every unread one read and answers the count left (0).

Row-Level Security scopes every statement to the caller (``Tenancy.USER``: ``user_id = app_user_id()``) and each one
also names the caller, so somebody else's id answers 404 exactly like an unknown one. bridge_app may update
``read_at`` only (revision 0006): nothing else of a notification changes once written, and ``read_at`` is the
database's clock, like ``created_at``. Reading and marking read are the person's own state, so no audit row. A stored
link that is not a platform path (``in_app.is_platform_path``) is served as null: the bell never sends anyone off the
site, whatever wrote the row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import Row, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import pagination
from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES, not_found
from bridge.notifications.in_app import is_platform_path
from bridge.notifications.models import InAppNotification

router = APIRouter(prefix="/api/me/notifications", tags=["notifications"], responses=ERROR_RESPONSES)
PAGE: Final = 20
MAX_PAGE: Final = 50
N = InAppNotification
_COLUMNS = (N.id, N.kind, N.title, N.body, N.link, N.created_at, N.read_at)


class NotificationOut(BaseModel):
    id: UUID
    kind: str = Field(description="What happened, for example engagement.n03 (the tracker's notice)")
    title: str
    body: str | None
    link: str | None = Field(description="A path on this platform to open (one leading '/'), or null")
    created_at: datetime
    read_at: datetime | None = Field(description="When the person first marked it read; null while unread")


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None = Field(description="Pass as ?cursor= for the next page; null on the last page")


class UnreadCount(BaseModel):
    count: int = Field(ge=0, description="The caller's unread notifications")


def _out(row: Row[Any]) -> NotificationOut:
    link = row.link if row.link is not None and is_platform_path(row.link) else None
    return NotificationOut(
        id=row.id,
        kind=row.kind,
        title=row.title,
        body=row.body,
        link=link,
        created_at=row.created_at,
        read_at=row.read_at,
    )


async def _unread(db: AsyncSession, user_id: UUID) -> int:
    found = await db.scalar(select(func.count()).select_from(N).where(N.user_id == user_id, N.read_at.is_(None)))
    return int(found or 0)


@router.get("")
async def list_notifications(
    live: CurrentSession,
    db: Db,
    unread: Annotated[bool, Query(description="1: only the unread ones")] = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = PAGE,
    cursor: pagination.Cursor = None,
) -> NotificationPage:
    """The caller's notifications, newest first, 20 a page."""
    after = pagination.decode(cursor)
    stmt = select(*_COLUMNS).where(N.user_id == live.user.id)
    if unread:
        stmt = stmt.where(N.read_at.is_(None))
    if after is not None:
        if after.at is None:  # every notification has its moment: this list never wrote such a cursor
            raise pagination.invalid_cursor()
        stmt = stmt.where(or_(N.created_at < after.at, and_(N.created_at == after.at, N.id < after.id)))
    rows = (await db.execute(stmt.order_by(N.created_at.desc(), N.id.desc()).limit(limit + 1))).all()
    last = rows[limit - 1] if len(rows) > limit else None
    return NotificationPage(
        items=[_out(row) for row in rows[:limit]],
        next_cursor=None if last is None else pagination.encode(last.created_at, last.id),
    )


@router.get("/unread-count")
async def unread_count(live: CurrentSession, db: Db) -> UnreadCount:
    """How many of the caller's notifications are unread (the bell's badge)."""
    return UnreadCount(count=await _unread(db, live.user.id))


@router.post("/read-all")
async def mark_all_read(live: CurrentSession, db: Db) -> UnreadCount:
    """Every unread notification of the caller's, read now; one read earlier keeps its moment."""
    await db.execute(
        update(N)
        .where(N.user_id == live.user.id, N.read_at.is_(None))
        .values(read_at=func.now())
        .execution_options(synchronize_session=False)
    )
    left = await _unread(db, live.user.id)
    await db.commit()
    return UnreadCount(count=left)


@router.post("/{notification_id}/read")
async def mark_read(notification_id: UUID, live: CurrentSession, db: Db) -> NotificationOut:
    """One of the caller's notifications, read; marking it again changes nothing. Anyone else's id is 404."""
    mine = (N.id == notification_id, N.user_id == live.user.id)
    marked = await db.execute(
        update(N)
        .where(*mine, N.read_at.is_(None))
        .values(read_at=func.now())
        .returning(*_COLUMNS)
        .execution_options(synchronize_session=False)
    )
    row = marked.one_or_none()
    if row is not None:
        await db.commit()
        return _out(row)
    row = (await db.execute(select(*_COLUMNS).where(*mine))).one_or_none()  # already read, or not the caller's
    if row is None:
        raise not_found("No such notification.")
    return _out(row)
