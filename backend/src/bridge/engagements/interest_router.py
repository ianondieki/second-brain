"""Stage-0 routes (REQ-ENG-04; docs/spec/06 6.9; ``bridge.engagements.interest``).

- ``POST /api/orgs/{org_id}/interest``: a signatory of the (E2) organisation, with a fresh second factor, expresses
  interest in a proposal from a scout match or the Browse repo, naming the contact (201: the engagement as they now
  see it). A non-member gets 404, a reviewer or any other role 403.
- ``GET /api/engagements/{id}/share-tier2``: either party reads whether the full proposal is shared.
- ``POST /api/engagements/{id}/share-tier2``: the developer shares it with the organisation (a manual Tier-2 grant,
  source ``org_interest``; idempotent), with a fresh second factor; the organisation's people are told in-app.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from bridge.auth.deps import Db, SettingsDep
from bridge.engagements import history
from bridge.engagements.interest import express_interest, share_state, share_tier2, tell_organisation
from bridge.engagements.models import Engagement
from bridge.engagements.router import PartyDep
from bridge.engagements.schemas import EngagementDetail, InterestBody, Tier2ShareOut
from bridge.engagements.service import resolve_party
from bridge.errors import ERROR_RESPONSES, not_found
from bridge.tenancy.deps import OrgMember

router = APIRouter(tags=["engagements"], responses=ERROR_RESPONSES)


@router.post("/api/orgs/{org_id}/interest", status_code=201)
async def post_interest(body: InterestBody, org: OrgMember, db: Db, settings: SettingsDep) -> EngagementDetail:
    """Express interest (stage 0, ORG_INTEREST): signatory of an E2 organisation, step-up; N17 to the developer."""
    engagement_id = await express_interest(db, settings, org, body)
    await db.commit()
    party = await resolve_party(db, org.live, engagement_id)
    return await history.detail(db, party, deals_enabled=settings.feature_deals_enabled)


@router.get("/api/engagements/{engagement_id}/share-tier2")
async def get_tier2_share(party: PartyDep, db: Db) -> Tier2ShareOut:
    """Whether the developer shared the full proposal with the organisation (both parties)."""
    engagement = await db.get(Engagement, party.engagement_id)
    if engagement is None:
        raise not_found()
    return await share_state(db, engagement)


@router.post("/api/engagements/{engagement_id}/share-tier2")
async def post_tier2_share(request: Request, party: PartyDep, db: Db, settings: SettingsDep) -> Tier2ShareOut:
    """The developer shares the full proposal (Tier 2) with the organisation that expressed interest."""
    share, changed = await share_tier2(db, settings, party)
    await db.commit()
    if changed and share.grant_id is not None:
        factory = request.app.state.session_factory
        await tell_organisation(factory, party.engagement_id, party.user_id, share.grant_id)
    return share
