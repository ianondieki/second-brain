"""Tier-1 teaser items for lists (REQ-REPO-03, REQ-REPO-02; docs/spec/06 6.1, 6.3): Browse repo search results and the
organisation Inbox.

An item is built from an allow-list of Tier-1 columns (``TIER1_COLUMNS``, read from the registered version the
proposal points at), the owner's pseudonymous handle and the certificate id. Nothing else reaches it: no Tier-2 field,
no embedding or search vector, and no tag, grant or engagement data, so no organisation a proposal was pitched to can
be read from a teaser (tag privacy, AC-REPO-6/a). Only a published proposal clear of moderation has an item.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.proposals.schemas import TeaserOut
from bridge.proposals.service import teaser_out

# The Tier-1 snapshot of a registered version (docs/spec/06 6.1 Tier 1) that a list may show.
TIER1_COLUMNS: Final = (
    "title",
    "niche_id",
    "country",
    "county_code",
    "maturity",
    "ask",
    "problem_statement",
    "impact_claims",
    "summary",
)
_ITEMS = text(
    "SELECT p.id, p.published_at, v.version_no, v.cert_id, v.owner_handle, "  # noqa: S608 (constant column names)
    + ", ".join(f"v.{column}" for column in TIER1_COLUMNS)
    + ", n.slug AS niche_slug, n.name_en AS niche_name, pn.name_en AS parent_name"
    " FROM proposals p JOIN proposal_versions v ON v.id = p.current_version_id"
    " LEFT JOIN niches n ON n.id = v.niche_id LEFT JOIN niches pn ON pn.id = n.parent_id"
    " WHERE p.id = ANY(:ids) AND p.status = 'published' AND p.moderation_state = 'clear'"
)


class TeaserItem(BaseModel):
    """A published teaser in a list: Tier 1 only, the owner's handle and the certificate id."""

    id: UUID
    owner_handle: str
    cert_id: str
    version_no: int
    published_at: datetime
    teaser: TeaserOut


async def teaser_items(db: AsyncSession, proposal_ids: Sequence[UUID]) -> dict[UUID, TeaserItem]:
    """The items of those proposals that are published and clear (others are left out), by proposal id."""
    ids = list(dict.fromkeys(proposal_ids))
    if not ids:
        return {}
    rows = (await db.execute(_ITEMS, {"ids": ids})).all()
    return {
        row.id: TeaserItem(
            id=row.id,
            owner_handle=row.owner_handle,
            cert_id=row.cert_id,
            version_no=row.version_no,
            published_at=row.published_at,
            teaser=teaser_out(row),
        )
        for row in rows
    }
