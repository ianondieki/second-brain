"""Browse repo (REQ-REPO-02; docs/spec/06 6.1, AC-REPO-5): keyword search over published Tier-1 teasers.

Only proposals that are published and clear of moderation are found; drafts, held, rejected and hidden ones never are
(for their owner neither). The keywords go through ``websearch_to_tsquery('simple', ...)`` against
``proposals.search_tsv`` (title weighted above the problem statement and summary, then impact claims; ``simple``: no
stemming, so English and Swahili words match as typed). Filters: niche (a parent niche includes its children), county,
maturity, ask and linked Problem (of the current version). Results are ordered by relevance when there are keywords,
then newest first, and paged with a keyset cursor over (rank, published_at, id).

Items are ``serializers.TeaserItem``: Tier 1 only, never a Tier-2 field, an embedding or tag data (AC-REPO-3,
AC-REPO-6/a).
"""

from __future__ import annotations

import base64
import binascii
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.models.enums import ProposalAsk, ProposalMaturity
from bridge.proposals.serializers import TeaserItem, teaser_items

_QUERY: Final = "websearch_to_tsquery('simple', :q)"


class BrowsePage(BaseModel):
    items: list[TeaserItem]
    next_cursor: str | None = Field(description="Pass as ?cursor= for the next page; null on the last page")


@dataclass(frozen=True, slots=True)
class BrowseFilters:
    q: str | None = None
    niches: Sequence[str] = ()  # slugs; a parent slug includes its children
    counties: Sequence[str] = ()
    maturities: Sequence[ProposalMaturity] = ()
    asks: Sequence[ProposalAsk] = ()
    problem_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Cursor:
    rank: float
    published_at: datetime
    proposal_id: UUID


def encode_cursor(cursor: Cursor) -> str:
    raw = json.dumps([cursor.rank, cursor.published_at.isoformat(), str(cursor.proposal_id)])
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode_cursor(value: str) -> Cursor:
    """Raise ValueError for anything that is not a cursor this module wrote."""
    try:
        rank, published_at, proposal_id = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if type(rank) not in (int, float) or not math.isfinite(rank):  # bool is not accepted (type, not isinstance)
            raise ValueError("malformed cursor")
        if not isinstance(published_at, str) or not isinstance(proposal_id, str):
            raise ValueError("malformed cursor")
        moment = datetime.fromisoformat(published_at)
        if moment.tzinfo is None:
            raise ValueError("malformed cursor")
        return Cursor(float(rank), moment, UUID(proposal_id))
    except (binascii.Error, UnicodeDecodeError, TypeError, ValueError) as exc:  # JSONDecodeError is a ValueError
        raise ValueError("invalid cursor") from exc


def _where(filters: BrowseFilters, params: dict[str, Any]) -> list[str]:
    conditions = ["p.status = 'published'", "p.moderation_state = 'clear'", "p.published_at IS NOT NULL"]
    if filters.q:
        conditions.append(f"p.search_tsv @@ {_QUERY}")
        params["q"] = filters.q
    if filters.niches:
        conditions.append(
            "p.niche_id IN (SELECT n.id FROM niches n LEFT JOIN niches pn ON pn.id = n.parent_id"
            " WHERE n.slug = ANY(:niches) OR pn.slug = ANY(:niches))"
        )
        params["niches"] = list(filters.niches)
    if filters.counties:
        conditions.append("p.county_code = ANY(:counties)")
        params["counties"] = list(filters.counties)
    if filters.maturities:
        conditions.append("p.maturity = ANY(CAST(:maturities AS proposal_maturity[]))")
        params["maturities"] = [m.value for m in filters.maturities]
    if filters.asks:
        conditions.append("p.ask = ANY(CAST(:asks AS proposal_ask[]))")
        params["asks"] = [a.value for a in filters.asks]
    if filters.problem_id is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM proposal_problems pp WHERE pp.proposal_version_id = p.current_version_id"
            " AND pp.problem_id = :problem)"
        )
        params["problem"] = filters.problem_id
    return conditions


async def browse(db: AsyncSession, filters: BrowseFilters, *, cursor: Cursor | None, limit: int) -> BrowsePage:
    params: dict[str, Any] = {"limit": limit + 1}
    conditions = _where(filters, params)
    rank = f"CAST(ts_rank(p.search_tsv, {_QUERY}) AS float8)" if filters.q else "CAST(0 AS float8)"
    if cursor is not None:
        conditions.append(f"({rank}, p.published_at, p.id) < (:c_rank, :c_published, :c_id)")
        params |= {"c_rank": cursor.rank, "c_published": cursor.published_at, "c_id": cursor.proposal_id}
    sql = (
        f"SELECT p.id, {rank} AS rank, p.published_at FROM proposals p WHERE {' AND '.join(conditions)}"  # noqa: S608
        " ORDER BY rank DESC, p.published_at DESC, p.id DESC LIMIT :limit"
    )
    rows = (await db.execute(text(sql), params)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    items = await teaser_items(db, [row.id for row in rows])
    next_cursor = None
    if more:
        last = rows[-1]
        next_cursor = encode_cursor(Cursor(float(last.rank), last.published_at, last.id))
    return BrowsePage(items=[items[row.id] for row in rows if row.id in items], next_cursor=next_cursor)
