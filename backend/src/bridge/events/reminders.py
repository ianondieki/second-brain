"""Remind me: the day-before email (N26) and the morning-of in-app notice (N27) (REQ-DEV-02; D-61; P22 card B, default
(4); ``REQUIREMENTS.md`` §5 N26, N27).

``run_event_reminders`` is the job ``events.remind`` (``bridge.jobs.events``: every 15 minutes). "Now" is the shared
clock (``app_clock_now()``: the dev and test clock moves it; a test may pass ``now``). With no user bound it lists the
reminders that may be due (``app_event_reminders_due(now)``: ids only, active users, published events that have not
ended and start today or tomorrow in Nairobi), then handles each developer in a session bound to them, in their own
transaction, reading their reminders and the events again under their policies, so a reminder deleted (Decline) or an
event cancelled before the moment means nothing is sent. Per reminder:

- **N26**, by email, from 18:00 Nairobi on the day before the event's Nairobi start date until the earlier of its
  start and midnight (a reminder made later never gets a "Tomorrow" email on the day itself): only with the reminders
  consent and a verified address (EM7's gate, ``bridge.reminders.dispatch.email_block``), through ``send_email`` with
  the key ``n26:email:<user>:<event>`` (once; a transient failure is retried by the next runs, at most 3 attempts).
  Subject "Tomorrow: <title>"; the title, when (Nairobi time), where or "Online" and the two calendar links; never the
  description (``templates/n26.*.j2``).
- **N27**, in the app, from 08:00 Nairobi on the event's start date until the earlier of its end and midnight: the
  event's title and "Today at HH:MM · <place>", linking to the event's page, keyed ``n27:in_app:<user>:<event>``
  (once). It needs only the Remind me (in-app is always on).

One developer's failure is logged and never stops the run; the next run picks them up. A run with nothing due writes
nothing and logs nothing.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Final, Literal, NamedTuple
from uuid import UUID

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.models import User
from bridge.config import Settings, get_settings
from bridge.db import bind_tenant, create_engine, create_session_factory
from bridge.engagements.calendar import NAIROBI
from bridge.events.calendar import CalendarEvent, calendar_path, google_calendar_url
from bridge.logging import get_logger
from bridge.models.enums import DeliveryStatus, NotificationChannel, UserStatus
from bridge.notifications.deliveries import MAX_ATTEMPTS, send_email
from bridge.notifications.em1 import unlinkable
from bridge.notifications.email import EmailMessage, EmailProvider, provider_from_settings
from bridge.notifications.in_app import post_in_app
from bridge.notifications.models import NotificationDelivery
from bridge.reminders.dispatch import Recipient, email_block
from bridge.web_paths import dev_event_path

N26: Final = "n26"  # the day-before email
N27: Final = "n27"  # the morning-of in-app notice
EVENING: Final = time(18, 0)
MORNING: Final = time(8, 0)
ONLINE: Final = "Online"  # [[COPY-REVIEW]]
SUBJECT: Final = "Tomorrow: {title}"  # [[COPY-REVIEW]]
TODAY_AT: Final = "Today at {at} · {place}"  # [[COPY-REVIEW]] the N27 body; the title is the event's
_DUE: Final = text("SELECT user_id, event_id FROM app_event_reminders_due(:now)")
_CLOCK: Final = text("SELECT app_clock_now()")
# The caller's reminders on the listed events, as they stand now under the caller's policies: a reminder deleted, or
# an event no longer published (cancelled), is not here.
_MINE: Final = text(
    "SELECT e.id, e.title, e.description, e.starts_at, e.ends_at, e.updated_at, e.online, e.venue, e.join_url,"
    " e.link, r.name AS county_name"
    " FROM event_reminders m JOIN events e ON e.id = m.event_id LEFT JOIN regions r ON r.code = e.county_code"
    " LEFT JOIN organizations o ON o.id = e.org_id"
    " WHERE m.user_id = app_user_id() AND m.event_id = ANY(:ids) AND e.status = 'published'"
    " AND (e.org_id IS NULL OR (o.id IS NOT NULL AND o.suspended_at IS NULL AND o.delisted_at IS NULL))"
    " ORDER BY e.starts_at, e.id"
)
_ENV: Final = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False, default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
log = get_logger(__name__)


@dataclass(frozen=True)
class Deps:
    factory: async_sessionmaker[AsyncSession]
    settings: Settings
    email: EmailProvider


class EventReminderRuntime:
    """The job's long-lived parts, built from settings on first use (tests pass their own)."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        factory: async_sessionmaker[AsyncSession] | None = None,
        email: EmailProvider | None = None,
    ) -> None:
        self._settings, self._factory, self._email = settings, factory, email

    def deps(self) -> Deps:
        settings = self._settings = self._settings or get_settings()
        if self._factory is None:
            self._factory = create_session_factory(create_engine(settings.database_url.get_secret_value()))
        if self._email is None:
            self._email = provider_from_settings(settings)
        return Deps(self._factory, settings, self._email)


Kind = Literal["n26", "n27"]


@dataclass(frozen=True, slots=True)
class Outcome:
    """One reminder's result this run: ``status`` is the email row's status (N26), ``posted`` or ``already`` (N27),
    or why no email was wanted (``unverified``, ``no_consent``, ``preference_off``) or ``error``."""

    user_id: UUID
    event_id: UUID | None
    kind: Kind | None
    status: str


@dataclass(frozen=True, slots=True)
class Report:
    now: datetime
    due: int
    outcomes: tuple[Outcome, ...] = ()


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(0, 0), tzinfo=NAIROBI)


def n26_window(starts_at: datetime) -> tuple[datetime, datetime]:
    """From 18:00 Nairobi the day before the event's start date until the earlier of its start and that midnight."""
    day = starts_at.astimezone(NAIROBI).date()
    return datetime.combine(day - timedelta(days=1), EVENING, tzinfo=NAIROBI), min(starts_at, _midnight(day))


def n27_window(starts_at: datetime, ends_at: datetime) -> tuple[datetime, datetime]:
    """From 08:00 Nairobi on the event's start date until the earlier of its end and the next midnight."""
    day = starts_at.astimezone(NAIROBI).date()
    return datetime.combine(day, MORNING, tzinfo=NAIROBI), min(ends_at, _midnight(day + timedelta(days=1)))


def place(row: Any) -> str:
    """Where, for people: the venue and county, or "Online" (never the join address in a notice)."""
    if row.online:
        return ONLINE
    return ", ".join(part for part in (row.venue, row.county_name) if part)


def when(starts_at: datetime, ends_at: datetime) -> str:
    """``Wednesday 14 October, 18:00 to 20:30 (Nairobi time)``; across days, both days."""
    start, end = starts_at.astimezone(NAIROBI), ends_at.astimezone(NAIROBI)
    first = f"{start:%A} {start.day} {start:%B}"
    if start.date() == end.date():
        return f"{first}, {start:%H:%M} to {end:%H:%M} (Nairobi time)"  # [[COPY-REVIEW]]
    return f"{first} {start:%H:%M} to {end:%A} {end.day} {end:%B} {end:%H:%M} (Nairobi time)"  # [[COPY-REVIEW]]


class Rendered(NamedTuple):
    subject: str
    text: str
    html: str


def _calendar_event(row: Any) -> CalendarEvent:
    return CalendarEvent(
        id=row.id,
        title=row.title,
        description=row.description,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        updated_at=row.updated_at,
        online=row.online,
        venue=row.venue,
        county_name=row.county_name,
        join_url=row.join_url,
        link=row.link,
    )


def render_n26(row: Any, *, base_url: str, product: str) -> Rendered:
    """The day-before email of one event (see the module docstring)."""
    base = base_url.rstrip("/")
    title = unlinkable(row.title)
    subject = SUBJECT.format(title=title)
    values = {
        "subject": subject,
        "title": title,
        "when": when(row.starts_at, row.ends_at),
        "place": unlinkable(place(row)),
        # Nothing the poster wrote beyond the title and venue: no description, no link, no join address (N26).
        "google_url": google_calendar_url(_calendar_event(row), location=place(row), details=False),
        "ics_url": base + calendar_path(row.id),
        "settings_url": f"{base}/settings/notifications",
        "help_url": f"{base}/help",
        "product": unlinkable(product),
    }
    return Rendered(
        subject, _ENV.get_template("n26.txt.j2").render(values), _ENV.get_template("n26.html.j2").render(values)
    )


def n26_key(user_id: UUID, event_id: UUID) -> str:
    return f"{N26}:{NotificationChannel.EMAIL.value}:{user_id}:{event_id}"


def n27_key(user_id: UUID, event_id: UUID) -> str:
    return f"{N27}:{NotificationChannel.IN_APP.value}:{user_id}:{event_id}"


async def clock_now(db: AsyncSession) -> datetime:
    now: datetime = (await db.execute(_CLOCK)).scalar_one()
    return now


async def run_event_reminders(deps: Deps, *, now: datetime | None = None) -> Report:
    """One pass of ``events.remind`` (see the module docstring)."""
    async with deps.factory() as db:
        now = now or await clock_now(db)
        due = (await db.execute(_DUE, {"now": now})).all()
    if not due:
        return Report(now, 0)
    by_user: dict[UUID, list[UUID]] = defaultdict(list)
    for row in due:
        by_user[row.user_id].append(row.event_id)
    outcomes: list[Outcome] = []
    for user_id, event_ids in by_user.items():
        try:
            outcomes += await remind_one(deps, user_id, event_ids, now)
        except Exception as exc:  # one developer never stops the run; the next run retries them
            log.error("events.remind_failed", user_id=str(user_id), error_type=type(exc).__name__)
            outcomes.append(Outcome(user_id, None, None, "error"))
    acted = [o for o in outcomes if o.status not in ("already",)]
    if acted:
        log.info("events.reminded", count=len(acted), recipients=len(by_user))
    return Report(now, len(due), tuple(outcomes))


async def _recipient(db: AsyncSession, user_id: UUID) -> Recipient | None:
    """An active user (``users`` has no RLS)."""
    row = (
        await db.execute(
            select(User.email, User.email_verified_at).where(User.id == user_id, User.status == UserStatus.ACTIVE)
        )
    ).one_or_none()
    return None if row is None else Recipient(user_id, row.email, row.email_verified_at is not None)


async def remind_one(deps: Deps, user_id: UUID, event_ids: Sequence[UUID], now: datetime) -> list[Outcome]:
    """One developer's due reminders, in a session bound to them and one transaction."""
    outcomes: list[Outcome] = []
    async with deps.factory() as db:
        recipient = await _recipient(db, user_id)
        if recipient is None:
            return outcomes
        await bind_tenant(db, user_id=user_id)
        block: str | None = None
        gate_read = False
        for row in (await db.execute(_MINE, {"ids": list(event_ids)})).all():
            start, end = n26_window(row.starts_at)
            if start <= now < end:
                if not gate_read:
                    block, gate_read = await email_block(db, recipient, N26), True
                outcomes.append(await _email(deps, db, recipient, row, now, block))
            start, end = n27_window(row.starts_at, row.ends_at)
            if start <= now < end:
                outcomes.append(await _notice(db, user_id, row, now))
        await db.commit()
    return outcomes


async def _email(deps: Deps, db: AsyncSession, r: Recipient, row: Any, now: datetime, block: str | None) -> Outcome:
    if block is not None:
        return Outcome(r.id, row.id, N26, block)
    key = n26_key(r.id, row.id)
    found = await db.scalar(select(NotificationDelivery.status).where(NotificationDelivery.dedupe_key == key))
    if found is not None and found is not DeliveryStatus.QUEUED:  # sent (or ended) by an earlier run
        return Outcome(r.id, row.id, N26, "already")
    rendered = render_n26(row, base_url=deps.settings.public_base_url, product=deps.settings.product_name)
    message = EmailMessage(to=r.email, subject=rendered.subject, text=rendered.text, html=rendered.html, tag=N26)
    delivery = await send_email(
        db,
        deps.email,
        message=message,
        kind=N26,
        user_id=r.id,
        dedupe_key=key,
        local_date=now.astimezone(NAIROBI).date(),
        max_attempts=1,  # one per run: the next run (15 minutes later) retries a transient failure
        attempt_limit=MAX_ATTEMPTS,
    )
    return Outcome(r.id, row.id, N26, str(delivery.status))


async def _notice(db: AsyncSession, user_id: UUID, row: Any, now: datetime) -> Outcome:
    at = row.starts_at.astimezone(NAIROBI)
    wrote = await post_in_app(
        db,
        user_id=user_id,
        kind=N27,
        title=row.title,
        body=TODAY_AT.format(at=f"{at:%H:%M}", place=place(row)),
        link=dev_event_path(row.id),
        dedupe_key=n27_key(user_id, row.id),
        local_date=now.astimezone(NAIROBI).date(),
    )
    return Outcome(user_id, row.id, N27, "posted" if wrote else "already")
