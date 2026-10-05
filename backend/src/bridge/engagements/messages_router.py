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
  name percent-encoded in ``X-File-Name``; up to 20 MB; scanned; 422 ``attachment_infected``; 30 an hour per
  engagement, 429 ``too_many_uploads`` with ``Retry-After``).
- ``DELETE /api/engagements/{id}/messages/attachments/{attachment_id}``: remove the caller's own staged file.
- ``GET /api/engagements/{id}/messages/{message_id}/attachments/{attachment_id}``: a short-lived link, signed for the
  caller, to a sent file; ``GET .../file?expires=&sig=`` serves it (signed in as the same person).
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from bridge import pagination
from bridge.auth.deps import Db, SettingsDep
from bridge.engagements import message_files, messages
from bridge.engagements.message_schemas import (
    AttachmentLinkOut,
    MessageBody,
    MessageOut,
    MessageThreadOut,
    ReadBody,
    ReadOut,
    ReportBody,
    ReportOut,
    StagedAttachmentOut,
)
from bridge.engagements.models import MAX_MESSAGE_ATTACHMENT_BYTES
from bridge.engagements.router import PREFIX, PartyDep
from bridge.errors import ERROR_RESPONSES, ApiError, ApiErrorBody, json_errors
from bridge.proposals.deps import ScannerDep, StoreDep
from bridge.proposals.editor import ACCEPTED_TYPES

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


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    too_large = ApiError(413, "too_large", "Files can be up to 20 MB.")
    if declared is not None and declared.isdigit() and int(declared) > MAX_MESSAGE_ATTACHMENT_BYTES:
        raise too_large
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_MESSAGE_ATTACHMENT_BYTES:
            raise too_large
        chunks.append(chunk)
    if size == 0:
        raise ApiError(422, "empty_file", "The file is empty.")
    return b"".join(chunks)


@router.post(
    f"{THREAD}/attachments",
    status_code=201,
    responses={413: {"model": ApiErrorBody}, **UNAVAILABLE},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                content_type: {"schema": {"type": "string", "format": "binary"}} for content_type in ACCEPTED_TYPES
            },
        }
    },
)
async def stage_attachment(
    request: Request,
    party: PartyDep,
    db: Db,
    store: StoreDep,
    scanner: ScannerDep,
    x_file_name: Annotated[str | None, Header(max_length=1000, description="Percent-encoded UTF-8 name")] = None,
) -> StagedAttachmentOut:
    """Stage a file for the caller's next message: scanned before it is kept; only the uploader sees it until sent."""
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    try:
        file_name = message_files.file_name_of(x_file_name)
    except UnicodeDecodeError as exc:
        raise ApiError(422, "invalid_file_name", "Send the file name as percent-encoded UTF-8.") from exc
    await message_files.check_upload_rate(db, party)  # before the body is read
    data = await _read_body(request)
    return await message_files.stage_upload(
        db, store, scanner, party, data=data, content_type=content_type, file_name=file_name
    )


@router.delete(f"{THREAD}/attachments/{{attachment_id}}", status_code=204, responses=UNAVAILABLE)
async def remove_staged_attachment(attachment_id: UUID, party: PartyDep, db: Db, store: StoreDep) -> None:
    """Remove one of the caller's staged files (a sent file never goes)."""
    await message_files.remove_staged(db, store, party, attachment_id)


@router.get(f"{THREAD}/{{message_id}}/attachments/{{attachment_id}}")
async def attachment_link(
    message_id: UUID, attachment_id: UUID, party: PartyDep, db: Db, settings: SettingsDep
) -> AttachmentLinkOut:
    """A link to a sent file, signed for the caller and valid for 5 minutes."""
    return await message_files.attachment_link(db, settings, party, message_id, attachment_id)


@router.get(f"{THREAD}/{{message_id}}/attachments/{{attachment_id}}/file", response_class=Response, responses=FILE)
async def attachment_file(
    message_id: UUID,
    attachment_id: UUID,
    party: PartyDep,
    db: Db,
    settings: SettingsDep,
    store: StoreDep,
    expires: Annotated[int, Query(ge=0)],
    sig: Annotated[str, Query(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")],
) -> Response:
    """The file behind a signed link, as a download (never rendered by the browser as a page)."""
    row, data = await message_files.attachment_file(
        db, store, settings, party, message_id, attachment_id, expires=expires, sig=sig
    )
    fallback = "".join(ch if ch.isascii() and ch.isprintable() and ch not in '"\\;' else "_" for ch in row.file_name)
    disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(row.file_name, safe='')}"
    return Response(
        content=data,
        media_type=row.content_type,
        headers={
            "Content-Disposition": disposition,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )
