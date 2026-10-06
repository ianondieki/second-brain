"""Team threads (REQ-DEV-03; D-58; revision 0011's ``team_threads``, ``team_messages``, ``team_thread_reads``): the
engagement thread's rules between two developers (P21), without its contact-details rule.

- **Who.** The thread's two parties, developers (Row-Level Security: anyone else reads nothing and gets 404).
- **List** (``threads``): open threads first, then closed ones, each newest activity first, with the other developer's
  card (``app_developer_card``; null once a block stands), the problem's id and title, the last message's time, the
  unread count and the reason a thread closed as the caller is told it (``shown_reason``): ``left``; ``blocked`` for
  the developer who blocked; ``ended`` for the other one, who is never told they were blocked (the 0011 security
  review's MINOR 1). One statement however many threads.
- **Read** (``page``): the newest 50 messages and a cursor for older ones, as the engagement thread pages.
- **Post** (``post``): append-only plain text, 1 to 4,000 characters (``bridge.teams.text``); a phone number or a link
  posts (no contact rule between developers). One post at a time per thread (an advisory lock, so a message's time
  follows the commit order and a read marker never passes a message not yet committed); at most
  ``teams.posts_per_hour`` per sender and thread in any hour on the database's clock (429 ``too_many_messages`` with
  ``Retry-After``); a closed thread 409 ``thread_closed``. No audit event (a message is the thread's own record); N29
  to the other party, at most once per 30-minute window, after the commit. The text never enters a payload, a log or a
  notice.
- **Read marker** (``mark_read``): moves to a message's time, or to the newest message; never back.
- **Leave** (``leave``): ``app_close_team_thread(thread, 'left')``; read-only for both from then on, for good.
- **Report** (``report``): one message of the thread, by a party who did not write it, through
  ``app_report_team_message`` (the message report reasons; once per reporter and message: a repeat is 409
  ``already_reported``; 10 a day: 429 ``too_many_reports``). Staff read it through the moderation queue only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import and_, func, insert, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge import pagination
from bridge.audit.service import record as audit
from bridge.errors import ApiError, not_found
from bridge.ids import uuid7
from bridge.teams import errors, limits, notices
from bridge.teams.invitations import card
from bridge.teams.models import TEAM_MESSAGE_REPORTS_PER_DAY, TeamMessage, TeamThreadRead
from bridge.teams.policy import get_teams_policy
from bridge.teams.schemas import (
    ReadOut,
    ShownCloseReason,
    TeamMessageOut,
    TeamProblemOut,
    ThreadOut,
    ThreadsOut,
    ThreadSummaryOut,
    UnreadCountOut,
)

PAGE: Final = 50
MAX_PAGE: Final = 100
LIST_LIMIT: Final = 200
NO_MESSAGE: Final = "No such message in this thread."
# [[COPY-REVIEW]]
TOO_MANY: Final = "You have sent {limit} messages in this thread in the last hour. Try again later."

# One row per thread of the caller's (the threads' policy), with everything its summary shows.
_SUMMARY: Final = (
    "SELECT t.id, t.problem_id, t.created_at, t.closed_at, t.closed_reason, o.other_id,"
    " c.user_id AS card_id, c.handle::text AS handle, c.headline, p.title AS problem_title, lm.last_message_at,"
    " (SELECT count(*) FROM team_messages m WHERE m.thread_id = t.id AND m.sender_user_id <> app_user_id()"
    "   AND m.created_at > coalesce((SELECT r.last_read_at FROM team_thread_reads r"
    "     WHERE r.thread_id = t.id AND r.user_id = app_user_id()), '-infinity')) AS unread,"
    " EXISTS (SELECT 1 FROM developer_blocks b WHERE b.blocker_user_id = app_user_id()"
    "   AND b.blocked_user_id = o.other_id) AS i_blocked"
    " FROM team_threads t"
    " CROSS JOIN LATERAL (SELECT CASE WHEN t.a_user_id = app_user_id() THEN t.b_user_id ELSE t.a_user_id END"
    "   AS other_id) o"
    " CROSS JOIN LATERAL (SELECT max(m.created_at) AS last_message_at FROM team_messages m"
    "   WHERE m.thread_id = t.id) lm"
    " LEFT JOIN LATERAL app_developer_card(o.other_id) c ON true"
    " LEFT JOIN problems p ON p.id = t.problem_id"
)
_THREADS: Final = text(
    _SUMMARY + " ORDER BY t.closed_at IS NULL DESC, coalesce(lm.last_message_at, t.created_at) DESC, t.id DESC"
    " LIMIT :limit"
)
_THREAD: Final = text(_SUMMARY + " WHERE t.id = :id")
_UNREAD: Final = text(
    "SELECT count(*) FROM team_messages m"
    " LEFT JOIN team_thread_reads r ON r.thread_id = m.thread_id AND r.user_id = app_user_id()"
    " WHERE m.sender_user_id <> app_user_id() AND (r.last_read_at IS NULL OR m.created_at > r.last_read_at)"
)
_POST_FACTS: Final = text(
    "SELECT t.a_user_id, t.b_user_id, t.closed_at, p.title AS problem_title,"
    " (SELECT handle::text FROM developer_profiles WHERE user_id = app_user_id()) AS handle"
    " FROM team_threads t LEFT JOIN problems p ON p.id = t.problem_id WHERE t.id = :id"
)
_CLOSE: Final = text("SELECT app_close_team_thread(:id, 'left')")
_REPORT: Final = text("SELECT case_id, created FROM app_report_team_message(:message, CAST(:reasons AS text[]))")


def shown_reason(reason: str | None, *, i_blocked: bool) -> ShownCloseReason | None:
    """What the caller is told of why a thread closed: a block is ``blocked`` only for the developer who blocked (while
    the block stands) and ``ended`` for the other, never that they were blocked."""
    if reason is None:
        return None
    if reason == "blocked":
        return "blocked" if i_blocked else "ended"
    return "left"


def summary_out(row: Any) -> ThreadSummaryOut:
    return ThreadSummaryOut(
        id=row.id,
        counterpart=card(row.card_id, row.handle, row.headline),
        problem=TeamProblemOut(id=row.problem_id, title=row.problem_title),
        created_at=row.created_at,
        last_message_at=row.last_message_at,
        unread=int(row.unread),
        open=row.closed_at is None,
        closed_at=row.closed_at,
        closed_reason=shown_reason(row.closed_reason, i_blocked=bool(row.i_blocked)),
    )


async def threads(db: AsyncSession) -> ThreadsOut:
    """The caller's threads (one statement)."""
    rows = (await db.execute(_THREADS, {"limit": LIST_LIMIT})).all()
    return ThreadsOut(threads=[summary_out(row) for row in rows])


async def unread_count(db: AsyncSession) -> UnreadCountOut:
    """Unread messages over all the caller's threads (one statement)."""
    return UnreadCountOut(unread=int(await db.scalar(_UNREAD) or 0))


async def _summary(db: AsyncSession, thread_id: UUID) -> Any:
    row = (await db.execute(_THREAD, {"id": thread_id})).one_or_none()
    if row is None:
        raise errors.not_a_party()
    return row


def message_out(message: Any, me: UUID) -> TeamMessageOut:
    return TeamMessageOut(
        id=message.id,
        mine=message.sender_user_id == me,
        body=message.body,
        redacted=message.redacted_at is not None,
        created_at=message.created_at,
    )


async def page(
    db: AsyncSession, me: UUID, thread_id: UUID, *, limit: int = PAGE, cursor: str | None = None
) -> ThreadOut:
    """One page of the thread, the newest first page; within it oldest first."""
    row = await _summary(db, thread_id)
    after = pagination.decode(cursor)
    m = TeamMessage
    stmt = select(m.id, m.sender_user_id, m.body, m.redacted_at, m.created_at).where(m.thread_id == thread_id)
    if after is not None:
        if after.at is None:  # every message has its moment: this thread never wrote such a cursor
            raise pagination.invalid_cursor()
        stmt = stmt.where(or_(m.created_at < after.at, and_(m.created_at == after.at, m.id < after.id)))
    found = list((await db.execute(stmt.order_by(m.created_at.desc(), m.id.desc()).limit(limit + 1))).all())
    shown = found[:limit]
    next_cursor = pagination.encode(shown[-1].created_at, shown[-1].id) if len(found) > limit else None
    shown.reverse()
    last_read_at = await db.scalar(
        select(TeamThreadRead.last_read_at).where(TeamThreadRead.thread_id == thread_id, TeamThreadRead.user_id == me)
    )
    return ThreadOut(
        thread=summary_out(row),
        can_post=row.closed_at is None,
        last_read_at=last_read_at,
        items=[message_out(message, me) for message in shown],
        next_cursor=next_cursor,
    )


@dataclass(frozen=True, slots=True)
class Posted:
    message: TeamMessageOut
    other_id: UUID
    handle: str
    problem_title: str | None


async def _post(db: AsyncSession, me: UUID, thread_id: UUID, body: str) -> Posted:
    facts = (await db.execute(_POST_FACTS, {"id": thread_id})).one_or_none()
    if facts is None:
        raise errors.not_a_party()
    if facts.closed_at is not None:
        raise errors.thread_closed()
    # One post at a time per thread, until commit: a message's time then follows the commit order.
    await limits.lock(db, f"team_messages:{thread_id}")
    message_id = uuid7()
    try:
        created_at: datetime = (
            await db.execute(
                insert(TeamMessage)
                .values(id=message_id, thread_id=thread_id, sender_user_id=me, body=body)
                .returning(TeamMessage.created_at)
            )
        ).scalar_one()
    except DBAPIError as exc:
        await db.rollback()
        refusal = errors.message_refusal(exc)
        if refusal is None:
            raise
        raise refusal from None
    await _throttle(db, me, thread_id, created_at)
    await db.commit()
    other = facts.b_user_id if facts.a_user_id == me else facts.a_user_id
    message = TeamMessageOut(id=message_id, mine=True, body=body, redacted=False, created_at=created_at)
    return Posted(message, other, str(facts.handle), facts.problem_title)


async def _throttle(db: AsyncSession, me: UUID, thread_id: UUID, created_at: datetime) -> None:
    """429 ``too_many_messages`` (``Retry-After``) when this post is beyond the caller's hourly limit in the thread."""
    limit = get_teams_policy().posts_per_hour
    m = TeamMessage
    window = (m.thread_id == thread_id, m.sender_user_id == me, m.created_at > created_at - timedelta(hours=1))
    count, oldest = (await db.execute(select(func.count(), func.min(m.created_at)).where(*window))).one()
    if int(count) <= limit:
        return
    await db.rollback()
    raise limits.too_many(
        "too_many_messages", TOO_MANY.format(limit=limit), limits.retry_after(oldest, timedelta(hours=1), created_at)
    )


async def post(
    db: AsyncSession, factory: async_sessionmaker[AsyncSession], me: UUID, thread_id: UUID, body: str
) -> TeamMessageOut:
    """Post as the caller (see the module docstring); committed, then N29 to the other party."""
    posted = await _post(db, me, thread_id, body)
    await notices.new_message(
        factory,
        thread_id=thread_id,
        to_user_id=posted.other_id,
        writer_handle=posted.handle,
        problem_title=posted.problem_title,
        written_at=posted.message.created_at,
    )
    return posted.message


async def mark_read(db: AsyncSession, me: UUID, thread_id: UUID, up_to: UUID | None) -> ReadOut:
    """Move the caller's read marker to ``up_to``'s time (a message of the thread; 404 otherwise) or, without it, to
    the newest message committed now; it never moves back, and an empty thread writes nothing. Committed."""
    await _summary(db, thread_id)
    m = TeamMessage
    if up_to is None:
        at = await db.scalar(select(func.max(m.created_at)).where(m.thread_id == thread_id))
    else:
        at = await db.scalar(select(m.created_at).where(m.id == up_to, m.thread_id == thread_id))
        if at is None:
            raise not_found(NO_MESSAGE)
    r = TeamThreadRead
    marked: datetime | None = None
    if at is not None:
        values = pg_insert(r).values(thread_id=thread_id, user_id=me, last_read_at=at)
        upsert = values.on_conflict_do_update(
            index_elements=[r.thread_id, r.user_id],
            set_={"last_read_at": func.greatest(r.last_read_at, values.excluded.last_read_at)},
        ).returning(r.last_read_at)
        marked = (await db.execute(upsert)).scalar_one()
    else:
        marked = await db.scalar(select(r.last_read_at).where(r.thread_id == thread_id, r.user_id == me))
    unread = int((await _summary(db, thread_id)).unread)
    await db.commit()
    return ReadOut(unread=unread, last_read_at=marked)


async def leave(db: AsyncSession, me: UUID, thread_id: UUID) -> None:
    """Close the thread for both with the reason ``left`` (404 for a non-party, 409 when already closed). Committed."""
    try:
        await db.execute(_CLOSE, {"id": thread_id})
    except DBAPIError as exc:
        await db.rollback()
        state = errors.sqlstate(exc)
        if state == "42501":
            raise errors.not_a_party() from None
        if state == "55000":
            raise errors.thread_closed() from None
        raise
    await audit(db, "team.left", actor_user_id=me, subject_type="team_thread", subject_id=thread_id)
    await db.commit()


async def report(db: AsyncSession, me: UUID, thread_id: UUID, message_id: UUID, reasons: list[str]) -> UUID:
    """File the moderation case of the caller's report of one message of the thread; its id. Committed."""
    sender = await db.scalar(
        select(TeamMessage.sender_user_id).where(TeamMessage.id == message_id, TeamMessage.thread_id == thread_id)
    )
    if sender is None:
        raise not_found(NO_MESSAGE)
    if sender == me:
        raise ApiError(409, "own_message", "You cannot report your own message.")
    try:
        row = (await db.execute(_REPORT, {"message": message_id, "reasons": reasons})).one()
    except DBAPIError as exc:
        await db.rollback()
        state = errors.sqlstate(exc)
        if state == "42501":
            raise not_found(NO_MESSAGE) from None
        if state == "54000":
            raise ApiError(
                429,
                "too_many_reports",
                f"You have reported {TEAM_MESSAGE_REPORTS_PER_DAY} team messages in the last day. Try again later.",
            ) from None
        if state == "22023":
            raise ApiError(422, "invalid_reasons", "Choose one or more of the listed reasons.") from None
        raise
    case_id = UUID(str(row.case_id))
    if not row.created:
        await db.rollback()
        raise ApiError(409, "already_reported", "You already reported this message.")
    await audit(
        db,
        "team.message_reported",
        actor_user_id=me,
        subject_type="team_thread",
        subject_id=thread_id,
        payload={"message_id": str(message_id), "case_id": str(case_id), "reasons": sorted(reasons)},
    )
    await db.commit()
    return case_id
