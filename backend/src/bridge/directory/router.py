"""Directory API (REQ-DIR-01, REQ-DIR-02): /api/directory/*. Signed-in users only; unknown or unlisted ids get 404.

- ``GET /orgs``: listed organisations grouped under niche headings, filtered by org type, county, niche and keywords
  (each word of ``q`` matches the name, a niche or its parent, or the county), cursor-paginated.
- ``GET /orgs/{org_id}``: one card.
- ``GET /niches``: the two-level niche taxonomy for pickers (directory filter, proposal editor, scout form).
- ``GET /filter-options``: org types and counties for the filters.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import StringConstraints

from bridge import clock
from bridge.auth.deps import CurrentSession, Db
from bridge.directory import service
from bridge.directory.responsiveness import ResponsivenessSource
from bridge.directory.schemas import DirectoryPage, FilterOptions, NicheNode, OrgCard
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.models.enums import OrgKind

router = APIRouter(prefix="/api/directory", tags=["directory"], responses=ERROR_RESPONSES)

CountyCode = Annotated[str, StringConstraints(pattern=r"^KE-\d{2}$")]
NicheSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)]
NO_NUL = r"^[^\x00]*$"  # Postgres text cannot hold NUL (0x00); a URL query cannot carry a lone surrogate
MAX_FILTER_VALUES = 50


def get_responsiveness(request: Request) -> ResponsivenessSource:
    source: ResponsivenessSource = request.app.state.responsiveness
    return source


ResponsivenessDep = Annotated[ResponsivenessSource, Depends(get_responsiveness)]


def _capped(values: list[str] | list[OrgKind] | None, name: str) -> tuple[str, ...]:
    unique = tuple(dict.fromkeys(values or ()))
    if len(unique) > MAX_FILTER_VALUES:
        raise ApiError(422, "too_many_filter_values", f"Choose at most {MAX_FILTER_VALUES} values for {name}.")
    return unique


@router.get("/orgs")
async def browse(
    live: CurrentSession,
    db: Db,
    responsiveness: ResponsivenessDep,
    kind: Annotated[list[OrgKind] | None, Query(description="Org type; repeat for several")] = None,
    county: Annotated[list[CountyCode] | None, Query(description="ISO 3166-2:KE county code; repeat")] = None,
    niche: Annotated[list[NicheSlug] | None, Query(description="Niche slug (a parent includes its children)")] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=100,
            pattern=NO_NUL,
            description="Keywords: each word matches the name, a niche or the county",
        ),
    ] = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DirectoryPage:
    try:
        after = service.decode_cursor(cursor) if cursor else None
    except ValueError as exc:
        raise ApiError(400, "invalid_cursor", "Start again from the first page.") from exc
    filters = service.DirectoryFilters(
        kinds=[OrgKind(k) for k in _capped(kind, "org type")],
        counties=_capped(county, "county"),
        niches=_capped(niche, "niche"),
        q=(q.strip() or None) if q else None,
    )
    return await service.list_directory(
        db, filters, cursor=after, limit=limit, responsiveness=responsiveness, now=clock.utcnow()
    )


@router.get("/orgs/{org_id}")
async def get_org_card(org_id: UUID, live: CurrentSession, db: Db, responsiveness: ResponsivenessDep) -> OrgCard:
    card = await service.get_card(db, org_id, responsiveness=responsiveness, now=clock.utcnow())
    if card is None:
        raise not_found()
    return card


@router.get("/niches")
async def list_niches(live: CurrentSession, db: Db) -> list[NicheNode]:
    return await service.niche_tree(db)


@router.get("/filter-options")
async def get_filter_options(live: CurrentSession, db: Db) -> FilterOptions:
    return await service.filter_options(db)
