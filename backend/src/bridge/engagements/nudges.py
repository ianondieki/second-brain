"""The tracker's escalations and reminders, each sent once (REQ-NOT-05, REQ-NOT-03, REQ-ENG-05; P28 track B;
docs/spec/06 6.9 Due rules, 6.10 EM5 and EM6; ``REQUIREMENTS.md`` §5 N05, N07, N12; AC-MAIL-2).

``run_nudges`` (job ``engagements.nudge``, every 15 minutes; ``bridge.jobs.nudges``) reads the shared clock
(``app_clock_now()``: the dev/test clock moves it, as every deadline) and the business days of ``policy.yaml``, and
for each engagement ``app_nudge_candidates()`` lists (revision 0015: ids only, a superset of what is due, to a session
with no user bound) decides what is due now (``due_nudges``, pure):

- ``contact_escalation``: in ``INTEREST_CONFIRMED``, ``escalate_bd`` (3) business days after the stage was entered
  from the main path: the organisation's admins (active owners and admins) and its escalation contact.
- ``contact_overdue``: in ``INTEREST_CONFIRMED``, once the contact-by date (the stage's deadline, moved by holds) has
  passed, once per entry into the stage (a hold placed after the date, resumed to a deadline still past, sends no
  second EM6): EM6, the organisation's version to the named contact and the admins, the developer's to the
  developer; the organisation's tracker then shows the escalation (``escalated_at``). The +10 BD expiry stays the
  expiry job's.
- ``nda_reminder``: in ``NDA_PENDING``, at each of ``remind_bd`` (2, 4): EM5 to each signer who has not signed (the
  developer; the organisation's signatories). Only the latest reminder due is sent (a run after a long gap sends one).
- ``procurement_escalation``: in ``PROCUREMENT_ROUTE`` (a public entity's 3b), ``escalate_bd`` (5) business days in:
  the admins and the escalation contact.
- ``milestone_reminder``: a milestone ``SUBMITTED_FOR_REVIEW`` for ``milestones.reminder_bd`` (3) business days: the
  organisation's reviewers of the engagement (in-app only, N12): the members who may accept a milestone (owner, admin,
  signatory, reviewer) among its assignee, its named contact and those who acted on it; every reviewer when none.
- ``milestone_escalation``: the same milestone at ``milestones.escalation_bd`` (5): the admins and escalation contact.

A count starts on the Nairobi day the stage was entered from the main path (a milestone: its latest submission) and
runs out at the end of its N-th Kenyan business day, plus the business days holds and requests for information moved
the stage's deadline by: the expiry job's arithmetic (``state_machine.paused_business_days``,
``state_machine.after_business_days``); a nudge is due once that moment has passed. An engagement on hold is not a
candidate, so nothing is due while the clock is paused.

Each engagement is decided in its own transaction: bound to its developer (the engagement, its chain, its NDA's
signatures, its milestones), then to ``member_id`` with the organisation (its roster, escalation contact and
assignment: the organisation's own, never read as the developer, D-68), then with no user bound each due nudge is
recorded (``app_record_nudge(engagement, kind, key, state)``, with the state the nudge was decided in: a command a
party committed meanwhile makes it record nothing) and its notification queued in the same transaction only when
that call recorded it (``engagements.nudge_notify``, ``deliver``): a nudge fires once, whatever the runs and retries.
Keys are the job's codes: the stage entry's event seq with the business-day count (``overdue`` for EM6), the
milestone and its submission's seq; never a name, an address or free text. One engagement's failure is logged and
never stops the run (the next run retries it).

``deliver`` tells each recipient in the bell, always, and by email in their own language (``nudge_copy``): EM5 is 🔒
(a signature is needed: ``REQUIREMENTS.md`` N07), the escalations and EM6 follow the person's email preference for the
matrix row's kind (N05, N12: mutable), the milestone review reminder is in-app only (N12). Recipients are read again
when told: someone no longer an active member is skipped. Plain code decides everything here; nothing is worded by a
model.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.models import User
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements import notify
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import local_date
from bridge.engagements.models import (
    Engagement,
    EngagementAssignment,
    EngagementEvent,
    EngagementNudge,
    Milestone,
)
from bridge.engagements.policy import TrackerPolicy, get_policy
from bridge.engagements.service import all_holidays, app_now, entering_event, load
from bridge.jobs.outbox import defer
from bridge.logging import get_logger
from bridge.models.enums import (
    DeliveryStatus,
    EngagementParty,
    EngagementState,
    MembershipStatus,
    MilestoneState,
    NotificationChannel,
    NudgeKind,
    OrgRole,
)
from bridge.notifications import nudge_copy
from bridge.notifications.deliveries import send_email
from bridge.notifications.email import EmailMessage, EmailProvider
from bridge.notifications.in_app import MAX_TITLE_CHARS, post_in_app
from bridge.notifications.preferences import channel_enabled
from bridge.proposals.models import ProposalVersion
from bridge.tenancy.models import Membership, Organization, OrgEscalationContact
from bridge.tenancy.service import membership_of
from bridge.web_paths import engagement_path

S = EngagementState
K = NudgeKind
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
TASK: Final = "engagements.nudge_notify"
QUEUE: Final = notify.QUEUE
_CANDIDATES: Final = text("SELECT engagement_id, org_id, developer_id, member_id FROM app_nudge_candidates()")
_RECORD: Final = text("SELECT app_record_nudge(:engagement, :kind, :key, CAST(:state AS engagement_state))")
# The stages a nudge counts from the main-path entry of (a milestone counts from its submission).
COUNTED: Final = frozenset({S.INTEREST_CONFIRMED, S.NDA_PENDING, S.PROCUREMENT_ROUTE})
# The nudges that flag the organisation's admins: the latest is the tracker's ``escalated_at`` (organisation only).
ESCALATIONS: Final = frozenset(
    {K.CONTACT_ESCALATION, K.CONTACT_OVERDUE, K.PROCUREMENT_ESCALATION, K.MILESTONE_ESCALATION}
)
# The escalations of each stage: ``escalated_at`` reads the current stage's own (3b's procurement escalation is not
# stage 3's once the route is chosen).
STAGE_ESCALATIONS: Final[dict[EngagementState, frozenset[NudgeKind]]] = {
    S.INTEREST_CONFIRMED: frozenset({K.CONTACT_ESCALATION, K.CONTACT_OVERDUE}),
    S.PROCUREMENT_ROUTE: frozenset({K.PROCUREMENT_ESCALATION}),
    S.IN_IMPLEMENTATION: frozenset({K.MILESTONE_ESCALATION}),
}
ADMINS: Final = frozenset({OrgRole.OWNER, OrgRole.ADMIN})
# Who accepts a milestone (state_machine.DECIDERS): the organisation's reviewers of an engagement among its members.
MILESTONE_REVIEWERS: Final = frozenset({OrgRole.OWNER, OrgRole.ADMIN, OrgRole.SIGNATORY, OrgRole.REVIEWER})


@dataclass(frozen=True, slots=True)
class Rule:
    """How a nudge is told: the notification-matrix kind (the bell's kind, the email preference's and the ledger's),
    whether that preference may stop its email, the copy for each side (``nudge_copy``), whether it goes by email."""

    matrix_kind: str
    mutable: bool
    org_copy: str | None
    developer_copy: str | None = None
    email: bool = True
    tag: str = "escalation"


RULES: Final[dict[NudgeKind, Rule]] = {
    K.CONTACT_ESCALATION: Rule("engagement.n05", True, "contact_escalation"),
    # EM6 Contact overdue: REQUIREMENTS.md §5 N05 "EM6: yes" (mutable); docs/spec/06 6.10 does not mark it 🔒.
    K.CONTACT_OVERDUE: Rule("engagement.n05", True, "contact_overdue_org", "contact_overdue_developer", tag="em6"),
    # EM5 Signature needed 🔒 (N07: "🔒 (signature needed)").
    K.NDA_REMINDER: Rule("engagement.n07", False, "nda_reminder_org", "nda_reminder_developer", tag="em5"),
    K.PROCUREMENT_ESCALATION: Rule("engagement.n05", True, "procurement_escalation"),
    K.MILESTONE_REMINDER: Rule("engagement.n12", True, "milestone_reminder", email=False),  # N12: in-app + EM7 line
    K.MILESTONE_ESCALATION: Rule("engagement.n12", True, "milestone_escalation"),
}


# ------------------------------------------------------------------------------------------------- pure rules


@dataclass(frozen=True, slots=True)
class StageClock:
    """An engagement's stage as the counts read it: the event that entered it from the main path (its seq, Nairobi
    date and the deadline it set) and the stage's deadline now (moved by holds)."""

    entered_seq: int
    entered_on: date
    entered_due_on: date | None
    deadline: datetime | None


@dataclass(frozen=True, slots=True)
class Submission:
    """A milestone waiting for review: its id and number, and its latest submission (event seq, Nairobi date)."""

    milestone_id: UUID
    seq: int
    event_seq: int
    submitted_on: date


@dataclass(frozen=True, slots=True)
class Due:
    """A nudge due now: its kind, its key (once per engagement, kind and key) and what its notice says."""

    kind: NudgeKind
    key: str
    days: int | None = None  # the business days counted
    on: date | None = None  # the date it names: the contact-by date, the stage's due date
    expires: date | None = None  # EM6: when the engagement expires if first contact is not made
    milestone: Submission | None = None


def counted_out(entered_on: date, days: int, paused: int, now: datetime, holidays: Collection[date]) -> bool:
    """Whether a count of ``days`` business days from ``entered_on``, ``paused`` business days added back, has run
    out at ``now`` (the expiry job's rule: past the end of that business day)."""
    return now > sm.after_business_days(entered_on, days, paused, holidays)


def due_nudges(
    state: EngagementState,
    now: datetime,
    clock: StageClock | None,
    submissions: Sequence[Submission],
    holidays: Collection[date],
    policy: TrackerPolicy,
) -> list[Due]:
    """What is due for an engagement in ``state`` at ``now`` (see the module docstring), in a stable order."""
    found: list[Due] = []
    if clock is not None and state in COUNTED:
        due_on = local_date(clock.deadline) if clock.deadline is not None else None
        paused = sm.paused_business_days(clock.entered_due_on, due_on, holidays)
        stage = policy.stage(state)
        entry = f"e{clock.entered_seq}"
        escalate = stage.escalate_bd
        if state is S.INTEREST_CONFIRMED:
            if escalate is not None and counted_out(clock.entered_on, escalate, paused, now, holidays):
                found.append(Due(K.CONTACT_ESCALATION, f"{entry}:bd{escalate}", days=escalate, on=due_on))
            if clock.deadline is not None and due_on is not None and now > clock.deadline:
                expires = sm.expires_at(state, clock.entered_on, clock.entered_due_on, due_on, holidays, policy)
                found.append(
                    Due(
                        K.CONTACT_OVERDUE,
                        f"{entry}:overdue",  # once per stage entry, whatever a hold moves the date to
                        on=due_on,
                        expires=local_date(expires) if expires is not None else None,
                    )
                )
        elif state is S.NDA_PENDING:
            passed = [n for n in stage.remind_bd if counted_out(clock.entered_on, n, paused, now, holidays)]
            if passed:  # only the latest reminder due: a run after a long gap sends one
                found.append(Due(K.NDA_REMINDER, f"{entry}:bd{max(passed)}", days=max(passed), on=due_on))
        elif escalate is not None and counted_out(clock.entered_on, escalate, paused, now, holidays):  # 3b
            found.append(Due(K.PROCUREMENT_ESCALATION, f"{entry}:bd{escalate}", days=escalate, on=due_on))
    if state is S.IN_IMPLEMENTATION:
        for waiting in submissions:
            key = f"{waiting.milestone_id}:e{waiting.event_seq}"
            for kind, days in (
                (K.MILESTONE_REMINDER, policy.milestone_reminder_bd),
                (K.MILESTONE_ESCALATION, policy.milestone_escalation_bd),
            ):
                if counted_out(waiting.submitted_on, days, 0, now, holidays):
                    found.append(Due(kind, key, days=days, milestone=waiting))
    return found


@dataclass(frozen=True, slots=True)
class Roster:
    """The organisation's side of one engagement, read by a member (never the engagement's developer): its active
    members by role, its escalation contact and named contact while active members, and the members on the
    engagement (its assignee, named contact and those who acted on it)."""

    roles: dict[UUID, frozenset[OrgRole]] = field(default_factory=dict)
    escalation_contact: UUID | None = None
    contact: UUID | None = None
    on_engagement: frozenset[UUID] = frozenset()

    def holding(self, wanted: Collection[OrgRole]) -> set[UUID]:
        return {user for user, roles in self.roles.items() if roles & set(wanted)}

    def admins(self) -> set[UUID]:
        """The admins and the escalation contact: who hears an escalation."""
        return self.holding(ADMINS) | ({self.escalation_contact} if self.escalation_contact else set())


def recipients(due: Due, roster: Roster, *, signed: Collection[EngagementParty] = ()) -> tuple[list[UUID], bool]:
    """(the organisation's people to tell, whether to tell the developer) for one nudge (see the module docstring).
    The roster never holds the engagement's developer."""
    developer = False
    if due.kind is K.CONTACT_OVERDUE:
        people = roster.holding(ADMINS) | ({roster.contact} if roster.contact else set())
        developer = True
    elif due.kind is K.NDA_REMINDER:
        people = roster.holding({OrgRole.SIGNATORY}) if ORG not in signed else set()
        developer = DEV not in signed
    elif due.kind is K.MILESTONE_REMINDER:
        reviewers = roster.holding(MILESTONE_REVIEWERS)
        people = (reviewers & roster.on_engagement) or roster.holding({OrgRole.REVIEWER}) or reviewers
    else:
        people = roster.admins()
    return sorted(people), developer


# ------------------------------------------------------------------------------------------------ the job


@dataclass(frozen=True, slots=True)
class Sent:
    engagement_id: UUID
    kind: NudgeKind
    key: str
    org_recipients: int
    developer: bool


@dataclass(frozen=True, slots=True)
class NudgeReport:
    now: datetime
    sent: tuple[Sent, ...] = ()
    failed: tuple[UUID, ...] = ()

    def of(self, engagement_id: UUID) -> list[Sent]:
        return [s for s in self.sent if s.engagement_id == engagement_id]


async def stage_clock(db: AsyncSession, engagement: Engagement) -> StageClock | None:
    """The engagement's stage as the counts read it (``StageClock``), or None without its entering event."""
    entered = await entering_event(db, engagement.id, engagement.state, from_main_path=True)
    if entered is None:
        return None
    return StageClock(
        entered_seq=entered.seq,
        entered_on=local_date(entered.created_at),
        entered_due_on=local_date(entered.stage_deadline_at) if entered.stage_deadline_at is not None else None,
        deadline=engagement.stage_deadline_at,
    )


async def submissions_of(db: AsyncSession, engagement_id: UUID) -> list[Submission]:
    """The milestones waiting for review, each with its latest submission (the chain records every one)."""
    waiting = list(
        (
            await db.execute(
                select(Milestone).where(
                    Milestone.engagement_id == engagement_id,
                    Milestone.state == MilestoneState.SUBMITTED_FOR_REVIEW,
                )
            )
        ).scalars()
    )
    if not waiting:
        return []
    milestone_id = EngagementEvent.payload["milestone_id"].astext
    rows = await db.execute(
        select(milestone_id, func.max(EngagementEvent.seq), func.max(EngagementEvent.created_at))
        .where(
            EngagementEvent.engagement_id == engagement_id,
            EngagementEvent.command == sm.Command.SUBMIT_MILESTONE.value,
            milestone_id.in_([str(m.id) for m in waiting]),
        )
        .group_by(milestone_id)
    )
    by_id = {str(m.id): m for m in waiting}
    return [
        Submission(by_id[key].id, by_id[key].seq, int(seq), local_date(at))
        for key, seq, at in rows.tuples()
        if key in by_id
    ]


async def roster_of(db: AsyncSession, engagement: Engagement) -> Roster:
    """The organisation's side (``Roster``), read in a session bound to one of its members and the organisation."""
    rows = await db.execute(
        select(Membership.user_id, Membership.roles).where(
            Membership.org_id == engagement.org_id, Membership.status == MembershipStatus.ACTIVE
        )
    )
    roles = {
        user: frozenset(OrgRole(r) for r in held)
        for user, held in rows.tuples()
        if user != engagement.developer_id  # D-68: never the engagement's own developer
    }
    escalation = await db.scalar(
        select(OrgEscalationContact.user_id).where(OrgEscalationContact.org_id == engagement.org_id)
    )
    assignee = await db.scalar(
        select(EngagementAssignment.assignee_user_id).where(
            EngagementAssignment.engagement_id == engagement.id, EngagementAssignment.unassigned_at.is_(None)
        )
    )
    on = set(await notify.org_people(db, engagement)) | ({assignee} if assignee else set())
    return Roster(
        roles=roles,
        escalation_contact=escalation if escalation in roles else None,
        contact=engagement.contact_user_id if engagement.contact_user_id in roles else None,
        on_engagement=frozenset(user for user in on if user in roles),
    )


def _args(engagement: Engagement, due: Due, people: Iterable[UUID], developer: bool) -> dict[str, Any]:
    """The notification job's arguments: ids, codes, counts and dates only."""
    return {
        "engagement_id": str(engagement.id),
        "developer_id": str(engagement.developer_id),
        "kind": due.kind.value,
        "key": due.key,
        "org_recipients": [str(user) for user in people],
        "developer": developer,
        "days": due.days,
        "on": due.on.isoformat() if due.on else None,
        "expires": due.expires.isoformat() if due.expires else None,
        "seq": due.milestone.seq if due.milestone else None,
    }


async def nudge_one(
    db: AsyncSession,
    *,
    engagement_id: UUID,
    developer_id: UUID,
    member_id: UUID | None,
    now: datetime,
    holidays: Collection[date],
    policy: TrackerPolicy,
) -> list[Sent]:
    """Decide one engagement's nudges and record and queue each due one (see the module docstring). The caller
    commits."""
    await bind_tenant(db, user_id=developer_id)
    engagement = await db.get(Engagement, engagement_id, populate_existing=True)
    if engagement is None or engagement.ended_at is not None or engagement.developer_id != developer_id:
        return []
    clock = await stage_clock(db, engagement) if engagement.state in COUNTED else None
    waiting = await submissions_of(db, engagement.id) if engagement.state is S.IN_IMPLEMENTATION else []
    due = due_nudges(engagement.state, now, clock, waiting, holidays, policy)
    if not due:
        return []
    signed: frozenset[EngagementParty] = frozenset()
    if any(d.kind is K.NDA_REMINDER for d in due):
        signed = (await load(db, engagement, deals_enabled=True)).facts.signed
    roster = Roster()
    if member_id is not None:
        await bind_tenant(db, user_id=member_id, org_id=engagement.org_id)
        roster = await roster_of(db, engagement)
    await bind_tenant(db, user_id=None)  # the ledger is the job's only, with no user bound
    sent: list[Sent] = []
    for nudge in due:
        people, developer = recipients(nudge, roster, signed=signed)
        params = {
            "engagement": engagement.id,
            "kind": nudge.kind.value,
            "key": nudge.key,
            "state": engagement.state.value,  # the state it was decided in
        }
        if not (await db.execute(_RECORD, params)).scalar_one():
            continue  # already sent, or the engagement ended or moved on meanwhile
        if people or developer:
            args = _args(engagement, nudge, people, developer)
            await defer(db, TASK, args, queue=QUEUE, lock=f"engagement:{engagement.id}")
        sent.append(Sent(engagement.id, nudge.kind, nudge.key, len(people), developer))
    return sent


async def run_nudges(
    factory: async_sessionmaker[AsyncSession],
    *,
    now: datetime | None = None,
    engagement_ids: Collection[UUID] | None = None,
    policy: TrackerPolicy | None = None,
) -> NudgeReport:
    """One pass of ``engagements.nudge``: every candidate decided on the shared clock (``now``: a test's), each in its
    own transaction (``engagement_ids``: only those). The report lists each nudge recorded and each failure."""
    log = get_logger(__name__)
    policy = policy or get_policy()
    async with factory() as db:
        clock = now or await app_now(db)
        holidays = await all_holidays(db)
        listed = (await db.execute(_CANDIDATES)).all()
    sent: list[Sent] = []
    failed: list[UUID] = []
    for row in listed:
        if engagement_ids is not None and row.engagement_id not in engagement_ids:
            continue
        try:  # one engagement never stops the run; the next run retries it
            async with factory() as db:
                found = await nudge_one(
                    db,
                    engagement_id=row.engagement_id,
                    developer_id=row.developer_id,
                    member_id=row.member_id,
                    now=clock,
                    holidays=holidays,
                    policy=policy,
                )
                await db.commit()
        except Exception:
            log.exception("engagements.nudge_failed", engagement_id=str(row.engagement_id))
            failed.append(row.engagement_id)
            continue
        for item in found:
            log.info("engagements.nudge", engagement_id=str(item.engagement_id), kind=item.kind.value)
        sent.extend(found)
    return NudgeReport(clock, tuple(sent), tuple(failed))


# ------------------------------------------------------------------------------------------ telling people


def dedupe_key(channel: str, engagement_id: UUID, kind: NudgeKind, key: str, user_id: UUID) -> str:
    """One notice per channel, nudge and recipient (at most 200 characters: the job's keys are short codes)."""
    return f"nudge-{channel}:{engagement_id}:{kind.value}:{key}:{user_id}"


@dataclass(frozen=True, slots=True)
class Telling:
    """One nudge's notice to one person: who, which side, and the facts it states."""

    engagement_id: UUID
    kind: NudgeKind
    key: str
    party: EngagementParty
    values: nudge_copy.Values


async def tell(
    db: AsyncSession, provider: EmailProvider, settings: Settings, telling: Telling, user_id: UUID, org_id: UUID | None
) -> bool:
    """The bell (always) and the email (``Rule``) of one nudge to ``user_id``, in their language, once each, on a
    session bound to them. False while the email is still queued after transient errors (retry)."""
    rule = RULES[telling.kind]
    name = rule.developer_copy if telling.party is DEV else rule.org_copy
    user = await db.get(User, user_id)
    if name is None or user is None:
        return True
    locale = nudge_copy.locale_of(user.locale)
    words = nudge_copy.wording(name, locale, telling.values)
    path = engagement_path(telling.party, telling.engagement_id)
    await post_in_app(
        db,
        user_id=user_id,
        org_id=org_id,
        kind=rule.matrix_kind,
        title=words.title[:MAX_TITLE_CHARS],
        body=words.body,
        link=path,
        dedupe_key=dedupe_key("inapp", telling.engagement_id, telling.kind, telling.key, user_id),
    )
    if not rule.email or user.email_verified_at is None:
        return True
    if rule.mutable and not await channel_enabled(db, user_id, rule.matrix_kind, NotificationChannel.EMAIL):
        return True
    rendered = nudge_copy.render(
        words,
        locale,
        engagement_id=telling.engagement_id,
        path=path,
        base_url=settings.public_base_url,
        product=settings.product_name,
    )
    message = EmailMessage(
        to=user.email, subject=rendered.subject, text=rendered.text, html=rendered.html, tag=rule.tag
    )
    delivery = await send_email(
        db,
        provider,
        message=message,
        kind=rule.matrix_kind,
        user_id=user_id,
        dedupe_key=dedupe_key("email", telling.engagement_id, telling.kind, telling.key, user_id),
    )
    return delivery.status is not DeliveryStatus.QUEUED


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


async def deliver(
    factory: async_sessionmaker[AsyncSession],
    provider: EmailProvider,
    settings: Settings,
    *,
    engagement_id: UUID,
    developer_id: UUID,
    kind: str,
    key: str,
    org_recipients: Sequence[str],
    developer: bool,
    days: int | None = None,
    on: str | None = None,
    expires: str | None = None,
    seq: int | None = None,
) -> bool:
    """Tell one recorded nudge's recipients (idempotent: dedupe keys). Returns False when an email is still queued."""
    nudge = NudgeKind(kind)
    async with factory() as db:
        await bind_tenant(db, user_id=developer_id)
        engagement = await db.get(Engagement, engagement_id)
        if engagement is None or engagement.developer_id != developer_id:
            get_logger(__name__).warning("engagement.nudge_skipped", engagement_id=str(engagement_id))
            return True
        org = await db.get(Organization, engagement.org_id)
        version = await db.get(ProposalVersion, engagement.version_id)
        values = nudge_copy.Values(
            org=org.legal_name if org is not None else "The organisation",
            title=(version.title if version is not None else None) or "your proposal",
            on=_date(on),
            days=days,
            expires=_date(expires),
            seq=seq,
        )
        done = True
        if developer:
            telling = Telling(engagement.id, nudge, key, DEV, values)
            done = await tell(db, provider, settings, telling, developer_id, None)
        await db.commit()
    for raw in org_recipients:
        user_id = UUID(raw)
        if user_id == engagement.developer_id:  # D-68: never the developer as the organisation's
            continue
        async with factory() as db:
            await bind_tenant(db, user_id=user_id, org_id=engagement.org_id)
            if await membership_of(db, engagement.org_id, user_id) is None:
                continue  # no longer a member: nothing to tell them
            telling = Telling(engagement.id, nudge, key, ORG, values)
            done = await tell(db, provider, settings, telling, user_id, engagement.org_id) and done
            await db.commit()
    return done


async def escalated_at(db: AsyncSession, engagement: Engagement, stage: EngagementState | None) -> datetime | None:
    """The latest escalation sent about the engagement's current stage (``stage``: the state, or the stage a side
    state returns to), read by a member of its organisation (the ledger is never the developer's): one of that stage's
    own kinds (``STAGE_ESCALATIONS``), sent since the stage was entered from the main path; None without one."""
    if stage is None or stage not in STAGE_ESCALATIONS:
        return None
    kinds = STAGE_ESCALATIONS[stage]
    entered = await entering_event(db, engagement.id, stage, from_main_path=True)
    query = select(func.max(EngagementNudge.sent_at)).where(
        EngagementNudge.engagement_id == engagement.id,
        EngagementNudge.kind.in_(sorted(kind.value for kind in kinds)),
    )
    if entered is not None:
        query = query.where(EngagementNudge.sent_at >= entered.created_at)
    found: datetime | None = await db.scalar(query)
    return found
