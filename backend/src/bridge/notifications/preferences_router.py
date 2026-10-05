"""The signed-in person's notification preferences (REQ-NOT-06; docs/spec/06 6.10; ``REQUIREMENTS.md`` §5 "Mutable"):
the kinds of ``preferences.CATALOGUE`` a person may turn on or off, for anyone signed in, on either side.

- ``GET /api/me/notification-preferences``: each settable kind and channel with its label, its default and the
  person's current choice (the default when they never chose).
- ``PUT /api/me/notification-preferences``: one choice (``kind``, ``channel``, ``enabled``); 422
  ``unknown_preference`` for anything the catalogue does not list as settable (in-app is always on). Answers the list.

Rows are the person's own under Row-Level Security (``notification_preferences``, Tenancy USER). A choice is the
person's own state, like a read notification: no audit event.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.models.enums import NotificationChannel
from bridge.notifications.models import NotificationPreference
from bridge.notifications.preferences import CATALOGUE, catalogued

router = APIRouter(prefix="/api/me/notification-preferences", tags=["notifications"], responses=ERROR_RESPONSES)
P = NotificationPreference


class PreferenceOut(BaseModel):
    kind: str
    channel: NotificationChannel
    label: str = Field(description="What the person is choosing, in the settings page's words")
    default: bool = Field(description="What it is for someone who never chose")
    enabled: bool


class PreferencesOut(BaseModel):
    items: list[PreferenceOut]


class PreferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(max_length=40)
    channel: NotificationChannel
    enabled: bool


async def _preferences(db: AsyncSession, user_id: UUID) -> PreferencesOut:
    rows = await db.execute(select(P.kind, P.channel, P.enabled).where(P.user_id == user_id))
    chosen = {(row.kind, row.channel): bool(row.enabled) for row in rows}
    return PreferencesOut(
        items=[
            PreferenceOut(
                kind=info.kind,
                channel=info.channel,
                label=info.label,
                default=info.default,
                enabled=chosen.get((info.kind, info.channel), info.default),
            )
            for info in CATALOGUE
            if info.mutable
        ]
    )


@router.get("")
async def my_preferences(live: CurrentSession, db: Db) -> PreferencesOut:
    """The notifications you may turn on or off, and your choices."""
    return await _preferences(db, live.user.id)


@router.put("")
async def set_preference(body: PreferenceIn, live: CurrentSession, db: Db) -> PreferencesOut:
    """Turn one notification on or off."""
    info = catalogued(body.kind, body.channel)
    if info is None or not info.mutable:
        raise ApiError(422, "unknown_preference", "This notification cannot be changed here.")
    statement = insert(P).values(user_id=live.user.id, kind=body.kind, channel=body.channel, enabled=body.enabled)
    await db.execute(
        statement.on_conflict_do_update(index_elements=[P.user_id, P.kind, P.channel], set_={"enabled": body.enabled})
    )
    await db.commit()
    return await _preferences(db, live.user.id)
