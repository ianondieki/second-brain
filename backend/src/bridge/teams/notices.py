"""N28 and N29 (REQUIREMENTS.md §5; REQ-DEV-03; the P22 card's "Defaults taken" (5)): in-app only, no email.

- **N28**: a developer invited the recipient to team up. Title "Team-up invitation from {handle}", body the problem's
  title, link ``/dev/teams``; once per invitation (dedupe ``n28:<invitation>``).
- **N29**: the recipient's invitation was accepted (title "{handle} accepted: team up on {problem}", link to the new
  thread; once per invitation, ``n29:accepted:<invitation>``), or a new message in a team thread (title "New team
  message from {handle}", link to the thread; at most one per thread and recipient in each 30-minute window of the
  message's time on the database's clock, ``n29:<thread>:<user>:<bucket>``).

Neither carries a note or a message's text (free text a developer typed stays in the thread). Each is written after the
action committed, in a session bound to the recipient (the bell's tables are the user's own under Row-Level Security),
and never raises: a notice never undoes what it tells. Wording is ordinary product copy ([[COPY-REVIEW]]).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.db import bind_tenant
from bridge.logging import get_logger
from bridge.notifications import em2
from bridge.notifications.in_app import MAX_TITLE_CHARS, post_in_app
from bridge.web_paths import DEV_TEAMS, team_thread_path

N28: Final = "team.n28"
N29: Final = "team.n29"
BUCKET_SECONDS: Final = 30 * 60
# [[COPY-REVIEW]] the bell's words.
INVITED_TITLE: Final = "Team-up invitation from {handle}"
ACCEPTED_TITLE: Final = "{handle} accepted: team up on {problem}"
ACCEPTED_BODY: Final = "Your team thread is open. Say hello and plan the work."
MESSAGE_TITLE: Final = "New team message from {handle}"
MESSAGE_BODY: Final = 'On "{problem}". Open the thread to read it.'
SOME_PROBLEM: Final = "a problem"

log = get_logger(__name__)


def bucket(at: datetime) -> int:
    """The 30-minute window of ``at`` (seconds since the epoch, floored)."""
    return int(at.timestamp()) // BUCKET_SECONDS


def message_key(thread_id: UUID, user_id: UUID, at: datetime) -> str:
    return f"n29:{thread_id}:{user_id}:{bucket(at)}"


def fit(template: str, *, handle: str, problem: str = "") -> str:
    """``template`` filled, cut to the bell's 200 characters by shortening the problem's title."""
    handle, problem = em2.one_line(handle), em2.one_line(problem)
    full = template.format(handle=handle, problem=problem)
    if len(full) <= MAX_TITLE_CHARS:
        return full
    room = max(MAX_TITLE_CHARS - len(template.format(handle=handle, problem="")) - 1, 0)
    return template.format(handle=handle, problem=problem[:room] + "…")[:MAX_TITLE_CHARS]


async def _post(
    factory: async_sessionmaker[AsyncSession],
    *,
    user_id: UUID,
    kind: str,
    title: str,
    body: str | None,
    link: str,
    dedupe_key: str,
) -> bool:
    try:
        async with factory() as db:
            await bind_tenant(db, user_id=user_id)
            wrote = await post_in_app(
                db, user_id=user_id, kind=kind, title=title, body=body, link=link, dedupe_key=dedupe_key
            )
            await db.commit()
            return wrote
    except Exception as exc:  # a notice never undoes what it tells
        log.error("teams.notice_failed", kind=kind, user_id=str(user_id), error_type=type(exc).__name__)
        return False


async def invited(
    factory: async_sessionmaker[AsyncSession],
    *,
    invitation_id: UUID,
    to_user_id: UUID,
    sender_handle: str,
    problem_title: str | None,
) -> bool:
    """N28 to the invited developer."""
    return await _post(
        factory,
        user_id=to_user_id,
        kind=N28,
        title=fit(INVITED_TITLE, handle=sender_handle),
        body=em2.one_line(problem_title or SOME_PROBLEM)[:500],
        link=DEV_TEAMS,
        dedupe_key=f"n28:{invitation_id}",
    )


async def accepted(
    factory: async_sessionmaker[AsyncSession],
    *,
    invitation_id: UUID,
    thread_id: UUID,
    sender_id: UUID,
    accepter_handle: str,
    problem_title: str | None,
) -> bool:
    """N29 to the sender of an accepted invitation."""
    return await _post(
        factory,
        user_id=sender_id,
        kind=N29,
        title=fit(ACCEPTED_TITLE, handle=accepter_handle, problem=problem_title or SOME_PROBLEM),
        body=ACCEPTED_BODY,
        link=team_thread_path(thread_id),
        dedupe_key=f"n29:accepted:{invitation_id}",
    )


async def new_message(
    factory: async_sessionmaker[AsyncSession],
    *,
    thread_id: UUID,
    to_user_id: UUID,
    writer_handle: str,
    problem_title: str | None,
    written_at: datetime,
) -> bool:
    """N29 to the other party of a thread, at most once per 30-minute window."""
    return await _post(
        factory,
        user_id=to_user_id,
        kind=N29,
        title=fit(MESSAGE_TITLE, handle=writer_handle),
        body=MESSAGE_BODY.format(problem=em2.one_line(problem_title or SOME_PROBLEM)[:300]),
        link=team_thread_path(thread_id),
        dedupe_key=message_key(thread_id, to_user_id, written_at),
    )
