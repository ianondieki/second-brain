"""Notification preferences (REQ-NOT-06; docs/spec/06 6.10; ``REQUIREMENTS.md`` §5 "Mutable").

``notification_preferences(user_id, kind, channel, enabled)`` holds a user's explicit choices; a kind and channel with
no row is on (mutable notifications default on; the 🔒 transactional ones never read this). Read on a session bound to
the user (the table is the user's own under RLS). In-app is always on and is never looked up here.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.models.enums import NotificationChannel
from bridge.notifications.models import NotificationPreference


async def channel_enabled(db: AsyncSession, user_id: UUID, kind: str, channel: NotificationChannel) -> bool:
    """The user's choice for ``kind`` on ``channel``; True when they never made one."""
    enabled = await db.scalar(
        select(NotificationPreference.enabled).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.kind == kind,
            NotificationPreference.channel == channel,
        )
    )
    return True if enabled is None else bool(enabled)
