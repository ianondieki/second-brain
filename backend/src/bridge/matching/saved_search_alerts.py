"""Saved-search alerts (P21 track C; REQ-PERS-03, REQ-TREND-02; D-57 (7); revision 0008's ``app_saved_searches_due``).

``run_alerts`` is the daily job ``saved_searches.alert`` (``bridge.jobs.saved_searches``: 04:05 UTC, 07:05 in
Nairobi). "Now" is the shared clock (``app_clock_now()``: the dev/test clock moves it; a test may pass ``now``).

1. With no user bound, ``app_saved_searches_due(now)`` lists the (user, saved search) ids with alerts on, of active
   users, not alerted since 00:00 Nairobi of ``now``'s day: ids only, a superset of what is due (no application role
   reads every user's searches).
2. Per user, in a session bound to them and one transaction: their listed searches are locked (``FOR UPDATE``) and
   decided again (still theirs, alerts still on, still not alerted today), then each is matched under their own RLS
   (``discover.NewMatches``: what Discover lists for the saved view and filters, published after ``last_alerted_at``,
   or after the search was saved, and at or before ``now``). A count above zero writes one in-app notification
   (``saved_search_match``: "3 new problems match Agriculture in Nakuru", linking to Discover with the filters;
   dedupe key ``saved_search_match:<search>:<Nairobi date>``). Every decided search's ``last_alerted_at`` becomes
   ``now`` in the same transaction, matches or not, so an item is never counted twice and a re-run the same day finds
   nothing due.
3. Then, when the day had matches and the person turned the digest on (``saved_search_digest`` email, off by default)
   with a verified address: one status email listing the searches' names and counts, never an item's text
   (``bridge.notifications.saved_search_digest``; once per person and Nairobi day, ``daily_key``; at most 3 attempts,
   a dead letter after that). The in-app notices stand whether or not the email goes.

One person's failure is logged (ids and the error's type only, never a search's name or words) and never stops the
run; their searches stay due, so the next run (the next day, or a forced one) retries them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Final
from uuid import UUID

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.models import User
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements.service import app_now
from bridge.logging import get_logger
from bridge.matching.discover import NewMatches, SavedQuery
from bridge.matching.trending import NAIROBI, nairobi_day
from bridge.models.enums import DeliveryStatus, NotificationChannel
from bridge.notifications import saved_search_digest as digest
from bridge.notifications.deliveries import MAX_ATTEMPTS, send_email
from bridge.notifications.email import EmailMessage, EmailProvider
from bridge.notifications.in_app import post_in_app
from bridge.notifications.preferences import SAVED_SEARCH_DIGEST, SAVED_SEARCH_MATCH, channel_enabled
from bridge.profiles.models import SavedSearch
from bridge.web_paths import discover_path

_DUE: Final = text("SELECT user_id, saved_search_id FROM app_saved_searches_due(:now)")
log = get_logger(__name__)


@dataclass(frozen=True)
class AlertDeps:
    factory: async_sessionmaker[AsyncSession]
    settings: Settings
    email: EmailProvider


@dataclass(frozen=True, slots=True)
class Alert:
    search_id: UUID
    count: int  # new matches since the last alert
    notified: bool  # this run wrote the in-app notification


@dataclass(frozen=True, slots=True)
class Outcome:
    """One person's result: their decided searches, and the digest email's status (None: no email, ``email_skipped``
    says why when there were matches) or ``error`` (logged; their searches stay due)."""

    user_id: UUID
    alerts: tuple[Alert, ...] = ()
    email: DeliveryStatus | None = None
    email_skipped: str | None = None
    error: bool = False


@dataclass(frozen=True, slots=True)
class Report:
    now: datetime
    outcomes: tuple[Outcome, ...] = field(default=())

    def of(self, user_id: UUID) -> Outcome | None:
        return next((o for o in self.outcomes if o.user_id == user_id), None)


def day_start(now: datetime) -> datetime:
    """00:00 in Nairobi of ``now``'s day (``app_saved_searches_due``'s line)."""
    return datetime.combine(nairobi_day(now), time.min, tzinfo=NAIROBI)


def title(count: int, view: str, name: str) -> str:
    """'3 new problems match Agriculture in Nakuru', '1 new Brief matches Water' ([[COPY-REVIEW]])."""
    return f"{digest.new_items(count, view)} {'matches' if count == 1 else 'match'} {name}"


def in_app_key(search_id: UUID, day: date) -> str:
    return f"{SAVED_SEARCH_MATCH}:{search_id}:{day.isoformat()}"


async def _due(db: AsyncSession, user_id: UUID, search_ids: Sequence[UUID], now: datetime) -> list[SavedSearch]:
    """The listed searches still due, locked: the person's own (RLS and the id), alerts on, not alerted today."""
    stmt = (
        select(SavedSearch)
        .where(
            SavedSearch.id.in_(list(search_ids)),
            SavedSearch.user_id == user_id,
            SavedSearch.alerts.is_(True),
            or_(SavedSearch.last_alerted_at.is_(None), SavedSearch.last_alerted_at < day_start(now)),
        )
        .order_by(SavedSearch.created_at, SavedSearch.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


async def alert_user(deps: AlertDeps, user_id: UUID, search_ids: Sequence[UUID], now: datetime) -> Outcome:
    """Match, notify and advance one person's due searches in one transaction, then send their digest if wanted."""
    today = nairobi_day(now)
    found: list[digest.Match] = []
    alerts: list[Alert] = []
    async with deps.factory() as db:
        await bind_tenant(db, user_id=user_id)
        matches = NewMatches(db, now)
        for search in await _due(db, user_id, search_ids, now):
            query = SavedQuery(search.view, search.niche_slug, search.county_code, search.words)
            count = await matches.count(query, search.last_alerted_at or search.created_at)
            notified = False
            if count > 0:
                notified = await post_in_app(
                    db,
                    user_id=user_id,
                    kind=SAVED_SEARCH_MATCH,
                    title=title(count, search.view, search.name),
                    body=None,
                    link=discover_path(
                        search.view, niche=search.niche_slug, county=search.county_code, words=search.words
                    ),
                    dedupe_key=in_app_key(search.id, today),
                    local_date=today,
                )
                found.append(digest.Match(search.name, search.view, count))
            search.last_alerted_at = now
            alerts.append(Alert(search.id, count, notified))
        await db.commit()
    if not found:
        return Outcome(user_id, tuple(alerts))
    status, skipped = await _send_digest(deps, user_id, found, today)
    return Outcome(user_id, tuple(alerts), email=status, email_skipped=skipped)


async def _send_digest(
    deps: AlertDeps, user_id: UUID, found: Sequence[digest.Match], today: date
) -> tuple[DeliveryStatus | None, str | None]:
    """The day's digest email, when the person turned it on and has a verified address; (status, why not)."""
    async with deps.factory() as db:
        await bind_tenant(db, user_id=user_id)
        user = await db.get(User, user_id)
        if user is None or user.email_verified_at is None:
            return None, "unverified"
        if not await channel_enabled(db, user_id, SAVED_SEARCH_DIGEST, NotificationChannel.EMAIL):
            return None, "preference_off"
        rendered = digest.render(
            digest.DigestFacts(found, base_url=deps.settings.public_base_url, product=deps.settings.product_name)
        )
        message = EmailMessage(
            to=user.email, subject=rendered.subject, text=rendered.text, html=rendered.html, tag=digest.KIND
        )
        delivery = await send_email(
            db,
            deps.email,
            message=message,
            kind=digest.KIND,
            user_id=user_id,
            dedupe_key=digest.dedupe_key(user_id, today),
            local_date=today,
            attempt_limit=MAX_ATTEMPTS,
        )
        await db.commit()
        return delivery.status, None


async def run_alerts(deps: AlertDeps, *, now: datetime | None = None, user_ids: Sequence[UUID] | None = None) -> Report:
    """One pass of ``saved_searches.alert`` (``user_ids``: only those people's searches)."""
    async with deps.factory() as db:
        clock = now or await app_now(db)
        listed = (await db.execute(_DUE, {"now": clock})).tuples().all()
    wanted = None if user_ids is None else set(user_ids)
    by_user: dict[UUID, list[UUID]] = defaultdict(list)
    for user_id, search_id in listed:
        if wanted is None or user_id in wanted:
            by_user[user_id].append(search_id)
    outcomes = []
    for user_id, search_ids in by_user.items():
        try:  # one person never stops the run; their searches stay due
            outcomes.append(await alert_user(deps, user_id, search_ids, clock))
        except Exception as exc:
            log.error("saved_searches.alert_failed", user_id=str(user_id), error_type=type(exc).__name__)
            outcomes.append(Outcome(user_id, error=True))
    report = Report(clock, tuple(outcomes))
    log.info(
        "saved_searches.alerted",
        recipients=len(outcomes),
        items=sum(len(o.alerts) for o in outcomes),
        matched=sum(a.notified for o in outcomes for a in o.alerts),
        failed=sum(o.error for o in outcomes),
    )
    return report
