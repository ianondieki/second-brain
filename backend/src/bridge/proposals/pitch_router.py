"""Browse repo, "Pitch to company" and the organisation Inbox (P4: REQ-REPO-02, REQ-PROP-03, REQ-REPO-03,
REQ-NOT-02, REQ-BIL-02, REQ-DIR-04; docs/spec/06 6.1-6.3). Signed-in users only.

- ``GET /api/proposals``: Browse repo, keyword search over published Tier-1 teasers with filters (niche, county,
  maturity, ask, linked Problem), cursor-paginated.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import StringConstraints

from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.models.enums import ProposalAsk, ProposalMaturity
from bridge.proposals import search

router = APIRouter(tags=["pitch"], responses=ERROR_RESPONSES)

CountyCode = Annotated[str, StringConstraints(pattern=r"^KE-\d{2}$")]
NicheSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)]
NO_NUL = r"^[^\x00]*$"  # Postgres text cannot hold NUL (0x00)
MAX_FILTER_VALUES = 50


def _capped[T](values: list[T] | None, name: str) -> list[T]:
    unique = list(dict.fromkeys(values or ()))
    if len(unique) > MAX_FILTER_VALUES:
        raise ApiError(422, "too_many_filter_values", f"Choose at most {MAX_FILTER_VALUES} values for {name}.")
    return unique


@router.get("/api/proposals")
async def browse_proposals(
    live: CurrentSession,
    db: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=200, pattern=NO_NUL, description="Keywords")] = None,
    niche: Annotated[list[NicheSlug] | None, Query(description="Niche slug (a parent includes its children)")] = None,
    county: Annotated[list[CountyCode] | None, Query(description="ISO 3166-2:KE county code; repeat")] = None,
    maturity: Annotated[list[ProposalMaturity] | None, Query()] = None,
    ask: Annotated[list[ProposalAsk] | None, Query()] = None,
    problem: Annotated[UUID | None, Query(description="A linked Problem")] = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> search.BrowsePage:
    """Published teasers (Tier 1 only) matching the keywords and filters; the most relevant, then newest, first."""
    try:
        after = search.decode_cursor(cursor) if cursor else None
    except ValueError as exc:
        raise ApiError(400, "invalid_cursor", "Start again from the first page.") from exc
    filters = search.BrowseFilters(
        q=(q.strip() or None) if q else None,
        niches=_capped(niche, "niche"),
        counties=_capped(county, "county"),
        maturities=_capped(maturity, "maturity"),
        asks=_capped(ask, "ask"),
        problem_id=problem,
    )
    return await search.browse(db, filters, cursor=after, limit=limit)
