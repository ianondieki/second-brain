"""The engagement thread (REQ-ENG-11, AC-TRACK-9, N18; docs/spec/06 6.9 "Messages tab"; revision 0008; D-57).

Parties only (``service.resolve_party``: 404 for anyone else, staff included; 403 ``both_parties`` for a developer who
is also a member of the organisation). Under the caller's RLS throughout.

- **When.** The thread opens once the engagement's chain has entered ``INTEREST_CONFIRMED`` (or ``CONTACT_MADE``,
  the public-entity path) and is read-only once the engagement ends. Writes leave that rule to the database
  (``engagement_thread_open()``, SQLSTATE 55000, read back here: the organisation's 403 ``thread_not_open``, the
  developer's 409, and 409 ``thread_read_only`` for both); reads mirror it (``OPENING_STATES``): before it opens the
  organisation's reads are 403 (AC-TRACK-9), and the developer reads an empty thread saying where it opens.
- **Who posts.** The developer, and the organisation's members who act on the tracker (never a viewer: the database's
  row-level security refuses them, 403 ``cannot_post``); every member reads.
- **What.** Plain text, 1 to 4,000 characters (``message_schemas.MessageBody``); before first contact (the stage, or
  the stage a side state returns to, is in ``state_machine.BEFORE_CONTACT``) no contact details or links, as for the
  side states' notes (every member reads the thread: THREAT_MODEL I). Up to 5 staged uploads, each the caller's own,
  scanned and clean (409 ``attachment_pending`` while a scan is pending, 422 otherwise), join the message in its
  transaction. 60 messages per user per hour per engagement (``POSTS_PER_HOUR``; 429 with ``Retry-After``).
- **Record.** Append-only (the database); each post writes an audit event (ids and counts, never the text) and queues
  N18 (``message_notify``). The text never enters a payload, a log, an audit detail, a notification or an email.
- **Files.** A staged upload (raw body, ``Content-Type`` on the proposal attachments' allow-list, the name in
  ``X-File-Name``, up to 20 MB) is inserted pending, scanned (``storage.scanner``), and given its verdict: a clean
  file is stored under ``messages/<engagement>/<attachment>`` (ids only); an infected one is never stored, stays
  marked ``infected`` (unsendable; the purge job removes it) and is refused (422). A sent file is downloaded by the
  parties only, through a link signed for the caller and valid for ``LINK_TTL``.
- **Report.** ``app_report_message`` (once per reporter and message; 10 a day, SQLSTATE 54000: 429).
- **Unread.** A per-member read marker (``engagement_message_reads``); the thread, the lists and the detail count the
  messages by others after it.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import pagination
from bridge.audit.service import record as audit
from bridge.engagements import message_notify
from bridge.engagements import state_machine as sm
from bridge.engagements.history import party_names, unread_counts
from bridge.engagements.message_schemas import (
    MessageAttachmentOut,
    MessageBody,
    MessageOut,
    MessageThreadOut,
    ReadOut,
    ReportOut,
    ThreadLimits,
    ThreadStatus,
)
from bridge.engagements.models import (
    Engagement,
    EngagementEvent,
    EngagementMessage,
    EngagementMessageAttachment,
    EngagementMessageRead,
)
from bridge.engagements.service import Party, app_now, entering_event
from bridge.errors import ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.models.enums import AvStatus, EngagementState
from bridge.proposals.editor import ACCEPTED_TYPES
from bridge.proposals.sanitise import contact_codes

S = EngagementState
# revision 0008's engagement_thread_open(): the thread opens once the chain has entered one of these.
OPENING_STATES: Final = frozenset({S.INTEREST_CONFIRMED, S.CONTACT_MADE})
POSTS_PER_HOUR: Final = 60  # D-57 / P21 card: per user, per engagement
PAGE: Final = 30
MAX_PAGE: Final = 100
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_REPORT = text("SELECT case_id, created FROM app_report_message(:message, CAST(:reasons AS text[]))")
PENDING: Final = frozenset({AvStatus.PENDING_UPLOAD, AvStatus.PENDING_SCAN})

# [[COPY-REVIEW]] refusals, in the API's words (the web app shows its own).
NOT_OPEN = "The thread opens once the organisation approves to proceed (Approved to proceed)."
READ_ONLY = "This engagement has ended, so its thread is read-only."
CANNOT_POST = "Viewers read the thread; ask a colleague who acts on this engagement to reply."
CONTAINS_CONTACT = "Contact details and links are shared once first contact is made. Remove them from the message."


@dataclass(frozen=True, slots=True)
class Gate:
    engagement: Engagement
    status: ThreadStatus


async def thread_reached(db: AsyncSession, engagement_id: UUID) -> bool:
    """Whether the engagement's chain has entered a state the thread opens at (the database's rule, mirrored)."""
    found = await db.scalar(
        select(EngagementEvent.id)
        .where(EngagementEvent.engagement_id == engagement_id, EngagementEvent.to_state.in_(list(OPENING_STATES)))
        .limit(1)
    )
    return found is not None


async def gate(db: AsyncSession, party: Party) -> Gate:
    """The thread as the caller may read it: the organisation is refused before it opens (403, AC-TRACK-9)."""
    engagement = await db.get(Engagement, party.engagement_id)
    if engagement is None:
        raise not_found()
    reached = await thread_reached(db, engagement.id)
    if not reached and not party.is_developer:
        raise forbidden("thread_not_open", NOT_OPEN)
    if engagement.state in sm.TERMINAL:
        status = ThreadStatus.READ_ONLY
    else:
        status = ThreadStatus.OPEN if reached else ThreadStatus.NOT_OPEN
    return Gate(engagement, status)


def can_post(party: Party, status: ThreadStatus) -> bool:
    return status is ThreadStatus.OPEN and (party.is_developer or bool(party.actor.roles))


def refusal(exc: DBAPIError, party: Party) -> ApiError | None:
    """The API error for the database's refusal of a thread write, or None (a bug: re-raise)."""
    orig = exc.orig
    sqlstate = getattr(orig, "sqlstate", None)
    diag = getattr(orig, "diag", None)
    message = str(getattr(diag, "message_primary", "") or "")
    constraint = str(getattr(diag, "constraint_name", "") or "")
    if sqlstate == "55000":
        if "read-only" in message:
            return ApiError(409, "thread_read_only", READ_ONLY)
        if party.is_developer:
            return ApiError(409, "thread_not_open", NOT_OPEN)
        return forbidden("thread_not_open", NOT_OPEN)
    if sqlstate == "42501":
        if "no engagement of the caller" in message:
            return not_found()
        return forbidden("cannot_post", CANNOT_POST)
    if sqlstate == "54000":
        return ApiError(429, "too_many_reports", "You have reported 10 messages today. Try again tomorrow.")
    if sqlstate == "23514" and constraint.endswith("at_most_5"):
        return ApiError(422, "too_many_attachments", "A message can carry up to 5 files.")
    if sqlstate == "23514" and constraint.endswith("attached_only_when_clean"):
        return ApiError(409, "attachment_pending", "A file is still being scanned. Send it once the scan is done.")
    if sqlstate in ("23514", "23505", "40001", "40P01"):
        return ApiError(409, "conflict", "The thread changed or this step is not possible now. Reload and retry.")
    return None


def _refused(exc: DBAPIError, party: Party) -> ApiError | DBAPIError:
    mapped = refusal(exc, party)
    return exc if mapped is None else mapped


# ------------------------------------------------------------------------------------------------------------- read


async def thread(db: AsyncSession, party: Party, *, limit: int = PAGE, cursor: str | None = None) -> MessageThreadOut:
    """One page of the thread, the latest first page; within it oldest first. 403 for the organisation before the
    thread opens; an empty, not-yet-open thread for the developer."""
    current = await gate(db, party)
    engagement = current.engagement
    after = pagination.decode(cursor)
    m = EngagementMessage
    stmt = select(m).where(m.engagement_id == engagement.id)
    if after is not None:
        if after.at is None:  # every message has its moment: this thread never wrote such a cursor
            raise pagination.invalid_cursor()
        stmt = stmt.where(or_(m.created_at < after.at, and_(m.created_at == after.at, m.id < after.id)))
    rows = list((await db.execute(stmt.order_by(m.created_at.desc(), m.id.desc()).limit(limit + 1))).scalars())
    page = rows[:limit]
    next_cursor = pagination.encode(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    page.reverse()
    files = await _attachments_of(db, [message.id for message in page])
    names = await party_names(
        db, engagement, {message.sender_user_id for message in page}, developer_caller=party.is_developer
    )
    last_read_at = await db.scalar(
        select(EngagementMessageRead.last_read_at).where(
            EngagementMessageRead.engagement_id == engagement.id, EngagementMessageRead.user_id == party.user_id
        )
    )
    unread = (await unread_counts(db, party.user_id, [engagement.id])).get(engagement.id, 0)
    return MessageThreadOut(
        engagement_id=engagement.id,
        status=current.status,
        opens_at_stage=S.INTEREST_CONFIRMED,
        can_post=can_post(party, current.status),
        unread=unread,
        last_read_at=last_read_at,
        limits=ThreadLimits(accepted_types=list(ACCEPTED_TYPES)),
        items=[_out(message, names, files.get(message.id, []), party) for message in page],
        next_cursor=next_cursor,
    )


async def _attachments_of(db: AsyncSession, message_ids: list[UUID]) -> dict[UUID, list[MessageAttachmentOut]]:
    if not message_ids:
        return {}
    a = EngagementMessageAttachment
    rows = await db.execute(
        select(a.id, a.message_id, a.file_name, a.content_type, a.size_bytes)
        .where(a.message_id.in_(message_ids))
        .order_by(a.created_at, a.id)
    )
    found: dict[UUID, list[MessageAttachmentOut]] = defaultdict(list)
    for row in rows:
        found[row.message_id].append(
            MessageAttachmentOut(
                id=row.id, file_name=row.file_name, content_type=row.content_type, size_bytes=row.size_bytes
            )
        )
    return found


def _out(
    message: EngagementMessage, names: dict[UUID, str], files: list[MessageAttachmentOut], party: Party
) -> MessageOut:
    return MessageOut(
        id=message.id,
        sender_party=message.sender_party,
        sender_name=names.get(message.sender_user_id) or "Former member",  # [[COPY-REVIEW]]
        mine=message.sender_user_id == party.user_id,
        body=message.body,
        redacted=message.redacted_at is not None,
        created_at=message.created_at,
        attachments=files,
    )


# ------------------------------------------------------------------------------------------------------------- post


async def post_message(db: AsyncSession, party: Party, body: MessageBody) -> MessageOut:
    """Post as the caller on their side (the database decides whether the thread is open and whether they may post),
    then check the rate and the text, attach the staged uploads, audit and queue N18. Committed."""
    engagement_id, user_id = party.engagement_id, party.user_id
    await db.execute(_LOCK, {"key": f"engagement_messages:{engagement_id}:{user_id}"})  # one post at a time per user
    message_id = uuid7()
    try:
        created_at: datetime = (
            await db.execute(
                insert(EngagementMessage)
                .values(
                    id=message_id,
                    engagement_id=engagement_id,
                    sender_user_id=user_id,
                    sender_party=party.actor.party,
                    body=body.body,
                )
                .returning(EngagementMessage.created_at)
            )
        ).scalar_one()
    except DBAPIError as exc:
        raise _refused(exc, party) from exc
    await _throttle(db, party, created_at)
    engagement = await db.get(Engagement, engagement_id)
    if engagement is None:  # it was visible a moment ago (the insert's check)
        raise not_found()
    await _no_contact_details(db, engagement, body.body)
    files = await _attach(db, party, message_id, body.attachment_ids)
    await audit(
        db,
        "engagement.message_posted",
        actor_user_id=user_id,
        org_id=None if party.is_developer else party.org_id,
        subject_type="engagement",
        subject_id=engagement_id,
        payload={
            "message_id": str(message_id),
            "sender_party": party.actor.party.value,
            "attachments": len(files),
        },
    )
    await message_notify.enqueue(db, engagement, message_id)
    names = await party_names(db, engagement, {user_id}, developer_caller=party.is_developer)
    await db.commit()
    message = EngagementMessage(
        id=message_id,
        engagement_id=engagement_id,
        sender_user_id=user_id,
        sender_party=party.actor.party,
        body=body.body,
        created_at=created_at,
    )
    return _out(message, names, files, party)


def retry_after(oldest: datetime, now: datetime) -> int:
    """Whole seconds until the oldest message of the hour leaves the window (at least 1)."""
    return max(1, math.ceil((oldest + timedelta(hours=1) - now).total_seconds()))


async def _throttle(db: AsyncSession, party: Party, created_at: datetime) -> None:
    """429 ``too_many_messages`` (with ``Retry-After``) when this post is the caller's 61st on the engagement within
    the hour (on the database's clock; posts of one user are serialised by the advisory lock)."""
    m = EngagementMessage
    window = (
        m.engagement_id == party.engagement_id,
        m.sender_user_id == party.user_id,
        m.created_at > created_at - timedelta(hours=1),
    )
    count, oldest = (await db.execute(select(func.count(), func.min(m.created_at)).where(*window))).one()
    if int(count) <= POSTS_PER_HOUR:
        return
    seconds = retry_after(oldest, created_at)
    error = ApiError(
        429,
        "too_many_messages",
        f"You have sent {POSTS_PER_HOUR} messages on this engagement in the last hour. Try again later.",
        retry_after_seconds=seconds,
    )
    error.headers = {"Retry-After": str(seconds)}
    raise error


async def _no_contact_details(db: AsyncSession, engagement: Engagement, body: str) -> None:
    stage = engagement.state
    if stage in sm.RETURNING:
        paused = await entering_event(db, engagement.id, stage)
        stage = paused.from_state if paused is not None and paused.from_state is not None else stage
    if stage in sm.BEFORE_CONTACT and contact_codes(body):
        raise ApiError(422, "contains_contact", CONTAINS_CONTACT)


async def _attach(db: AsyncSession, party: Party, message_id: UUID, ids: list[UUID]) -> list[MessageAttachmentOut]:
    """Join the caller's staged uploads to the message (in its transaction, as revision 0008 requires)."""
    if not ids:
        return []
    a = EngagementMessageAttachment
    mine = (
        a.id.in_(ids),
        a.engagement_id == party.engagement_id,
        a.uploader_user_id == party.user_id,
        a.message_id.is_(None),
    )
    rows = {row.id: row for row in (await db.execute(select(a).where(*mine))).scalars()}
    if len(rows) != len(ids):
        raise ApiError(422, "unknown_attachment", "A file is no longer waiting to be sent. Upload it again.")
    if any(row.av_status in PENDING for row in rows.values()):
        raise ApiError(409, "attachment_pending", "A file is still being scanned. Send it once the scan is done.")
    if any(row.av_status is not AvStatus.CLEAN for row in rows.values()):
        raise ApiError(422, "attachment_infected", "A file did not pass the malware scan, so it cannot be sent.")
    try:
        result = await db.execute(
            update(a).where(*mine).values(message_id=message_id).execution_options(synchronize_session=False)
        )
    except DBAPIError as exc:
        raise _refused(exc, party) from exc
    if int(getattr(result, "rowcount", 0)) != len(ids):
        raise ApiError(409, "conflict", "A file changed while it was being sent. Reload and retry.")
    return [
        MessageAttachmentOut(
            id=row.id, file_name=row.file_name, content_type=row.content_type, size_bytes=row.size_bytes
        )
        for row in (rows[i] for i in ids)
    ]


# ------------------------------------------------------------------------------------------------------- read marker


async def mark_read(db: AsyncSession, party: Party, up_to: UUID | None) -> ReadOut:
    """Move the caller's read marker to ``up_to``'s time (a message of this thread; 404 otherwise) or to now; it
    never moves back. Committed."""
    current = await gate(db, party)
    if up_to is None:
        at = await app_now(db)
    else:
        found = await db.scalar(
            select(EngagementMessage.created_at).where(
                EngagementMessage.id == up_to, EngagementMessage.engagement_id == current.engagement.id
            )
        )
        if found is None:
            raise not_found("No such message in this thread.")
        at = found
    r = EngagementMessageRead
    values = pg_insert(r).values(engagement_id=current.engagement.id, user_id=party.user_id, last_read_at=at)
    upsert = values.on_conflict_do_update(
        index_elements=[r.engagement_id, r.user_id],
        set_={"last_read_at": func.greatest(r.last_read_at, values.excluded.last_read_at)},
    ).returning(r.last_read_at)
    marked: datetime = (await db.execute(upsert)).scalar_one()
    unread = (await unread_counts(db, party.user_id, [current.engagement.id])).get(current.engagement.id, 0)
    await db.commit()
    return ReadOut(unread=unread, last_read_at=marked)


# ----------------------------------------------------------------------------------------------------------- report


async def report(db: AsyncSession, party: Party, message_id: UUID, reasons: list[str]) -> ReportOut:
    """File the one moderation case of the caller's report of a message of this thread (``app_report_message``:
    once per reporter and message, 10 a day). The caller shares that one message with staff. Committed."""
    await gate(db, party)
    sender = await db.scalar(
        select(EngagementMessage.sender_user_id).where(
            EngagementMessage.id == message_id, EngagementMessage.engagement_id == party.engagement_id
        )
    )
    if sender is None:
        raise not_found("No such message in this thread.")
    if sender == party.user_id:
        raise ApiError(409, "own_message", "You cannot report your own message.")
    try:
        row = (await db.execute(_REPORT, {"message": message_id, "reasons": reasons})).one()
    except DBAPIError as exc:
        mapped = refusal(exc, party)
        if mapped is None:
            raise
        raise (not_found("No such message in this thread.") if mapped.status_code == 403 else mapped) from exc
    case_id, created = UUID(str(row.case_id)), bool(row.created)
    if created:
        await audit(
            db,
            "engagement.message_reported",
            actor_user_id=party.user_id,
            org_id=None if party.is_developer else party.org_id,
            subject_type="engagement",
            subject_id=party.engagement_id,
            payload={"message_id": str(message_id), "case_id": str(case_id), "reasons": sorted(reasons)},
        )
    await db.commit()
    return ReportOut(case_id=case_id, created=created)
