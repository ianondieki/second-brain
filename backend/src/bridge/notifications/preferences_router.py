"""A signed-in person's notification choices (REQ-NOT-03 "email per preference"; docs/spec/06 6.10; the catalogue in
``notifications.catalogue``).

- ``GET /api/me/notification-preferences``: every choice of the catalogue with the person's value (their explicit
  choice, else the default) and the default.
- ``PUT /api/me/notification-preferences``: set one or more choices; a (kind, channel) the catalogue does not offer is
  422 ``unknown_preference`` (nothing is saved). Answers the choices as GET does.

The rows are the person's own (``notification_preferences``, Tenancy USER: every statement is scoped to the caller by
row-level security and names them). A choice is the person's own setting, not a consent, so no audit row (consents
are ``PUT /api/me/consents``).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.models.enums import NotificationChannel
from bridge.notifications.catalogue import BY_KEY, CHOICES, Audience
from bridge.notifications.models import NotificationPreference

router = APIRouter(prefix="/api/me/notification-preferences", tags=["notifications"], responses=ERROR_RESPONSES)
P = NotificationPreference


class PreferenceOut(BaseModel):
    kind: str = Field(description="The notice, for example engagement.n18 (a new message in an engagement's thread)")
    channel: NotificationChannel
    enabled: bool = Field(description="The person's choice, or the default while they made none")
    default: bool
    audience: Audience = Field(description="Who receives it: show the rows that apply to the person's portals")


class PreferencesOut(BaseModel):
    items: list[PreferenceOut]


class PreferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=40)
    channel: NotificationChannel
    enabled: bool


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PreferenceIn] = Field(min_length=1, max_length=50)


async def _choices(db: AsyncSession, user_id: UUID) -> PreferencesOut:
    rows = await db.execute(select(P.kind, P.channel, P.enabled).where(P.user_id == user_id))
    chosen = {(kind, channel): bool(enabled) for kind, channel, enabled in rows.tuples()}
    return PreferencesOut(
        items=[
            PreferenceOut(
                kind=c.kind,
                channel=c.channel,
                enabled=chosen.get((c.kind, c.channel), c.default),
                default=c.default,
                audience=c.audience,
            )
            for c in CHOICES
        ]
    )


@router.get("")
async def get_preferences(live: CurrentSession, db: Db) -> PreferencesOut:
    """The caller's notification choices (in-app is always on and is not one of them)."""
    return await _choices(db, live.user.id)


@router.put("")
async def put_preferences(body: PreferencesIn, live: CurrentSession, db: Db) -> PreferencesOut:
    """Set the caller's choices; 422 unknown_preference for anything the catalogue does not offer."""
    if any((item.kind, item.channel) not in BY_KEY for item in body.items):
        raise ApiError(422, "unknown_preference", "One of these notifications cannot be turned on or off.")
    for item in body.items:
        values = pg_insert(P).values(user_id=live.user.id, kind=item.kind, channel=item.channel, enabled=item.enabled)
        await db.execute(
            values.on_conflict_do_update(
                index_elements=[P.user_id, P.kind, P.channel], set_={"enabled": values.excluded.enabled}
            )
        )
    await db.commit()
    return await _choices(db, live.user.id)
