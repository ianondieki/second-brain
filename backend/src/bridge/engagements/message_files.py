"""The thread's files (REQ-ENG-11; revision 0008; ``bridge.engagements.messages`` for the thread itself).

- **Stage.** A party who may post uploads a file (the raw body, ``Content-Type`` on the proposal attachments'
  allow-list with its magic bytes, the name in ``X-File-Name``, up to 20 MB). The row is inserted pending (the
  database decides whether the caller may: the thread's gate and its row-level security), the file is scanned
  (``storage.scanner``) and the verdict recorded: a clean file is stored under ``messages/<engagement>/<attachment>``
  (ids only, never the name) and waits for the uploader's next message; an infected one is never stored, stays marked
  ``infected`` (it can never be sent; its uploader or the purge removes it) and is refused (422, naming its id), with an
  audit event either way. A user holds at most ``STAGED_PER_ENGAGEMENT`` unsent files per engagement, an infected one
  included (so a refused file cannot be retried without bound); makes at most ``UPLOADS_PER_HOUR`` upload attempts per
  engagement in any hour, refused ones included (429 ``too_many_uploads``), and has at most ``UPLOAD_BYTES_PER_DAY``
  scanned per engagement in any 24 hours (429 ``upload_quota``), both counted from those audit events so that removing
  a file frees nothing, each with ``Retry-After``. What needs no body (the gate, the posting role, the type, the
  unsent cap, the limits) is checked before the body is read, and the transaction is ended while it streams in; the
  limits are checked again, with the size, under a per-user lock once it is in.
- **Remove.** The uploader removes a staged file (never a sent one); the row goes first, then its object.
- **Download.** A sent (hence clean) file is read by the parties only: ``attachment_link`` signs a link for the caller
  (HMAC under ``SECRET_KEY`` over the engagement, message, file, user and expiry; ``LINK_TTL``) and
  ``attachment_file`` serves it to the same signed-in person while it is valid, after checking that the bytes still
  hash to the recorded SHA-256.
- **Purge.** ``purge_stale_uploads`` (the hourly job) deletes what ``app_purge_stale_message_uploads`` finds can never
  be sent, then the files.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import unquote, urlencode
from uuid import UUID

from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge import clock
from bridge.audit.models import AuditEvent
from bridge.audit.service import record as audit
from bridge.auth.crypto import keyed_digest
from bridge.config import Settings
from bridge.engagements.message_schemas import AttachmentLinkOut, StagedAttachmentOut, ThreadStatus
from bridge.engagements.messages import CANNOT_POST, NOT_OPEN, READ_ONLY, can_post, gate, refusal
from bridge.engagements.models import MAX_FILE_NAME_CHARS, EngagementMessageAttachment, message_attachment_key
from bridge.engagements.service import Party
from bridge.errors import ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.models.enums import AvStatus
from bridge.proposals.editor import ACCEPTED_TYPES, attachment_problem
from bridge.storage.objects import ObjectNotFoundError, ObjectStore
from bridge.storage.scanner import Scanner, Verdict

STAGED_PER_ENGAGEMENT: Final = 10  # unsent files a user may hold on one engagement (two messages' worth)
UPLOADS_PER_HOUR: Final = 30  # upload attempts a user may make on one engagement in any hour, removed and refused ones
UPLOAD_BYTES_PER_DAY: Final = 200 * 1024 * 1024  # bytes a user may have scanned on one engagement in any 24 hours
HOUR: Final = timedelta(hours=1)
DAY: Final = timedelta(hours=24)
STAGED: Final = "engagement.message_attachment_staged"  # the audit events of an upload, whatever its verdict
REJECTED: Final = "engagement.message_attachment_rejected"
REFUSED: Final = "engagement.message_attachment_refused"  # refused before or without a scan (no file data)
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
LINK_TTL: Final = timedelta(minutes=5)
UPLOADS: Final = "uploads"
LINK_PURPOSE: Final = "message-attachment"


def object_key(engagement_id: UUID, attachment_id: UUID) -> str:
    """The row's own key (revision 0008's CHECK ``object_key_is_its_own``): ids only, never anything the client sent."""
    return message_attachment_key(engagement_id, attachment_id)


def _too_many(code: str, message: str, seconds: int) -> ApiError:
    error = ApiError(429, code, message, retry_after_seconds=seconds)
    error.headers = {"Retry-After": str(seconds)}
    return error


def _wait(at: datetime, window: timedelta, now: datetime) -> int:
    """Whole seconds until ``at`` leaves a window of ``window`` ending ``now`` (at least 1)."""
    return max(1, math.ceil((at + window - now).total_seconds()))


async def check_limits(db: AsyncSession, party: Party, *, size: int) -> None:
    """The caller's upload limits on this engagement, from their upload audit events (which no removal or purge takes
    back; on the database's clock): 429 ``too_many_uploads`` after ``UPLOADS_PER_HOUR`` attempts within the hour
    (refused ones included), 429 ``upload_quota`` when ``size`` more bytes would pass ``UPLOAD_BYTES_PER_DAY``
    scanned within 24 hours; each with ``Retry-After``."""
    e = AuditEvent
    now: datetime = (await db.execute(select(func.now()))).scalar_one()
    rows = (
        await db.execute(
            select(e.action, e.occurred_at, e.payload["size_bytes"].astext)
            .where(
                e.actor_user_id == party.user_id,
                e.subject_type == "engagement",
                e.subject_id == party.engagement_id,
                e.action.in_((STAGED, REJECTED, REFUSED)),
                e.occurred_at > now - DAY,
            )
            .order_by(e.occurred_at)
        )
    ).all()
    hour = [at for _, at, _ in rows if at > now - HOUR]
    if len(hour) >= UPLOADS_PER_HOUR:
        raise _too_many(
            "too_many_uploads",
            f"You have uploaded {UPLOADS_PER_HOUR} files on this engagement in the last hour. Try again later.",
            _wait(hour[0], HOUR, now),
        )
    scanned = [(at, int(n)) for action, at, n in rows if action in (STAGED, REJECTED) and n and n.isdigit()]
    excess = sum(n for _, n in scanned) + max(size, 1) - UPLOAD_BYTES_PER_DAY
    if excess <= 0:
        return
    freed, wait = 0, int(DAY.total_seconds())
    for at, n in scanned:  # the moment enough of the day's bytes have left the window
        freed += n
        if freed >= excess:
            wait = _wait(at, DAY, now)
            break
    raise _too_many(
        "upload_quota",
        f"You have uploaded {UPLOAD_BYTES_PER_DAY // (1024 * 1024)} MB on this engagement in the last day. Try again"
        " later.",
        wait,
    )


async def precheck_upload(db: AsyncSession, party: Party, *, content_type: str) -> None:
    """What an upload must pass before its body is read (the caller then ends the transaction, so nothing is held
    while the file streams in): the thread is open and the caller may post (the database decides again at the
    insert), the type is on the allow-list, fewer than ``STAGED_PER_ENGAGEMENT`` files wait unsent, and the limits
    hold for at least one more byte. The limits come first: a refusal below is recorded and counts toward them, so
    refused attempts stop at the hourly limit too (a 429 is never recorded)."""
    await check_limits(db, party, size=0)
    current = await gate(db, party)  # the organisation before the thread opens: 403 thread_not_open
    if current.status is ThreadStatus.READ_ONLY:
        raise ApiError(409, "thread_read_only", READ_ONLY)
    if current.status is ThreadStatus.NOT_OPEN:
        raise ApiError(409, "thread_not_open", NOT_OPEN)
    if not can_post(party, current.status):
        raise forbidden("cannot_post", CANNOT_POST)
    if content_type not in ACCEPTED_TYPES:
        raise ApiError(422, "unsupported_file", attachment_problem(content_type, b"") or "Attach a supported file.")
    if await _unsent(db, party) >= STAGED_PER_ENGAGEMENT:
        raise _too_many_staged()


async def record_refusal(db: AsyncSession, party: Party, refused: ApiError) -> None:
    """An upload attempt refused with ``refused`` counts toward the hourly limit: its audit event (the refusal's code,
    no file data), committed on a fresh transaction."""
    # Read before the rollback, which expires the session's rows (the caller's user among them).
    user_id, org_id = party.user_id, None if party.is_developer else party.org_id
    await db.rollback()
    code = refused.detail.get("code") if isinstance(refused.detail, dict) else None
    await audit(
        db,
        REFUSED,
        actor_user_id=user_id,
        org_id=org_id,
        subject_type="engagement",
        subject_id=party.engagement_id,
        payload={"code": str(code or "refused")[:64], "status": refused.status_code},
    )
    await db.commit()


async def _unsent(db: AsyncSession, party: Party) -> int:
    a = EngagementMessageAttachment
    found = await db.scalar(
        select(func.count()).where(
            a.engagement_id == party.engagement_id,
            a.uploader_user_id == party.user_id,
            a.message_id.is_(None),  # whatever its verdict: an infected file holds its place until removed or purged
        )
    )
    return int(found or 0)


def _too_many_staged() -> ApiError:
    return ApiError(
        409,
        "too_many_staged",
        f"You have {STAGED_PER_ENGAGEMENT} files waiting to be sent here. Send or remove some first.",
    )


def file_name_of(raw: str | None) -> str:
    """The upload's name from ``X-File-Name`` (percent-encoded UTF-8; ``UnicodeDecodeError`` otherwise): its last
    path segment without control or format characters, at most 255 characters, else ``attachment``."""
    name = unquote(raw or "", errors="strict") if raw else ""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    return name[:MAX_FILE_NAME_CHARS].strip() or "attachment"


async def stage_upload(
    db: AsyncSession,
    store: ObjectStore,
    scanner: Scanner,
    party: Party,
    *,
    data: bytes,
    content_type: str,
    file_name: str,
) -> StagedAttachmentOut:
    """After ``precheck_upload`` and the body: serialise the caller's uploads on the engagement (an advisory lock until
    commit) and check the limits again with the file's size, then insert the upload pending (the database decides
    whether the caller may), scan it and record the verdict: a clean file is stored and staged for the caller's next
    message; an infected one is never stored, stays marked infected and is refused (422, committed with its audit
    event)."""
    await db.execute(_LOCK, {"key": f"engagement_uploads:{party.engagement_id}:{party.user_id}"})
    await check_limits(db, party, size=len(data))
    reason = attachment_problem(content_type, data)
    if reason is not None:
        raise ApiError(422, "unsupported_file", reason)
    a = EngagementMessageAttachment
    attachment_id, digest = uuid7(), hashlib.sha256(data).digest()
    key = object_key(party.engagement_id, attachment_id)
    try:
        await db.execute(
            insert(a).values(
                id=attachment_id,
                engagement_id=party.engagement_id,
                uploader_user_id=party.user_id,
                file_name=file_name,
                content_type=content_type,
                size_bytes=len(data),
                sha256=digest,
                object_key=key,
            )
        )
    except DBAPIError as exc:
        mapped = refusal(exc, party)
        if mapped is None:
            raise
        raise mapped from exc
    if await _unsent(db, party) > STAGED_PER_ENGAGEMENT:  # this one included: a race past the pre-check
        raise _too_many_staged()
    verdict = await scanner.scan(data)
    clean = verdict.verdict is Verdict.CLEAN
    if clean:
        await store.put(UPLOADS, key, data, content_type=content_type)
    status = AvStatus.CLEAN if clean else AvStatus.INFECTED
    await db.execute(
        update(a).where(a.id == attachment_id).values(av_status=status).execution_options(synchronize_session=False)
    )
    await audit(
        db,
        STAGED if clean else REJECTED,
        actor_user_id=party.user_id,
        org_id=None if party.is_developer else party.org_id,
        subject_type="engagement",
        subject_id=party.engagement_id,
        payload={
            "attachment_id": str(attachment_id),
            "size_bytes": len(data),
            "scanner": scanner.name,
            "verdict": verdict.verdict.value,
            "signature": verdict.signature,
        },
    )
    await db.commit()
    if not clean:
        raise ApiError(
            422,
            "attachment_infected",
            "This file did not pass the malware scan, so it was not kept.",
            attachment_id=str(attachment_id),  # the refused upload's record, which its uploader may remove
        )
    return StagedAttachmentOut(
        id=attachment_id,
        file_name=file_name,
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest.hex(),
        av_status=status,
    )


async def remove_staged(db: AsyncSession, store: ObjectStore, party: Party, attachment_id: UUID) -> None:
    """Delete one of the caller's own staged uploads (404 for anything else: a sent file, someone else's). One
    ``DELETE ... RETURNING`` under the caller's RLS, staged rows only: a send of the same file in flight holds its row
    lock, so the delete waits and, once the send commits, matches nothing (404), and the object of the now-sent
    attachment is never touched. The object goes before the row's deletion commits: when the store refuses, the
    deletion rolls back (503 ``storage_unavailable``; the file stays staged and whole, to remove again), so no object
    is left without its row."""
    a = EngagementMessageAttachment
    mine = (
        a.id == attachment_id,
        a.engagement_id == party.engagement_id,
        a.uploader_user_id == party.user_id,
        a.message_id.is_(None),
    )
    deleted = await db.execute(
        delete(a).where(*mine).returning(a.object_key).execution_options(synchronize_session=False)
    )
    key = deleted.scalar_one_or_none()
    if key is None:
        await db.rollback()
        raise not_found("No such file waiting to be sent.")
    try:
        await store.delete(UPLOADS, key)
    except Exception as exc:  # the store's own failure, whatever its type: keep the row, try again later
        await db.rollback()
        get_logger(__name__).warning("message_attachment.object_not_deleted", attachment_id=str(attachment_id))
        raise ApiError(503, "storage_unavailable", "The file could not be removed just now. Try again.") from exc
    await db.commit()


def sign_link(settings: Settings, party: Party, message_id: UUID, attachment_id: UUID, expires: int) -> str:
    value = f"{party.engagement_id}|{message_id}|{attachment_id}|{party.user_id}|{expires}"
    return keyed_digest(settings.secret_key.get_secret_value(), LINK_PURPOSE, value).hex()


async def _sent_file(
    db: AsyncSession, party: Party, message_id: UUID, attachment_id: UUID
) -> EngagementMessageAttachment:
    a = EngagementMessageAttachment
    found: EngagementMessageAttachment | None = await db.scalar(
        select(a).where(
            a.id == attachment_id,
            a.message_id == message_id,
            a.engagement_id == party.engagement_id,
            a.av_status == AvStatus.CLEAN,
        )
    )
    if found is None:
        raise not_found("No such file in this thread.")
    return found


async def attachment_link(
    db: AsyncSession, settings: Settings, party: Party, message_id: UUID, attachment_id: UUID
) -> AttachmentLinkOut:
    """A link to a sent, clean file, signed for the caller and valid for ``LINK_TTL`` (parties only)."""
    await gate(db, party)
    await _sent_file(db, party, message_id, attachment_id)
    expires = int((clock.utcnow() + LINK_TTL).timestamp())
    query = urlencode({"expires": expires, "sig": sign_link(settings, party, message_id, attachment_id, expires)})
    url = f"/api/engagements/{party.engagement_id}/messages/{message_id}/attachments/{attachment_id}/file?{query}"
    return AttachmentLinkOut(url=url, expires_at=datetime.fromtimestamp(expires, tz=UTC))


async def attachment_file(
    db: AsyncSession,
    store: ObjectStore,
    settings: Settings,
    party: Party,
    message_id: UUID,
    attachment_id: UUID,
    *,
    expires: int,
    sig: str,
) -> tuple[EngagementMessageAttachment, bytes]:
    """The file behind a signed link: the caller's own link (403 ``link_invalid``), still valid (403
    ``link_expired``), to a sent, clean file of this thread (404), whose bytes still hash to the recorded SHA-256."""
    await gate(db, party)
    wanted = sign_link(settings, party, message_id, attachment_id, expires)
    if not hmac.compare_digest(wanted, sig):
        raise forbidden("link_invalid", "This download link is not yours or was changed. Open the file again.")
    if expires < clock.utcnow().timestamp():
        raise forbidden("link_expired", "This download link has expired. Open the file again.")
    row = await _sent_file(db, party, message_id, attachment_id)
    try:
        data = await store.get(UPLOADS, row.object_key)
    except ObjectNotFoundError as exc:
        raise not_found("This file is no longer available.") from exc
    if hashlib.sha256(data).digest() != row.sha256:
        raise ApiError(409, "file_changed", "This file does not match what was sent, so it is not served.")
    return row, data


_PURGE = text("SELECT * FROM app_purge_stale_message_uploads(app_clock_now())")


async def purge_stale_uploads(factory: async_sessionmaker[AsyncSession], store: ObjectStore) -> int:
    """Delete the staged uploads that can never be sent (``app_purge_stale_message_uploads``, revision 0008: called
    with no user bound, on the shared clock) and their files. The rows' deletion commits only once every file went
    (deleting a file that is already gone succeeds; a key outside the thread's prefix is never touched): when the
    store refuses any of them the whole run rolls back and the next one retries every key, so no object is left
    without its row. Returns how many uploads went (0 after a rollback)."""
    log = get_logger(__name__)
    async with factory() as db:
        keys = [str(row[0]) for row in (await db.execute(_PURGE)).all()]
        failed = 0
        for key in keys:
            if not key.startswith("messages/"):
                log.warning("message_attachment.purge_key_refused")
                continue
            try:
                await store.delete(UPLOADS, key)
            except Exception:  # the store's own failure, whatever its type: retried with every key next run
                failed += 1
        if failed:
            await db.rollback()
            log.warning("message_attachment.purge_rolled_back", failed=failed, count=len(keys))
            return 0
        await db.commit()
    log.info("message_attachment.purged", count=len(keys))
    return len(keys)
