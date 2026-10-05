"""The organisation shortlist's API (REQ-REPO-02, R10; P21 track B; ``bridge.proposals.shortlist``). Members only: a
non-member gets 404 (the organisation is not confirmed), a member without the role 403.

- ``GET /api/orgs/{org_id}/shortlist``: every member; newest first, ``limit`` and ``cursor``; each entry says who added
  it and when (a proposal the organisation can no longer see is ``available`` false, with no Tier-1 facts).
- ``PUT /api/orgs/{org_id}/shortlist/{proposal_id}``: reviewer, signatory or admin; a proposal of the organisation's
  Inbox (else 404); idempotent (the first add keeps its author and time). Audited when it adds.
- ``DELETE /api/orgs/{org_id}/shortlist/{proposal_id}``: reviewer, signatory or admin; 204 whether or not it was on
  the list. Audited when it removes.
- ``GET /api/orgs/{org_id}/shortlist/compare?ids=a,b[,c,d]``: every member; 2 to 4 distinct shortlisted proposals
  (else 422), Tier-1 facts only, in the order asked.
"""

from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from bridge import pagination
from bridge.auth.deps import Db
from bridge.errors import ERROR_RESPONSES
from bridge.proposals import shortlist
from bridge.tenancy.deps import OrgContext, OrgMember, org_member

router = APIRouter(prefix="/api/orgs/{org_id}/shortlist", tags=["organisations"], responses=ERROR_RESPONSES)
PAGE: Final = 50
MAX_PAGE: Final = 100
Tier2Member = Annotated[OrgContext, Depends(org_member(*sorted(shortlist.TIER2_ROLES)))]


@router.get("")
async def list_shortlist(
    org: OrgMember,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = PAGE,
    cursor: pagination.Cursor = None,
) -> shortlist.ShortlistPage:
    """The organisation's shortlist, newest first."""
    return await shortlist.entries(db, org.org_id, limit=limit, cursor=cursor)


@router.get("/compare")
async def compare_shortlisted(
    org: OrgMember,
    db: Db,
    ids: Annotated[
        str,
        Query(max_length=200, description="2 to 4 shortlisted proposal ids, separated by commas"),
    ],
) -> shortlist.CompareOut:
    """Shortlisted proposals side by side, on their Tier-1 facts only."""
    return await shortlist.compare(db, org.org_id, shortlist.compare_ids(ids))


@router.put("/{proposal_id}")
async def add_to_shortlist(proposal_id: UUID, org: Tier2Member, db: Db) -> shortlist.ShortlistEntry:
    """Shortlist a proposal of the organisation's Inbox (reviewer, signatory or admin); a repeat changes nothing."""
    return await shortlist.add(db, org.org_id, org.live.user.id, proposal_id)


@router.delete("/{proposal_id}", status_code=204)
async def remove_from_shortlist(proposal_id: UUID, org: Tier2Member, db: Db) -> Response:
    """Take a proposal off the shortlist (reviewer, signatory or admin)."""
    await shortlist.remove(db, org.org_id, org.live.user.id, proposal_id)
    return Response(status_code=204)
