"""Public reads for signed-out visitors: the landing's "What's happening" feed and the Explore page (REQ-UX-03,
REQ-DIR-01, REQ-REPO-02; P24-B). No session needed.

- ``GET /api/public/activity``: the 20 latest public events, anonymised (``bridge.public.feed``): a problem posted, a
  Brief opened, a proposal version registered (and, once the database offers it, an engagement reaching a stage).
- ``GET /api/public/explore``: published problems anyone may read, counted by county and by top-level niche, with the
  three newest of each.

Both are the same for everyone, so each API worker keeps one copy for 60 seconds (one database read per minute per
worker) and says ``Cache-Control: public, max-age=60``. Every request still counts against its client address on the
login-attempt ledger, as ``/api/verify`` does (``verify.allow``: keyed digests of the address only), 60 a minute per
route; past that it is 429 ``rate_limited`` (``no-store``) and nothing is read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Final

from fastapi import APIRouter, Request, Response

from bridge import clock
from bridge.auth.deps import Db, SettingsDep, client_ip
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.provenance import verify
from bridge.public import feed
from bridge.public.cache import Cached
from bridge.public.schemas import ActivityFeed, Explore

router = APIRouter(prefix="/api/public", tags=["public"], responses=ERROR_RESPONSES)

CACHE_SECONDS: Final = 60.0
PUBLIC_CACHE: Final = "public, max-age=60"
READS_PER_MINUTE: Final = 60  # per client address and route; a page view reads each once
ACTIVITY_PURPOSE: Final = "public-activity"
EXPLORE_PURPOSE: Final = "public-explore"


@dataclass(frozen=True, slots=True)
class PublicCaches:
    activity: Cached[ActivityFeed]
    explore: Cached[Explore]


def caches(request: Request) -> PublicCaches:
    """This worker's caches (one per app; made on the first public read)."""
    found: PublicCaches | None = getattr(request.app.state, "public_caches", None)
    if found is None:
        found = PublicCaches(Cached(CACHE_SECONDS, now=monotonic), Cached(CACHE_SECONDS, now=monotonic))
        request.app.state.public_caches = found
    return found


async def _throttle(db: Db, settings: SettingsDep, request: Request, *, purpose: str) -> None:
    allowed = await verify.allow(db, settings, purpose=purpose, ip=client_ip(request), per_minute=READS_PER_MINUTE)
    await db.commit()
    if not allowed:
        raise ApiError(429, "rate_limited", "Too many requests from this address. Wait a minute and try again.")


def _platform_now(request: Request) -> datetime:
    """The instant ``X-App-Now`` carries for this request (the platform clock), else the wall clock."""
    moment = getattr(request.state, "app_now", None)
    return moment if isinstance(moment, datetime) else clock.utcnow()


@router.get("/activity")
async def public_activity(request: Request, response: Response, db: Db, settings: SettingsDep) -> ActivityFeed:
    """The 20 latest public events, newest first: never a person, a handle, an organisation or private text."""
    await _throttle(db, settings, request, purpose=ACTIVITY_PURPOSE)
    factory, demo, generated_at = (
        request.app.state.session_factory,
        feed.demo_deployment(settings),
        _platform_now(request),
    )
    result = await caches(request).activity.get(lambda: feed.activity(factory, generated_at=generated_at, demo=demo))
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return result


@router.get("/explore")
async def public_explore(request: Request, response: Response, db: Db, settings: SettingsDep) -> Explore:
    """Published problems by county and by top-level niche, each with its three newest."""
    await _throttle(db, settings, request, purpose=EXPLORE_PURPOSE)
    factory, demo = request.app.state.session_factory, feed.demo_deployment(settings)
    result = await caches(request).explore.get(lambda: feed.explore(factory, demo=demo))
    response.headers["Cache-Control"] = PUBLIC_CACHE
    return result
