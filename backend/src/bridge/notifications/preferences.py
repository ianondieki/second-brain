"""Notification preferences (REQ-NOT-06; docs/spec/06 6.10; ``REQUIREMENTS.md`` §5 "Mutable").

``notification_preferences(user_id, kind, channel, enabled)`` holds a user's explicit choices; a kind and channel with
no row takes the catalogue's default, and a kind the catalogue does not list is on (mutable notifications default on;
the 🔒 transactional ones never read this). Read on a session bound to the user (the table is the user's own under
RLS). In-app is always on and is never looked up here.

``CATALOGUE`` lists the kinds a person sets on the notification settings page (``bridge.notifications.
preferences_router``), each with its channel and its default, plus the in-app kinds registered alongside them (always
on, never settable): P21's saved-search alerts (D-57 (7)), the daily in-app ``saved_search_match`` and the opt-in
``saved_search_digest`` email, off until the person turns it on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.models.enums import NotificationChannel
from bridge.notifications.models import NotificationPreference

SAVED_SEARCH_MATCH: Final = "saved_search_match"  # in-app, once per saved search and day (P21 track C)
SAVED_SEARCH_DIGEST: Final = "saved_search_digest"  # the day's saved-search counts by email, opt-in (P21 track C)
ENGAGEMENT_MESSAGE: Final = "engagement.n18"  # N18, a new message on an engagement: its email is mutable (P21 track A)


@dataclass(frozen=True, slots=True)
class KindInfo:
    """One kind on one channel: whether a person may change it and what it is when they never did."""

    kind: str
    channel: NotificationChannel
    mutable: bool
    default: bool
    label: str  # the settings page's line [[COPY-REVIEW]]
    developer_only: bool = False  # offered only to someone with a developer profile


CATALOGUE: Final[tuple[KindInfo, ...]] = (
    KindInfo(
        SAVED_SEARCH_MATCH,
        NotificationChannel.IN_APP,
        mutable=False,
        default=True,
        label="New matches for a saved Discover search, in the app",
        developer_only=True,
    ),
    KindInfo(
        SAVED_SEARCH_DIGEST,
        NotificationChannel.EMAIL,
        mutable=True,
        default=False,
        label="A daily email with how many new problems or Briefs match your saved searches",
        developer_only=True,
    ),
    KindInfo(
        ENGAGEMENT_MESSAGE,
        NotificationChannel.EMAIL,
        mutable=True,
        default=True,
        label="A new message on an engagement, by email (at most one per engagement every 30 minutes)",
    ),
)
_BY_KEY: Final = {(info.kind, info.channel): info for info in CATALOGUE}


def catalogued(kind: str, channel: NotificationChannel) -> KindInfo | None:
    return _BY_KEY.get((kind, channel))


def default_for(kind: str, channel: NotificationChannel) -> bool:
    """What ``kind`` on ``channel`` is for someone who never chose: the catalogue's default, else on."""
    info = catalogued(kind, channel)
    return True if info is None else info.default


async def channel_enabled(db: AsyncSession, user_id: UUID, kind: str, channel: NotificationChannel) -> bool:
    """The user's choice for ``kind`` on ``channel``; the kind's default when they never made one."""
    enabled = await db.scalar(
        select(NotificationPreference.enabled).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.kind == kind,
            NotificationPreference.channel == channel,
        )
    )
    return default_for(kind, channel) if enabled is None else bool(enabled)
