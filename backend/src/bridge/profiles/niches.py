"""Liked niches (REQ-PERS-03; docs/spec/06 6.7 cold start, docs/spec/05: 3 to 5 liked niches on every plan).

Rows of ``developer_niches`` with ``kind = liked`` (tenancy USER: Row-Level Security limits every read and write to
the signed-in user). ``replace_liked`` sets the whole list at once: the count must be within the configured range
(``config/ranking/weights_v1.yaml`` ``liked_niches``) and every niche must exist and be active; followed niches
(``kind = followed``, capped per plan, for trending alerts) are never touched here.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.errors import ApiError

_LIKED = text(
    "SELECT d.niche_id FROM developer_niches d JOIN niches n ON n.id = d.niche_id"
    " WHERE d.user_id = :user AND d.kind = 'liked' ORDER BY n.sort_order, n.name_en, n.id"
)
_ACTIVE = text("SELECT id FROM niches WHERE id = ANY(:ids) AND active")
_DROP = text("DELETE FROM developer_niches WHERE user_id = :user AND kind = 'liked' AND NOT (niche_id = ANY(:ids))")
_ADD = text(
    "INSERT INTO developer_niches (user_id, niche_id, kind) SELECT :user, unnest(CAST(:ids AS uuid[])), 'liked'"
    " ON CONFLICT (user_id, niche_id, kind) DO NOTHING"
)


async def liked(db: AsyncSession, user_id: UUID) -> list[UUID]:
    return list((await db.execute(_LIKED, {"user": user_id})).scalars().all())


async def replace_liked(
    db: AsyncSession, user_id: UUID, niche_ids: Sequence[UUID], *, least: int, most: int
) -> list[UUID]:
    """Set the user's liked niches to exactly ``niche_ids`` (duplicates count once); the caller commits."""
    ids = list(dict.fromkeys(niche_ids))
    if not least <= len(ids) <= most:
        raise ApiError(422, "liked_niches_count", f"Choose {least} to {most} niches you like.")
    active = set((await db.execute(_ACTIVE, {"ids": ids})).scalars().all())
    unknown = [str(i) for i in ids if i not in active]
    if unknown:
        raise ApiError(422, "unknown_niche", "Choose niches from the list.", niches=unknown)
    await db.execute(_DROP, {"user": user_id, "ids": ids})
    await db.execute(_ADD, {"user": user_id, "ids": ids})
    return await liked(db, user_id)
