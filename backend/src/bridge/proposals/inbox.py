"""The organisation Inbox (REQ-PROP-03, REQ-REPO-03; docs/spec/06 6.3, 6.9, REQUIREMENTS.md §5 N01 org side): the
proposals pitched to this organisation, newest first, each as its Tier-1 teaser with the engagement it opened.

Only ``delivered`` tags of the organisation the request is scoped to are read (the ``org_member`` dependency binds
``app.org_id``; Row-Level Security admits members to delivered tags only). Held tags stay invisible: an E1
organisation sees only how many wait for its verification (``app_held_tag_count``, AC-PROP-1/a). Nothing names
another organisation a proposal was pitched to (AC-REPO-6/a): an item is the tag, the engagement and the teaser.
A proposal hidden or held after it was pitched drops out of the list (its teaser is no longer readable). Each item
says whether the proposal is on the organisation's shortlist (``shortlisted``, the Inbox's star; P21 track B).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.models.enums import EngagementState, OrgVerification
from bridge.proposals.serializers import TeaserItem, teaser_items
from bridge.proposals.shortlist import starred


def _without_default(schema: dict[str, Any]) -> None:
    """Leave a field's default out of the OpenAPI document: always sent, it stays optional in the generated web types,
    so a client reads an older API as "not sent" (as ``matching.schemas``)."""
    schema.pop("default", None)


class InboxEngagement(BaseModel):
    id: UUID
    state: EngagementState
    stage_deadline_at: datetime | None


class InboxItem(BaseModel):
    tag_id: UUID
    pitched_at: datetime
    engagement: InboxEngagement | None = Field(description="Null until the engagement is opened")
    proposal: TeaserItem
    shortlisted: bool = Field(
        default=False,
        description="Whether the proposal is on this organisation's shortlist (the Inbox's star)",
        json_schema_extra=_without_default,
    )


class InboxPage(BaseModel):
    items: list[InboxItem]
    next_cursor: str | None
    held_count: int = Field(description="Proposals waiting until this organisation is verified (E1 sees only this)")
    verification: OrgVerification


@dataclass(frozen=True, slots=True)
class Cursor:
    pitched_at: datetime
    tag_id: UUID


def encode_cursor(cursor: Cursor) -> str:
    raw = json.dumps([cursor.pitched_at.isoformat(), str(cursor.tag_id)])
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> Cursor:
    """Raise ValueError for anything that is not a cursor this module wrote."""
    try:
        pitched_at, tag_id = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if not isinstance(pitched_at, str) or not isinstance(tag_id, str):
            raise ValueError("malformed cursor")
        moment = datetime.fromisoformat(pitched_at)
        if moment.tzinfo is None:
            raise ValueError("malformed cursor")
        return Cursor(moment, UUID(tag_id))
    except (binascii.Error, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise ValueError("invalid cursor") from exc


_ITEMS = text(
    "SELECT t.id, t.proposal_id, t.created_at, e.id AS engagement_id, e.state, e.stage_deadline_at FROM tags t"
    " LEFT JOIN engagements e ON e.proposal_id = t.proposal_id AND e.org_id = t.org_id"
    " WHERE t.org_id = :org AND t.status = 'delivered'"
    " AND (CAST(:c_at AS timestamptz) IS NULL"
    " OR (t.created_at, t.id) < (CAST(:c_at AS timestamptz), CAST(:c_id AS uuid)))"
    " ORDER BY t.created_at DESC, t.id DESC LIMIT :limit"
)
_ORG = text("SELECT verification, app_held_tag_count(id) AS held FROM organizations WHERE id = :org")


def _engagement(row: Any) -> InboxEngagement | None:
    if row.engagement_id is None:
        return None
    return InboxEngagement(id=row.engagement_id, state=row.state, stage_deadline_at=row.stage_deadline_at)


async def inbox(db: AsyncSession, *, org_id: UUID, cursor: Cursor | None, limit: int) -> InboxPage:
    org = (await db.execute(_ORG, {"org": org_id})).one()
    params = {
        "org": org_id,
        "c_at": cursor.pitched_at if cursor else None,
        "c_id": cursor.tag_id if cursor else None,
        "limit": limit + 1,
    }
    rows = (await db.execute(_ITEMS, params)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    teasers = await teaser_items(db, [row.proposal_id for row in rows])
    stars = await starred(db, org_id, list(teasers))
    items = [
        InboxItem(
            tag_id=row.id,
            pitched_at=row.created_at,
            engagement=_engagement(row),
            proposal=teasers[row.proposal_id],
            shortlisted=row.proposal_id in stars,
        )
        for row in rows
        if row.proposal_id in teasers
    ]
    next_cursor = encode_cursor(Cursor(rows[-1].created_at, rows[-1].id)) if more else None
    return InboxPage(items=items, next_cursor=next_cursor, held_count=int(org.held), verification=org.verification)
