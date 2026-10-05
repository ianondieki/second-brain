"""The engagement thread's API (REQ-ENG-11, AC-TRACK-9, N18; ``bridge.engagements.messages``). Parties only: anyone
else gets 404 (``service.resolve_party``), staff included; the organisation gets 403 ``thread_not_open`` until the
engagement reaches ``INTEREST_CONFIRMED``.

- ``GET /api/engagements/{id}/messages``: a page of the thread (the latest first; ``next_cursor`` for older ones),
  its status, whether the caller may post, the unread count and the caller's read marker.
- ``POST /api/engagements/{id}/messages``: post (201); 403 ``cannot_post`` for a viewer, 409 ``thread_not_open`` /
  ``thread_read_only``, 422 for a blank, over-long or contact-bearing text or an unusable file, 409
  ``attachment_pending``, 429 ``too_many_messages`` with ``Retry-After``.
- ``POST /api/engagements/{id}/messages/read``: move the caller's read marker.
- ``POST /api/engagements/{id}/messages/{message_id}/report``: report one message to the moderators (once; 10 a day).
- ``POST /api/engagements/{id}/messages/attachments``: stage a file (the raw body, its type in ``Content-Type``, its
  name percent-encoded in ``X-File-Name``; up to 20 MB; scanned; 422 ``attachment_infected``).
- ``DELETE /api/engagements/{id}/messages/attachments/{attachment_id}``: remove the caller's own staged file.
- ``GET /api/engagements/{id}/messages/{message_id}/attachments/{attachment_id}``: a short-lived link, signed for the
  caller, to a sent file; ``GET .../file?expires=&sig=`` serves it (signed in as the same person).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query

from bridge import pagination
from bridge.auth.deps import Db
from bridge.engagements import messages
from bridge.engagements.message_schemas import (
    MessageBody,
    MessageOut,
    MessageThreadOut,
    ReadBody,
    ReadOut,
    ReportBody,
    ReportOut,
)
from bridge.engagements.router import PREFIX, PartyDep
from bridge.errors import ERROR_RESPONSES, ApiErrorBody, json_errors

router = APIRouter(tags=["engagements"], responses=ERROR_RESPONSES)
THREAD = f"{PREFIX}/messages"
UNAVAILABLE: dict[int | str, dict[str, Any]] = {503: {"model": ApiErrorBody}}
FILE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
    **json_errors(*ERROR_RESPONSES, 503),
}


@router.get(THREAD)
async def get_thread(
    party: PartyDep,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=messages.MAX_PAGE)] = messages.PAGE,
    cursor: pagination.Cursor = None,
) -> MessageThreadOut:
    """The thread, the latest page first (within a page oldest first). 403 for the organisation before it opens."""
    return await messages.thread(db, party, limit=limit, cursor=cursor)


@router.post(THREAD, status_code=201)
async def post_message(body: MessageBody, party: PartyDep, db: Db) -> MessageOut:
    """Post a message (plain text) with up to 5 staged files; the other side is told (N18, never the text)."""
    return await messages.post_message(db, party, body)


@router.post(f"{THREAD}/read")
async def mark_read(body: ReadBody, party: PartyDep, db: Db) -> ReadOut:
    """Mark the thread read up to one of its messages, or up to now."""
    return await messages.mark_read(db, party, body.up_to)


@router.post(f"{THREAD}/{{message_id}}/report")
async def report_message(message_id: UUID, body: ReportBody, party: PartyDep, db: Db) -> ReportOut:
    """Report one message of the thread to the moderators (it stays visible to the parties)."""
    return await messages.report(db, party, message_id, list(body.reasons))
