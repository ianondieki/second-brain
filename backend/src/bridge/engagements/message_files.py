"""The thread's files (REQ-ENG-11; revision 0008; ``bridge.engagements.messages`` for the thread itself).

- **Stage.** A party who may post uploads a file (the raw body, ``Content-Type`` on the proposal attachments'
  allow-list with its magic bytes, the name in ``X-File-Name``, up to 20 MB). The row is inserted pending (the
  database decides whether the caller may: the thread's gate and its row-level security), the file is scanned
  (``storage.scanner``) and the verdict recorded: a clean file is stored under ``messages/<engagement>/<attachment>``
  (ids only, never the name) and waits for the uploader's next message; an infected one is never stored, stays marked
  ``infected`` (it can never be sent; its uploader or the purge removes it) and is refused (422, naming its id), with an
  audit event either way. A user holds at most ``STAGED_PER_ENGAGEMENT`` unsent files per engagement, an infected one
  included (so a refused file cannot be retried without bound), and makes at most ``UPLOADS_PER_HOUR`` uploads per
  engagement in any hour, counted from those audit events so that removing a file does not free its place (429
  ``too_many_uploads`` with ``Retry-After``, checked before the body is read).
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
from bridge.engagements.message_schemas import AttachmentLinkOut, StagedAttachmentOut
from bridge.engagements.messages import gate, refusal, retry_after
from bridge.engagements.models import MAX_FILE_NAME_CHARS, EngagementMessageAttachment, message_attachment_key
from bridge.engagements.service import Party
from bridge.errors import ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.models.enums import AvStatus
from bridge.proposals.editor import attachment_problem
from bridge.storage.objects import ObjectNotFoundError, ObjectStore
from bridge.storage.scanner import Scanner, Verdict

STAGED_PER_ENGAGEMENT: Final = 10  # unsent files a user may hold on one engagement (two messages' worth)
UPLOADS_PER_HOUR: Final = 30  # uploads a user may make on one engagement in any hour, removed ones included
STAGED: Final = "engagement.message_attachment_staged"  # the audit events of an upload, whatever its verdict
REJECTED: Final = "engagement.message_attachment_rejected"
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
LINK_TTL: Final = timedelta(minutes=5)
UPLOADS: Final = "uploads"
LINK_PURPOSE: Final = "message-attachment"


def object_key(engagement_id: UUID, attachment_id: UUID) -> str:
    """The row's own key (revision 0008's CHECK ``object_key_is_its_own``): ids only, never anything the client sent."""
    return message_attachment_key(engagement_id, attachment_id)


async def check_upload_rate(db: AsyncSession, party: Party) -> None:
    """429 ``too_many_uploads`` (with ``Retry-After``) once the caller made ``UPLOADS_PER_HOUR`` uploads on this
    engagement within the hour (their staged and rejected audit events, which no removal or purge takes back; on the
    database's clock). Serialises the caller's uploads on the engagement until the upload commits."""
    await db.execute(_LOCK, {"key": f"engagement_uploads:{party.engagement_id}:{party.user_id}"})
    e = AuditEvent
    count, oldest, now = (
        await db.execute(
            select(func.count(), func.min(e.occurred_at), func.now()).where(
                e.actor_user_id == party.user_id,
                e.subject_type == "engagement",
                e.subject_id == party.engagement_id,
                e.action.in_((STAGED, REJECTED)),
                e.occurred_at > func.now() - timedelta(hours=1),
            )
        )
    ).one()
    if int(count) < UPLOADS_PER_HOUR:
        return
    seconds = retry_after(oldest, now)
    error = ApiError(
        429,
        "too_many_uploads",
        f"You have uploaded {UPLOADS_PER_HOUR} files on this engagement in the last hour. Try again later.",
        retry_after_seconds=seconds,
    )
    error.headers = {"Retry-After": str(seconds)}
    raise error


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
    """Insert the upload pending (the database decides whether the caller may), scan it, then record the verdict: a
    clean file is stored and staged for the caller's next message; an infected one is never stored, stays marked
    infected and is refused (422, committed with its audit event)."""
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
    staged = await db.scalar(
        select(func.count()).where(
            a.engagement_id == party.engagement_id,
            a.uploader_user_id == party.user_id,
            a.message_id.is_(None),  # whatever its verdict: an infected file holds its place until removed or purged
        )
    )
    if int(staged or 0) > STAGED_PER_ENGAGEMENT:
        raise ApiError(
            409,
            "too_many_staged",
            f"You have {STAGED_PER_ENGAGEMENT} files waiting to be sent here. Send or remove some first.",
        )
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
    attachment is never touched. Committed before its object goes, so no row is ever left pointing at a missing
    file."""
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
    await db.commit()
    try:
        await store.delete(UPLOADS, key)
    except Exception:  # an unreferenced object (ids only) is harmless; the row is gone
        get_logger(__name__).warning("message_attachment.object_not_deleted", attachment_id=str(attachment_id))


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
    with no user bound, on the shared clock), committed, then their files from the object store (an object that is
    already gone, or a key outside the thread's prefix, is skipped). Returns how many uploads went."""
    async with factory() as db:
        keys = [str(row[0]) for row in (await db.execute(_PURGE)).all()]
        await db.commit()
    log = get_logger(__name__)
    for key in keys:
        if not key.startswith("messages/"):
            log.warning("message_attachment.purge_key_refused")
            continue
        try:
            await store.delete(UPLOADS, key)
        except Exception:  # the row is gone; an unreferenced object (ids only) is harmless and retried by nobody
            log.warning("message_attachment.object_not_deleted")
    log.info("message_attachment.purged", count=len(keys))
    return len(keys)
