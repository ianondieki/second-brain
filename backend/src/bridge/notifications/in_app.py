"""In-app notifications, once per dedupe key (REQ-NOT-06; docs/spec/06 6.10: in-app is always on).

``post_in_app`` writes the ``notification_deliveries`` ledger row (channel ``in_app``, ``sent``) and the
``in_app_notifications`` row together in the caller's transaction, on a session bound to the recipient (both tables
are the user's own under RLS). The ledger row's unique ``dedupe_key`` makes it idempotent: a second call, or a
concurrent one, finds the key taken and writes nothing (``SqlDeliveryStore.add``: a savepoint, so the caller's
transaction stays usable). A daily message keys it with ``deliveries.daily_key(kind, IN_APP, ...)``, so at most one
in-app summary exists per user, kind and Nairobi date. Links are platform paths only, never another site
(``is_platform_path``: the bell's API serves nothing else either).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.ids import uuid7
from bridge.models.enums import DeliveryStatus, NotificationChannel
from bridge.notifications.deliveries import SqlDeliveryStore
from bridge.notifications.models import InAppNotification, NotificationDelivery

IN_APP_ADDRESS: Final = "in-app"  # notification_deliveries.to_address of an in-app row (there is no address)
IN_APP_PROVIDER: Final = "in_app"
MAX_TITLE_CHARS: Final = 200  # in_app_notifications.title
MAX_LINK_CHARS: Final = 500  # in_app_notifications.link
# One '/', then no second '/', no backslash (browsers read "/\x" as "//x") and no space or control character (they
# drop tabs and newlines, so "/\t/x" would be "//x" too): a path on this site, never a way to another one.
_PLATFORM_PATH: Final = re.compile(r"/(?![/\\])[^\\\x00-\x20\x7f]*")


def is_platform_path(link: str) -> bool:
    """Whether ``link`` is a path on this platform (what an in-app notification may link to)."""
    return len(link) <= MAX_LINK_CHARS and _PLATFORM_PATH.fullmatch(link) is not None


def _check(title: str, link: str | None) -> None:
    if not title.strip() or len(title) > MAX_TITLE_CHARS:
        raise ValueError(f"an in-app title is 1-{MAX_TITLE_CHARS} characters")
    if link is not None and not is_platform_path(link):
        raise ValueError("an in-app link is a platform path starting with a single '/'")


async def post_in_app(
    db: AsyncSession,
    *,
    user_id: UUID,
    kind: str,
    title: str,
    body: str | None,
    link: str | None,
    dedupe_key: str,
    org_id: UUID | None = None,
    local_date: date | None = None,
) -> bool:
    """Write the notification once; False (nothing written) when ``dedupe_key`` is already taken."""
    _check(title, link)
    delivery = NotificationDelivery(
        id=uuid7(),
        user_id=user_id,
        org_id=org_id,
        kind=kind,
        channel=NotificationChannel.IN_APP,
        to_address=IN_APP_ADDRESS,
        dedupe_key=dedupe_key,
        local_date=local_date,
        status=DeliveryStatus.SENT,
        attempts=1,
        provider=IN_APP_PROVIDER,
        sent_at=clock.utcnow(),
    )
    if not await SqlDeliveryStore(db).add(delivery):
        return False
    db.add(InAppNotification(id=uuid7(), user_id=user_id, org_id=org_id, kind=kind, title=title, body=body, link=link))
    await db.flush()
    return True
