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
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from bridge.auth.deps import Db
from bridge.errors import ERROR_RESPONSES
from bridge.events import service
from bridge.events.schemas import EventIn, EventList, EventOut
from bridge.problems import brief_rules
from bridge.tenancy.deps import OrgContext, OrgMember, org_member

router = APIRouter(tags=["events"], responses=ERROR_RESPONSES)
PREFIX: Final = "/api/orgs/{org_id}/events"
EventEditor = Annotated[OrgContext, Depends(org_member(*brief_rules.EDITORS))]


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
