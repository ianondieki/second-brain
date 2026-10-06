"""Team-up invitations (REQ-DEV-03; D-58; revision 0011's ``team_invitations``).

- **Send** (``create``): a developer who turned Peers on (403 ``peers_off`` otherwise: their own state) invites a
  peer or a counterpart (``app_is_visible_peer``) to team up on a published problem or a public, published Brief
  (``app_team_problem_open``), with an optional note (``bridge.teams.text``: the contact-details rule does not apply
  between developers). The database refuses the rest: a problem not open to teams 404 ``problem_unavailable``; a
  recipient who is not the sender's peer or counterpart, who turned Peers off, who blocked the sender or whom the
  sender blocked, or an unknown id, all the same 404 ``peer_unavailable`` (nothing tells a block apart); a pending
  invitation between the two on the same problem, either way, 409 ``already_invited``. At most
  ``teams.invitations_per_day`` in any 24 hours per sender, withdrawn and refused ones included (429
  ``too_many_invitations``), counted under the sender's advisory lock on the database's clock. Audited
  ``team.invited`` (ids only, never the note); N28 to the recipient after the commit.
- **List** (``pending``): the caller's pending invitations, received and sent, each with the other developer's card
  (``app_developer_card``) and the problem's id and title, in one statement.
- **Decide** (``decide``): accept or decline by the recipient, withdraw by the sender, through
  ``app_decide_team_invitation`` (404 for a non-party, 403 ``wrong_party``, 409 ``already_decided`` or
  ``invitation_unavailable``). Accepting opens the pair's thread and tells the sender (N29). Audited
  ``team.invitation_decided``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final, Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.audit.service import record as audit
from bridge.errors import ApiError, forbidden
from bridge.ids import uuid7
from bridge.teams import errors, limits, notices
from bridge.teams.policy import get_teams_policy
from bridge.teams.schemas import (
    DeveloperCard,
    InvitationIn,
    InvitationOut,
    InvitationsOut,
    TeamProblemOut,
)

Decision = Literal["accept", "decline", "withdraw"]
LIST_LIMIT: Final = 200
# [[COPY-REVIEW]]
TOO_MANY: Final = "You have sent {limit} team-up invitations in the last day. Try again later."
YOURSELF: Final = "Invite another developer."

_SENDER: Final = text(
    "SELECT app_is_visible_peer(app_user_id()) AS opted_in, app_clock_now() AS now,"
    " (SELECT handle::text FROM developer_profiles WHERE user_id = app_user_id()) AS handle,"
    " (SELECT count(*) FROM team_invitations WHERE from_user_id = app_user_id()"
    "   AND created_at > app_clock_now() - make_interval(hours => 24)) AS sent,"
    " (SELECT min(created_at) FROM team_invitations WHERE from_user_id = app_user_id()"
    "   AND created_at > app_clock_now() - make_interval(hours => 24)) AS oldest"
)
_INSERT: Final = text(
    "INSERT INTO team_invitations (id, from_user_id, to_user_id, problem_id, note)"
    " VALUES (:id, app_user_id(), :to, :problem, :note) RETURNING status, created_at, decided_at"
)
_CARD_AND_TITLE: Final = text(
    "SELECT c.user_id, c.handle::text AS handle, c.headline,"
    " (SELECT p.title FROM problems p WHERE p.id = :problem) AS problem_title"
    " FROM (SELECT 1) AS one LEFT JOIN LATERAL app_developer_card(:user) c ON true"
)
_SELECT: Final = (
    "SELECT i.id, i.from_user_id, i.to_user_id, i.problem_id, i.note, i.status, i.created_at, i.decided_at,"
    " c.user_id AS card_id, c.handle::text AS handle, c.headline, p.title AS problem_title"
    " FROM team_invitations i"
    " LEFT JOIN LATERAL app_developer_card(CASE WHEN i.from_user_id = app_user_id() THEN i.to_user_id"
    "   ELSE i.from_user_id END) c ON true"
    " LEFT JOIN problems p ON p.id = i.problem_id"
)
_PENDING: Final = text(_SELECT + " WHERE i.status = 'pending' ORDER BY i.created_at DESC, i.id DESC LIMIT :limit")
_ONE: Final = text(
    "SELECT i.from_user_id, i.to_user_id, i.problem_id, i.status FROM team_invitations i WHERE i.id = :id"
)
_DECIDE: Final = text("SELECT app_decide_team_invitation(:id, :decision)")
_ACCEPTED_FACTS: Final = text(
    "SELECT (SELECT handle::text FROM developer_profiles WHERE user_id = app_user_id()) AS handle,"
    " (SELECT title FROM problems WHERE id = :problem) AS problem_title"
)


def card(user_id: Any, handle: Any, headline: Any) -> DeveloperCard | None:
    return None if user_id is None else DeveloperCard(user_id=user_id, handle=str(handle), headline=headline)


def invitation_out(row: Any, me: UUID) -> InvitationOut:
    return InvitationOut(
        id=row.id,
        direction="sent" if row.from_user_id == me else "received",
        status=row.status,
        counterpart=card(row.card_id, row.handle, row.headline),
        problem=TeamProblemOut(id=row.problem_id, title=row.problem_title),
        note=row.note,
        created_at=row.created_at,
        decided_at=row.decided_at,
    )


@dataclass(frozen=True, slots=True)
class Sent:
    invitation: InvitationOut
    sender_handle: str


async def create(db: AsyncSession, me: UUID, body: InvitationIn) -> Sent:
    """Insert the caller's invitation (see the module docstring); committed."""
    if body.to_user_id == me:
        raise ApiError(422, "cannot_invite_yourself", YOURSELF)
    policy = get_teams_policy()
    await limits.lock(db, f"team_invitations:{me}")
    sender = (await db.execute(_SENDER)).one()
    if not sender.opted_in:
        raise forbidden("peers_off", errors.PEERS_OFF)
    if int(sender.sent) >= policy.invitations_per_day:
        seconds = limits.retry_after(sender.oldest, timedelta(hours=24), sender.now)
        message = TOO_MANY.format(limit=policy.invitations_per_day)
        raise limits.too_many("too_many_invitations", message, seconds)
    invitation_id = uuid7()
    try:
        inserted = (
            await db.execute(
                _INSERT, {"id": invitation_id, "to": body.to_user_id, "problem": body.problem_id, "note": body.note}
            )
        ).one()
    except DBAPIError as exc:
        await db.rollback()
        refusal = errors.invitation_refusal(exc)
        if refusal is None:
            raise
        raise refusal from None
    shown = (await db.execute(_CARD_AND_TITLE, {"user": body.to_user_id, "problem": body.problem_id})).one()
    await audit(
        db,
        "team.invited",
        actor_user_id=me,
        subject_type="team_invitation",
        subject_id=invitation_id,
        payload={"to_user_id": str(body.to_user_id), "problem_id": str(body.problem_id)},
    )
    await db.commit()
    out = InvitationOut(
        id=invitation_id,
        direction="sent",
        status=inserted.status,
        counterpart=card(shown.user_id, shown.handle, shown.headline),
        problem=TeamProblemOut(id=body.problem_id, title=shown.problem_title),
        note=body.note,
        created_at=inserted.created_at,
        decided_at=inserted.decided_at,
    )
    return Sent(out, str(sender.handle))


async def send(
    db: AsyncSession, factory: async_sessionmaker[AsyncSession], me: UUID, body: InvitationIn
) -> InvitationOut:
    """``create``, then N28 to the recipient."""
    sent = await create(db, me, body)
    await notices.invited(
        factory,
        invitation_id=sent.invitation.id,
        to_user_id=body.to_user_id,
        sender_handle=sent.sender_handle,
        problem_title=sent.invitation.problem.title,
    )
    return sent.invitation


async def pending(db: AsyncSession, me: UUID) -> InvitationsOut:
    """The caller's pending invitations, received and sent, newest first (one statement)."""
    rows = (await db.execute(_PENDING, {"limit": LIST_LIMIT})).all()
    shown = [invitation_out(row, me) for row in rows]
    return InvitationsOut(
        received=[i for i in shown if i.direction == "received"], sent=[i for i in shown if i.direction == "sent"]
    )


async def decide(
    db: AsyncSession, factory: async_sessionmaker[AsyncSession], me: UUID, invitation_id: UUID, decision: Decision
) -> UUID | None:
    """The caller's decision through ``app_decide_team_invitation``; the new thread's id for ``accept``. Committed;
    an accepted invitation's sender is told (N29)."""
    row = (await db.execute(_ONE, {"id": invitation_id})).one_or_none()
    if row is None:
        raise errors.not_a_party()
    try:
        thread_id: UUID | None = await db.scalar(_DECIDE, {"id": invitation_id, "decision": decision})
    except DBAPIError as exc:
        await db.rollback()
        refusal = errors.decision_refusal(exc)
        if refusal is None:
            raise
        raise refusal from None
    payload = {"decision": decision, "thread_id": None if thread_id is None else str(thread_id)}
    await audit(
        db,
        "team.invitation_decided",
        actor_user_id=me,
        subject_type="team_invitation",
        subject_id=invitation_id,
        payload=payload,
    )
    facts = (await db.execute(_ACCEPTED_FACTS, {"problem": row.problem_id})).one() if thread_id else None
    await db.commit()
    if thread_id is not None and facts is not None:
        await notices.accepted(
            factory,
            invitation_id=invitation_id,
            thread_id=thread_id,
            sender_id=row.from_user_id,
            accepter_handle=str(facts.handle),
            problem_title=facts.problem_title,
        )
    return thread_id
