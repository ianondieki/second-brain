"""Tracker API (REQ-ENG-01..REQ-ENG-03, REQ-ENG-05, REQ-ENG-07..REQ-ENG-10 main path; docs/spec/06 6.9).

Reads (parties only; anyone else gets 404):

- ``GET /api/me/engagements``: the caller's engagements as the developer.
- ``GET /api/orgs/{org_id}/engagements``: the organisation's engagements (any member; the org inbox), each with the
  organisation's triage (``team``; D-68: never on the developer's list).
- ``GET /api/engagements/{id}``: one engagement with whose turn, the caller's actions, the contact, endorsements,
  agreements, signatures and payments, in the caller's side's shape (``my_party``): the developer's (the
  prior-knowledge declaration on their proposal, the IP nudge) or an organisation member's (the organisation's triage
  and its declaration window).
- ``GET /api/engagements/{id}/history``: the History tab (the hash chain and endorsements), the same for both parties.
- ``GET /api/engagements/{id}/documents/{kind}``: the exact text of the NDA, agreement or acceptance certificate.
- ``GET /api/engagements/{id}/contact``: the developer's contact details, for the named contact once approved.

Commands: ``POST /api/engagements/{id}/<command>`` (and ``.../milestones/{milestone_id}/<step>``), one per row of
the state machine's table, each with ``lock_version``; the side states (REQ-ENG-10 part) are ``request-info``,
``answer-info``, ``pause`` and ``resume``, each with its text (a question, an answer, a reason), and
``cancel-request`` (the organisation withdraws its open question). A public entity's procurement route (3b,
REQ-ENG-06) is chosen by its owner or admin under the organisation's path:
``POST /api/orgs/{org_id}/engagements/{id}/procurement-route`` (``ProcurementBody``; a non-member, or another
organisation's engagement, 404). Refusals: 404 (not a
party), 403 (wrong party or role, a missing fresh second factor for signing or endorsing, D2 for the developer's
agreement signature, the deals flag), 409 (a transition not in the table, a precondition, a stale ``lock_version``),
422 (an invalid body). A command's response is the engagement as the caller now sees it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.engagements import history, team
from bridge.engagements import state_machine as sm
from bridge.engagements.commands import (
    ContactInput,
    Inputs,
    MilestoneInput,
    PaymentInput,
    ProcurementInput,
    RequestMeta,
    TermsInput,
    execute,
)
from bridge.engagements.models import Engagement
from bridge.engagements.schemas import (
    AnswerInfoBody,
    ApproveBody,
    CommandBody,
    ConfirmPaymentBody,
    ContactRevealOut,
    DeclineBody,
    DocumentOut,
    EngagementList,
    HistoryOut,
    OrgEngagementDetail,
    OrgEngagementList,
    PauseBody,
    PaymentBody,
    ProcurementBody,
    RequestInfoBody,
    ResumeBody,
    TermsBody,
    TrackerDetail,
)
from bridge.engagements.service import Party, resolve_party
from bridge.errors import ERROR_RESPONSES, not_found
from bridge.models.enums import SignatureDocumentKind
from bridge.tenancy.deps import OrgMember

router = APIRouter(tags=["engagements"], responses=ERROR_RESPONSES)
PREFIX = "/api/engagements/{engagement_id}"


async def party_of(engagement_id: UUID, live: CurrentSession, db: Db) -> Party:
    return await resolve_party(db, live, engagement_id)


PartyDep = Annotated[Party, Depends(party_of)]


def _meta(request: Request) -> RequestMeta:
    return RequestMeta(ip=request.client.host if request.client else None, user_agent=request.headers.get("user-agent"))


@router.get("/api/me/engagements")
async def my_engagements(live: CurrentSession, db: Db, settings: SettingsDep) -> EngagementList:
    rows = await db.execute(
        select(Engagement).where(Engagement.developer_id == live.user.id).order_by(Engagement.updated_at.desc())
    )
    items = await history.summaries(
        db,
        list(rows.scalars()),
        deals_enabled=settings.feature_deals_enabled,
        developer_caller=True,
        reader_id=live.user.id,
    )
    return EngagementList(items=items)


@router.get("/api/orgs/{org_id}/engagements")
async def org_engagements(org: OrgMember, db: Db, settings: SettingsDep) -> OrgEngagementList:
    rows = await db.execute(
        select(Engagement).where(Engagement.org_id == org.org_id).order_by(Engagement.updated_at.desc())
    )
    items = await history.summaries(
        db,
        list(rows.scalars()),
        deals_enabled=settings.feature_deals_enabled,
        developer_caller=False,
        reader_id=org.live.user.id,
    )
    return OrgEngagementList(items=await team.with_team(db, org.org_id, org.live.user.id, items))


@router.get(PREFIX)
async def get_engagement(party: PartyDep, db: Db, settings: SettingsDep) -> TrackerDetail:
    return await history.detail(db, party, deals_enabled=settings.feature_deals_enabled)


@router.get(f"{PREFIX}/history")
async def get_history(party: PartyDep, db: Db) -> HistoryOut:
    return await history.history(db, party.engagement_id, developer_caller=party.is_developer)


@router.get(f"{PREFIX}/documents/{{kind}}")
async def get_document(party: PartyDep, kind: SignatureDocumentKind, db: Db) -> DocumentOut:
    engagement = await db.get(Engagement, party.engagement_id)
    if engagement is None:
        raise not_found()
    return await history.document(db, engagement, kind)


@router.get(f"{PREFIX}/contact")
async def reveal_contact(party: PartyDep, db: Db) -> ContactRevealOut:
    revealed = await history.contact_reveal(db, party)
    await db.commit()  # the audit event of the reveal
    return revealed


async def _run(
    request: Request,
    db: Db,
    settings: SettingsDep,
    party: Party,
    command: sm.Command,
    body: CommandBody,
    inputs: Inputs,
) -> TrackerDetail:
    await execute(db, settings, party, command, lock_version=body.lock_version, meta=_meta(request), inputs=inputs)
    await db.commit()
    return await history.detail(db, party, deals_enabled=settings.feature_deals_enabled)


# Commands whose body is only lock_version: (URL segment, command).
SIMPLE_COMMANDS: tuple[tuple[str, sm.Command], ...] = (
    ("accept-interest", sm.Command.ACCEPT_INTEREST),
    ("decline-interest", sm.Command.DECLINE_INTEREST),
    ("start-review", sm.Command.START_REVIEW),
    ("withdraw", sm.Command.WITHDRAW),
    ("mark-contacted", sm.Command.MARK_CONTACTED),
    ("confirm-contact", sm.Command.CONFIRM_CONTACT),
    ("send-nda", sm.Command.SEND_NDA),
    ("sign-nda", sm.Command.SIGN_NDA),
    ("mark-final", sm.Command.MARK_FINAL),
    ("reopen-negotiation", sm.Command.REOPEN_NEGOTIATION),
    ("sign-agreement", sm.Command.SIGN_AGREEMENT),
    ("deliver", sm.Command.DELIVER),
    ("accept-delivery", sm.Command.ACCEPT_DELIVERY),
    ("sign-certificate", sm.Command.SIGN_CERTIFICATE),
    ("cancel-request", sm.Command.CANCEL_REQUEST),  # the organisation withdraws its open question
)
MILESTONE_COMMANDS: tuple[tuple[str, sm.Command], ...] = (
    ("start", sm.Command.START_MILESTONE),
    ("submit", sm.Command.SUBMIT_MILESTONE),
    ("accept", sm.Command.ACCEPT_MILESTONE),
    ("request-changes", sm.Command.REQUEST_CHANGES),
)


def _simple(command: sm.Command) -> Callable[..., Awaitable[TrackerDetail]]:
    async def endpoint(
        body: CommandBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep
    ) -> TrackerDetail:
        return await _run(request, db, settings, party, command, body, Inputs())

    endpoint.__name__ = f"engagement_{command.value}"
    endpoint.__doc__ = f"Run '{command.value}' (docs/spec/06 6.9; the state machine's table)."
    return endpoint


def _milestone(command: sm.Command) -> Callable[..., Awaitable[TrackerDetail]]:
    async def endpoint(
        milestone_id: UUID, body: CommandBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep
    ) -> TrackerDetail:
        return await _run(request, db, settings, party, command, body, Inputs(milestone_id=milestone_id))

    endpoint.__name__ = f"milestone_{command.value}"
    endpoint.__doc__ = f"Run '{command.value}' on one milestone of the signed agreement (the milestone sub-tracker)."
    return endpoint


for _segment, _command in SIMPLE_COMMANDS:
    router.add_api_route(f"{PREFIX}/{_segment}", _simple(_command), methods=["POST"])
for _segment, _command in MILESTONE_COMMANDS:
    router.add_api_route(f"{PREFIX}/milestones/{{milestone_id}}/{_segment}", _milestone(_command), methods=["POST"])


@router.post(f"{PREFIX}/approve")
async def approve(body: ApproveBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep) -> TrackerDetail:
    """Approve to proceed (non-binding), naming the contact person, channel and contact-by date (stage 3; EM2)."""
    contact = ContactInput(body.contact_user_id, body.contact_channel, body.contact_by)
    return await _run(request, db, settings, party, sm.Command.APPROVE, body, Inputs(contact=contact))


@router.post("/api/orgs/{org_id}/engagements/{engagement_id}/procurement-route")
async def choose_procurement_route(
    engagement_id: UUID, body: ProcurementBody, request: Request, org: OrgMember, db: Db, settings: SettingsDep
) -> OrgEngagementDetail:
    """Choose a public entity's procurement route (stage 3b; docs/spec/06 6.9): an owner or admin of the organisation
    (403 ``role_required`` for any other member), while the engagement waits in ``PROCUREMENT_ROUTE`` (409
    otherwise), with the contact-by date of stage 3. The engagement enters ``INTEREST_CONFIRMED`` (non-binding): the
    named contact may then read the developer's contact details, and the developer is told the route and gets EM2."""
    engagement = await team.org_engagement(db, org.org_id, engagement_id, org.live.user.id)  # 404: another's
    party = await resolve_party(db, org.live, engagement_id)
    inputs = Inputs(procurement=ProcurementInput(body.route, body.justification, body.contact_by))
    # Without lock_version, the version just read: a route is chosen once and in 3b only (the state machine and the
    # database), so a decision never overwrites another.
    lock = body.lock_version if body.lock_version is not None else engagement.lock_version
    await execute(db, settings, party, sm.Command.CHOOSE_ROUTE, lock_version=lock, meta=_meta(request), inputs=inputs)
    await db.commit()
    detail = await history.detail(db, party, deals_enabled=settings.feature_deals_enabled)
    if not isinstance(detail, OrgEngagementDetail):  # pragma: no cover - org_engagement refused the developer
        raise not_found()
    return detail


@router.post(f"{PREFIX}/decline")
async def decline(body: DeclineBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep) -> TrackerDetail:
    """Decline with a reason code (``ALREADY_IN_PROGRESS_INTERNALLY``: start date and attestation; ``OTHER``: text)."""
    details = sm.DeclineDetails(body.reason, body.other_text, body.internal_start_date, body.attested)
    return await _run(request, db, settings, party, sm.Command.DECLINE, body, Inputs(decline=details))


@router.post(f"{PREFIX}/propose-terms")
async def propose_terms(
    body: TermsBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep
) -> TrackerDetail:
    """A new agreement version (draft): IP terms, milestones, deemed-acceptance clause, optional exclusivity."""
    terms = TermsInput(
        ip_terms=body.ip_terms,
        deemed_acceptance_days=body.deemed_acceptance_days,
        exclusivity=body.exclusivity,
        milestones=tuple(
            MilestoneInput(m.deliverable, m.amount_kes_minor, m.due_date, m.review_window_bd) for m in body.milestones
        ),
    )
    return await _run(request, db, settings, party, sm.Command.PROPOSE_TERMS, body, Inputs(terms=terms))


@router.post(f"{PREFIX}/record-payment")
async def record_payment(
    body: PaymentBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep
) -> TrackerDetail:
    """The organisation records the final payment it made (the platform never holds or moves money)."""
    payment = PaymentInput(body.amount_kes_minor, body.method, body.paid_on, body.reference)
    return await _run(request, db, settings, party, sm.Command.RECORD_PAYMENT, body, Inputs(payment=payment))


@router.post(f"{PREFIX}/confirm-payment")
async def confirm_payment(
    body: ConfirmPaymentBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep
) -> TrackerDetail:
    """The developer confirms the amount received; it must equal the recorded amount (409 otherwise)."""
    inputs = Inputs(amount_received=body.amount_received_kes_minor)
    return await _run(request, db, settings, party, sm.Command.CONFIRM_PAYMENT, body, inputs)


@router.post(f"{PREFIX}/request-info")
async def request_info(
    body: RequestInfoBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep
) -> TrackerDetail:
    """The organisation asks the developer a question (stages 1-2); the review clock pauses until the answer."""
    inputs = Inputs(note=body.question)
    return await _run(request, db, settings, party, sm.Command.REQUEST_INFO, body, inputs)


@router.post(f"{PREFIX}/answer-info")
async def answer_info(
    body: AnswerInfoBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep
) -> TrackerDetail:
    """The developer answers; the engagement returns to its stage with the deadline moved by the pause."""
    return await _run(request, db, settings, party, sm.Command.ANSWER_INFO, body, Inputs(note=body.answer))


@router.post(f"{PREFIX}/pause")
async def pause(body: PauseBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep) -> TrackerDetail:
    """Either party puts the engagement on hold before the agreement, until ``resume_at`` (at most 60 days)."""
    inputs = Inputs(note=body.reason, resume_at=body.resume_at)
    return await _run(request, db, settings, party, sm.Command.PAUSE, body, inputs)


@router.post(f"{PREFIX}/resume")
async def resume(body: ResumeBody, request: Request, party: PartyDep, db: Db, settings: SettingsDep) -> TrackerDetail:
    """Either party resumes a hold early; due dates move by the business days on hold."""
    return await _run(request, db, settings, party, sm.Command.RESUME, body, Inputs(note=body.reason))
