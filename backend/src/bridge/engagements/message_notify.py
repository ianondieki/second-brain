"""N18: a new message in the engagement thread (REQ-ENG-11; REQUIREMENTS.md §5 N18; D-57 (2)).

Posting a message queues one job in the post's own transaction (``bridge.jobs.outbox``: the job exists if and only if
the message committed), on the tracker's ``notifications`` queue, one engagement at a time (lock
``engagement:<id>``). The job tells the other party's people on the thread:

- When an organisation member writes, the developer.
- When the developer writes, the organisation's people on this engagement: its named contact, the members who acted
  on its tracker and the members who wrote in its thread, each still an active member (the developer cannot read the
  organisation's roster; ``notify.org_people``'s rule plus the thread's own writers).

Each recipient gets, in a session bound to them:

- in-app always (the bell), once per message and recipient (``post_in_app``, dedupe key
  ``n18:inapp:<message>:<user>``), linking to their tracker's Messages tab;
- a status email (ADR-004's fixed layout), mutable (the recipient's ``engagement.n18`` email preference, on unless
  they turned it off), at most one per recipient and engagement in any 30 minutes (``EMAIL_GAP``, on the messages'
  own clock: no other N18 email to that recipient about the engagement was sent or is queued for a message written
  within 30 minutes of this one), idempotent per message (dedupe key ``n18:email:<engagement>:<user>:<message>``).

Neither carries the message's text (it may hold contact or confidential details; email is the weaker channel): they
say who wrote, on which proposal, and link to the tab. Wording is fixed product copy ([[COPY-REVIEW]]).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.models import User
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements import notify
from bridge.engagements.history import developer_identity
from bridge.engagements.models import Engagement, EngagementMessage
from bridge.jobs.outbox import defer
from bridge.logging import get_logger
from bridge.models.enums import DeliveryStatus, EngagementParty, NotificationChannel
from bridge.notifications import em2, status
from bridge.notifications.deliveries import send_email
from bridge.notifications.email import EmailMessage, EmailProvider
from bridge.notifications.in_app import MAX_TITLE_CHARS, post_in_app
from bridge.notifications.models import NotificationDelivery
from bridge.notifications.preferences import channel_enabled
from bridge.proposals.models import ProposalVersion
from bridge.tenancy.models import Organization
from bridge.tenancy.service import membership_of
from bridge.web_paths import messages_path

KIND: Final = "engagement.n18"
QUEUE: Final = notify.QUEUE
TASK: Final = "engagements.message_notify"
EMAIL_GAP: Final = timedelta(minutes=30)
LABEL: Final = "New message"  # [[COPY-REVIEW]] the status email's label (its subject begins with it)
TITLE: Final = 'New message from {party} on "{title}"'  # [[COPY-REVIEW]] the bell's title
BODY: Final = "Open the Messages tab to read it."  # [[COPY-REVIEW]] never the message's text
SENTENCE: Final = '{party} wrote to you about "{title}". Read the message on your tracker.'  # [[COPY-REVIEW]]
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG


async def enqueue(db: AsyncSession, engagement: Engagement, message_id: UUID) -> int:
    """Queue the N18 job of ``message_id`` in the caller's transaction (ids only)."""
    args = {
        "engagement_id": str(engagement.id),
        "message_id": str(message_id),
        "developer_id": str(engagement.developer_id),
    }
    return await defer(db, TASK, args, queue=QUEUE, lock=f"engagement:{engagement.id}")


def in_app_key(message_id: UUID, user_id: UUID) -> str:
    return f"n18:inapp:{message_id}:{user_id}"


def email_prefix(engagement_id: UUID, user_id: UUID) -> str:
    return f"n18:email:{engagement_id}:{user_id}:"


def email_key(engagement_id: UUID, user_id: UUID, message_id: UUID) -> str:
    return f"{email_prefix(engagement_id, user_id)}{message_id}"


def title_for(party: str, title: str) -> str:
    """The bell's title, cut to the column's 200 characters by shortening the proposal's title."""
    party, title = em2.one_line(party), em2.one_line(title)
    full = TITLE.format(party=party, title=title)
    if len(full) <= MAX_TITLE_CHARS:
        return full
    room = max(MAX_TITLE_CHARS - len(TITLE.format(party=party, title="")) - 1, 0)
    return TITLE.format(party=party, title=title[:room] + "…")[:MAX_TITLE_CHARS]


async def _throttled(db: AsyncSession, user_id: UUID, message: EngagementMessage) -> bool:
    """Whether an N18 email to ``user_id`` about this engagement was sent, or is queued, for another message written
    within ``EMAIL_GAP`` of ``message`` (the session is bound to the recipient: their ledger, the parties' thread)."""
    prefix = email_prefix(message.engagement_id, user_id)
    keys = await db.scalars(
        select(NotificationDelivery.dedupe_key).where(
            NotificationDelivery.user_id == user_id,
            NotificationDelivery.kind == KIND,
            NotificationDelivery.channel == NotificationChannel.EMAIL,
            NotificationDelivery.status.in_((DeliveryStatus.SENT, DeliveryStatus.QUEUED)),
            NotificationDelivery.dedupe_key.startswith(prefix, autoescape=True),
        )
    )
    earlier: list[UUID] = []
    for key in keys:
        try:
            earlier.append(UUID(str(key)[len(prefix) :]))
        except ValueError:
            continue
    if not earlier:
        return False
    near = await db.scalar(
        select(func.count())
        .select_from(EngagementMessage)
        .where(
            EngagementMessage.id.in_(earlier),
            EngagementMessage.id != message.id,
            EngagementMessage.engagement_id == message.engagement_id,
            EngagementMessage.created_at > message.created_at - EMAIL_GAP,
            EngagementMessage.created_at < message.created_at + EMAIL_GAP,
        )
    )
    return bool(near)


async def _email(
    db: AsyncSession,
    provider: EmailProvider,
    settings: Settings,
    *,
    user_id: UUID,
    party: EngagementParty,
    message: EngagementMessage,
    writer: str,
    title: str,
) -> bool:
    """The status email to ``user_id`` (the session is bound to them) when their preference allows it and the
    30-minute gap holds; False while the send is still queued after transient errors."""
    user = await db.get(User, user_id)
    if user is None or user.email_verified_at is None:
        get_logger(__name__).warning("n18.email_skipped", message_id=str(message.id), user_id=str(user_id))
        return True
    if not await channel_enabled(db, user.id, KIND, NotificationChannel.EMAIL):
        return True
    key = email_key(message.engagement_id, user.id, message.id)
    known = await db.scalar(select(NotificationDelivery.id).where(NotificationDelivery.dedupe_key == key))
    if known is None and await _throttled(db, user.id, message):
        return True
    rendered = status.render(
        status.StatusFacts(
            engagement_id=message.engagement_id,
            label=LABEL,
            title=title,
            sentence=SENTENCE.format(party=em2.one_line(writer), title=em2.one_line(title)),
            path=messages_path(party, message.engagement_id),
            base_url=settings.public_base_url,
            product=settings.product_name,
        )
    )
    email = EmailMessage(to=user.email, subject=rendered.subject, text=rendered.text, html=rendered.html, tag=KIND)
    delivery = await send_email(db, provider, message=email, kind=KIND, user_id=user.id, dedupe_key=key)
    return delivery.status is not DeliveryStatus.QUEUED


async def _tell(
    db: AsyncSession,
    provider: EmailProvider,
    settings: Settings,
    *,
    user_id: UUID,
    party: EngagementParty,
    org_id: UUID | None,
    message: EngagementMessage,
    writer: str,
    title: str,
) -> bool:
    await post_in_app(
        db,
        user_id=user_id,
        kind=KIND,
        title=title_for(writer, title),
        body=BODY,
        link=messages_path(party, message.engagement_id),
        dedupe_key=in_app_key(message.id, user_id),
        org_id=org_id,
    )
    return await _email(
        db, provider, settings, user_id=user_id, party=party, message=message, writer=writer, title=title
    )


async def _org_writers(db: AsyncSession, engagement_id: UUID) -> set[UUID]:
    found = await db.scalars(
        select(EngagementMessage.sender_user_id)
        .where(EngagementMessage.engagement_id == engagement_id, EngagementMessage.sender_party == ORG)
        .distinct()
    )
    return set(found)


async def deliver(
    factory: async_sessionmaker[AsyncSession],
    provider: EmailProvider,
    settings: Settings,
    *,
    engagement_id: UUID,
    message_id: UUID,
    developer_id: UUID,
) -> bool:
    """Tell the other party's people about one message (idempotent). False when an email is still queued (retry)."""
    done = True
    async with factory() as db:
        await bind_tenant(db, user_id=developer_id)
        engagement = await db.get(Engagement, engagement_id)
        message = await db.scalar(
            select(EngagementMessage).where(
                EngagementMessage.id == message_id, EngagementMessage.engagement_id == engagement_id
            )
        )
        if engagement is None or message is None or engagement.developer_id != developer_id:
            get_logger(__name__).warning("n18.skipped", message_id=str(message_id))
            return True
        version = await db.get(ProposalVersion, engagement.version_id)
        title = (version.title if version is not None else None) or "your proposal"
        people: list[UUID] = []
        developer_name = ""
        if message.sender_party is ORG:
            org = await db.get(Organization, engagement.org_id)
            company = org.legal_name if org is not None else "The organisation"
            done = await _tell(
                db,
                provider,
                settings,
                user_id=developer_id,
                party=DEV,
                org_id=None,
                message=message,
                writer=company,
                title=title,
            )
        else:
            people = sorted(
                (set(await notify.org_people(db, engagement)) | await _org_writers(db, engagement.id))
                - {developer_id, message.sender_user_id}
            )
            _, developer_name, _ = await developer_identity(db, engagement, developer_caller=False)
        await db.commit()
    for user_id in people:
        async with factory() as db:
            await bind_tenant(db, user_id=user_id, org_id=engagement.org_id)
            if await membership_of(db, engagement.org_id, user_id) is None:
                continue  # no longer a member: nothing to tell them
            message = await db.scalar(select(EngagementMessage).where(EngagementMessage.id == message_id))
            if message is None:
                continue
            sent = await _tell(
                db,
                provider,
                settings,
                user_id=user_id,
                party=ORG,
                org_id=engagement.org_id,
                message=message,
                writer=developer_name,
                title=title,
            )
            done = done and sent
            await db.commit()
    return done
