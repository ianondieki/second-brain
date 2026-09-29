"""Sending the reminders: once per recipient and period, on the shared clock (REQ-REM-01, REQ-REM-02, REQ-NOT-06).

``run_developer_nudges`` (EM7, job ``reminders.dispatch``) and ``run_org_digests`` (org EM7, ``reminders.org_digest``)
run every 15 minutes. "Now" is ``app_clock_now()`` (the dev/test clock moves them; a test may pass ``now``), turned into
the Nairobi date. Nothing is looked at before ``SEND_AFTER`` (07:30 EAT) or ``ORG_SEND_AFTER`` (08:30 EAT) unless the
run is forced (``force=True``: ``python -m bridge.reminders run --now``, dev and test only). Each recipient is handled
in its own session bound to them (one tenant at a time) and its own transaction; one recipient's failure is logged
and never stops the run.

Per recipient and period (the Nairobi day; for a weekly digest, its ISO week):

1. The once-a-day guard: the ledger's rows under ``daily_key`` (in-app and email). When the in-app summary exists
   and the email is finished or not wanted, nothing more happens (no facts are read, no LLM is called).
2. The facts (``bridge.reminders.facts``) and the composition (``compose_nudge`` / ``compose_digest``). Nothing open
   is quiet: nothing is sent and nothing is recorded, so a later run the same day may still send.
3. The developer's wording (``word_nudge``: the LLM's two lines or the fixed text; the organisation's digest has no
   LLM), then the in-app summary (always on) and the email: only with the ``reminders`` consent, a verified address,
   the kind's email preference on and, for developers, a plan with ``daily_email_reminders``; ``send_email`` checks
   suppressions. One attempt per run and at most 3 per message (REQ-NOT-06), so the 15-minute runs space the retries
   of a transient failure; a permanent failure, or the third, ends the message ``failed`` (dead letter). One commit
   per recipient.

Organisation digests go to members who opted in (the ``reminders`` consent), one per member, organisation and period
(``daily_key(..., org_id=...)``), cadence from the organisation's plan (``progress_digest``: daily or weekly).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Final, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.models import User
from bridge.billing.entitlements import for_subject
from bridge.config import Settings, get_settings
from bridge.db import bind_tenant, create_engine, create_session_factory
from bridge.engagements.calendar import NAIROBI
from bridge.llm.deps import build_runtime, routed_client
from bridge.llm.routing import LLMRuntime
from bridge.llm.types import CallContext
from bridge.logging import get_logger
from bridge.models.enums import (
    ConsentPurpose,
    DeliveryStatus,
    MembershipStatus,
    NotificationChannel,
    UserStatus,
)
from bridge.notifications.deliveries import MAX_ATTEMPTS, daily_key, send_email
from bridge.notifications.email import EmailMessage, EmailProvider, provider_from_settings
from bridge.notifications.in_app import post_in_app
from bridge.notifications.models import NotificationDelivery
from bridge.notifications.preferences import channel_enabled
from bridge.profiles.consents import latest
from bridge.reminders import nudge as developer
from bridge.reminders import org_digest
from bridge.reminders.facts import clock_now, developer_facts, load_holidays, org_facts
from bridge.reminders.health import Health, nairobi_today
from bridge.reminders.render import TRACKER_PATH
from bridge.reminders.wording import word_nudge
from bridge.tenancy.models import Membership

SEND_AFTER: Final = time(7, 30)  # docs/spec/06 6.11: developers, at send_after_hour (default 07:30 EAT)
ORG_SEND_AFTER: Final = time(8, 30)  # docs/spec/06 6.11: reminders.org_digest 08:30
EMAIL, IN_APP = NotificationChannel.EMAIL, NotificationChannel.IN_APP
Status = Literal["sent", "already", "quiet", "not_opted_in", "error"]
log = get_logger(__name__)


@dataclass(frozen=True)
class Deps:
    """What a run needs. ``llm`` None words every nudge with the fixed text (no LLM)."""

    factory: async_sessionmaker[AsyncSession]
    settings: Settings
    email: EmailProvider
    llm: LLMRuntime | None = None


@dataclass(frozen=True, slots=True)
class Outcome:
    """One recipient's result. ``email`` is the email row's status after the run (None: no email row);
    ``email_skipped`` why no email was wanted; ``in_app`` whether the summary was written by this run."""

    user_id: UUID
    status: Status
    org_id: UUID | None = None
    email: DeliveryStatus | None = None
    email_skipped: str | None = None
    in_app: bool = False
    wording: developer.Wording | None = None
    health: Mapping[UUID, Health] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Report:
    now: datetime
    today: date
    ran: bool  # False: before the send-after time, nothing was looked at
    outcomes: tuple[Outcome, ...] = ()

    def of(self, user_id: UUID, org_id: UUID | None = None) -> Outcome | None:
        return next((o for o in self.outcomes if o.user_id == user_id and o.org_id == org_id), None)


@dataclass(frozen=True, slots=True)
class Recipient:
    """An active user (``users`` has no RLS: read before any tenant is bound)."""

    id: UUID
    email: str
    verified: bool


class ReminderRuntime:
    """The long-lived parts of the jobs and the CLI, built from settings on first use (tests pass their own)."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        email: EmailProvider | None = None,
        llm: LLMRuntime | None = None,
    ) -> None:
        self._settings, self._factory, self._email, self._llm = settings, factory, email, llm

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def deps(self) -> Deps:
        if self._factory is None:
            self._factory = create_session_factory(create_engine(self.settings.database_url.get_secret_value()))
        if self._email is None:
            self._email = provider_from_settings(self.settings)
        if self._llm is None:
            self._llm = build_runtime(self.settings)
        return Deps(self._factory, self.settings, self._email, self._llm)

    async def aclose(self) -> None:
        if self._llm is not None:
            await self._llm.aclose()


async def _now(deps: Deps, now: datetime | None) -> datetime:
    if now is not None:
        return now
    async with deps.factory() as db:
        return await clock_now(db)


async def _recipients(db: AsyncSession, user_ids: Sequence[UUID] | None) -> list[Recipient]:
    query = select(User.id, User.email, User.email_verified_at).where(User.status == UserStatus.ACTIVE)
    if user_ids is not None:
        query = query.where(User.id.in_(list(user_ids)))
    rows = await db.execute(query.order_by(User.id))
    return [Recipient(user_id, address, verified is not None) for user_id, address, verified in rows.all()]


async def _row(db: AsyncSession, key: str) -> NotificationDelivery | None:
    row: NotificationDelivery | None = await db.scalar(
        select(NotificationDelivery).where(NotificationDelivery.dedupe_key == key)
    )
    return row


async def _email_block(db: AsyncSession, r: Recipient, kind: str) -> str | None:
    """Why ``r`` gets no email of ``kind`` (None: they do). Suppressions are ``send_email``'s check."""
    if not r.verified:
        return "unverified"
    consent = await latest(db, r.id, ConsentPurpose.REMINDERS)
    if consent is None or not consent.granted:
        return "no_consent"
    if not await channel_enabled(db, r.id, kind, EMAIL):
        return "preference_off"
    return None


def _finished(row: NotificationDelivery | None) -> bool:
    return row is not None and row.status is not DeliveryStatus.QUEUED


async def _send(
    deps: Deps,
    db: AsyncSession,
    message: EmailMessage,
    *,
    kind: str,
    user_id: UUID,
    org_id: UUID | None,
    key: str,
    period: date,
) -> DeliveryStatus:
    delivery = await send_email(
        db,
        deps.email,
        message=message,
        kind=kind,
        user_id=user_id,
        org_id=org_id,
        dedupe_key=key,
        local_date=period,
        max_attempts=1,  # one per run: the next run (15 minutes later) retries a transient failure
        attempt_limit=MAX_ATTEMPTS,
    )
    return delivery.status


def _gate(now: datetime, after: time, force: bool) -> bool:
    return force or now.astimezone(NAIROBI).time() >= after


async def _each(
    deps: Deps, now: datetime, user_ids: Sequence[UUID] | None
) -> tuple[date, frozenset[date], list[Recipient]]:
    """Today's Nairobi date, the holidays and the active users (all, or ``user_ids``)."""
    async with deps.factory() as db:
        return nairobi_today(now), await load_holidays(db), await _recipients(db, user_ids)


# ------------------------------------------------------------------------------------------------ developers (EM7)


async def run_developer_nudges(
    deps: Deps, *, now: datetime | None = None, force: bool = False, user_ids: Sequence[UUID] | None = None
) -> Report:
    """One pass of ``reminders.dispatch``: each active user's EM7 for today, at most once per channel."""
    now = await _now(deps, now)
    if not _gate(now, SEND_AFTER, force):
        return Report(now, nairobi_today(now), ran=False)
    today, holidays, recipients = await _each(deps, now, user_ids)
    outcomes = []
    for r in recipients:
        try:
            outcomes.append(await nudge_one(deps, r, today=today, holidays=holidays))
        except Exception as exc:  # one recipient never stops the run; the next run retries them
            log.error("reminders.nudge_failed", user_id=str(r.id), error_type=type(exc).__name__)
            outcomes.append(Outcome(r.id, "error"))
    report = Report(now, today, True, tuple(outcomes))
    log.info("reminders.dispatched", today=today.isoformat(), **_counts(report))
    return report


async def nudge_one(deps: Deps, r: Recipient, *, today: date, holidays: frozenset[date]) -> Outcome:
    kind = developer.KIND
    in_key, email_key = daily_key(kind, IN_APP, r.id, today), daily_key(kind, EMAIL, r.id, today)
    async with deps.factory() as db:
        await bind_tenant(db, user_id=r.id)
        in_app_done = await _row(db, in_key) is not None
        email_row = await _row(db, email_key)
        block = await _email_block(db, r, kind)
        if block is None:
            plan = await for_subject(db, deps.settings, user_id=r.id)
            block = None if plan.allows("daily_email_reminders") else "plan"
        email_open = block is None and not _finished(email_row)
        status = email_row.status if email_row is not None else None
        if in_app_done and not email_open:
            return Outcome(r.id, "already", email=status, email_skipped=block)
        composed = developer.compose_nudge(await developer_facts(db, r.id, today), holidays)
        if composed.empty:
            return Outcome(r.id, "quiet", email=status, email_skipped=block)
        client = None
        if deps.llm is not None:
            client = routed_client(db, factory=deps.factory, settings=deps.settings, runtime=deps.llm)
        ctx = CallContext(user_id=r.id, trace_id=f"em7-{today:%Y%m%d}-{r.id.hex[-12:]}")
        wording = await word_nudge(client, composed, ctx=ctx)
        wrote = not in_app_done and await post_in_app(
            db,
            user_id=r.id,
            kind=kind,
            title=developer.IN_APP_TITLE,
            body=developer.in_app_body(composed),
            link=TRACKER_PATH,
            dedupe_key=in_key,
            local_date=today,
        )
        if email_open:
            message = developer.render_nudge(composed, wording, to=r.email, base_url=deps.settings.public_base_url)
            status = await _send(deps, db, message, kind=kind, user_id=r.id, org_id=None, key=email_key, period=today)
        await db.commit()
    return Outcome(
        r.id, "sent", email=status, email_skipped=block, in_app=wrote, wording=wording, health=composed.health_of()
    )


# ------------------------------------------------------------------------------------------ organisations (org EM7)


async def run_org_digests(
    deps: Deps, *, now: datetime | None = None, force: bool = False, user_ids: Sequence[UUID] | None = None
) -> Report:
    """One pass of ``reminders.org_digest``: each opted-in member's digest per organisation and period."""
    now = await _now(deps, now)
    if not _gate(now, ORG_SEND_AFTER, force):
        return Report(now, nairobi_today(now), ran=False)
    today, holidays, recipients = await _each(deps, now, user_ids)
    outcomes: list[Outcome] = []
    for r in recipients:
        try:
            async with deps.factory() as db:
                await bind_tenant(db, user_id=r.id)
                orgs = (
                    await db.scalars(
                        select(Membership.org_id)
                        .where(Membership.user_id == r.id, Membership.status == MembershipStatus.ACTIVE)
                        .order_by(Membership.org_id)
                    )
                ).all()
            for org_id in orgs:
                outcomes.append(await digest_one(deps, r, org_id, today=today, holidays=holidays))
        except Exception as exc:  # one recipient never stops the run; the next run retries them
            log.error("reminders.digest_failed", user_id=str(r.id), error_type=type(exc).__name__)
            outcomes.append(Outcome(r.id, "error"))
    report = Report(now, today, True, tuple(outcomes))
    log.info("reminders.digests", today=today.isoformat(), **_counts(report))
    return report


async def digest_one(deps: Deps, r: Recipient, org_id: UUID, *, today: date, holidays: frozenset[date]) -> Outcome:
    kind = org_digest.KIND
    async with deps.factory() as db:
        await bind_tenant(db, user_id=r.id, org_id=org_id)
        consent = await latest(db, r.id, ConsentPurpose.REMINDERS)
        if consent is None or not consent.granted:
            return Outcome(r.id, "not_opted_in", org_id=org_id)
        plan = await for_subject(db, deps.settings, org_id=org_id)
        cadence: org_digest.Cadence = "daily" if plan.limits.get("progress_digest") == "daily" else "weekly"
        period = org_digest.period_start(today, cadence)
        in_key = daily_key(kind, IN_APP, r.id, period, org_id=org_id)
        email_key = daily_key(kind, EMAIL, r.id, period, org_id=org_id)
        in_app_done = await _row(db, in_key) is not None
        email_row = await _row(db, email_key)
        block = await _email_block(db, r, kind)
        email_open = block is None and not _finished(email_row)
        status = email_row.status if email_row is not None else None
        if in_app_done and not email_open:
            return Outcome(r.id, "already", org_id=org_id, email=status, email_skipped=block)
        digest = org_digest.compose_digest(await org_facts(db, org_id, today, cadence), holidays)
        if digest.empty:
            return Outcome(r.id, "quiet", org_id=org_id, email=status, email_skipped=block)
        wrote = not in_app_done and await post_in_app(
            db,
            user_id=r.id,
            org_id=org_id,
            kind=kind,
            title=org_digest.subject(digest)[:200],
            body=f"{digest.summary}.",
            link=TRACKER_PATH,
            dedupe_key=in_key,
            local_date=period,
        )
        if email_open:
            message = org_digest.render_digest(digest, to=r.email, base_url=deps.settings.public_base_url)
            status = await _send(
                deps, db, message, kind=kind, user_id=r.id, org_id=org_id, key=email_key, period=period
            )
        await db.commit()
    return Outcome(
        r.id, "sent", org_id=org_id, email=status, email_skipped=block, in_app=wrote, health=digest.health_of()
    )


def _counts(report: Report) -> dict[str, int]:
    counts: dict[str, int] = {}
    for outcome in report.outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    return counts
