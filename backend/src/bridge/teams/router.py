"""Team up's API (REQ-DEV-03; D-58; ``bridge.teams.invitations``, ``bridge.teams.threads``): ``/api/me/teams`` and
``/api/me/blocks``. Developers only (``deps.Developer``: 404 for an organisation-only account and staff; signed out
401); a developer who is not a party of an invitation or a thread gets 404 for it.

- ``POST /invitations`` ``{to_user_id, problem_id, note?}``: 201, the invitation. 403 ``peers_off``; 404
  ``peer_unavailable`` / ``problem_unavailable``; 409 ``already_invited``; 422; 429 ``too_many_invitations``.
- ``GET /invitations``: pending invitations received and sent.
- ``POST /invitations/{id}/accept`` (201 ``{thread_id}``), ``/decline``, ``/withdraw`` (204): 403 ``wrong_party``,
  409 ``already_decided`` / ``invitation_unavailable``.
- ``GET /``: the caller's threads; ``GET /unread-count``; ``GET /{thread_id}`` (a page of messages);
  ``POST /{thread_id}/messages`` ``{body}`` (201; 409 ``thread_closed``; 429 ``too_many_messages``);
  ``POST /{thread_id}/read`` ``{up_to?}``; ``POST /{thread_id}/leave`` (204; 409 ``thread_closed``);
  ``POST /{thread_id}/messages/{message_id}/report`` ``{reasons}`` (201 ``{case_id}``; 409 ``own_message`` /
  ``already_reported``; 429 ``too_many_reports``).
- ``POST /api/me/blocks`` ``{user_id}`` (204, through ``app_block_developer``: it ends the pair's pending invitations
  and closes their open threads; an unknown id or an account that is no developer answers 204 too, so nothing tells
  them apart; 422 ``cannot_block_yourself``), ``DELETE /api/me/blocks/{user_id}`` (204, idempotent; threads stay
  closed), ``GET /api/me/blocks`` (the caller's blocks with each handle).
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge import pagination
from bridge.audit.service import record as audit
from bridge.auth.deps import Db
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.teams import errors, invitations, threads
from bridge.teams.deps import Developer
from bridge.teams.schemas import (
    AcceptedOut,
    BlockedOut,
    BlockIn,
    BlocksOut,
    InvitationIn,
    InvitationOut,
    InvitationsOut,
    ReadIn,
    ReadOut,
    TeamMessageIn,
    TeamMessageOut,
    TeamReportIn,
    TeamReportOut,
    ThreadOut,
    ThreadsOut,
    UnreadCountOut,
)

router = APIRouter(prefix="/api/me/teams", tags=["teams"], responses=ERROR_RESPONSES)
blocks_router = APIRouter(prefix="/api/me/blocks", tags=["teams"], responses=ERROR_RESPONSES)
_BLOCK: Final = text("SELECT app_block_developer(:user)")
_UNBLOCK: Final = text("SELECT app_unblock_developer(:user)")
_BLOCKED: Final = text("SELECT user_id, handle::text AS handle, blocked_at FROM app_blocked_developers()")


def _factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


# ------------------------------------------------------------------------------------------------------ invitations


@router.post("/invitations", status_code=201)
async def invite(body: InvitationIn, request: Request, live: Developer, db: Db) -> InvitationOut:
    """Invite a peer (or a developer you team up with) to team up on a published problem or Brief."""
    return await invitations.send(db, _factory(request), live.user.id, body)


@router.get("/invitations")
async def my_invitations(live: Developer, db: Db) -> InvitationsOut:
    """Your pending invitations, received and sent."""
    return await invitations.pending(db, live.user.id)


@router.post("/invitations/{invitation_id}/accept", status_code=201)
async def accept(invitation_id: UUID, request: Request, live: Developer, db: Db) -> AcceptedOut:
    """Accept an invitation you received: the team thread opens and the sender is told."""
    thread_id = await invitations.decide(db, _factory(request), live.user.id, invitation_id, "accept")
    if thread_id is None:  # the function always returns the thread for an accept
        raise ApiError(409, "invitation_unavailable", errors.INVITATION_UNAVAILABLE)
    return AcceptedOut(thread_id=thread_id)


@router.post("/invitations/{invitation_id}/decline", status_code=204, response_class=Response)
async def decline(invitation_id: UUID, request: Request, live: Developer, db: Db) -> None:
    """Decline an invitation you received (the sender is not told)."""
    await invitations.decide(db, _factory(request), live.user.id, invitation_id, "decline")


@router.post("/invitations/{invitation_id}/withdraw", status_code=204, response_class=Response)
async def withdraw(invitation_id: UUID, request: Request, live: Developer, db: Db) -> None:
    """Withdraw an invitation you sent."""
    await invitations.decide(db, _factory(request), live.user.id, invitation_id, "withdraw")


# ---------------------------------------------------------------------------------------------------------- threads


@router.get("")
async def my_threads(live: Developer, db: Db) -> ThreadsOut:
    """Your team threads: open ones first, then closed ones."""
    return await threads.threads(db)


@router.get("/unread-count")
async def unread_count(live: Developer, db: Db) -> UnreadCountOut:
    """Unread messages over all your team threads."""
    return await threads.unread_count(db)


@router.get("/{thread_id}")
async def get_thread(
    thread_id: UUID,
    live: Developer,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=threads.MAX_PAGE)] = threads.PAGE,
    cursor: pagination.Cursor = None,
) -> ThreadOut:
    """A page of the thread: the newest first page, ``next_cursor`` for older ones."""
    return await threads.page(db, live.user.id, thread_id, limit=limit, cursor=cursor)


@router.post("/{thread_id}/messages", status_code=201)
async def post_message(
    thread_id: UUID, body: TeamMessageIn, request: Request, live: Developer, db: Db
) -> TeamMessageOut:
    """Post a message (plain text); the other developer is told in-app (never the text)."""
    return await threads.post(db, _factory(request), live.user.id, thread_id, body.body)


@router.post("/{thread_id}/read")
async def mark_read(thread_id: UUID, body: ReadIn, live: Developer, db: Db) -> ReadOut:
    """Mark the thread read up to one of its messages, or up to the newest."""
    return await threads.mark_read(db, live.user.id, thread_id, body.up_to)


@router.post("/{thread_id}/leave", status_code=204, response_class=Response)
async def leave(thread_id: UUID, live: Developer, db: Db) -> None:
    """Leave the thread: it closes for both of you and stays readable."""
    await threads.leave(db, live.user.id, thread_id)


@router.post("/{thread_id}/messages/{message_id}/report", status_code=201)
async def report(thread_id: UUID, message_id: UUID, body: TeamReportIn, live: Developer, db: Db) -> TeamReportOut:
    """Report one message of the thread to the moderators (it stays visible to both of you)."""
    case_id = await threads.report(db, live.user.id, thread_id, message_id, list(body.reasons))
    return TeamReportOut(case_id=case_id)


# ----------------------------------------------------------------------------------------------------------- blocks


@blocks_router.post("", status_code=204, response_class=Response)
async def block(body: BlockIn, live: Developer, db: Db) -> None:
    """Block a developer: pending invitations between you end, open threads close, and neither of you sees the other
    as a peer or can invite the other. Blocking an id that is no developer changes nothing and answers the same."""
    try:
        changed = int(await db.scalar(_BLOCK, {"user": body.user_id}) or 0)
    except DBAPIError as exc:
        await db.rollback()
        if errors.sqlstate(exc) == "22023":
            raise ApiError(422, "cannot_block_yourself", "Block another developer.") from None
        raise
    if changed:
        await audit(
            db,
            "team.blocked",
            actor_user_id=live.user.id,
            subject_type="user",
            subject_id=body.user_id,
            payload={"changed": changed},
        )
    await db.commit()


@blocks_router.delete("/{user_id}", status_code=204, response_class=Response)
async def unblock(user_id: UUID, live: Developer, db: Db) -> None:
    """Lift your block: closed threads and ended invitations stay as they are."""
    deleted = int(await db.scalar(_UNBLOCK, {"user": user_id}) or 0)
    if deleted:
        await audit(db, "team.unblocked", actor_user_id=live.user.id, subject_type="user", subject_id=user_id)
    await db.commit()


@blocks_router.get("")
async def my_blocks(live: Developer, db: Db) -> BlocksOut:
    """The developers you blocked, newest first."""
    rows = (await db.execute(_BLOCKED)).all()
    return BlocksOut(
        blocked=[BlockedOut(user_id=row.user_id, handle=row.handle, blocked_at=row.blocked_at) for row in rows]
    )
