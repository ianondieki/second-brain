"""This week's API (REQ-DEV-02; D-60, D-61; docs/platform/tasks/P22.md section B).

Organisation routes, ``/api/orgs/{org_id}/events`` (a non-member 404, a member without the role 403, another
organisation's event 404):

- ``GET`` (any member): the organisation's events, newest first, any status. ``GET /{id}`` likewise.
- ``POST`` (an editor: owner, admin, signatory or reviewer, as Briefs): 201, a draft waiting on the staff queue; 403
  ``verification_required`` unless the organisation is E2 (``org_unavailable`` while suspended or delisted), 429
  ``events_daily_limit`` beyond ``events.daily_posts`` a Nairobi day, 422 ``invalid_event`` (a code per field).
  Audited ``event.created``.
- ``PUT /{id}`` (the poster, an editor of an E2 organisation): replaces the content of a draft (409 ``not_draft``,
  403 ``not_poster``). ``POST /{id}/cancel`` (an editor): through ``app_cancel_event`` (409 ``not_cancellable``),
  audited ``event.cancelled``.

Developer routes (developers only: an organisation-only account and staff get 404 as on the quiz's routes; signed out
401):

- ``GET /api/me/week``: ``WeekOut``, at most 3 events of this week and next in the caller's county or online, the
  trend of the day and what the day-before email's gate says (one statement for the events, one for the trend).
  ``GET /api/me/week/events``: the same events without the cap (the ``/dev/week`` page).
- ``GET /api/me/trends/{id}``: a published trend card with its sources and the label's date; 404 otherwise.
- ``POST /api/me/events/{id}/reminder``: 201 ``{reminder: true, email}``, idempotent; 404 unless the event is published
  and has not ended. ``DELETE`` the same: 204, idempotent (the job then sends nothing).

Any signed-in reader of a published event (a developer, or a member of its organisation; 404 for anyone else):
``GET /api/events/{id}`` (the event page) and ``GET /api/events/{id}/calendar.ics`` (``text/calendar``, an attachment,
``private, no-store``).
"""

from __future__ import annotations

from typing import Annotated, Any, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import DBAPIError

from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.auth.sessions import LiveSession
from bridge.errors import ERROR_RESPONSES, json_errors, not_found
from bridge.events import calendar, service, week
from bridge.events.models import EventReminder
from bridge.events.schemas import (
    EventIn,
    EventList,
    EventOut,
    EventPageOut,
    ReminderOut,
    TrendCardDetailOut,
    WeekEventsOut,
    WeekOut,
)
from bridge.problems import brief_rules
from bridge.problems.trends import store as trends
from bridge.tenancy.deps import OrgContext, OrgMember, org_member

router = APIRouter(tags=["events"], responses=ERROR_RESPONSES)
PREFIX: Final = "/api/orgs/{org_id}/events"
EventEditor = Annotated[OrgContext, Depends(org_member(*brief_rules.EDITORS))]
_IS_DEVELOPER: Final = text("SELECT app_is_developer()")
NO_EVENT: Final = "No published event has this id."
NO_TREND: Final = "No published trend has this id."
ICS_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    200: {"content": {"text/calendar": {}}, "description": "The event as an iCalendar file"},
    **json_errors(401, 404),
}


@router.get(PREFIX)
async def list_org_events(org: OrgMember, db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 100) -> EventList:
    """The organisation's events, newest first, in every status."""
    return EventList(items=await service.list_events(db, org_id=org.org_id, limit=limit))


@router.post(PREFIX, status_code=201)
async def post_event(body: EventIn, org: EventEditor, db: Db) -> EventOut:
    """Post an event: a draft until staff publish it."""
    return await service.create(db, body, actor_id=org.live.user.id, org_id=org.org_id)


@router.get(f"{PREFIX}/{{event_id}}")
async def get_org_event(event_id: UUID, org: OrgMember, db: Db) -> EventOut:
    return await service.get_one(db, event_id, org_id=org.org_id)


@router.put(f"{PREFIX}/{{event_id}}")
async def edit_event(event_id: UUID, body: EventIn, org: EventEditor, db: Db) -> EventOut:
    """Replace the content of your draft (an event staff decided, or a cancelled one, is 409 ``not_draft``)."""
    await service.require_e2(db, org.org_id)
    return await service.edit(db, body, actor_id=org.live.user.id, org_id=org.org_id, event_id=event_id)


@router.post(f"{PREFIX}/{{event_id}}/cancel")
async def cancel_org_event(event_id: UUID, org: EventEditor, db: Db) -> EventOut:
    """Cancel a draft or published event of the organisation."""
    return await service.cancel(db, actor_id=org.live.user.id, event_id=event_id, org_id=org.org_id)


# ------------------------------------------------------------------------------------------------------- developers


async def week_developer(live: CurrentSession, db: Db) -> LiveSession:
    """A developer (``app_is_developer()``); 404 for everyone else signed in."""
    if not await db.scalar(_IS_DEVELOPER):
        raise not_found()
    return live


Developer = Annotated[LiveSession, Depends(week_developer)]


@router.get("/api/me/week")
async def my_week(live: Developer, db: Db) -> WeekOut:
    """Home's This week strip: up to three events, the trend of the day and the email gate's answer."""
    return WeekOut(
        events=await week.week_events(db),
        trend=await trends.trend_of_day(db),
        reminders_email=await week.email_state(db, live),
    )


@router.get("/api/me/week/events")
async def my_week_events(live: Developer, db: Db) -> WeekEventsOut:
    """Every event of this week and next for the caller (the strip's filter without its cap)."""
    return WeekEventsOut(items=await week.week_events(db, limit=None), reminders_email=await week.email_state(db, live))


@router.get("/api/me/trends/{card_id}")
async def my_trend(card_id: UUID, live: Developer, db: Db) -> TrendCardDetailOut:
    """A published trend card with its sources (its "Read more" page)."""
    found = await trends.published_card(db, card_id)
    if found is None:
        raise not_found(NO_TREND)
    return found


@router.post("/api/me/events/{event_id}/reminder", status_code=201)
async def remind_me(event_id: UUID, live: Developer, db: Db) -> ReminderOut:
    """Remind me: one email the day before (with the reminders consent and a verified address) and one in-app notice
    the morning of. Asking again changes nothing."""
    if not await week.can_remind(db, event_id):
        raise not_found(NO_EVENT)
    try:
        await db.execute(
            pg_insert(EventReminder).values(user_id=live.user.id, event_id=event_id).on_conflict_do_nothing()
        )
    except DBAPIError as exc:  # published and running when read, not any more (the policy): as if it never was
        await db.rollback()
        if service.sqlstate(exc) != "42501":
            raise
        raise not_found(NO_EVENT) from None
    email = await week.email_state(db, live)
    await db.commit()
    return ReminderOut(reminder=True, email=email)


@router.delete("/api/me/events/{event_id}/reminder", status_code=204, response_class=Response)
async def decline_reminder(event_id: UUID, live: Developer, db: Db) -> None:
    """Decline: neither the email nor the in-app notice comes. Declining again changes nothing."""
    await db.execute(
        delete(EventReminder).where(EventReminder.user_id == live.user.id, EventReminder.event_id == event_id)
    )
    await db.commit()


@router.get("/api/events/{event_id}")
async def event_page(event_id: UUID, live: CurrentSession, db: Db) -> EventPageOut:
    """A published event's page, for developers and its organisation's members."""
    found = await week.event_page(db, event_id)
    if found is None:
        raise not_found(NO_EVENT)
    return found


@router.get(
    "/api/events/{event_id}/calendar.ics",
    response_class=Response,
    responses=ICS_RESPONSES,
)
async def event_calendar(event_id: UUID, live: CurrentSession, db: Db, settings: SettingsDep) -> Response:
    """Add to calendar: the published event as an ``.ics`` file (byte-stable until the event changes)."""
    row = await week.page_row(db, event_id)
    if row is None:
        raise not_found(NO_EVENT)
    body = calendar.ics(
        week.calendar_event(row), host=calendar.public_host(settings.public_base_url), product=settings.product_name
    )
    return Response(
        content=body,
        media_type=calendar.MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{calendar.filename(event_id)}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
