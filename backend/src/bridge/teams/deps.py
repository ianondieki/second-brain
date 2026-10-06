"""Who may use the peers and teams routes (REQ-DEV-03; D-58 "no organisation route ever returns peers, teams or
threads"): developers only, ``app_is_developer()`` (an active user with a developer profile and no staff role). An
organisation-only account and staff get 404 on every route, as on the quiz's; signed out is 401 as on every
``/api/me`` route. Row-Level Security repeats the rule (every 0011 policy needs a developer)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends
from sqlalchemy import text

from bridge.auth.deps import CurrentSession, Db
from bridge.auth.sessions import LiveSession
from bridge.errors import not_found

_IS_DEVELOPER: Final = text("SELECT app_is_developer()")
# app_is_visible_peer(the caller) is app_is_developer() and the caller's own switch: one statement for both.
_PEERS_CALLER: Final = text("SELECT app_is_developer() AS developer, app_is_visible_peer(app_user_id()) AS opted_in")


async def team_developer(live: CurrentSession, db: Db) -> LiveSession:
    """A developer; 404 for everyone else signed in."""
    if not await db.scalar(_IS_DEVELOPER):
        raise not_found()
    return live


Developer = Annotated[LiveSession, Depends(team_developer)]


@dataclass(frozen=True, slots=True)
class PeersCaller:
    live: LiveSession
    opted_in: bool


async def peers_caller(live: CurrentSession, db: Db) -> PeersCaller:
    """A developer and whether they turned Peers on; 404 for everyone else signed in."""
    row = (await db.execute(_PEERS_CALLER)).one()
    if not row.developer:
        raise not_found()
    return PeersCaller(live, bool(row.opted_in))


PeersDeveloper = Annotated[PeersCaller, Depends(peers_caller)]
