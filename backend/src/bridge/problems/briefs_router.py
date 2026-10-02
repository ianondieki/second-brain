"""Problem Briefs API for the organisation (REQ-DIR-05; docs/spec/06 6.2, 6.5, 6.12; plan limits docs/spec/05).

- ``GET /api/orgs/{org_id}/briefs``: any member; the organisation's Briefs, newest first (every status, with the
  moderation facts and the published proposals linking each), what the plan allows and the budget band codes.
- ``POST /api/orgs/{org_id}/briefs``: an owner, admin, signatory or reviewer of an E2 organisation (403
  ``verification_required`` otherwise); 402 ``plan_limit`` beyond the plan's open Briefs (the next plan up), 422
  ``visibility_not_available`` for an invited Brief and ``invalid_brief`` (a code per field) for the form. The Brief
  waits for staff review (``pending_review``) before any developer sees it.
- ``GET /api/orgs/{org_id}/briefs/{problem_id}``: any member; ``PATCH`` (budget band, deadline; 409 ``brief_closed``
  once closed) and ``POST .../close`` (a published Brief; 409 ``brief_not_published`` while in review): the editors
  above. The Brief is a draft until staff approve its problem, which publishes both.

A non-member gets 404 (the organisation's existence is not confirmed), a member without the role 403, another
organisation's Brief 404. Developers read Briefs on Discover (``GET /api/discover/briefs``) and their problem page
(``GET /api/problems/{id}``, "Posted by <organisation>" with the band and deadline).
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from bridge import pagination
from bridge.auth.deps import Db, SettingsDep
from bridge.errors import ERROR_RESPONSES
from bridge.problems import brief_rules, briefs
from bridge.problems.brief_schemas import BriefIn, BriefList, BriefOut, BriefPatch
from bridge.proposals.deps import PreScreenDep
from bridge.tenancy.deps import OrgContext, OrgMember, org_member

router = APIRouter(tags=["briefs"], responses=ERROR_RESPONSES)
PREFIX: Final = "/api/orgs/{org_id}/briefs"
BriefEditor = Annotated[OrgContext, Depends(org_member(*brief_rules.EDITORS))]


@router.get(PREFIX)
async def list_briefs(
    org: OrgMember,
    db: Db,
    settings: SettingsDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: pagination.Cursor = None,
) -> BriefList:
    """The organisation's Briefs, what its plan allows and the budget band codes."""
    return await briefs.list_briefs(db, settings, org.org_id, limit=limit, after=pagination.decode(cursor))


@router.post(PREFIX, status_code=201)
async def create_brief(
    body: BriefIn, org: BriefEditor, db: Db, settings: SettingsDep, prescreen: PreScreenDep
) -> BriefOut:
    """Post a Brief; it waits for staff review before developers see it."""
    return await briefs.create(db, settings, prescreen, org, body)


@router.get(f"{PREFIX}/{{problem_id}}")
async def get_brief(problem_id: UUID, org: OrgMember, db: Db) -> BriefOut:
    return await briefs.get_one(db, org.org_id, problem_id)


@router.patch(f"{PREFIX}/{{problem_id}}")
async def update_brief(problem_id: UUID, body: BriefPatch, org: BriefEditor, db: Db) -> BriefOut:
    """Change the budget band or the deadline (``null`` clears it) while the Brief is not closed."""
    return await briefs.update(db, org, problem_id, body)


@router.post(f"{PREFIX}/{{problem_id}}/close")
async def close_brief(problem_id: UUID, org: BriefEditor, db: Db) -> BriefOut:
    """Close a published Brief: it leaves Discover and frees its plan slot; its problem page stays."""
    return await briefs.close(db, org, problem_id)
