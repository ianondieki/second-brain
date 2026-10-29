"""Deadlines API: the calendar, its ``.ics`` files and the private feeds (REQ-ENG-13; docs/platform/tasks/P27.md track
A; D-61, D-70).

Signed in:

- ``GET /api/me/deadlines?from=&to=``: the caller's deadlines as a developer; ``GET /api/orgs/{org_id}/deadlines`` the
  organisation's (any member; a non-member 404). ``DeadlineList`` sorted by ``due_at``: by default every overdue item
  and the next 90 days, else what falls due from ``from`` to ``to`` (Nairobi dates, at most 366 days apart; 422
  ``invalid_range``) (``bridge.engagements.deadlines``).
- ``GET .../deadlines/{kind}/{id}/calendar.ics`` on both: one deadline as an iCalendar file (an attachment); 404 when
  it is not the caller's.
- ``GET``, ``POST`` and ``DELETE /api/me/calendar-feed`` and ``/api/orgs/{org_id}/calendar-feed`` (any member): the
  live feed's status, a new feed (201 ``{url}``: rotates, the old URL answers 404 at once) and revoking it (204,
  idempotent). Creating and revoking are audited (``calendar_feed.created``, ``calendar_feed.revoked``; ids only).

Unauthenticated (D-70: the token is the capability): ``GET /api/calendar/{token}.ics``, the same deadlines as the
list's default as one named calendar (``X-WR-CALNAME``: ``<product> deadlines``, and for a member's feed of an
organisation ``<product> deadlines · <its legal name>``); 404 for an unknown, revoked or malformed
token (one body for all three); 429 ``too_many_fetches`` with ``Retry-After`` past 60 reads an hour of one feed; never
a cookie; ``Cache-Control: private, no-store``; each read stamps the feed's ``last_fetched_at``.

Every file and list carries titles, dates and names only: never a note, a message, a Brief's statement or a proposal's
text. Responses carry ``X-App-Now`` (the app's middleware).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements import deadlines, feeds
from bridge.engagements.calendar import local_date
from bridge.engagements.deadlines import Deadline, Viewer
from bridge.engagements.schemas import CalendarFeedOut, CalendarFeedStatus, DeadlineKind, DeadlineList
from bridge.engagements.service import app_now
from bridge.errors import ERROR_RESPONSES, json_errors, not_found
from bridge.events import calendar
from bridge.public_demo import LOCKED
from bridge.tenancy.deps import OrgMember
from bridge.tenancy.models import Organization

router = APIRouter(tags=["deadlines"], responses=ERROR_RESPONSES)

ME: Final = "/api/me"
ORG: Final = "/api/orgs/{org_id}"
ICS_CACHE: Final = "private, no-store"
SECTION: Final = "Deadlines"
FEED_NAME: Final = "{product} deadlines"  # [[COPY-REVIEW]] the subscribed calendar's name (a personal feed)
ORG_FEED_NAME: Final = "{product} deadlines · {org}"  # a member's feed of an organisation: its legal name
NO_FEED: Final = "No live calendar feed has this address."
ICS_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    200: {"content": {"text/calendar": {}}, "description": "The deadline as an iCalendar file"},
    **json_errors(401, 404, 422),
}
FEED_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    200: {"content": {"text/calendar": {}}, "description": "The deadlines as a named iCalendar feed"},
    **json_errors(404, 429),
}
From = Annotated[date | None, Query(alias="from", description="First Nairobi date; omitted: every overdue item")]
To = Annotated[date | None, Query(alias="to", description="Last Nairobi date; omitted: 90 days after from (or today)")]


async def _list(db: Db, settings: Settings, viewer: Viewer, start: date | None, end: date | None) -> DeadlineList:
    now = await app_now(db)
    frame = deadlines.window(local_date(now), start, end)
    found = await deadlines.list_deadlines(
        db,
        viewer,
        frame=frame,
        now=now,
        deals_enabled=settings.feature_deals_enabled,
        platform_name=settings.product_name,
    )
    return DeadlineList(items=[d.out for d in found], now=now)


@router.get(f"{ME}/deadlines")
async def my_deadlines(
    live: CurrentSession, db: Db, settings: SettingsDep, start: From = None, end: To = None
) -> DeadlineList:
    """Every deadline the caller carries as a developer: stage deadlines, answer-by dates, milestones, the Briefs they
    pitched to and the events they asked to be reminded of."""
    return await _list(db, settings, Viewer(live.user.id), start, end)


@router.get(f"{ORG}/deadlines")
async def org_deadlines(
    org: OrgMember, db: Db, settings: SettingsDep, start: From = None, end: To = None
) -> DeadlineList:
    """Every deadline of the organisation: its engagements' stage deadlines, answer-by dates and milestones, its open
    Briefs and its published events."""
    return await _list(db, settings, Viewer(org.live.user.id, org.org_id), start, end)


def _ics(found: Deadline, settings: Settings, stamp: datetime) -> Response:
    entry = deadlines.calendar_entry(found, base_url=settings.public_base_url, stamp=stamp)
    body = calendar.calendar_file([entry], product=settings.product_name, section=SECTION)
    filename = f"{found.item.kind.value}-{found.item.item_id}.ics"
    return Response(
        content=body,
        media_type=calendar.MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": ICS_CACHE,
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _one(db: Db, settings: Settings, viewer: Viewer, kind: DeadlineKind, item_id: UUID) -> Response:
    now = await app_now(db)
    found = await deadlines.one_deadline(
        db,
        viewer,
        kind,
        item_id,
        now=now,
        deals_enabled=settings.feature_deals_enabled,
        platform_name=settings.product_name,
    )
    return _ics(found, settings, now)


@router.get(f"{ME}/deadlines/{{kind}}/{{item_id}}/calendar.ics", response_class=Response, responses=ICS_RESPONSES)
async def my_deadline_calendar(
    kind: DeadlineKind, item_id: UUID, live: CurrentSession, db: Db, settings: SettingsDep
) -> Response:
    """Add to calendar: one of the caller's deadlines as an ``.ics`` file (a 15-minute entry at its instant)."""
    return await _one(db, settings, Viewer(live.user.id), kind, item_id)


@router.get(f"{ORG}/deadlines/{{kind}}/{{item_id}}/calendar.ics", response_class=Response, responses=ICS_RESPONSES)
async def org_deadline_calendar(
    kind: DeadlineKind, item_id: UUID, org: OrgMember, db: Db, settings: SettingsDep
) -> Response:
    """Add to calendar: one of the organisation's deadlines as an ``.ics`` file."""
    return await _one(db, settings, Viewer(org.live.user.id, org.org_id), kind, item_id)


# ------------------------------------------------------------------------------------------------------- the feeds


async def _create(db: Db, settings: Settings, user_id: UUID, org_id: UUID | None) -> CalendarFeedOut:
    created = await feeds.rotate(db, user_id, org_id)
    await audit(
        db,
        "calendar_feed.created",
        actor_user_id=user_id,
        org_id=org_id,
        subject_type="calendar_feed",
        subject_id=created.feed_id,
        payload={"replaced": str(created.replaced) if created.replaced else None},
    )
    await db.commit()
    return CalendarFeedOut(url=feeds.feed_url(settings.public_base_url, created.token))


async def _revoke(db: Db, user_id: UUID, org_id: UUID | None) -> None:
    revoked = await feeds.revoke(db, user_id, org_id)
    if revoked is not None:
        await audit(
            db,
            "calendar_feed.revoked",
            actor_user_id=user_id,
            org_id=org_id,
            subject_type="calendar_feed",
            subject_id=revoked,
        )
    await db.commit()


@router.get(f"{ME}/calendar-feed")
async def my_feed(live: CurrentSession, db: Db) -> CalendarFeedStatus:
    """Whether the caller has a live personal feed (its URL is shown only when it is created)."""
    return await feeds.status(db, live.user.id, None)


@router.post(f"{ME}/calendar-feed", status_code=201, dependencies=[LOCKED])  # REQ-FND-04: no public URL
async def create_my_feed(live: CurrentSession, db: Db, settings: SettingsDep) -> CalendarFeedOut:
    """A private feed of the caller's deadlines (a new URL; the previous one stops working at once)."""
    return await _create(db, settings, live.user.id, None)


@router.delete(f"{ME}/calendar-feed", status_code=204, response_class=Response)
async def revoke_my_feed(live: CurrentSession, db: Db) -> None:
    """Turn the personal feed off: its URL answers 404 from now on."""
    await _revoke(db, live.user.id, None)


@router.get(f"{ORG}/calendar-feed")
async def org_feed(org: OrgMember, db: Db) -> CalendarFeedStatus:
    """Whether the caller has a live feed of this organisation's deadlines."""
    return await feeds.status(db, org.live.user.id, org.org_id)


@router.post(f"{ORG}/calendar-feed", status_code=201, dependencies=[LOCKED])  # REQ-FND-04: no public URL
async def create_org_feed(org: OrgMember, db: Db, settings: SettingsDep) -> CalendarFeedOut:
    """A private feed of the organisation's deadlines, for the caller (one per member)."""
    return await _create(db, settings, org.live.user.id, org.org_id)


@router.delete(f"{ORG}/calendar-feed", status_code=204, response_class=Response)
async def revoke_org_feed(org: OrgMember, db: Db) -> None:
    """Turn the caller's feed of this organisation off."""
    await _revoke(db, org.live.user.id, org.org_id)


async def _feed_name(db: Db, settings: Settings, feed: feeds.FeedRef) -> str:
    """The subscribed calendar's name: the product's, and an organisation feed's organisation (its legal name)."""
    org = None
    if feed.org_id is not None:
        org = await db.scalar(select(Organization.legal_name).where(Organization.id == feed.org_id))
    if org is None:
        return FEED_NAME.format(product=settings.product_name)
    return ORG_FEED_NAME.format(product=settings.product_name, org=org)


@router.get(
    feeds.FEED_PATH,
    response_class=Response,
    responses=FEED_RESPONSES,
    openapi_extra={"security": []},
)
async def read_feed(token: str, db: Db, settings: SettingsDep) -> Response:
    """A calendar app's read of a private feed: no session, the token in the URL is the capability (D-70)."""
    digest = feeds.token_hash(token)
    feed = await feeds.lookup(db, digest) if digest is not None else None
    if digest is None or feed is None:
        raise not_found(NO_FEED)
    await bind_tenant(db, user_id=feed.user_id, org_id=feed.org_id)
    if not await feeds.verify(db, feed, digest):  # revoked between the two reads, or not the row the lookup named
        raise not_found(NO_FEED)
    await feeds.spend_fetch(db, settings, feed)
    now = await app_now(db)
    found = await deadlines.list_deadlines(
        db,
        Viewer(feed.user_id, feed.org_id),
        frame=deadlines.window(local_date(now), None, None),
        now=now,
        deals_enabled=settings.feature_deals_enabled,
        platform_name=settings.product_name,
    )
    name = await _feed_name(db, settings, feed)
    await feeds.touch(db, feed)
    await db.commit()
    entries = [deadlines.calendar_entry(d, base_url=settings.public_base_url, stamp=now) for d in found]
    body = calendar.calendar_file(entries, product=settings.product_name, section=SECTION, name=name)
    return Response(
        content=body,
        media_type=calendar.MEDIA_TYPE,
        headers={
            "Content-Disposition": 'inline; filename="deadlines.ics"',
            "Cache-Control": ICS_CACHE,
            "X-Content-Type-Options": "nosniff",
        },
    )
