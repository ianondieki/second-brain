"""Peers (REQ-DEV-03; D-58; the P22 card's "Defaults taken" (1) and (2)): ``GET /api/me/peers?page=``.

Developers only (``deps.PeersDeveloper``: 404 for an organisation-only account and staff). A developer who has not
turned Peers on (``developer_profiles.peers_visible``, ``PATCH /api/me/profile``) gets an empty page with
``opted_in: false`` (200, not an error): they neither see peers nor appear to anyone. One who has gets 20 a page from
``app_peers`` (revision 0011): the other opted-in developers of their kind (real or demo accounts) in their county or
sharing a liked niche, with no block either way, ordered by the number of shared niches, then the caller's county
first, then the newest opt-in (the time is never returned), then handle. Each row is the handle, headline, county name,
shared niche slugs and whether the county is the caller's: never an email, phone, name, bio or verification level.
The page is one statement (plus the caller's check, which the dependency asks with the developer check).

Pages are limited to ``teams.peers_pages_per_hour`` an hour per developer who opted in (429 ``too_many_peer_pages``,
``Retry-After``), so the opted-in set cannot be paged through at speed (the 0011 security review's MINOR 5).
"""

from __future__ import annotations

from typing import Annotated, Final

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bridge.auth.deps import Db, SettingsDep
from bridge.errors import ERROR_RESPONSES
from bridge.teams import limits
from bridge.teams.deps import PeersDeveloper
from bridge.teams.policy import get_teams_policy
from bridge.teams.schemas import PeerOut, PeersPage

router = APIRouter(prefix="/api/me/peers", tags=["teams"], responses=ERROR_RESPONSES)
PAGE_SIZE: Final = 20
MAX_PAGE: Final = 500
_PEERS: Final = text(
    "SELECT user_id, handle::text AS handle, headline, county_name, shared_niches, same_county"
    " FROM app_peers(:limit, :offset)"
)
# [[COPY-REVIEW]]
TOO_MANY_PAGES: Final = "You have looked through many pages of peers in the last hour. Try again later."


def empty() -> PeersPage:
    return PeersPage(peers=[], next=None, opted_in=False)


@router.get("")
async def my_peers(
    caller: PeersDeveloper,
    db: Db,
    settings: SettingsDep,
    page: Annotated[int, Query(ge=1, le=MAX_PAGE, description="1 for the first page")] = 1,
) -> PeersPage:
    """Developers near you or in your niches who turned Peers on, 20 a page; empty until you turn it on."""
    if not caller.opted_in:
        return empty()
    policy = get_teams_policy()
    await limits.spend(
        db,
        settings.secret_key.get_secret_value(),
        purpose=limits.PEERS_PAGE,
        user_id=caller.live.user.id,
        limit=policy.peers_pages_per_hour,
        window=limits.HOUR,
        code="too_many_peer_pages",
        message=TOO_MANY_PAGES,
    )
    try:
        rows = (await db.execute(_PEERS, {"limit": PAGE_SIZE + 1, "offset": (page - 1) * PAGE_SIZE})).all()
    except DBAPIError as exc:  # the switch turned off since the check: nothing to show, nothing counted
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) != "42501":
            raise
        return empty()
    await db.commit()
    return PeersPage(
        peers=[
            PeerOut(
                user_id=row.user_id,
                handle=row.handle,
                headline=row.headline,
                county_name=row.county_name,
                shared_niches=list(row.shared_niches),
                same_county=bool(row.same_county),
            )
            for row in rows[:PAGE_SIZE]
        ],
        next=page + 1 if len(rows) > PAGE_SIZE and page < MAX_PAGE else None,
        opted_in=True,
    )
