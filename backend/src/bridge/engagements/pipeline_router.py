"""The organisation's board (REQ-ENG-14; docs/platform/tasks/P27.md track B).

``GET /api/orgs/{org_id}/pipeline`` (any member; a non-member 404): ``PipelineOut``, the organisation's engagements in
five stage-group columns with their age and "no movement" mark, each column's count and median age, and the funnel
of the last 90 days (``bridge.engagements.pipeline``). Read-only; ``X-App-Now`` as every response.
"""

from __future__ import annotations

from fastapi import APIRouter

from bridge.auth.deps import Db, SettingsDep
from bridge.engagements import pipeline
from bridge.engagements.schemas import PipelineOut
from bridge.engagements.service import app_now
from bridge.errors import ERROR_RESPONSES
from bridge.tenancy.deps import OrgMember

router = APIRouter(tags=["engagements"], responses=ERROR_RESPONSES)


@router.get("/api/orgs/{org_id}/pipeline")
async def org_pipeline(org: OrgMember, db: Db, settings: SettingsDep) -> PipelineOut:
    """The organisation's engagements by stage group, what has stalled, and the funnel of the last 90 days."""
    return await pipeline.pipeline(
        db,
        org.org_id,
        now=await app_now(db),
        deals_enabled=settings.feature_deals_enabled,
        reader_id=org.live.user.id,
    )
