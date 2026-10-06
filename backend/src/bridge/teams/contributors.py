"""Contributors (REQ-DEV-03; D-62 (a): "Contributors: <handles>"; revision 0011's ``proposal_contributors``).

The registrant stays one person: the idea's owner. The owner credits the other developer of one of their team threads
(open or closed) as a contributor; the credit lists handles only, by the time each was added, on the idea page
(``MyProposalOut.contributors``), the organisation's proposal view (``TeaserCard.contributors``), and the certificate's
data and PDF (``bridge.provenance.certificate``), always through ``app_contributor_handles`` and never in the manifest
or its hash (``manifest_version`` stays "1"). Nothing about shares; the tracker's developer party and the originality
check are unchanged. Developers only (``deps.Developer``).

- ``GET /api/me/ideas/{proposal_id}/contributors``: the owner's view of the credit (each contributor's id and handle;
  the handle is null while a block stands between the two, whose credit still shows publicly). 404 unless the caller
  owns the idea.
- ``POST`` the same ``{user_id}``: 201. 404 ``not_a_counterpart`` unless the two have a team thread and no block stands
  (the database's policy); 409 ``already_contributor`` for a contributor credited before, removed ones included (a
  removed credit is never added back). Audited ``proposal.contributor_added``.
- ``DELETE /api/me/ideas/{proposal_id}/contributors/{user_id}``: the owner removes a credit (204; 404 when there is
  none). ``DELETE /api/me/contributions/{proposal_id}``: a contributor removes their own credit (204; 404). Both
  set ``removed_at`` (the database's time), once and for good. Audited ``proposal.contributor_removed``.
- ``GET /api/me/contributions``: the ideas that credit the caller (the title while the idea is published).
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth.deps import Db
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.teams import errors
from bridge.teams.deps import Developer
from bridge.teams.schemas import (
    ContributionOut,
    ContributionsOut,
    ContributorIn,
    ContributorOut,
    ContributorsOut,
)

router = APIRouter(tags=["teams"], responses=ERROR_RESPONSES)
IDEA: Final = "/api/me/ideas/{proposal_id}/contributors"
NO_IDEA: Final = "No idea of yours has this id."
NO_CREDIT: Final = "No such contributor on this idea."
ALREADY_CREDITED: Final = "This developer is or was already credited on this idea."  # [[COPY-REVIEW]]
_OWNED: Final = text("SELECT 1 FROM proposals WHERE id = :p AND owner_id = app_user_id()")
_THREAD: Final = text(
    "SELECT id FROM team_threads WHERE a_user_id = least(app_user_id(), CAST(:u AS uuid))"
    " AND b_user_id = greatest(app_user_id(), CAST(:u AS uuid)) ORDER BY created_at DESC, id DESC LIMIT 1"
)
_ADD: Final = text("INSERT INTO proposal_contributors (proposal_id, user_id, thread_id) VALUES (:p, :u, :t)")
_CREDIT: Final = text(
    "SELECT coalesce(app_contributor_handles(:p), '{}') AS handles, coalesce((SELECT json_agg(json_build_object("
    "'user_id', c.user_id, 'handle', d.handle, 'added_at', c.added_at) ORDER BY c.added_at, c.user_id)"
    " FROM proposal_contributors c LEFT JOIN LATERAL app_developer_card(c.user_id) d ON true"
    " WHERE c.proposal_id = :p AND c.removed_at IS NULL), '[]') AS items"
)
_REMOVE: Final = text(
    "UPDATE proposal_contributors SET removed_at = now() WHERE proposal_id = :p AND user_id = :u AND removed_at IS NULL"
)
_MINE: Final = text(
    "SELECT c.proposal_id, p.title, c.added_at FROM proposal_contributors c"
    " LEFT JOIN proposals p ON p.id = c.proposal_id AND p.status = 'published' AND p.moderation_state = 'clear'"
    " WHERE c.user_id = app_user_id() AND c.removed_at IS NULL ORDER BY c.added_at DESC, c.proposal_id LIMIT 200"
)


async def _owned(db: AsyncSession, proposal_id: UUID) -> None:
    if (await db.execute(_OWNED, {"p": proposal_id})).first() is None:
        raise not_found(NO_IDEA)


async def credit(db: AsyncSession, proposal_id: UUID) -> ContributorsOut:
    """The idea's credit as its owner sees it (one statement)."""
    row = (await db.execute(_CREDIT, {"p": proposal_id})).one()
    return ContributorsOut(
        contributors=list(row.handles), items=[ContributorOut.model_validate(item) for item in row.items]
    )


async def _removed(db: AsyncSession, me: UUID, proposal_id: UUID, user_id: UUID) -> None:
    result = await db.execute(_REMOVE, {"p": proposal_id, "u": user_id})
    if int(getattr(result, "rowcount", 0) or 0) == 0:
        await db.rollback()
        raise not_found(NO_CREDIT)
    await audit(
        db,
        "proposal.contributor_removed",
        actor_user_id=me,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={"user_id": str(user_id), "by_contributor": user_id == me},
    )
    await db.commit()


@router.get(IDEA)
async def contributors(proposal_id: UUID, live: Developer, db: Db) -> ContributorsOut:
    """Your idea's contributors."""
    await _owned(db, proposal_id)
    return await credit(db, proposal_id)


@router.post(IDEA, status_code=201)
async def add_contributor(proposal_id: UUID, body: ContributorIn, live: Developer, db: Db) -> ContributorsOut:
    """Credit a developer you team up with on your idea ("Contributors: <handles>")."""
    await _owned(db, proposal_id)
    thread_id = await db.scalar(_THREAD, {"u": body.user_id})
    if thread_id is None or body.user_id == live.user.id:
        raise ApiError(404, "not_a_counterpart", errors.NOT_A_COUNTERPART)
    try:
        await db.execute(_ADD, {"p": proposal_id, "u": body.user_id, "t": thread_id})
    except DBAPIError as exc:
        await db.rollback()
        state = errors.sqlstate(exc)
        if state == "23505":
            raise ApiError(
                409, "already_contributor", "This developer is or was already credited on this idea."
            ) from None
        if state in ("42501", "23503"):
            raise ApiError(404, "not_a_counterpart", errors.NOT_A_COUNTERPART) from None
        raise
    await audit(
        db,
        "proposal.contributor_added",
        actor_user_id=live.user.id,
        subject_type="proposal",
        subject_id=proposal_id,
        payload={"user_id": str(body.user_id), "thread_id": str(thread_id)},
    )
    out = await credit(db, proposal_id)
    await db.commit()
    return out


@router.delete(f"{IDEA}/{{user_id}}", status_code=204, response_class=Response)
async def remove_contributor(proposal_id: UUID, user_id: UUID, live: Developer, db: Db) -> None:
    """Remove a contributor's credit from your idea (for good: it cannot be added back)."""
    await _owned(db, proposal_id)
    await _removed(db, live.user.id, proposal_id, user_id)


@router.get("/api/me/contributions")
async def my_contributions(live: Developer, db: Db) -> ContributionsOut:
    """The ideas that credit you as a contributor."""
    rows = (await db.execute(_MINE)).all()
    return ContributionsOut(
        items=[ContributionOut(proposal_id=row.proposal_id, title=row.title, added_at=row.added_at) for row in rows]
    )


@router.delete("/api/me/contributions/{proposal_id}", status_code=204, response_class=Response)
async def leave_contribution(proposal_id: UUID, live: Developer, db: Db) -> None:
    """Remove your own credit from an idea (for good)."""
    await _removed(db, live.user.id, proposal_id, live.user.id)
