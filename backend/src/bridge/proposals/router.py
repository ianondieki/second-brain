"""Proposal API (REQ-PROP-01, REQ-PROP-02, REQ-PROV-05; docs/spec/06 6.1, 6.3, 6.4). Signed-in users only.

Owner ("My ideas"; 404 for anyone else's proposal):

- ``GET /api/me/proposals``: your proposals, Tier 1 only.
- ``POST /api/me/proposals``: a new draft (Tier 0) from a partial body.
- ``GET /api/me/proposals/{id}``: one proposal with its current and draft versions and your own Tier 2 (audited).
- ``PATCH /api/me/proposals/{id}``: save the draft (editing a published proposal starts its next version).
- ``POST /api/me/proposals/{id}/publish``: register the draft (D1 required: 403 ``d1_required``; 402 over the plan's
  active-proposal cap; 422 with the fields to fix).
- ``DELETE /api/me/proposals/{id}``: hide a registered proposal (its evidence is kept) or delete a never-published
  draft.
- ``POST /api/me/proposals/{id}/attachments``: the raw file as the body, its type in ``Content-Type`` and its name in
  ``X-File-Name`` (percent-encoded UTF-8; never in the URL, which reaches access logs). Scanned before it is kept.
- ``DELETE /api/me/proposals/{id}/attachments/{attachment_id}``: remove an attachment from the draft.

Everyone signed in: ``GET /api/proposals/attestations`` (the statements to confirm before publishing) and
``GET /api/proposals/{id}`` (a published, clear teaser: Tier 1 only).

Owner: ``GET /api/me/proposals/{id}/views`` ("Who has seen this": organisation, person, time and NDA version of every
Tier-2 view).

Tier 2 (REQ-REPO-01, REQ-PROV-03, REQ-SEC-01; ``tier2_router``, tag ``tier2``): ``access.tier2_gate`` answers 404 to
a signed-in non-member of the path's organisation, then 403 ``tier2_disabled`` to everyone while
``FEATURE_TIER2_ENABLED`` is off; then ``can_view_tier2`` decides (``access.py``; 404 for a proposal without a public
teaser, else 403 naming the first missing condition; every refusal audited):

- ``GET /api/orgs/{org_id}/proposals/{id}/nda``: the current Evaluation NDA with the viewer-logging notice, and your
  acceptance of it (needs every other condition).
- ``POST /api/orgs/{org_id}/proposals/{id}/nda``: accept what was shown (201; 200 when already accepted; 409
  ``nda_outdated`` when a newer version exists).
- ``GET /api/orgs/{org_id}/proposals/{id}/tier2``: the current version's Tier 2 as a marked, uncacheable HTML page;
  each page is one logged view. There is no JSON form of Tier 2 for organisations.
- ``GET /api/me/proposals/{id}/tier2``: the owner's preview of that page (marked for the owner, not logged; 404 for
  anyone else). The owner's JSON reads above are not gated by the flag (REQ-PROV-01 card); this render is.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Any
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import HTMLResponse

from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.errors import ERROR_RESPONSES, ApiError, ApiErrorBody, json_errors
from bridge.legal import nda
from bridge.profiles.verification import D1Developer
from bridge.proposals import access, attestations, editor, lifecycle, render, service, views
from bridge.proposals.deps import EmbedderDep, PreScreenDep, ScannerDep, StoreDep, WrapperDep, get_key_wrapper
from bridge.proposals.models import MAX_ATTACHMENT_BYTES
from bridge.proposals.schemas import (
    AttachmentOut,
    AttestationStatement,
    AttestationText,
    DraftIn,
    MyProposalOut,
    MyProposals,
    PublishIn,
    PublishOut,
    RemovedOut,
    TeaserCard,
)

router = APIRouter(tags=["proposals"], responses=ERROR_RESPONSES)
tier2_router = APIRouter(tags=["tier2"], responses=ERROR_RESPONSES, dependencies=[Depends(access.tier2_gate)])
UNAVAILABLE: dict[int | str, dict[str, Any]] = {503: {"model": ApiErrorBody}}
MAX_FILE_NAME = 200


@router.get("/api/me/proposals")
async def list_mine(live: CurrentSession, db: Db) -> MyProposals:
    return await service.my_proposals(db, live.user.id)


@router.post("/api/me/proposals", status_code=201, responses=UNAVAILABLE)
async def create_draft(body: DraftIn, live: CurrentSession, db: Db, wrapper: WrapperDep) -> MyProposalOut:
    proposal_id = await editor.create_draft(db, wrapper, live.user.id, body)
    return await service.my_proposal(db, wrapper, live.user.id, proposal_id)


@router.get("/api/me/proposals/{proposal_id}", responses=UNAVAILABLE)
async def get_mine(proposal_id: UUID, live: CurrentSession, db: Db, wrapper: WrapperDep) -> MyProposalOut:
    return await service.my_proposal(db, wrapper, live.user.id, proposal_id)


@router.patch("/api/me/proposals/{proposal_id}", responses=UNAVAILABLE)
async def save_draft(
    proposal_id: UUID, body: DraftIn, live: CurrentSession, db: Db, wrapper: WrapperDep
) -> MyProposalOut:
    await editor.save_draft(db, wrapper, live.user.id, proposal_id, body)
    return await service.my_proposal(db, wrapper, live.user.id, proposal_id)


@router.post("/api/me/proposals/{proposal_id}/publish", responses=UNAVAILABLE)
async def publish(
    proposal_id: UUID,
    body: PublishIn,
    profile: D1Developer,
    db: Db,
    settings: SettingsDep,
    wrapper: WrapperDep,
    prescreen: PreScreenDep,
    embedder: EmbedderDep,
) -> PublishOut:
    """Register the draft version: the one primary action of the editor."""
    return await service.publish(
        db, settings, wrapper, prescreen, embedder, user_id=profile.user_id, proposal_id=proposal_id, body=body
    )


@router.delete("/api/me/proposals/{proposal_id}")
async def remove(proposal_id: UUID, live: CurrentSession, db: Db, store: StoreDep) -> RemovedOut:
    return await lifecycle.remove(db, store, user_id=live.user.id, proposal_id=proposal_id)


def _file_name(raw: str | None) -> str:
    name = unquote(raw or "", errors="strict") if raw else ""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] != "C").strip()
    return name[:MAX_FILE_NAME] or "attachment"


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    too_large = ApiError(413, "too_large", "Attachments can be up to 20 MB.")
    if declared is not None and declared.isdigit() and int(declared) > MAX_ATTACHMENT_BYTES:
        raise too_large
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_ATTACHMENT_BYTES:
            raise too_large
        chunks.append(chunk)
    if size == 0:
        raise ApiError(422, "empty_file", "The file is empty.")
    return b"".join(chunks)


@router.post(
    "/api/me/proposals/{proposal_id}/attachments",
    status_code=201,
    responses={413: {"model": ApiErrorBody}, **UNAVAILABLE},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                content_type: {"schema": {"type": "string", "format": "binary"}}
                for content_type in editor.ACCEPTED_TYPES
            },
        }
    },
)
async def add_attachment(
    proposal_id: UUID,
    request: Request,
    live: CurrentSession,
    db: Db,
    wrapper: WrapperDep,
    store: StoreDep,
    scanner: ScannerDep,
    x_file_name: Annotated[str | None, Header(max_length=1000, description="Percent-encoded UTF-8 name")] = None,
) -> AttachmentOut:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    try:
        file_name = _file_name(x_file_name)
    except UnicodeDecodeError as exc:
        raise ApiError(422, "invalid_file_name", "Send the file name as percent-encoded UTF-8.") from exc
    data = await _read_body(request)
    return await editor.add_attachment(
        db,
        wrapper,
        store,
        scanner,
        user_id=live.user.id,
        proposal_id=proposal_id,
        data=data,
        content_type=content_type,
        file_name=file_name,
    )


@router.delete("/api/me/proposals/{proposal_id}/attachments/{attachment_id}", status_code=204, responses=UNAVAILABLE)
async def remove_attachment(
    proposal_id: UUID, attachment_id: UUID, live: CurrentSession, db: Db, wrapper: WrapperDep, store: StoreDep
) -> None:
    await editor.remove_attachment(
        db, wrapper, store, user_id=live.user.id, proposal_id=proposal_id, attachment_id=attachment_id
    )


@router.get("/api/proposals/attestations")
async def attestation_text(live: CurrentSession) -> AttestationText:
    """The ownership statements to show before publishing, with the version to send back."""
    return AttestationText(
        version=attestations.VERSION,
        sha256=attestations.text_digest().hex(),
        statements=[AttestationStatement(key=key, text=value) for key, value in attestations.STATEMENTS],
    )


@router.get("/api/proposals/{proposal_id}")
async def get_teaser(proposal_id: UUID, live: CurrentSession, db: Db) -> TeaserCard:
    """A published teaser (Tier 1 only). Drafts, held, rejected and hidden proposals are 404 for everyone."""
    return await service.teaser_card(db, proposal_id)


@router.get("/api/me/proposals/{proposal_id}/views")
async def who_has_seen(proposal_id: UUID, live: CurrentSession, db: Db) -> views.ProposalViews:
    """ "Who has seen this": every organisation view of your proposal's full version, newest first."""
    return await views.who_has_seen(db, owner_id=live.user.id, proposal_id=proposal_id)


# --- Tier 2 for organisations (gated by FEATURE_TIER2_ENABLED, then by can_view_tier2) -------------------------------

HTML_PAGE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"text/html": {"schema": {"type": "string"}}}, "description": "The marked page"},
    **json_errors(*ERROR_RESPONSES, 503),  # errors are JSON, as everywhere, not HTML
}
ALREADY_ACCEPTED: dict[int | str, dict[str, Any]] = {
    200: {"model": nda.NdaAcceptanceOut, "description": "Already accepted"}
}


def _not_for_the_owner(granted: access.Access) -> None:
    if granted.owner:
        raise ApiError(409, "nda_not_needed", "You own this proposal: no NDA is needed to read it.")


@tier2_router.get("/api/orgs/{org_id}/proposals/{proposal_id}/nda", responses=UNAVAILABLE)
async def evaluation_nda(
    org_id: UUID, proposal_id: UUID, live: CurrentSession, db: Db, settings: SettingsDep
) -> nda.EvaluationNdaOut:
    """The Evaluation NDA to accept before opening this proposal, with the viewer-logging notice."""
    granted = await access.require(
        db, settings, live, proposal_id=proposal_id, org_id=org_id, purpose=access.Purpose.NDA
    )
    _not_for_the_owner(granted)
    return await nda.terms(db, user_id=live.user.id, org_id=org_id, proposal_id=proposal_id)


@tier2_router.post(
    "/api/orgs/{org_id}/proposals/{proposal_id}/nda",
    status_code=201,
    responses={**ALREADY_ACCEPTED, **UNAVAILABLE},
)
async def accept_evaluation_nda(
    org_id: UUID,
    proposal_id: UUID,
    body: nda.NdaAcceptIn,
    response: Response,
    live: CurrentSession,
    db: Db,
    settings: SettingsDep,
) -> nda.NdaAcceptanceOut:
    """Accept the Evaluation NDA for this proposal, in your name and your organisation's (once per version)."""
    granted = await access.require(
        db, settings, live, proposal_id=proposal_id, org_id=org_id, purpose=access.Purpose.NDA
    )
    _not_for_the_owner(granted)
    accepted, created = await nda.accept(db, body, user_id=live.user.id, org_id=org_id, proposal_id=proposal_id)
    await db.commit()
    if not created:
        response.status_code = 200
    return accepted


@tier2_router.get(
    "/api/orgs/{org_id}/proposals/{proposal_id}/tier2",
    response_class=HTMLResponse,
    responses=HTML_PAGE,
)
async def tier2_page(
    org_id: UUID, proposal_id: UUID, request: Request, live: CurrentSession, db: Db, settings: SettingsDep
) -> HTMLResponse:
    """The full proposal as a marked page for you (one logged view each time); never cached."""
    granted = await access.require(
        db, settings, live, proposal_id=proposal_id, org_id=org_id, purpose=access.Purpose.RENDER
    )
    page = await views.render(db, settings, get_key_wrapper(request), live, granted)
    return HTMLResponse(page, headers=render.HEADERS)


@tier2_router.get(
    "/api/me/proposals/{proposal_id}/tier2",
    response_class=HTMLResponse,
    responses=HTML_PAGE,
)
async def tier2_preview(
    proposal_id: UUID, request: Request, live: CurrentSession, db: Db, settings: SettingsDep
) -> HTMLResponse:
    """Your proposal's full version as organisations see it, marked for you (not logged as a view)."""
    granted = await access.require(
        db, settings, live, proposal_id=proposal_id, org_id=None, purpose=access.Purpose.RENDER
    )
    page = await views.render(db, settings, get_key_wrapper(request), live, granted)
    return HTMLResponse(page, headers=render.HEADERS)


router.include_router(tier2_router)  # last: routes added to tier2_router after this line would be missed
