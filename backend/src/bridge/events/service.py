"""This week's events: posting, editing, cancelling and reading them (REQ-DEV-02; D-60; P22 card B, default (1)).

Plain code decides everything here; the database repeats the rules (revision 0010: the policies, ``events_guard``, the
definers ``app_decide_event`` and ``app_cancel_event``).

- Who posts: an editor of an organisation (owner, admin, signatory or reviewer: the Briefs' editors) for that
  organisation, which must be E2 and neither suspended nor delisted (403 ``verification_required`` /
  ``org_unavailable``, Briefs' rule), at most ``events.daily_posts`` (policy.yaml) a Nairobi day on the shared clock
  under a per-organisation lock (429 ``events_daily_limit``); or a staff admin for the platform (no organisation, no
  cap). Every event starts as a draft on the staff queue: nothing here writes a status.
- What: the text cleaned (``bridge.events.text``); times with their offset, stored in UTC, starting after the shared
  clock's now and lasting at most 3 days; online with a join address and no venue or county, or at a venue in a county
  (a ``regions`` row of kind county) without one. Refusals are 422 ``invalid_event`` with a code per field.
- Editing: the poster's own draft only (409 ``not_draft`` once decided or cancelled, 403 ``not_poster`` for another
  editor), audited ``event.updated``. The database sets ``updated_at`` on every content change, so a reviewer who read
  the event before is refused (``changed_since_review``).
- Cancelling: through ``app_cancel_event`` (an editor of the organisation, or staff), a draft or published event (409
  ``not_cancellable`` otherwise), audited ``event.cancelled``.
- Reads never carry who posted (``created_by``) or who decided (``decided_by``, never selected): the audit events do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import Select, insert, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.directory.models import Region
from bridge.errors import ApiError, forbidden, not_found
from bridge.events import text as rules
from bridge.events.models import MAX_SPAN_DAYS, Event
from bridge.events.policy import get_events_policy
from bridge.events.schemas import EventIn, EventOut
from bridge.ids import uuid7
from bridge.models.enums import AuditActor, OrgVerification, RegionKind
from bridge.proposals.sanitise import FieldError
from bridge.tenancy.models import Organization

PLATFORM: Final = "Platform"  # the organiser of a staff event [[COPY-REVIEW]]
# [[COPY-REVIEW]] the refusals' sentences (the field sentences are bridge.events.text.MESSAGES).
NOT_VERIFIED: Final = "Only organisations with legal verification (E2) can post events."
UNAVAILABLE: Final = "Your organisation cannot post events while it is suspended or delisted."
DAILY_LIMIT: Final = "Your organisation has posted as many events as it can today. Try again tomorrow."
NOT_DRAFT: Final = "Only an event waiting for review can be edited. Post a new event to change it."
NOT_POSTER: Final = "Only the person who posted this event can edit it."
NOT_CANCELLABLE: Final = "This event was already decided or cancelled."
NO_EVENT: Final = "No event of yours has this id."

_NOW: Final = text("SELECT app_clock_now()")
# One count at a time per organisation (as Briefs): released at commit or rollback, so parallel posts cannot pass it.
_DAILY_LOCK: Final = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
# Events the organisation posted since the start of today in Nairobi, on the shared clock (events.created_at's).
_POSTED_TODAY: Final = text(
    "SELECT count(*) FROM events WHERE org_id = :org AND created_at >= (date_trunc('day', app_clock_now()"
    " AT TIME ZONE 'Africa/Nairobi') AT TIME ZONE 'Africa/Nairobi')"
)
_CANCEL: Final = text("SELECT app_cancel_event(:e)")
CONTENT: Final = ("title", "description", "starts_at", "ends_at", "online", "venue", "county_code", "join_url", "link")


async def clock_now(db: AsyncSession) -> datetime:
    now: datetime = (await db.execute(_NOW)).scalar_one()
    return now


def sqlstate(exc: DBAPIError) -> str:
    return str(getattr(exc.orig, "sqlstate", None))


# --- who may post ------------------------------------------------------------------------------------------------


async def org_standing(db: AsyncSession, org_id: UUID) -> str | None:
    """Why the organisation may not post or have an event published (``verification_required``: not E2;
    ``org_unavailable``: suspended or delisted; also when the caller cannot read it), or None when it may."""
    org = (
        await db.execute(
            select(Organization.verification, Organization.suspended_at, Organization.delisted_at).where(
                Organization.id == org_id
            )
        )
    ).one_or_none()
    if org is None:
        return "org_unavailable"
    if org.verification is not OrgVerification.E2:
        return "verification_required"
    if org.suspended_at is not None or org.delisted_at is not None:
        return "org_unavailable"
    return None


async def require_e2(db: AsyncSession, org_id: UUID) -> None:
    """403 unless the organisation is E2 and neither suspended nor delisted (Briefs' ``_require_e2``)."""
    standing = await org_standing(db, org_id)
    if standing == "verification_required":
        raise forbidden(standing, NOT_VERIFIED)
    if standing is not None:
        raise forbidden(standing, UNAVAILABLE)


# --- the form ------------------------------------------------------------------------------------------------------


def _optional(value: str | None) -> str | None:
    """A venue or county the form left blank is absent."""
    return value if value is not None and rules.one_line(value) else None


async def checked(db: AsyncSession, body: EventIn) -> dict[str, Any]:
    """The event's content columns, cleaned and checked (see the module docstring); 422 ``invalid_event`` with every
    field's code otherwise."""
    errors: list[FieldError] = []
    values: dict[str, Any] = {
        "title": rules.text_field("title", body.title, errors),
        "description": rules.text_field("description", body.description, errors),
        "online": body.online,
    }
    venue_raw, county = _optional(body.venue), _optional(body.county_code)
    venue = None if venue_raw is None else rules.text_field("venue", venue_raw, errors)
    join_url = rules.link("join_url", body.join_url, errors)
    values["link"] = rules.link("link", body.link, errors)
    if body.online:
        if join_url is None:
            errors.append(rules.error("join_url", "join_url_required"))
        if venue is not None or county is not None:
            errors.append(rules.error("venue" if venue is not None else "county_code", "online_has_place"))
        venue, county = None, None
    else:
        if venue is None:
            errors.append(rules.error("venue", "venue_required"))
        if county is None:
            errors.append(rules.error("county_code", "county_required"))
        if join_url is not None:
            errors.append(rules.error("join_url", "venue_has_join_url"))
        join_url = None
    if county is not None:
        known = select(Region.code).where(Region.code == county, Region.kind == RegionKind.COUNTY)
        if await db.scalar(known) is None:
            errors.append(rules.error("county_code", "unknown_county"))
    starts, ends = body.starts_at.astimezone(UTC), body.ends_at.astimezone(UTC)
    if starts <= await clock_now(db):
        errors.append(rules.error("starts_at", "start_past"))
    if ends <= starts:
        errors.append(rules.error("ends_at", "end_before_start"))
    elif ends - starts > timedelta(days=MAX_SPAN_DAYS):
        errors.append(rules.error("ends_at", "span_too_long"))
    if errors:
        raise rules.invalid(errors)
    return values | {"venue": venue, "county_code": county, "join_url": join_url, "starts_at": starts, "ends_at": ends}


def _write_refusal(exc: DBAPIError) -> ApiError | None:
    """The database's refusals of a write that the form checked first (a race, such as a county removed): 422."""
    if sqlstate(exc) in ("23503", "23514"):
        return rules.invalid([])
    return None


# --- reads ---------------------------------------------------------------------------------------------------------


def _select() -> Select[Any]:
    return (
        select(
            Event.id,
            Event.org_id,
            Organization.legal_name.label("org_name"),
            Event.title,
            Event.description,
            Event.starts_at,
            Event.ends_at,
            Event.online,
            Event.venue,
            Event.county_code,
            Region.name.label("county_name"),
            Event.join_url,
            Event.link,
            Event.status,
            Event.decided_at,
            Event.cancelled_at,
            Event.created_at,
            Event.updated_at,
        )
        .select_from(Event)
        .outerjoin(Organization, Organization.id == Event.org_id)
        .outerjoin(Region, Region.code == Event.county_code)
    )


def organiser(org_id: UUID | None, org_name: str | None) -> str | None:
    return PLATFORM if org_id is None else org_name


def event_out(row: Any) -> EventOut:
    return EventOut(
        id=row.id,
        org_id=row.org_id,
        organiser=organiser(row.org_id, row.org_name),
        title=row.title,
        description=row.description,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        online=row.online,
        venue=row.venue,
        county_code=row.county_code,
        county_name=row.county_name,
        join_url=row.join_url,
        link=row.link,
        status=row.status,
        decided_at=row.decided_at,
        cancelled_at=row.cancelled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def find(db: AsyncSession, event_id: UUID, *, org_id: UUID | None = None) -> EventOut | None:
    """One event as the caller reads it under RLS (``org_id``: only that organisation's)."""
    stmt = _select().where(Event.id == event_id)
    if org_id is not None:
        stmt = stmt.where(Event.org_id == org_id)
    row = (await db.execute(stmt)).one_or_none()
    return None if row is None else event_out(row)


async def get_one(db: AsyncSession, event_id: UUID, *, org_id: UUID | None = None) -> EventOut:
    found = await find(db, event_id, org_id=org_id)
    if found is None:
        raise not_found(NO_EVENT)
    return found


async def list_events(
    db: AsyncSession, *, org_id: UUID | None = None, status: str | None = None, limit: int = 100
) -> list[EventOut]:
    """Events newest first (``org_id``: that organisation's; ``status``: of that status), as the caller reads them."""
    stmt = _select()
    if org_id is not None:
        stmt = stmt.where(Event.org_id == org_id)
    if status is not None:
        stmt = stmt.where(Event.status == status)
    rows = (await db.execute(stmt.order_by(Event.created_at.desc(), Event.id.desc()).limit(limit))).all()
    return [event_out(row) for row in rows]


# --- writes --------------------------------------------------------------------------------------------------------


async def create(
    db: AsyncSession, body: EventIn, *, actor_id: UUID, org_id: UUID | None, staff: bool = False
) -> EventOut:
    """Post a draft: for ``org_id`` by its editor (E2, the daily cap), or for the platform by a staff admin."""
    if org_id is not None:
        await require_e2(db, org_id)
        await db.execute(_DAILY_LOCK, {"key": f"events.daily:{org_id}"})
        if (await db.execute(_POSTED_TODAY, {"org": org_id})).scalar_one() >= get_events_policy().daily_posts:
            raise ApiError(429, "events_daily_limit", DAILY_LIMIT)
    values = await checked(db, body)
    event_id = uuid7()
    try:
        await db.execute(insert(Event).values(id=event_id, org_id=org_id, created_by=actor_id, **values))
        await audit(
            db,
            "event.created",
            actor_user_id=actor_id,
            actor_kind=AuditActor.STAFF if staff else AuditActor.USER,
            org_id=org_id,
            subject_type="event",
            subject_id=event_id,
            payload={"online": values["online"], "platform": org_id is None},
        )
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        refusal = _write_refusal(exc)
        if refusal is None:
            raise
        raise refusal from None
    return await get_one(db, event_id)


async def edit(db: AsyncSession, body: EventIn, *, actor_id: UUID, org_id: UUID, event_id: UUID) -> EventOut:
    """Replace the content of the caller's own draft (see the module docstring)."""
    row = (
        await db.execute(select(Event.status, Event.created_by).where(Event.id == event_id, Event.org_id == org_id))
    ).one_or_none()
    if row is None:
        raise not_found(NO_EVENT)
    if row.status != "draft":
        raise ApiError(409, "not_draft", NOT_DRAFT)
    if row.created_by != actor_id:
        raise forbidden("not_poster", NOT_POSTER)
    values = await checked(db, body)
    try:
        changed = await db.execute(
            update(Event)
            .where(Event.id == event_id, Event.org_id == org_id, Event.status == "draft")
            .values(**values)
            .returning(Event.id)
        )
        if changed.one_or_none() is None:  # decided or cancelled since it was read
            await db.rollback()
            raise ApiError(409, "not_draft", NOT_DRAFT)
        await audit(
            db,
            "event.updated",
            actor_user_id=actor_id,
            org_id=org_id,
            subject_type="event",
            subject_id=event_id,
            payload={"online": values["online"]},
        )
        await db.commit()
    except DBAPIError as exc:
        await db.rollback()
        refusal = _write_refusal(exc)
        if refusal is None:
            raise
        raise refusal from None
    return await get_one(db, event_id, org_id=org_id)


async def cancel(
    db: AsyncSession, *, actor_id: UUID, event_id: UUID, org_id: UUID | None = None, staff: bool = False
) -> EventOut:
    """Cancel a draft or published event through ``app_cancel_event`` (404 for an event the caller may not cancel,
    409 ``not_cancellable`` once decided otherwise or cancelled)."""
    found = await find(db, event_id, org_id=org_id)
    if found is None:
        raise not_found(NO_EVENT)
    try:
        await db.execute(_CANCEL, {"e": event_id})
    except DBAPIError as exc:
        await db.rollback()
        state = sqlstate(exc)
        if state == "42501":
            raise not_found(NO_EVENT) from None
        if state == "55000":
            raise ApiError(409, "not_cancellable", NOT_CANCELLABLE) from None
        raise
    await audit(
        db,
        "event.cancelled",
        actor_user_id=actor_id,
        actor_kind=AuditActor.STAFF if staff else AuditActor.USER,
        org_id=None if staff else org_id,
        subject_type="event",
        subject_id=event_id,
        payload={"was": found.status, "org_id": None if found.org_id is None else str(found.org_id)},
    )
    await db.commit()
    return await get_one(db, event_id)
