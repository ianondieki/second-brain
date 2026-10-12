"""The organisation's own work on an engagement (P27; members of its organisation only, under
``/api/orgs/{org_id}/engagements/{engagement_id}``; a non-member gets 404, as does another organisation's engagement).

Team triage (REQ-ENG-15, D-68; ``bridge.engagements.team``):

- ``GET …/team``: the team sheet (any member): the members it may be assigned to, the assignee, every recommendation.
- ``PUT …/assignee`` ``{user_id|null}``: assign (owner, admin, reviewer or signatory; 403 ``role_not_allowed``
  otherwise, 409 ``unchanged``, 422 ``invalid_assignee``: not a triage member, or the engagement's own developer);
  N30 to the assignee unless they assigned themselves. At most ``team.ASSIGNMENTS_PER_HOUR`` (30) changes an hour per
  member and organisation: past that, 429 ``too_many_assignments`` with ``Retry-After`` (whole seconds), checked after
  the role check and before any write, so nothing is written and nobody is told; a refused change is not counted.
- ``PUT …/recommendation`` ``{stance, note}`` (the same roles) and ``DELETE …/recommendation`` (the caller's own).

The prior-knowledge declaration (REQ-PROV-06; ``bridge.engagements.prior_knowledge``):

- ``POST …/prior-knowledge`` ``{evidence_sha256_hex, evidence_title, evidence_dated_on}``: 201 (owner, admin or
  signatory; inside the window).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.deps import Db, SettingsDep
from bridge.engagements import prior_knowledge, team
from bridge.engagements.schemas import AssigneeBody, DeclarationBody, DeclarationOut, RecommendationBody, TeamOut
from bridge.errors import ERROR_RESPONSES, ApiErrorBody
from bridge.tenancy.deps import OrgMember

router = APIRouter(tags=["engagements"], responses=ERROR_RESPONSES)
ORG_ENGAGEMENT = "/api/orgs/{org_id}/engagements/{engagement_id}"
ASSIGNEE_RESPONSES: dict[int | str, dict[str, object]] = {
    422: {"model": ApiErrorBody, "description": "invalid_assignee (or a request-validation error)"},
    429: {
        "model": ApiErrorBody,
        "description": f"too_many_assignments: more than {team.ASSIGNMENTS_PER_HOUR} changes in an hour by this member"
        " in this organisation",
        "headers": {"Retry-After": {"description": "Whole seconds to wait", "schema": {"type": "integer"}}},
    },
}


@router.get(f"{ORG_ENGAGEMENT}/team")
async def get_team(engagement_id: UUID, org: OrgMember, db: Db) -> TeamOut:
    """The team sheet: who the engagement may be assigned to, who it is assigned to and the members' internal
    recommendations (the organisation's own; never the developer's)."""
    engagement = await team.org_engagement(db, org.org_id, engagement_id, org.live.user.id)
    return await team.team_view(db, org.org_id, engagement)


@router.put(f"{ORG_ENGAGEMENT}/assignee", responses=ASSIGNEE_RESPONSES)
async def put_assignee(
    engagement_id: UUID, body: AssigneeBody, request: Request, org: OrgMember, db: Db, settings: SettingsDep
) -> TeamOut:
    """Assign the engagement to a member (an owner, admin, reviewer or signatory), or to nobody (``user_id`` null).
    At most 30 changes an hour per member and organisation (429 ``too_many_assignments``, ``Retry-After``)."""
    assigned = await team.assign(db, settings, org, engagement_id, body.user_id)
    await db.commit()
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    await team.tell_assignee(
        factory,
        assigned=assigned,
        org_id=org.org_id,
        engagement_id=engagement_id,
        assigner_name=org.live.user.display_name,
    )
    return assigned.team


@router.put(f"{ORG_ENGAGEMENT}/recommendation")
async def put_recommendation(engagement_id: UUID, body: RecommendationBody, org: OrgMember, db: Db) -> TeamOut:
    """Record or change your internal recommendation (pursue, pass or discuss, with an optional one-line note). It
    changes nothing on the engagement and the developer never sees it."""
    out = await team.recommend(db, org, engagement_id, body)
    await db.commit()
    return out


@router.delete(f"{ORG_ENGAGEMENT}/recommendation")
async def delete_recommendation(engagement_id: UUID, org: OrgMember, db: Db) -> TeamOut:
    """Withdraw your own recommendation (nothing to withdraw is no change)."""
    out = await team.withdraw(db, org, engagement_id)
    await db.commit()
    return out


@router.post(f"{ORG_ENGAGEMENT}/prior-knowledge", status_code=201)
async def post_prior_knowledge(engagement_id: UUID, body: DeclarationBody, org: OrgMember, db: Db) -> DeclarationOut:
    """Declare prior knowledge (docs/spec/06 6.4 pt 5): the SHA-256 of dated internal evidence (hashed on your device;
    no file is uploaded), its title and date, within 10 business days of your organisation's first view of the full
    proposal. The developer is told. Declarations are not recorded on the platform after this window."""
    out = await prior_knowledge.declare(db, org, engagement_id, body)
    await db.commit()
    return out
