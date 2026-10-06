"""The staff events queue (REQ-DEV-02, REQ-ADM-01; D-60; P22 card B, default (1)): ``/api/admin/events``.

Every route needs staff whose TOTP is enrolled and whose second factor is fresh (``bridge.admin.deps``: 404 for
everyone else, a developer and an organisation's member included; 403 ``step_up_required`` for an old second factor).
Staff admins post platform events; staff admins and moderators read the queue and decide. The database repeats the rule
(staff read every event; ``app_decide_event`` and ``app_cancel_event`` refuse anyone else).

- ``POST`` (staff admin): 201, a platform event (no organisation, "Platform" as the organiser) as a draft, audited
  ``event.created``; 422 ``invalid_event`` as the organisations' form.
- ``GET ?status=draft|published|rejected|cancelled`` and ``GET /{id}``: newest first, with ``updated_at``, the version
  the reviewer reads.
- ``POST /{id}/decision`` ``{decision: publish|reject, seen}``: before the definer, an organisation's event is decided
  only while the organisation is still E2 and neither suspended nor delisted (409 ``organisation_unavailable``); then
  ``app_decide_event(event, decision, seen)``: 409 ``already_decided`` (not a draft), ``changed_since_review`` (the
  poster edited it after ``seen``: reload and review again) or ``event_over`` (an ended event is only rejected).
  Audited ``event.decided`` on the staff member's chain, with the decision and the organisation.
- ``POST /{id}/cancel``: through ``app_cancel_event`` (409 ``not_cancellable``), audited ``event.cancelled``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bridge.admin.deps import StaffAdmin, StaffModerator
from bridge.audit.service import record as audit
from bridge.auth.deps import Db
from bridge.errors import ERROR_RESPONSES, ApiError, ApiErrorBody, not_found
from bridge.events import service
from bridge.events.schemas import EventDecisionIn, EventIn, EventList, EventOut, EventStatus
from bridge.models.enums import AuditActor

router = APIRouter(prefix="/api/admin/events", tags=["admin"], responses=ERROR_RESPONSES)

_DECIDE: Final = text("SELECT app_decide_event(:e, :d, :seen)")
NO_EVENT: Final = "No such event."
# [[COPY-REVIEW]] the queue's refusals. app_decide_event's messages (revision 0010) tell its 55000 refusals apart.
UNAVAILABLE: Final = "The organisation is no longer verified, or it is suspended or delisted: reject the event."
_DECISION_CONFLICTS: Final[Mapping[str, tuple[str, str]]] = {
    "the event changed since it was reviewed": (
        "changed_since_review",
        "The event changed after you opened it. Reload it and review it again.",
    ),
    "the event is over": ("event_over", "The event is over, so it can be rejected but not published."),
    "only a draft event is decided": ("already_decided", "This event was already decided or cancelled."),
}
DECISION_409: Final = "already_decided, changed_since_review, event_over or organisation_unavailable"


@router.post("", status_code=201)
async def post_platform_event(body: EventIn, staff: StaffAdmin, db: Db) -> EventOut:
    """A platform event ("Platform" as the organiser), waiting on the queue like any other."""
    return await service.create(db, body, actor_id=staff.live.user.id, org_id=None, staff=True)


@router.get("")
async def list_admin_events(
    staff: StaffModerator,
    db: Db,
    status: EventStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> EventList:
    """Every event, newest first (``status`` filters)."""
    return EventList(items=await service.list_events(db, status=status, limit=limit))


@router.get("/{event_id}")
async def get_admin_event(event_id: UUID, staff: StaffModerator, db: Db) -> EventOut:
    found = await service.find(db, event_id)
    if found is None:
        raise not_found(NO_EVENT)
    return found


def _conflict(exc: DBAPIError) -> ApiError | None:
    message = str(getattr(getattr(exc.orig, "diag", None), "message_primary", "") or "")
    for marker, (code, sentence) in _DECISION_CONFLICTS.items():
        if marker in message:
            return ApiError(409, code, sentence)
    return None


@router.post(
    "/{event_id}/decision",
    responses={409: {"model": ApiErrorBody, "description": DECISION_409}},
)
async def decide_event(event_id: UUID, body: EventDecisionIn, staff: StaffModerator, db: Db) -> EventOut:
    """Publish or reject a draft, on exactly the version read (see the module docstring)."""
    found = await service.find(db, event_id)
    if found is None:
        raise not_found(NO_EVENT)
    if found.org_id is not None and body.decision == "publish" and await service.org_standing(db, found.org_id):
        raise ApiError(409, "organisation_unavailable", UNAVAILABLE)
    try:
        await db.execute(_DECIDE, {"e": event_id, "d": body.decision, "seen": body.seen})
    except DBAPIError as exc:
        await db.rollback()
        state = service.sqlstate(exc)
        if state in ("P0002", "42501"):
            raise not_found(NO_EVENT) from None
        conflict = _conflict(exc) if state == "55000" else None
        if conflict is None:
            raise
        raise conflict from None
    await audit(
        db,
        "event.decided",
        actor_user_id=staff.live.user.id,
        actor_kind=AuditActor.STAFF,
        subject_type="event",
        subject_id=event_id,
        payload={
            "decision": body.decision,
            "org_id": None if found.org_id is None else str(found.org_id),
            "online": found.online,
        },
    )
    await db.commit()
    return await service.get_one(db, event_id)


@router.post("/{event_id}/cancel")
async def cancel_admin_event(event_id: UUID, staff: StaffModerator, db: Db) -> EventOut:
    """Cancel a draft or published event (an organisation's or the platform's)."""
    return await service.cancel(db, actor_id=staff.live.user.id, event_id=event_id, staff=True)
