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

from collections import defaultdict
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import pagination
from bridge.engagements import state_machine as sm
from bridge.engagements.history import party_names, unread_counts
from bridge.engagements.message_schemas import (
    MessageAttachmentOut,
    MessageOut,
    MessageThreadOut,
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
from bridge.engagements.service import Party
from bridge.errors import ApiError, forbidden, not_found
from bridge.models.enums import AvStatus, EngagementState
from bridge.proposals.editor import ACCEPTED_TYPES

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
