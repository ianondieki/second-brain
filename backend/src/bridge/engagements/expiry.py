"""The tracker's own clock (REQ-ENG-10 part, REQ-ENG-05 expiry; AC-PROP-3; docs/spec/06 6.9): engagements nobody
acts on expire, and holds resume at their date.

``run_expiry`` (job ``engagements.expire``, every 15 minutes; ``bridge.jobs.expiry``) reads the shared clock
(``app_clock_now()``, so the dev/test clock drives it like every deadline) and, for each engagement:

- in ``ORG_INTEREST``, ``SUBMITTED``, ``UNDER_REVIEW`` or ``INTEREST_CONFIRMED`` once ``state_machine.expires_at``
  has passed (policy.yaml ``expire_bd`` business days after the day it entered the stage from the main path, the
  business days a question or a hold paused it added back): the system's ``EXPIRED`` event with the stage's reason
  (``NO_DEV_RESPONSE``, ``NO_REVIEW``, ``NO_DECISION``, ``CONTACT_NOT_MADE``); a tagged engagement's tag closes;
- ``ON_HOLD`` once its resume date has come (Africa/Nairobi): the system's ``resume`` event back to the stage it was
  paused from, the deadline moved by the business days on hold (as a party's early resume);
- ``INFO_REQUESTED`` once its answer-by date (policy.yaml ``info_requested.expire_bd``) has passed: ``EXPIRED``
  (``NO_DEV_RESPONSE``: the developer left the organisation's question unanswered).

Each event is the system's (``actor_role`` system, no user: revision 0003 lets a job bound to a party write it; the
run binds the engagement's developer, always a party) and takes no note. Each is written in its own transaction under
the engagement's row lock, after reading the engagement and the clock again: a run that finds nothing due writes
nothing, and a terminal state never takes a second event (the chain refuses one too), so runs are idempotent. Both
parties are told (``bridge.engagements.notify``, queued in the same transaction).

Finding the engagements: no application role reads every tenant's engagements, so the run asks
``app_engagements_due_for_expiry(now)`` (revision 0007; ids only, a superset of what is due, called with no user
bound) and decides each listed engagement again in a session bound to its developer. An expired tagged engagement's
tag closes as ``expired`` (``app_close_tag(tag, 'expired')``); an organisation's interest has no tag. One
engagement's failure is logged and never stops the run (the next run retries it). The organisation's
responsiveness score is not recomputed here (its data source comes later; P19 card).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.admin.models import Holiday
from bridge.db import bind_tenant
from bridge.engagements import notify
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import local_date
from bridge.engagements.commands import close_tag, returning_deadline
from bridge.engagements.models import Engagement, EngagementEvent
from bridge.engagements.policy import TrackerPolicy, get_policy
from bridge.engagements.service import app_now, entering_event, lock_engagement
from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.models.enums import EngagementActorRole, EngagementState, TagStatus

S = EngagementState
Action = Literal["expire", "resume"]
# Revision 0007: the engagements the clock may act on at a time (ids only; called with no user bound).
_DUE: Final = text("SELECT developer_id, engagement_id FROM app_engagements_due_for_expiry(:now)")


@dataclass(frozen=True, slots=True)
class Outcome:
    engagement_id: UUID
    action: Action | None  # None: nothing was due any more once locked
    state: EngagementState | None = None  # the state it is in after this run (None: the run failed)
    error: bool = False


@dataclass(frozen=True, slots=True)
class Report:
    now: datetime
    outcomes: tuple[Outcome, ...] = ()

    def of(self, engagement_id: UUID) -> Outcome | None:
        return next((o for o in self.outcomes if o.engagement_id == engagement_id), None)


def due_action(
    state: EngagementState,
    now: datetime,
    deadline: datetime | None,
    entered: EngagementEvent | None,
    holidays: Collection[date],
    policy: TrackerPolicy,
) -> Action | None:
    """What the clock does to an engagement in ``state`` at ``now`` (pure): ``resume`` a hold whose resume date (the
    Nairobi date of its deadline) has come, ``expire`` a stage past ``expires_at`` (``entered``: the event that
    entered the stage from the main path, with the deadline it set; ``deadline``: the stage's deadline now), or
    nothing."""
    if state is S.ON_HOLD:
        return "resume" if deadline is not None and local_date(now) >= local_date(deadline) else None
    if state is S.INFO_REQUESTED:  # an unanswered question, past its answer-by date
        return "expire" if deadline is not None and now > deadline else None
    if state not in sm.EXPIRY or entered is None:
        return None
    at = sm.expires_at(
        state,
        local_date(entered.created_at),
        local_date(entered.stage_deadline_at) if entered.stage_deadline_at is not None else None,
        local_date(deadline) if deadline is not None else None,
        holidays,
        policy,
    )
    return "expire" if at is not None and now > at else None


async def _holidays(db: AsyncSession) -> frozenset[date]:
    """Every observed Kenyan holiday: a count may start months back (a stage entered long ago)."""
    return frozenset((await db.scalars(select(Holiday.observed_on).where(Holiday.country == "KE"))).all())


async def _action(
    db: AsyncSession, engagement: Engagement, now: datetime, holidays: Collection[date], policy: TrackerPolicy
) -> Action | None:
    entered = None
    if engagement.state in sm.EXPIRY:
        entered = await entering_event(db, engagement.id, engagement.state, from_main_path=True)
    return due_action(engagement.state, now, engagement.stage_deadline_at, entered, holidays, policy)


def _system_event(
    engagement: Engagement, command: str, to_state: EngagementState, deadline: datetime | None
) -> EngagementEvent:
    return EngagementEvent(
        id=uuid7(),
        engagement_id=engagement.id,
        actor_user_id=None,
        actor_role=EngagementActorRole.SYSTEM,
        command=command,
        from_state=engagement.state,
        to_state=to_state,
        end_reason=sm.expiry_reason(engagement.state) if to_state is S.EXPIRED else None,
        stage_deadline_at=deadline,
        payload={},
    )


async def act_on(
    db: AsyncSession, engagement_id: UUID, *, now: datetime | None, holidays: Collection[date], policy: TrackerPolicy
) -> Outcome:
    """Lock one engagement (the session is bound to its developer), decide again on the shared clock and, when it is
    still due, append the system's event, close an expired engagement's tag and queue both parties' notice. The
    caller commits."""
    engagement = await lock_engagement(db, engagement_id)
    now = now or await app_now(db)
    action = await _action(db, engagement, now, holidays, policy)
    if action is None:
        return Outcome(engagement_id, None, engagement.state)
    if action == "expire":
        event = _system_event(engagement, sm.EXPIRE, S.EXPIRED, None)
    else:
        paused = await entering_event(db, engagement.id, S.ON_HOLD)
        if paused is None or paused.from_state is None:  # every hold has its entering event
            raise RuntimeError("a hold without the event that entered it")
        event = _system_event(
            engagement, sm.Command.RESUME.value, paused.from_state, await returning_deadline(db, engagement, now)
        )
    db.add(event)
    await db.flush()
    await db.refresh(engagement)  # the database projected the event
    if engagement.state is S.EXPIRED:  # revision 0007: a tagged engagement's tag expires with it (AC-PROP-3)
        await close_tag(db, engagement, status=TagStatus.EXPIRED)
    await notify.enqueue(db, engagement, event)
    return Outcome(engagement_id, action, engagement.state)


async def run_expiry(
    factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    user_ids: Sequence[UUID] | None = None,
    policy: TrackerPolicy | None = None,
) -> Report:
    """One pass of ``engagements.expire``: the engagements ``app_engagements_due_for_expiry`` lists at the run's time
    (a superset of what is due, ids only, asked with no user bound), each decided again and acted on in a session bound
    to its developer (``user_ids``: only those developers'). The report holds what the run did: each event written and
    each failure; an engagement listed but not due yet is not reported."""
    log = get_logger(__name__)
    policy = policy or get_policy()
    async with factory() as db:
        clock = now or await app_now(db)
        holidays = await _holidays(db)
        listed = (await db.execute(_DUE, {"now": clock})).tuples().all()
    if user_ids is not None:
        listed = [(developer, engagement) for developer, engagement in listed if developer in set(user_ids)]
    outcomes: list[Outcome] = []
    for developer, engagement_id in listed:
        try:  # one engagement (or its developer's session) never stops the run; the next run retries it
            async with factory() as db:
                await bind_tenant(db, user_id=developer)
                outcome = await act_on(db, engagement_id, now=now, holidays=holidays, policy=policy)
                await db.commit()
        except Exception:
            log.exception("engagements.expiry_failed", engagement_id=str(engagement_id))
            outcome = Outcome(engagement_id, None, None, error=True)
        else:
            if outcome.action is None:
                continue
            log.info("engagements.expiry", engagement_id=str(engagement_id), step=outcome.action)
        outcomes.append(outcome)
    return Report(clock, tuple(outcomes))
