"""Saved Discover searches (REQ-PERS-03, R27, with REQ-TREND-02; P21 track C; D-57 (7); revision 0008).

A developer (any plan; someone without a developer profile has none: 404) keeps Discover's view (``problems`` or
``briefs``) and filters (a niche slug, a parent including its children; a county code; words found in a problem's
title or statement) under a name, at most ``MAX_SAVED_SEARCHES`` (10). ``alerts`` (on by default) lets the daily job
(``bridge.matching.saved_search_alerts``) tell them about what was published since. Everything is the owner's only
under Row-Level Security (``user_id = app_user_id()``): another user's id answers 404 exactly like an unknown one.

- ``GET /api/me/saved-searches``: newest first, with the cap.
- ``POST /api/me/saved-searches``: 201; 422 ``unknown_niche`` / ``unknown_county`` (the slug and code must exist);
  409 ``saved_searches_limit`` on the 11th (checked first; the database's ``saved_searches_cap`` is the backstop for
  two saves at once, mapped the same).
- ``PATCH /api/me/saved-searches/{id}``: the name and ``alerts`` only (the query is what was saved; save another).
  Turning alerts back on (off to on) moves ``last_alerted_at`` to that moment (the platform clock), so the next alert
  counts only what is published from then on, never what came out while they were off.
- ``DELETE /api/me/saved-searches/{id}``: 204.

A saved search is the owner's own state: no audit event (as a liked niche or a read notification).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Final, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import CursorResult, case, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.deps import CurrentSession, Db
from bridge.directory.models import Niche, Region
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.ids import uuid7
from bridge.models.enums import RegionKind
from bridge.profiles.models import (
    MAX_SAVED_SEARCHES,
    SAVED_SEARCH_NAME_CHARS,
    SAVED_SEARCH_WORDS_CHARS,
    DeveloperProfile,
    SavedSearch,
)

router = APIRouter(prefix="/api/me/saved-searches", tags=["discover"], responses=ERROR_RESPONSES)
CAP_CONSTRAINT: Final = "saved_searches_at_most_10"
NO_NUL: Final = r"^[^\x00]*$"  # Postgres text cannot hold NUL (0x00)
View = Literal["problems", "briefs"]
Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=SAVED_SEARCH_NAME_CHARS, pattern=NO_NUL)
]
S = SavedSearch


class SavedSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name = Field(description="1 to 60 characters, e.g. 'Agriculture in Nakuru'")
    view: View = Field(description="The Discover list: problems or briefs")
    niche: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)] | None = Field(
        default=None, description="A niche slug (a parent includes its children)"
    )
    county: Annotated[str, StringConstraints(pattern=r"^KE-\d{2}$")] | None = Field(
        default=None, description="An ISO 3166-2:KE county code"
    )
    words: (
        Annotated[str, StringConstraints(strip_whitespace=True, max_length=SAVED_SEARCH_WORDS_CHARS, pattern=NO_NUL)]
        | None
    ) = Field(
        default=None, description="Words a problem's title or statement holds (Discover's words filter); blank: none"
    )
    alerts: bool = Field(default=True, description="Tell me daily about new matches")

    @field_validator("words")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return value or None


class SavedSearchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    alerts: bool | None = None


class SavedSearchOut(BaseModel):
    id: UUID
    name: str
    view: View
    niche: str | None = Field(description="The niche slug")
    county: str | None = Field(description="The county code")
    words: str | None
    alerts: bool
    last_alerted_at: datetime | None = Field(description="When the daily job last looked for new matches")
    created_at: datetime


class SavedSearchList(BaseModel):
    items: list[SavedSearchOut]
    max: int = Field(description="How many searches a developer may save")


def _out(row: SavedSearch) -> SavedSearchOut:
    return SavedSearchOut(
        id=row.id,
        name=row.name,
        view=cast(View, row.view),
        niche=row.niche_slug,
        county=row.county_code,
        words=row.words,
        alerts=row.alerts,
        last_alerted_at=row.last_alerted_at,
        created_at=row.created_at,
    )


def _limit() -> ApiError:
    return ApiError(
        409,
        "saved_searches_limit",
        f"You can save up to {MAX_SAVED_SEARCHES} searches. Delete one to save another.",  # [[COPY-REVIEW]]
        max=MAX_SAVED_SEARCHES,
    )


def _rowcount(result: Any) -> int:
    return int(cast(CursorResult[Any], result).rowcount)


async def _developer(db: AsyncSession, user_id: UUID) -> None:
    if await db.get(DeveloperProfile, user_id) is None:
        raise not_found("No developer profile.")


async def _mine(db: AsyncSession, user_id: UUID, search_id: UUID) -> SavedSearch:
    row = await db.scalar(
        select(S).where(S.id == search_id, S.user_id == user_id).execution_options(populate_existing=True)
    )
    if row is None:
        raise not_found("No saved search of yours has this id.")
    return row


async def _check_filters(db: AsyncSession, body: SavedSearchIn) -> None:
    if body.niche is not None and await db.scalar(select(Niche.id).where(Niche.slug == body.niche)) is None:
        raise ApiError(422, "unknown_niche", "Choose a niche from the list.")
    if body.county is not None:
        found = await db.scalar(select(Region.code).where(Region.code == body.county, Region.kind == RegionKind.COUNTY))
        if found is None:
            raise ApiError(422, "unknown_county", "Choose a county from the list.")


@router.get("")
async def list_saved_searches(live: CurrentSession, db: Db) -> SavedSearchList:
    """Your saved Discover searches, newest first."""
    await _developer(db, live.user.id)
    rows = await db.scalars(select(S).where(S.user_id == live.user.id).order_by(S.created_at.desc(), S.id.desc()))
    return SavedSearchList(items=[_out(row) for row in rows], max=MAX_SAVED_SEARCHES)


@router.post("", status_code=201)
async def save_search(body: SavedSearchIn, live: CurrentSession, db: Db) -> SavedSearchOut:
    """Save Discover's current view and filters under a name (up to 10)."""
    me = live.user.id
    await _developer(db, me)
    await _check_filters(db, body)
    if (await db.scalar(select(func.count()).select_from(S).where(S.user_id == me)) or 0) >= MAX_SAVED_SEARCHES:
        raise _limit()
    search_id = uuid7()
    values = {
        "id": search_id,
        "user_id": me,
        "name": body.name,
        "view": body.view,
        "niche_slug": body.niche,
        "county_code": body.county,
        "words": body.words,
        "alerts": body.alerts,
    }
    try:
        await db.execute(insert(S).values(**values))  # the columns bridge_app may write (created_at is the database's)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == CAP_CONSTRAINT:
            raise _limit() from exc
        raise
    return _out(await _mine(db, me, search_id))


@router.patch("/{search_id}")
async def update_saved_search(search_id: UUID, body: SavedSearchPatch, live: CurrentSession, db: Db) -> SavedSearchOut:
    """Rename a saved search or turn its alerts on or off."""
    me = live.user.id
    await _developer(db, me)
    changes: dict[str, Any] = body.model_dump(exclude_none=True)
    if body.alerts:  # off to on restarts the window; SET reads the row as it was, so this is one atomic step
        changes["last_alerted_at"] = case((S.alerts.is_(False), func.app_clock_now()), else_=S.last_alerted_at)
    if changes:
        statement = update(S).where(S.id == search_id, S.user_id == me).values(**changes)
        updated = await db.execute(statement.execution_options(synchronize_session=False))
        if _rowcount(updated) == 0:
            raise not_found("No saved search of yours has this id.")
        await db.commit()
    return _out(await _mine(db, me, search_id))


@router.delete("/{search_id}", status_code=204)
async def delete_saved_search(search_id: UUID, live: CurrentSession, db: Db) -> Response:
    """Delete a saved search (its alerts stop with it)."""
    me = live.user.id
    await _developer(db, me)
    deleted = await db.execute(delete(S).where(S.id == search_id, S.user_id == me))
    if _rowcount(deleted) == 0:
        raise not_found("No saved search of yours has this id.")
    await db.commit()
    return Response(status_code=204)
