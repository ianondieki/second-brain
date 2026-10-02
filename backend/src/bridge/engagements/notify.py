"""The tracker's notifications (REQ-NOT-04 EM2; the prototype's thin part of REQ-NOT-03; REQUIREMENTS.md §5).

Generated from the state machine: a command whose row names a ``notice`` queues one job in the command's own
transaction (``bridge.jobs.outbox``: the job exists if and only if the event committed), and the job tells the other
party. Each recipient's rows are written in a session bound to that recipient (in-app rows are the user's own under
RLS), with a ledger row per recipient and event (``notification_deliveries``, dedupe key ``inapp:<event>:<user>``)
so a retried job never notifies twice. Entering ``INTEREST_CONFIRMED`` also sends EM2 to the developer, exactly once
per engagement (dedupe key ``em2:<engagement>``, AC-MAIL-1), through the configured email provider (Mailpit in dev).

An organisation's interest (stage 0, REQ-ENG-04) is told by its engagement's genesis event: the developer gets N17
in-app and by email (``bridge.notifications.n17``: mutable, default on, once per engagement).

Side states and the system's events (REQ-ENG-10 part): a question and its answer (N03), a hold and an early resume
(N20) tell the other party; the expiry job's events tell both parties (``compose_system``: an expiry under the
matrix row of the stage it ended, N01, N03, N05 or N17, with the reason in words; a hold resumed on its date, N20).
Each of these also goes by email in the fixed status layout (``bridge.notifications.status``: one sentence, one link
to the tracker; mutable per kind; once per event and recipient). A note's text never leaves the tracker.

Recipients: when the organisation acts, the developer; when the developer acts, the organisation's people on this
engagement (its named contact and the members who acted on it, each still an active member). The developer cannot
read the organisation's roster, so an engagement nobody at the organisation has touched yet notifies nobody there;
the organisation's inbox shows it (the full dispatch to role seats, REQ-NOT-03, comes after the prototype).

Wording is fixed product copy ([[COPY-REVIEW]]); a decline's written reason (``OTHER``) is the one free text, passed
in the job's arguments to the developer's notification (it never enters the hash chain).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.models import User
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import NAIROBI
from bridge.engagements.models import Engagement, EngagementEvent
from bridge.ids import uuid7
from bridge.jobs.outbox import defer
from bridge.logging import get_logger
from bridge.models.enums import (
    DeliveryStatus,
    EngagementActorRole,
    EngagementEndReason,
    EngagementParty,
    EngagementState,
    GrantStatus,
    NotificationChannel,
)
from bridge.notifications import em2, n17, status
from bridge.notifications.deliveries import send_email
from bridge.notifications.email import EmailMessage, EmailProvider
from bridge.notifications.models import InAppNotification, NotificationDelivery
from bridge.notifications.preferences import channel_enabled
from bridge.proposals.models import DisclosureGrant, DocumentView, ProposalVersion
from bridge.tenancy.models import Organization
from bridge.tenancy.service import membership_of
from bridge.web_paths import engagement_path

QUEUE: Final = "notifications"
TASK: Final = "engagements.notify"
GENESIS: Final = "create"  # the database's first event of every engagement (revision 0003)
N17_KIND: Final = "engagement.n17"
C = sm.Command
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
DECLINE_LABELS: Final = {  # docs/spec/06 6.9 Codes. [[COPY-REVIEW]]
    EngagementEndReason.NOT_PRIORITY: "not a current priority",
    EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY: "already solved internally",
    EngagementEndReason.BUDGET: "budget",
    EngagementEndReason.NOT_RELEVANT: "not relevant",
    EngagementEndReason.NEEDS_MATURITY: "needs more maturity",
    EngagementEndReason.OTHER: "other",
    EngagementEndReason.BY_DEVELOPER: "declined by the developer",
}
# What the other party reads, by (command, the party that acted). {org} and {title} are filled in. [[COPY-REVIEW]]
SENTENCES: Final[dict[tuple[sm.Command, EngagementParty], str]] = {
    (C.ACCEPT_INTEREST, DEV): 'The developer accepted your interest in "{title}".',
    (C.DECLINE_INTEREST, DEV): 'The developer declined your interest in "{title}".',
    (C.START_REVIEW, ORG): '{org} started reviewing "{title}".',
    (C.DECLINE, ORG): '{org} declined "{title}". Reason: {reason}.',
    (C.APPROVE, ORG): '{org} approved "{title}" to proceed (non-binding). They will contact you shortly.',
    (C.WITHDRAW, DEV): 'The developer withdrew "{title}".',
    (C.MARK_CONTACTED, ORG): '{org} marked first contact on "{title}". Confirm it on your tracker.',
    (C.CONFIRM_CONTACT, DEV): 'The developer confirmed first contact on "{title}".',
    (C.SEND_NDA, DEV): 'The developer sent the mutual NDA for "{title}". It needs your signatory\'s signature.',
    (C.SEND_NDA, ORG): '{org} sent the mutual NDA for "{title}". It needs your signature.',
    (C.SIGN_NDA, DEV): 'The developer signed the mutual NDA for "{title}".',
    (C.SIGN_NDA, ORG): '{org} signed the mutual NDA for "{title}".',
    (C.PROPOSE_TERMS, DEV): 'The developer proposed terms for "{title}".',
    (C.PROPOSE_TERMS, ORG): '{org} proposed terms for "{title}".',
    (
        C.MARK_FINAL,
        DEV,
    ): 'The developer marked the agreement for "{title}" final. It needs your signatory\'s signature.',
    (C.MARK_FINAL, ORG): '{org} marked the agreement for "{title}" final. It needs your signature.',
    (C.REOPEN_NEGOTIATION, DEV): 'The developer reopened the terms of "{title}".',
    (C.REOPEN_NEGOTIATION, ORG): '{org} reopened the terms of "{title}".',
    (C.SIGN_AGREEMENT, DEV): 'The developer signed the agreement for "{title}".',
    (C.SIGN_AGREEMENT, ORG): '{org} signed the agreement for "{title}".',
    (C.SUBMIT_MILESTONE, DEV): 'The developer submitted a milestone of "{title}" for review.',
    (C.ACCEPT_MILESTONE, ORG): '{org} accepted a milestone of "{title}".',
    (C.REQUEST_CHANGES, ORG): '{org} asked for changes to a milestone of "{title}".',
    (C.DELIVER, DEV): 'The developer submitted the final delivery of "{title}".',
    (C.ACCEPT_DELIVERY, ORG): '{org} accepted the delivery of "{title}". They sign the acceptance certificate first.',
    (C.SIGN_CERTIFICATE, DEV): 'The developer countersigned the acceptance certificate for "{title}".',
    (C.SIGN_CERTIFICATE, ORG): '{org} signed the acceptance certificate for "{title}". Countersign it on your tracker.',
    (C.RECORD_PAYMENT, ORG): '{org} recorded the final payment for "{title}". Confirm the amount you received.',
    (C.CONFIRM_PAYMENT, DEV): 'The developer confirmed the final payment for "{title}". The project is closed.',
    (C.REQUEST_INFO, ORG): '{org} asked you a question about "{title}". The review waits for your answer.',
    (C.ANSWER_INFO, DEV): 'The developer answered your question about "{title}". The review clock runs again.',
    (C.CANCEL_REQUEST, ORG): '{org} withdrew its question about "{title}". The review clock runs again.',
    (C.PAUSE, DEV): 'The developer put "{title}" on hold until {until}. Due dates move by the time on hold.',
    (C.PAUSE, ORG): '{org} put "{title}" on hold until {until}. Due dates move by the time on hold.',
    (C.RESUME, DEV): 'The developer resumed "{title}" before its hold ended. Due dates moved by the time on hold.',
    (C.RESUME, ORG): '{org} resumed "{title}" before its hold ended. Due dates moved by the time on hold.',
}
# [[COPY-REVIEW]] why an engagement expired (docs/spec/06 6.9 Codes), in words both parties read.
EXPIRY_LABELS: Final = {
    EngagementEndReason.NO_REVIEW: "nobody started the review in time",
    EngagementEndReason.NO_DECISION: "no decision was made in time",
    EngagementEndReason.CONTACT_NOT_MADE: "first contact was not made in time",
    EngagementEndReason.NO_DEV_RESPONSE: "the interest was not answered in time",
}
# [[COPY-REVIEW]] the system's events, as each party reads them.
EXPIRED_SENTENCES: Final = {
    DEV: 'Your engagement with {org} on "{title}" expired: {reason}.',
    ORG: 'The engagement on "{title}" expired: {reason}.',
}
RESUMED_SENTENCE: Final = '"{title}" is no longer on hold: it resumed on its date. Due dates moved by the time on hold.'
# Party events that also go by email in the status layout (the system's always do).
EMAILED: Final = frozenset({C.REQUEST_INFO, C.ANSWER_INFO, C.CANCEL_REQUEST, C.PAUSE, C.RESUME})
# An expiry's words when the stage it ended reads better than its reason code (an unanswered question).
EXPIRY_LABELS_BY_STATE: Final = {EngagementState.INFO_REQUESTED: "the organisation's question was not answered in time"}
# [[COPY-REVIEW]] the developer's in-app N17, when an organisation expresses interest (stage 0).
INTEREST_SENTENCE: Final = '{org} is interested in "{title}". Accept or decline on your tracker.'
ORG_ROLES: Final = frozenset(
    {
        EngagementActorRole.OWNER,
        EngagementActorRole.ADMIN,
        EngagementActorRole.SIGNATORY,
        EngagementActorRole.REVIEWER,
        EngagementActorRole.FINANCE,
    }
)


def is_interest(event: EngagementEvent) -> bool:
    """The genesis of an engagement an organisation member opened at ORG_INTEREST (stage 0)."""
    return event.command == GENESIS and event.to_state is EngagementState.ORG_INTEREST and event.actor_role in ORG_ROLES


@dataclass(frozen=True, slots=True)
class Notice:
    kind: str
    title: str
    body: str
    link: str


async def enqueue(
    db: AsyncSession, engagement: Engagement, event: EngagementEvent, *, reason_text: str | None = None
) -> int:
    """Queue the notification of ``event`` in the caller's transaction (ids only, and a decline's written reason)."""
    args: dict[str, Any] = {
        "engagement_id": str(engagement.id),
        "event_id": str(event.id),
        "developer_id": str(engagement.developer_id),
    }
    if reason_text:
        args["reason_text"] = reason_text
    return await defer(db, TASK, args, queue=QUEUE, lock=f"engagement:{engagement.id}")


def compose(
    event: EngagementEvent, company: str, title: str, *, reason_text: str | None = None
) -> tuple[EngagementParty, Notice] | None:
    """The party to tell and what to tell them, or None for an event the table does not notify."""
    if is_interest(event):
        body = INTEREST_SENTENCE.format(org=em2.one_line(company), title=em2.one_line(title))
        label = sm.STAGE_LABELS[EngagementState.ORG_INTEREST]
        return DEV, Notice(N17_KIND, label, body, engagement_path(DEV, event.engagement_id))
    try:
        command = sm.Command(event.command)
    except ValueError:  # the genesis ("create") and anything outside the table
        return None
    notice = sm.TABLE[command].notice
    if event.actor_role is EngagementActorRole.SYSTEM:  # the prototype writes no system events; jobs come later
        return None
    acted = DEV if event.actor_role is EngagementActorRole.DEVELOPER else ORG
    sentence = SENTENCES.get((command, acted))
    if notice is None or sentence is None:
        return None
    reason = DECLINE_LABELS.get(event.end_reason, "") if event.end_reason else ""
    payload = dict(event.payload)
    body = sentence.format(
        org=em2.one_line(company), title=em2.one_line(title), reason=reason, until=_until(payload.get("resume_at"))
    )
    if event.end_reason is EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY and "internal_start_date" in payload:
        body += f" They attest the same work was already in progress internally since {payload['internal_start_date']}."
    if reason_text:
        body += f" Their reason: {reason_text}"
    label = sm.STAGE_LABELS.get(event.to_state, event.to_state.value)
    told = sm.other(acted)
    return told, Notice(f"engagement.{notice.lower()}", label, body, engagement_path(told, event.engagement_id))


def _until(resume_at: object) -> str:
    """A hold's resume date as people read it ("20 Oct 2026"), from the pausing event's payload."""
    try:
        return em2.eat_date(date.fromisoformat(str(resume_at)))
    except ValueError:
        return "its resume date"


def compose_system(event: EngagementEvent, company: str, title: str) -> list[tuple[EngagementParty, Notice]]:
    """Both parties' notices of a system event (the expiry job's): an expiry, under the matrix row of the stage it
    ended (``state_machine.EXPIRY_NOTICE``), or a hold resumed on its date (N20). Nothing for anything else."""
    if event.actor_role is not EngagementActorRole.SYSTEM or event.from_state is None:
        return []
    org, name = em2.one_line(company), em2.one_line(title)
    if event.command == sm.EXPIRE and event.end_reason in EXPIRY_LABELS and event.from_state in sm.EXPIRY_NOTICE:
        kind = f"engagement.{sm.EXPIRY_NOTICE[event.from_state].lower()}"
        reason = EXPIRY_LABELS_BY_STATE.get(event.from_state) or EXPIRY_LABELS[event.end_reason]
        label = sm.STAGE_LABELS[EngagementState.EXPIRED]
        return [
            (party, Notice(kind, label, sentence.format(org=org, title=name, reason=reason), _link(party, event)))
            for party, sentence in EXPIRED_SENTENCES.items()
        ]
    if event.command == C.RESUME.value and event.from_state is EngagementState.ON_HOLD:
        kind = f"engagement.{sm.RESUME_NOTICE.lower()}"
        label = sm.STAGE_LABELS.get(event.to_state, event.to_state.value)
        body = RESUMED_SENTENCE.format(title=name)
        return [(party, Notice(kind, label, body, _link(party, event))) for party in (DEV, ORG)]
    return []


def _link(party: EngagementParty, event: EngagementEvent) -> str:
    return engagement_path(party, event.engagement_id)


def emailed(event: EngagementEvent) -> bool:
    """Whether the event's notices also go by email in the status layout."""
    return event.actor_role is EngagementActorRole.SYSTEM or event.command in EMAILED


async def _send_status(
    db: AsyncSession,
    provider: EmailProvider,
    settings: Settings,
    *,
    user_id: UUID,
    notice: Notice,
    event: EngagementEvent,
    title: str,
) -> bool:
    """The status email of ``notice`` to ``user_id`` (the session is bound to them), once per event, when their
    preference for the kind allows it; False while the send is still queued after transient errors."""
    user = await db.get(User, user_id)
    if user is None or user.email_verified_at is None:
        get_logger(__name__).warning("status_email.skipped", event_id=str(event.id), user_id=str(user_id))
        return True
    if not await channel_enabled(db, user.id, notice.kind, NotificationChannel.EMAIL):
        return True
    rendered = status.render(
        status.StatusFacts(
            engagement_id=event.engagement_id,
            label=notice.title,
            title=title,
            sentence=notice.body,
            path=notice.link,
            base_url=settings.public_base_url,
            product=settings.product_name,
        )
    )
    message = EmailMessage(
        to=user.email, subject=rendered.subject, text=rendered.text, html=rendered.html, tag=notice.kind
    )
    delivery = await send_email(
        db,
        provider,
        message=message,
        kind=notice.kind,
        user_id=user.id,
        dedupe_key=status.dedupe_key(event.id, user.id),
    )
    return delivery.status is not DeliveryStatus.QUEUED


async def _in_app(db: AsyncSession, user_id: UUID, org_id: UUID | None, notice: Notice, event_id: UUID) -> bool:
    """One in-app notification for ``user_id`` (the session is bound to them), once per event."""
    key = f"inapp:{event_id}:{user_id}"
    if await db.scalar(select(NotificationDelivery.id).where(NotificationDelivery.dedupe_key == key)) is not None:
        return False
    db.add(
        NotificationDelivery(
            id=uuid7(),
            user_id=user_id,
            kind=notice.kind[:40],
            channel=NotificationChannel.IN_APP,
            to_address="in-app",
            dedupe_key=key,
            status=DeliveryStatus.SENT,
            attempts=1,
            provider="in_app",
            sent_at=datetime.now(UTC),
        )
    )
    db.add(
        InAppNotification(
            id=uuid7(),
            user_id=user_id,
            org_id=org_id,
            kind=notice.kind[:40],
            title=notice.title,
            body=notice.body,
            link=notice.link,
        )
    )
    await db.flush()
    return True


async def org_people(db: AsyncSession, engagement: Engagement) -> list[UUID]:
    """The organisation's people on this engagement: its named contact and every member who acted on it."""
    actors = await db.execute(
        select(EngagementEvent.actor_user_id)
        .where(
            EngagementEvent.engagement_id == engagement.id,
            EngagementEvent.actor_user_id.is_not(None),
            EngagementEvent.actor_role.not_in((EngagementActorRole.DEVELOPER, EngagementActorRole.SYSTEM)),
        )
        .distinct()
    )
    people = {user_id for user_id in actors.scalars() if user_id is not None}
    if engagement.contact_user_id is not None:
        people.add(engagement.contact_user_id)
    people.discard(engagement.developer_id)
    return sorted(people)


async def em2_facts(db: AsyncSession, engagement: Engagement, settings: Settings) -> em2.Em2Facts | None:
    """EM2's values, read as the developer (their own proposal, the listed organisation, the Tier-2 access log)."""
    if engagement.contact_user_id is None or engagement.contact_channel is None or engagement.contact_by is None:
        return None
    org = await db.get(Organization, engagement.org_id)
    version = await db.get(ProposalVersion, engagement.version_id)
    contact = await db.scalar(select(User.display_name).where(User.id == engagement.contact_user_id))
    if org is None or version is None or version.registered_at is None or contact is None:
        return None
    role = await db.scalar(
        select(EngagementEvent.payload["contact_role"].astext)
        .where(EngagementEvent.engagement_id == engagement.id, EngagementEvent.payload.has_key("contact_role"))
        .order_by(EngagementEvent.seq.desc())
        .limit(1)
    )
    viewers = await db.scalar(
        select(func.count(func.distinct(DocumentView.viewer_user_id))).where(
            DocumentView.proposal_id == engagement.proposal_id, DocumentView.org_id == engagement.org_id
        )
    )
    shared = await db.scalar(
        select(DisclosureGrant.id)
        .where(
            DisclosureGrant.proposal_id == engagement.proposal_id,
            DisclosureGrant.org_id == engagement.org_id,
            DisclosureGrant.status == GrantStatus.ACTIVE,
            DisclosureGrant.tier >= 2,
        )
        .limit(1)
    )
    return em2.Em2Facts(
        engagement_id=engagement.id,
        company_name=org.legal_name,
        title=version.title or "your proposal",
        contact_person_name=contact,
        contact_person_role=role or "",
        contact_channel=engagement.contact_channel,
        contact_by=engagement.contact_by,
        receipt_id=version.cert_id or "",
        registered_at=version.registered_at,
        viewers=int(viewers or 0),
        shared=shared is not None,
        public_entity=org.public_entity,
        base_url=settings.public_base_url,
        product=settings.product_name,
    )


async def _send_em2(db: AsyncSession, provider: EmailProvider, settings: Settings, engagement: Engagement) -> bool:
    """EM2 to the developer, once per engagement; False while the send is still queued after transient errors."""
    log = get_logger(__name__)
    developer = await db.get(User, engagement.developer_id)
    facts = await em2_facts(db, engagement, settings)
    if developer is None or developer.email_verified_at is None or facts is None:
        log.warning("em2.skipped", engagement_id=str(engagement.id))
        return True
    rendered = em2.render(facts)
    message = EmailMessage(
        to=developer.email, subject=rendered.subject, text=rendered.text, html=rendered.html, tag=em2.KIND
    )
    delivery = await send_email(
        db, provider, message=message, kind=em2.KIND, user_id=developer.id, dedupe_key=em2.dedupe_key(engagement.id)
    )
    return delivery.status is not DeliveryStatus.QUEUED


async def _send_n17(
    db: AsyncSession, provider: EmailProvider, settings: Settings, engagement: Engagement, company: str, title: str
) -> bool:
    """N17 by email to the developer, once per engagement, when their preference allows it; False while the send is
    still queued after transient errors."""
    developer = await db.get(User, engagement.developer_id)
    if developer is None or developer.email_verified_at is None:
        get_logger(__name__).warning("n17.skipped", engagement_id=str(engagement.id))
        return True
    if not await channel_enabled(db, developer.id, n17.KIND, NotificationChannel.EMAIL):
        return True
    deadline = engagement.stage_deadline_at
    rendered = n17.render(
        n17.N17Facts(
            engagement_id=engagement.id,
            company_name=company,
            title=title,
            origin=engagement.origin,
            respond_by=deadline.astimezone(NAIROBI).date() if deadline else None,
            base_url=settings.public_base_url,
            product=settings.product_name,
        )
    )
    message = EmailMessage(
        to=developer.email, subject=rendered.subject, text=rendered.text, html=rendered.html, tag=n17.KIND
    )
    delivery = await send_email(
        db, provider, message=message, kind=n17.KIND, user_id=developer.id, dedupe_key=n17.dedupe_key(engagement.id)
    )
    return delivery.status is not DeliveryStatus.QUEUED


async def deliver(
    factory: async_sessionmaker[AsyncSession],
    provider: EmailProvider,
    settings: Settings,
    *,
    engagement_id: UUID,
    event_id: UUID,
    developer_id: UUID,
    reason_text: str | None = None,
) -> bool:
    """Notify the other party of one event (idempotent). Returns False when an email is still queued (retry)."""
    done = True
    async with factory() as db:
        await bind_tenant(db, user_id=developer_id)
        engagement = await db.get(Engagement, engagement_id)
        event = await db.scalar(
            select(EngagementEvent).where(
                EngagementEvent.id == event_id, EngagementEvent.engagement_id == engagement_id
            )
        )
        if engagement is None or event is None or engagement.developer_id != developer_id:
            get_logger(__name__).warning("engagement.notify_skipped", event_id=str(event_id))
            return True
        org = await db.get(Organization, engagement.org_id)
        version = await db.get(ProposalVersion, engagement.version_id)
        company = org.legal_name if org is not None else "The organisation"
        title = (version.title if version is not None else None) or "your proposal"
        if event.actor_role is EngagementActorRole.SYSTEM:
            notices = dict(compose_system(event, company, title))
        else:
            composed = compose(event, company, title, reason_text=reason_text)
            notices = dict([composed]) if composed is not None else {}
        by_email = emailed(event)
        if DEV in notices:
            await _in_app(db, developer_id, None, notices[DEV], event.id)
            if by_email:
                sent = await _send_status(
                    db, provider, settings, user_id=developer_id, notice=notices[DEV], event=event, title=title
                )
                done = done and sent
            if is_interest(event):
                done = await _send_n17(db, provider, settings, engagement, company, title)
        people = await org_people(db, engagement) if ORG in notices else []
        if event.to_state is EngagementState.INTEREST_CONFIRMED and event.from_state is not event.to_state:
            # EM2 goes to the developer whoever moved the engagement there (the signatory's approval, or the
            # developer's own acceptance of an organisation's interest at stage 0).
            done = await _send_em2(db, provider, settings, engagement) and done
        await db.commit()
    for user_id in people:
        async with factory() as db:
            await bind_tenant(db, user_id=user_id, org_id=engagement.org_id)
            if await membership_of(db, engagement.org_id, user_id) is None:
                continue  # no longer a member: nothing to tell them
            await _in_app(db, user_id, engagement.org_id, notices[ORG], event.id)
            if by_email:
                sent = await _send_status(
                    db, provider, settings, user_id=user_id, notice=notices[ORG], event=event, title=title
                )
                done = done and sent
            await db.commit()
    return done
