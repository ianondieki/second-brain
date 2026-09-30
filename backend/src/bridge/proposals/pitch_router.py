"""Browse repo, "Pitch to company" and the organisation Inbox (P4: REQ-REPO-02, REQ-PROP-03, REQ-REPO-03,
REQ-NOT-02, REQ-BIL-02, REQ-DIR-04; docs/spec/06 6.1-6.3). Signed-in users only.

- ``GET /api/proposals``: Browse repo, keyword search over published Tier-1 teasers with filters (niche, county,
  maturity, ask, linked Problem), cursor-paginated.

The developer's Pitch (their own proposals only; 404 for anyone else's):

- ``GET /api/me/proposals/{id}/pitch/orgs``: the picker, the directory grouped by niche with E0/E1/E2, what a tag
  would do and whether each organisation can be pitched to now, and the plan cap.
- ``GET /api/me/proposals/{id}/tags``: the proposal's tags and the plan cap.
- ``POST /api/me/proposals/{id}/tags``: pitch to several organisations at once (D1 required: 403 ``d1_required``;
  402 over the plan's tags per proposal; 409 ``tag_conflict`` with a reason per organisation; nothing is created
  unless every tag is). E2 tags are delivered (engagement, Tier-2 grant, EM1 to you); E0/E1 tags are held and reach
  nobody.
- ``POST /api/me/proposals/{id}/tags/{tag_id}/withdraw``: withdraw a held tag.

The organisation (members only; 404 for anyone else):

- ``GET /api/orgs/{org_id}/inbox``: proposals pitched to the organisation, newest first, and the count held for it.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Query, Request
from pydantic import StringConstraints

from bridge import clock
from bridge.auth.deps import CurrentSession, Db, EmailDep, SettingsDep
from bridge.directory import service as directory
from bridge.directory.router import ResponsivenessDep
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.models.enums import OrgKind, ProposalAsk, ProposalMaturity
from bridge.notifications import em1
from bridge.profiles.verification import D1Developer
from bridge.proposals import inbox, picker, search, tags
from bridge.proposals.tag_hooks import TagHooksDep
from bridge.tenancy.deps import OrgMember

router = APIRouter(tags=["pitch"], responses=ERROR_RESPONSES)

CountyCode = Annotated[str, StringConstraints(pattern=r"^KE-\d{2}$")]
NicheSlug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)]
NO_NUL = r"^[^\x00]*$"  # Postgres text cannot hold NUL (0x00)
MAX_FILTER_VALUES = 50


def _capped[T](values: list[T] | None, name: str) -> list[T]:
    unique = list(dict.fromkeys(values or ()))
    if len(unique) > MAX_FILTER_VALUES:
        raise ApiError(422, "too_many_filter_values", f"Choose at most {MAX_FILTER_VALUES} values for {name}.")
    return unique


@router.get("/api/proposals")
async def browse_proposals(
    live: CurrentSession,
    db: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=200, pattern=NO_NUL, description="Keywords")] = None,
    niche: Annotated[list[NicheSlug] | None, Query(description="Niche slug (a parent includes its children)")] = None,
    county: Annotated[list[CountyCode] | None, Query(description="ISO 3166-2:KE county code; repeat")] = None,
    maturity: Annotated[list[ProposalMaturity] | None, Query()] = None,
    ask: Annotated[list[ProposalAsk] | None, Query()] = None,
    problem_id: Annotated[UUID | None, Query(description="A linked Problem's id")] = None,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> search.BrowsePage:
    """Published teasers (Tier 1 only) matching the keywords and filters; the most relevant, then newest, first."""
    try:
        after = search.decode_cursor(cursor) if cursor else None
    except ValueError as exc:
        raise ApiError(400, "invalid_cursor", "Start again from the first page.") from exc
    filters = search.BrowseFilters(
        q=(q.strip() or None) if q else None,
        niches=_capped(niche, "niche"),
        counties=_capped(county, "county"),
        maturities=_capped(maturity, "maturity"),
        asks=_capped(ask, "ask"),
        problem_id=problem_id,
    )
    return await search.browse(db, filters, cursor=after, limit=limit)


@router.get("/api/me/proposals/{proposal_id}/pitch/orgs")
async def pitch_picker(
    proposal_id: UUID,
    live: CurrentSession,
    db: Db,
    settings: SettingsDep,
    responsiveness: ResponsivenessDep,
    kind: Annotated[list[OrgKind] | None, Query(description="Org type; repeat for several")] = None,
    county: Annotated[list[CountyCode] | None, Query(description="ISO 3166-2:KE county code; repeat")] = None,
    niche: Annotated[list[NicheSlug] | None, Query(description="Niche slug (a parent includes its children)")] = None,
    q: Annotated[
        str | None,
        Query(min_length=1, max_length=100, pattern=NO_NUL, description="Keywords: name, niche or county"),
    ] = None,
    cursor: Annotated[str | None, Query(max_length=2000)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> picker.PitchPicker:
    """The directory grouped by niche for this proposal's Pitch (the Companies page's filters and cursor)."""
    try:
        after = directory.decode_cursor(cursor) if cursor else None
    except ValueError as exc:
        raise ApiError(400, "invalid_cursor", "Start again from the first page.") from exc
    filters = directory.DirectoryFilters(
        kinds=_capped(kind, "org type"),
        counties=_capped(county, "county"),
        niches=_capped(niche, "niche"),
        q=(q.strip() or None) if q else None,
    )
    return await picker.picker(
        db,
        settings,
        developer_id=live.user.id,
        proposal_id=proposal_id,
        filters=filters,
        cursor=after,
        limit=limit,
        responsiveness=responsiveness,
        now=clock.utcnow(),
    )


@router.get("/api/me/proposals/{proposal_id}/tags")
async def list_tags(proposal_id: UUID, live: CurrentSession, db: Db, settings: SettingsDep) -> tags.MyTags:
    return await tags.my_tags(db, settings, developer_id=live.user.id, proposal_id=proposal_id)


@router.post("/api/me/proposals/{proposal_id}/tags", status_code=201)
async def pitch(
    proposal_id: UUID,
    body: tags.TagsIn,
    request: Request,
    background: BackgroundTasks,
    profile: D1Developer,
    live: CurrentSession,
    db: Db,
    settings: SettingsDep,
    provider: EmailDep,
    hooks: TagHooksDep,
) -> tags.PitchResult:
    """Pitch the proposal to organisations (the Pitch picker's one primary action)."""
    recipient = tags.Recipient(
        address=live.user.email, base_url=settings.public_base_url, product=settings.product_name
    )
    pitched = await tags.pitch(
        db,
        settings,
        hooks,
        developer_id=profile.user_id,
        recipient=recipient,
        proposal_id=proposal_id,
        org_ids=body.org_ids,
    )
    if pitched.email is not None:
        background.add_task(em1.deliver, request.app.state.session_factory, provider, pitched.email)
    return pitched.result


@router.post("/api/me/proposals/{proposal_id}/tags/{tag_id}/withdraw")
async def withdraw_tag(proposal_id: UUID, tag_id: UUID, live: CurrentSession, db: Db) -> tags.TagOut:
    """Withdraw a held tag (a delivered one is withdrawn on the tracker)."""
    return await tags.withdraw(db, developer_id=live.user.id, proposal_id=proposal_id, tag_id=tag_id)


@router.get("/api/orgs/{org_id}/inbox", tags=["organisations"])
async def org_inbox(
    ctx: OrgMember,
    db: Db,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> inbox.InboxPage:
    """Proposals pitched to this organisation (Tier 1 and the engagement), newest first."""
    try:
        after = inbox.decode_cursor(cursor) if cursor else None
    except ValueError as exc:
        raise ApiError(400, "invalid_cursor", "Start again from the first page.") from exc
    return await inbox.inbox(db, org_id=ctx.org_id, cursor=after, limit=limit)
