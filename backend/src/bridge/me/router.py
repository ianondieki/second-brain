"""The signed-in person's palette search and activity calendar (REQ-UX-01, REQ-UX-05; D-67; P25-B).

- ``GET /api/me/search?q=``: the command palette's results, grouped by what they are (``bridge.me.search``). ``q`` is
  2 to 80 characters once trimmed (else 422 ``invalid_query``). Each person may search ``SEARCHES`` times in any
  ``SEARCH_WINDOW`` (the ``login_attempts`` ledger, keyed by a digest of the user's id: ``bridge.teams.limits``);
  past that it is 429 ``rate_limited`` with ``Retry-After`` and nothing is read. ``Cache-Control: private,
  no-store``.
- ``GET /api/me/activity?weeks=26``: the caller's own actions per Nairobi day over ``weeks`` (1 to 52) weeks ending
  today (``bridge.me.activity``). ``Cache-Control: private, max-age=60``.

Both read as the signed-in person under Row-Level Security (the session dependency binds the caller), in a read-only
transaction of their own whose statements the database cancels after ``READ_TIMEOUT`` (a 500 then, nothing kept).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Annotated, Final

from fastapi import APIRouter, Query, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.errors import ERROR_RESPONSES
from bridge.me import activity, caller, search
from bridge.me.schemas import ActivityCalendar, SearchResults
from bridge.teams import limits

router = APIRouter(prefix="/api/me", tags=["me"], responses=ERROR_RESPONSES)

SEARCHES: Final = 30
SEARCH_WINDOW: Final = timedelta(seconds=10)
SEARCH_PURPOSE: Final = "me_search"  # the ledger's purpose label
# [[COPY-REVIEW]]
TOO_FAST: Final = "You are searching very quickly. Wait a few seconds and try again."
SEARCH_CACHE: Final = "private, no-store"
ACTIVITY_CACHE: Final = "private, max-age=60"
READ_TIMEOUT: Final = "2s"
_READ_ONLY = text("SET TRANSACTION READ ONLY")
_TIMEOUT = text(f"SET LOCAL statement_timeout = '{READ_TIMEOUT}'")
RAW_QUERY_MAX: Final = 200  # a longer q is refused before it is trimmed (FastAPI's 422)


@asynccontextmanager
async def read_only(db: AsyncSession) -> AsyncIterator[AsyncSession]:
    """A new read-only transaction on the request's session (still bound to the caller for RLS), its statements
    cancelled after ``READ_TIMEOUT``. Whatever the session had open is committed first (the session's own touch)."""
    if db.in_transaction():
        await db.commit()
    async with db.begin():
        await db.execute(_READ_ONLY)
        await db.execute(_TIMEOUT)
        yield db


@router.get("/search")
async def search_mine(
    live: CurrentSession,
    db: Db,
    settings: SettingsDep,
    response: Response,
    q: Annotated[
        str,
        Query(max_length=RAW_QUERY_MAX, description="The words to find: 2 to 80 characters once trimmed"),
    ],
) -> SearchResults:
    """The command palette: the caller's ideas, engagements, Inbox and Briefs, readable problems and (for a developer)
    listed companies whose title (or name) holds the words, at most five of each."""
    term = search.normalise(q)
    await limits.spend(
        db,
        settings.secret_key.get_secret_value(),
        purpose=SEARCH_PURPOSE,
        user_id=live.user.id,
        limit=SEARCHES,
        window=SEARCH_WINDOW,
        code="rate_limited",
        message=TOO_FAST,
    )
    await db.commit()
    async with read_only(db):
        found = await search.run(db, await caller.caller_of(db, live), term)
    response.headers["Cache-Control"] = SEARCH_CACHE
    return found


@router.get("/activity")
async def my_activity(
    live: CurrentSession,
    db: Db,
    response: Response,
    weeks: Annotated[
        int, Query(ge=1, le=activity.MAX_WEEKS, description="How many weeks, ending today (Africa/Nairobi)")
    ] = activity.DEFAULT_WEEKS,
) -> ActivityCalendar:
    """The caller's own actions per day (Africa/Nairobi) for the activity calendar: counts only."""
    async with read_only(db):
        calendar = await activity.read(db, await caller.caller_of(db, live), weeks)
    response.headers["Cache-Control"] = ACTIVITY_CACHE
    return calendar
