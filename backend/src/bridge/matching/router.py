"""Discover, "Recommended for you" and liked niches (REQ-TREND-02, REQ-PERS-01, REQ-PERS-03; docs/spec/06 6.6,
6.7). Signed-in users only; everything is computed on read under the caller's Row-Level Security.

- ``GET /api/discover/trending``: Trending Problems (sources, Why chips, a self-explaining badge) and Trending
  Projects, each beside the problem it solves; no organisation count on a project, and no organisation name or id
  but a Brief's own ("Posted by <organisation>", ``ProblemRef.org``).
- ``GET /api/discover/opportunity-gap``: the top decile of trending problems with fewer than 3 proposals.
- ``GET /api/discover/briefs``: verified organisations' published, open Problem Briefs (REQ-DIR-05), newest first,
  with the organisation, budget band, deadline and the proposals linking each; paged with ``limit`` and ``cursor``.
  All three take ``niche`` (a slug; a parent includes its children) and ``county`` (an ISO 3166-2 code).
- ``GET /api/me/recommendations``: the developer's ranked cards with score, label, pursuit decision, Why chips and
  the feature vector; ``personalised`` is false without the ``profiling`` consent (404 without a developer profile).
- ``GET|PUT /api/me/niches``: the developer's liked niches (PUT sets all of them: 3 to 5 active niche ids; 422
  ``liked_niches_count`` or ``unknown_niche``).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from bridge import pagination
from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES, not_found
from bridge.matching import discover
from bridge.matching.discover_schemas import (
    DiscoverBriefsOut,
    LikedNichesIn,
    LikedNichesOut,
    OpportunityGapOut,
    RecommendationsOut,
    TrendingOut,
)
from bridge.matching.ranking_config import get_ranking
from bridge.matching.recommendations import recommendations
from bridge.profiles import niches as liked_niches
from bridge.profiles.models import DeveloperProfile

router = APIRouter(tags=["discover"], responses=ERROR_RESPONSES)

NicheSlug = Annotated[
    str | None,
    Query(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80, description="Niche slug (a parent includes children)"),
]
CountyCode = Annotated[str | None, Query(pattern=r"^[A-Z]{2}-[A-Z0-9]{1,5}$", description="ISO 3166-2 county code")]


@router.get("/api/discover/trending")
async def discover_trending(
    live: CurrentSession, db: Db, niche: NicheSlug = None, county: CountyCode = None
) -> TrendingOut:
    """Trending Problems and Trending Projects (with the problem each solves), Trending first, then New this week."""
    return await discover.trending(db, get_ranking(), niche=niche, county=county)


@router.get("/api/discover/opportunity-gap")
async def discover_opportunity_gap(
    live: CurrentSession, db: Db, niche: NicheSlug = None, county: CountyCode = None
) -> OpportunityGapOut:
    """Problems in the top trend decile with fewer than 3 proposals."""
    return await discover.opportunity_gap(db, get_ranking(), niche=niche, county=county)


@router.get("/api/discover/briefs")
async def discover_briefs(
    live: CurrentSession,
    db: Db,
    niche: NicheSlug = None,
    county: CountyCode = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: pagination.Cursor = None,
) -> DiscoverBriefsOut:
    """Verified organisations' published, open Problem Briefs (a passed deadline leaves the list), newest first."""
    return await discover.briefs_view(db, niche=niche, county=county, limit=limit, after=pagination.decode(cursor))


@router.get("/api/me/recommendations")
async def my_recommendations(live: CurrentSession, db: Db) -> RecommendationsOut:
    """Research cards and verified organisations' Briefs ranked for you, each explained."""
    return await recommendations(db, get_ranking(), live.user.id)


async def _niches_out(db: Db, user_id: UUID) -> LikedNichesOut:
    cfg = get_ranking()
    tree = await discover.niches(db)
    ids = await liked_niches.liked(db, user_id)
    return LikedNichesOut(
        liked=[n for n in (tree.out(i) for i in ids) if n is not None], min=cfg.liked_min, max=cfg.liked_max
    )


@router.get("/api/me/niches")
async def my_niches(live: CurrentSession, db: Db) -> LikedNichesOut:
    """Your liked niches (they rank "Recommended for you"; any plan)."""
    if await db.get(DeveloperProfile, live.user.id) is None:
        raise not_found("No developer profile.")
    return await _niches_out(db, live.user.id)


@router.put("/api/me/niches")
async def set_my_niches(body: LikedNichesIn, live: CurrentSession, db: Db) -> LikedNichesOut:
    """Set your liked niches: 3 to 5 niche ids from ``GET /api/directory/niches``."""
    if await db.get(DeveloperProfile, live.user.id) is None:
        raise not_found("No developer profile.")
    cfg = get_ranking()
    await liked_niches.replace_liked(db, live.user.id, body.liked, least=cfg.liked_min, most=cfg.liked_max)
    await db.commit()
    return await _niches_out(db, live.user.id)
