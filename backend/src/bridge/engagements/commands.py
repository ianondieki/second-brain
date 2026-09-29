"""Running a tracker command (REQ-ENG-01..REQ-ENG-10 main path; docs/spec/06 6.9).

``execute`` is the one way the API changes an engagement:

1. lock the engagement (``FOR UPDATE``, until commit) and check the caller's party and roles (403, the state
   machine), the fresh second factor where the command signs or endorses (403, ADR-002), and ``lock_version`` against
   the version the caller last read (409 ``stale``);
2. ask the state machine (``decide``) with the engagement's facts: a command not in the table for this state is 409;
3. apply the command's own effects (the contact, a decline's details, an NDA, an agreement version, a signature, a
   milestone step, a payment), then record the party's endorsement and append the event: the database projects the
   state, sets the times and extends the hash chain (revision 0003), and the engagement is re-read;
4. close the tag when the engagement ends, and queue the other party's notification (outbox, same transaction).

The caller commits. Nothing here chooses a state the table did not; the database refuses anything outside its
backstop, and such a refusal maps to 404/403/409 (``service.db_refusal``). ``step_up_method`` is only ever the
second factor this request verified through the session (TOTP; passkeys are not built, so never ``passkey``).
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth.deps import ensure_step_up
from bridge.config import Settings
from bridge.db import tenant_of
from bridge.engagements import documents, notify
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import local_date
from bridge.engagements.models import (
    Agreement,
    Engagement,
    EngagementEndorsement,
    EngagementEvent,
    Milestone,
    PaymentRecord,
    Signature,
)
from bridge.engagements.policy import TrackerPolicy, get_policy
from bridge.engagements.service import (
    Loaded,
    Party,
    api_error,
    app_now,
    db_refusal,
    load,
    load_holidays,
    lock_engagement,
)
from bridge.errors import ApiError, forbidden, not_found
from bridge.ids import uuid7
from bridge.legal.models import LegalTemplate, NdaTemplate
from bridge.models.enums import (
    AgreementStatus,
    ContactChannel,
    EndorsementMethod,
    EngagementEndReason,
    EngagementOrigin,
    EngagementParty,
    EngagementState,
    IpTerms,
    MilestoneState,
    NdaKind,
    OrgRole,
    PaymentMethod,
    SignatureDocumentKind,
    StepUpMethod,
    TagStatus,
)
from bridge.proposals.models import Proposal, Tag
from bridge.tenancy.service import membership_of

C = sm.Command
S = EngagementState
ATTESTATION_VERSION: Final = "v1"  # the wording of the "already in progress internally" checkbox (frontend copy)
CONTACT_ROLE_ORDER: Final = (
    OrgRole.SIGNATORY,
    OrgRole.OWNER,
    OrgRole.ADMIN,
    OrgRole.REVIEWER,
    OrgRole.FINANCE,
    OrgRole.VIEWER,
)
_DIGEST = text("SELECT app_subject_digest(:user_id, convert_to(:data, 'UTF8'))")
_CLOSE_TAG = text("SELECT app_close_tag(:tag_id)")


@dataclass(frozen=True, slots=True)
class RequestMeta:
    """What a signature records about the request (docs/spec/06 6.9 SignatureProvider: IP, UA, time)."""

    ip: str | None = None
    user_agent: str | None = None


@dataclass(frozen=True, slots=True)
class ContactInput:
    user_id: UUID
    channel: ContactChannel
    contact_by: date


@dataclass(frozen=True, slots=True)
class MilestoneInput:
    deliverable: str
    amount_kes_minor: int
    due_date: date
    review_window_bd: int


@dataclass(frozen=True, slots=True)
class TermsInput:
    ip_terms: IpTerms
    deemed_acceptance_days: int
    milestones: tuple[MilestoneInput, ...]
    exclusivity: str | None = None


@dataclass(frozen=True, slots=True)
class PaymentInput:
    amount_kes_minor: int
    method: PaymentMethod
    paid_on: date
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class Inputs:
    """A command's body beyond ``lock_version`` (each command reads its own part)."""

    contact: ContactInput | None = None
    decline: sm.DeclineDetails | None = None
    terms: TermsInput | None = None
    payment: PaymentInput | None = None
    amount_received: int | None = None
    milestone_id: UUID | None = None


@dataclass(slots=True)
class Step:
    """One command in flight: what it read, and what its event will carry."""

    db: AsyncSession
    settings: Settings
    policy: TrackerPolicy
    party: Party
    engagement: Engagement
    decision: sm.Decision
    loaded: Loaded
    inputs: Inputs
    meta: RequestMeta
    now: datetime
    holidays: frozenset[date]
    step_up: StepUpMethod | None
    milestone: Milestone | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    named_deadline: date | None = None
    notice_text: str | None = None
    keep_endorsement: bool = False  # a re-submitted milestone keeps the developer's first endorsement


def verified_step_up(party: Party, settings: Settings) -> StepUpMethod:
    """The second factor behind a signature or endorsement: TOTP verified on this session within the step-up window
    (ADR-002: 12 h), else 403. Passkeys are not built, so this is never ``passkey``."""
    if party.live.user.totp_enabled_at is None:
        raise forbidden("mfa_enrolment_required", "Turn on two-step sign-in to sign or endorse.")
    ensure_step_up(party.live, settings)
    return StepUpMethod.TOTP


def _ip(value: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None


async def execute(
    db: AsyncSession,
    settings: Settings,
    party: Party,
    command: sm.Command,
    *,
    lock_version: int,
    meta: RequestMeta,
    inputs: Inputs | None = None,
) -> Engagement:
    """Run ``command`` for ``party`` (see the module docstring); returns the re-read engagement. The caller commits."""
    inputs = inputs or Inputs()
    engagement = await lock_engagement(db, party.engagement_id)
    try:
        transition, _ = sm.authorize(command, party.actor, deals_enabled=settings.feature_deals_enabled)
    except sm.TrackerError as error:
        raise api_error(error) from error
    method = verified_step_up(party, settings) if transition.step_up else None
    if engagement.lock_version != lock_version:
        raise ApiError(409, "stale", "The engagement changed since you loaded it. Reload it and try again.")
    loaded = await load(
        db, engagement, deals_enabled=settings.feature_deals_enabled, developer_caller=party.is_developer
    )
    milestone = None
    if command in sm.MILESTONE_STEPS:
        try:  # a transition not in the table is 409 before the milestone it names is looked up (AC-TRACK-1)
            sm.check_source(command, engagement.state)
        except sm.TrackerError as error:
            raise api_error(error) from error
        milestone = next((m for m in loaded.milestones if m.id == inputs.milestone_id), None)
        if milestone is None:
            raise not_found("No such milestone on this engagement.")
    try:
        decision = sm.decide(
            command,
            party.actor,
            engagement.state,
            loaded.facts,
            milestone=milestone.state if milestone else None,
            reason=inputs.decline.reason if inputs.decline else None,
        )
    except sm.TrackerError as error:
        raise api_error(error) from error
    now = await app_now(db)
    step = Step(
        db=db,
        settings=settings,
        policy=get_policy(),
        party=party,
        engagement=engagement,
        decision=decision,
        loaded=loaded,
        inputs=inputs,
        meta=meta,
        now=now,
        holidays=await load_holidays(db, local_date(now)),
        step_up=method,
        milestone=milestone,
    )
    try:
        await _apply(step)
    except sm.TrackerError as error:
        raise api_error(error) from error
    except DBAPIError as exc:
        mapped = db_refusal(exc)
        if mapped is None:
            raise
        raise mapped from exc
    return engagement


async def _apply(step: Step) -> None:
    decision, db = step.decision, step.db
    await EFFECTS[decision.command](step)
    endorsement_id = None
    if decision.endorse is not None and not step.keep_endorsement:
        # The event names the endorsement, so the hash chain carries every endorsement (AC-TRACK-3).
        endorsement_id = uuid7()
        step.payload["endorsement_id"] = str(endorsement_id)
        if decision.endorse is sm.Endorse.BEFORE:
            await _endorse(step, endorsement_id, decision.from_state)
    event = await _append(step)
    await db.refresh(step.engagement)  # the database projected the event: state, stage times, lock_version
    if endorsement_id is not None and decision.endorse is sm.Endorse.AFTER:
        await _endorse(step, endorsement_id, decision.to_state)
    if decision.to_state is S.WITHDRAWN:
        await _withdraw_tag(step)
    elif decision.to_state in (S.DECLINED, S.CLOSED):
        await _close_tag(step)
    if decision.notice is not None:
        await notify.enqueue(db, step.engagement, event, reason_text=step.notice_text)
    await db.flush()


async def _endorse(step: Step, endorsement_id: UUID, stage: EngagementState) -> None:
    party, decision = step.party, step.decision
    step.db.add(
        EngagementEndorsement(
            id=endorsement_id,
            engagement_id=step.engagement.id,
            stage=stage,
            milestone_id=step.milestone.id if step.milestone else None,
            party=party.actor.party,
            user_id=party.user_id,
            role=decision.role,
            method=EndorsementMethod.TOTP,  # every endorsing command requires the step-up (verified_step_up)
        )
    )
    await step.db.flush()


async def _append(step: Step) -> EngagementEvent:
    decision = step.decision
    deadline = None
    if decision.changes_state or decision.renews_deadline:
        deadline = sm.stage_deadline(decision.to_state, step.now, step.holidays, step.policy, named=step.named_deadline)
    event = EngagementEvent(
        id=uuid7(),
        engagement_id=step.engagement.id,
        actor_user_id=step.party.user_id,
        actor_role=decision.role,
        command=decision.command.value,
        from_state=decision.from_state,
        to_state=decision.to_state,
        end_reason=decision.end_reason,
        stage_deadline_at=deadline,
        payload=step.payload,
    )
    step.db.add(event)
    await step.db.flush()
    return event


async def _open_tag(step: Step) -> Tag | None:
    """The developer's open tag behind a ``tagged`` engagement (an organisation's interest has none)."""
    engagement = step.engagement
    if engagement.origin is not EngagementOrigin.TAGGED:
        return None
    found: Tag | None = await step.db.scalar(
        select(Tag).where(
            Tag.proposal_id == engagement.proposal_id,
            Tag.org_id == engagement.org_id,
            Tag.developer_id == engagement.developer_id,
            Tag.closed_at.is_(None),
        )
    )
    return found


async def _withdraw_tag(step: Step) -> None:
    """The developer withdraws their tag with the engagement (the tag closes; Tier-2 access stops with the
    engagement's WITHDRAWN state in ``app_tier2_granted``)."""
    tag = await _open_tag(step)
    if tag is not None:
        tag.status = TagStatus.WITHDRAWN
        await step.db.flush()


async def _close_tag(step: Step) -> None:
    """The engagement ended (DECLINED or CLOSED): its tag closes (``app_close_tag``), freeing the developer's one open
    tag with this organisation."""
    tag = await _open_tag(step)
    if tag is not None:
        await step.db.execute(_CLOSE_TAG, {"tag_id": tag.id})


# ------------------------------------------------------------------------------------------------ the effects


async def _nothing(step: Step) -> None:
    return None


async def _accept_interest(step: Step) -> None:
    contact_by = step.engagement.contact_by
    step.named_deadline = contact_by
    if contact_by is not None:
        step.payload["contact_by"] = contact_by.isoformat()


async def _decline(step: Step) -> None:
    if step.decision.command is C.DECLINE_INTEREST:
        return
    details = step.inputs.decline
    if details is None:  # the router always sends one
        raise sm.Invalid("invalid_reason", "Choose one of the organisation's decline reasons.")
    sm.check_decline(details, step.now, step.policy)
    if details.reason is EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY:
        assert details.internal_start_date is not None  # check_decline
        step.payload.update(
            internal_start_date=details.internal_start_date.isoformat(),
            attested=True,
            attestation_version=ATTESTATION_VERSION,
        )
    elif details.reason is EngagementEndReason.OTHER:
        reason_text = (details.other_text or "").strip()
        digest: bytes = (
            await step.db.execute(_DIGEST, {"user_id": step.party.user_id, "data": reason_text})
        ).scalar_one()
        step.payload["reason_text_sha256"] = digest.hex()
        # Free text stays out of the hash chain (docs/spec/06 6.4 item 4): it is kept in the audit event's mutable
        # details, and reaches the developer with the decline notification.
        await audit(
            step.db,
            "engagement.declined",
            actor_user_id=step.party.user_id,
            org_id=step.party.org_id,
            subject_type="engagement",
            subject_id=step.engagement.id,
            payload={"reason": details.reason.value, "reason_text_sha256": digest.hex()},
            details={"reason_text": reason_text},
        )
        step.notice_text = reason_text


async def _approve(step: Step) -> None:
    contact = step.inputs.contact
    if contact is None:  # the router always sends one
        raise sm.Invalid("invalid_contact", "Name the contact person, channel and contact-by date.")
    sm.check_contact_by(contact.contact_by, step.now, step.holidays, step.policy)
    membership = await membership_of(step.db, step.party.org_id, contact.user_id)
    if membership is None:
        raise sm.Invalid("invalid_contact", "Choose an active member of your organisation as the contact person.")
    roles = {OrgRole(r) for r in membership.roles}
    role = next((r for r in CONTACT_ROLE_ORDER if r in roles), OrgRole.VIEWER)  # a member with no role reads as one
    engagement = step.engagement
    engagement.contact_user_id = contact.user_id
    engagement.contact_channel = contact.channel
    engagement.contact_by = contact.contact_by
    await step.db.flush()  # the ORM's version check (lock_version) and the database's contact rules
    step.named_deadline = contact.contact_by
    step.payload.update(
        contact_user_id=str(contact.user_id),
        contact_role=role.value,
        contact_channel=contact.channel.value,
        contact_by=contact.contact_by.isoformat(),
    )


async def _send_nda(step: Step) -> None:
    found = await step.db.execute(
        select(NdaTemplate, LegalTemplate)
        .join(LegalTemplate, LegalTemplate.id == NdaTemplate.legal_template_id)
        .where(NdaTemplate.kind == NdaKind.MUTUAL)
        .order_by(NdaTemplate.created_at.desc())
        .limit(1)
    )
    row = found.first()
    if row is None:
        raise sm.Conflict("nda_template_missing", "The platform mutual NDA is not installed yet (run the seed).")
    nda, legal = row
    engagement = step.engagement
    document = documents.mutual_nda(
        ref=uuid7(),
        engagement_id=engagement.id,
        proposal_id=engagement.proposal_id,
        org_id=engagement.org_id,
        developer_id=engagement.developer_id,
        template_version=nda.version,
        template_sha256=nda.sha256,
        template_body=legal.body,
    )
    step.payload.update(document_ref=str(document.ref), document_sha256=document.sha256.hex(), template_id=str(nda.id))


def _document_to_sign(step: Step) -> tuple[SignatureDocumentKind, UUID, bytes]:
    loaded = step.loaded
    if step.decision.command is C.SIGN_AGREEMENT:
        final = loaded.final_agreement
        if final is None or final.final_pdf_sha256 is None:  # decide() checked the status
            raise sm.Conflict("no_final_agreement", "There is no final agreement version to sign.")
        return SignatureDocumentKind.AGREEMENT, final.id, final.final_pdf_sha256
    document = loaded.nda if step.decision.command is C.SIGN_NDA else loaded.certificate
    if document is None:
        raise sm.Conflict("no_document", "There is no document to sign at this stage.")
    return document.kind, document.ref, document.sha256


async def _sign(step: Step) -> None:
    kind, ref, digest = _document_to_sign(step)
    assert step.step_up is not None  # every signing command requires the step-up
    signature = Signature(
        id=uuid7(),
        engagement_id=step.engagement.id,
        document_kind=kind,
        document_ref=ref,
        document_sha256=digest,
        signer_user_id=step.party.user_id,
        party=step.party.actor.party,
        step_up_method=step.step_up,
        ip=_ip(step.meta.ip),
        user_agent=(step.meta.user_agent or "")[:200] or None,
    )
    step.db.add(signature)
    await step.db.flush()
    await audit(
        step.db,
        "doc.signed",
        actor_user_id=step.party.user_id,
        org_id=None if step.party.is_developer else step.party.org_id,
        subject_type="engagement",
        subject_id=step.engagement.id,
        payload={
            "signature_id": str(signature.id),
            "document_kind": kind.value,
            "document_ref": str(ref),
            "document_sha256": digest.hex(),
            "step_up_method": step.step_up.value,
        },
    )
    if step.decision.to_state is S.IN_IMPLEMENTATION and step.loaded.final_agreement is not None:
        step.loaded.final_agreement.status = AgreementStatus.SIGNED  # both signed its hash (the database checks)
        await step.db.flush()
    step.payload.update(document_ref=str(ref), document_sha256=digest.hex(), signature_id=str(signature.id))


def _check_terms(terms: TermsInput, step: Step) -> None:
    policy, today = step.policy, local_date(step.now)
    if not 1 <= len(terms.milestones) <= policy.max_milestones:
        raise sm.Invalid("invalid_terms", f"An agreement has 1 to {policy.max_milestones} milestones.")
    if not 0 <= terms.deemed_acceptance_days <= policy.deemed_acceptance_days_max:
        raise sm.Invalid("invalid_terms", f"Deemed acceptance is 0 to {policy.deemed_acceptance_days_max} days.")
    if terms.exclusivity is not None and not 0 < len(terms.exclusivity.strip()) <= policy.exclusivity_max_chars:
        raise sm.Invalid("invalid_terms", f"The exclusivity clause is 1 to {policy.exclusivity_max_chars} characters.")
    for m in terms.milestones:
        if not 1 <= m.review_window_bd <= policy.review_window_bd_max or m.due_date < today:
            raise sm.Invalid(
                "invalid_terms",
                f"Each milestone needs a due date from today and a review window of 1 to"
                f" {policy.review_window_bd_max} business days.",
            )


async def _propose_terms(step: Step) -> None:
    terms = step.inputs.terms
    if terms is None:  # the router always sends one
        raise sm.Invalid("invalid_terms", "Give the agreement's terms.")
    _check_terms(terms, step)
    latest = step.loaded.latest_agreement
    agreement = Agreement(
        id=uuid7(),
        engagement_id=step.engagement.id,
        version=(latest.version + 1) if latest is not None else 1,
        ip_terms=terms.ip_terms,
        exclusivity=terms.exclusivity.strip() if terms.exclusivity else None,
        deemed_acceptance_days=terms.deemed_acceptance_days,
        status=AgreementStatus.DRAFT,
        created_by=step.party.user_id,
    )
    step.db.add(agreement)
    await step.db.flush()
    for seq, m in enumerate(terms.milestones, start=1):
        step.db.add(
            Milestone(
                id=uuid7(),
                agreement_id=agreement.id,
                engagement_id=step.engagement.id,
                seq=seq,
                deliverable=m.deliverable.strip(),
                amount_kes_minor=m.amount_kes_minor,
                due_date=m.due_date,
                review_window_bd=m.review_window_bd,
                state=MilestoneState.PLANNED,
            )
        )
    await step.db.flush()
    step.payload.update(agreement_id=str(agreement.id), version=agreement.version)


async def agreement_document(db: AsyncSession, agreement: Agreement) -> documents.Document:
    """The text of an agreement version (the one whose hash is signed once it is final)."""
    milestones = (
        await db.execute(select(Milestone).where(Milestone.agreement_id == agreement.id).order_by(Milestone.seq))
    ).scalars()
    if agreement.ip_terms is None or agreement.deemed_acceptance_days is None:  # every version sets both
        raise sm.Conflict("invalid_terms", "This agreement version has no IP terms or deemed-acceptance clause.")
    return documents.agreement(
        agreement_id=agreement.id,
        engagement_id=agreement.engagement_id,
        version=agreement.version,
        ip_terms=agreement.ip_terms,
        exclusivity=agreement.exclusivity,
        deemed_acceptance_days=agreement.deemed_acceptance_days,
        milestones=[
            documents.MilestoneTerms(m.seq, m.deliverable, m.amount_kes_minor, m.due_date, m.review_window_bd)
            for m in milestones
        ],
    )


async def _mark_final(step: Step) -> None:
    latest = step.loaded.latest_agreement
    assert latest is not None  # decide(): a draft exists
    document = await agreement_document(step.db, latest)
    latest.final_pdf_sha256 = document.sha256
    latest.status = AgreementStatus.FINAL
    await step.db.flush()
    step.payload.update(agreement_id=str(latest.id), version=latest.version, document_sha256=document.sha256.hex())


async def _reopen(step: Step) -> None:
    final = step.loaded.final_agreement
    if final is not None:
        step.payload["agreement_id"] = str(final.id)


async def _milestone_step(step: Step) -> None:
    milestone = step.milestone
    assert milestone is not None  # execute() found it
    if step.decision.command is C.SUBMIT_MILESTONE:
        already = await step.db.scalar(
            select(EngagementEndorsement.id).where(
                EngagementEndorsement.engagement_id == step.engagement.id,
                EngagementEndorsement.milestone_id == milestone.id,
                EngagementEndorsement.party == EngagementParty.DEVELOPER,
            )
        )
        step.keep_endorsement = already is not None
    _, target = sm.MILESTONE_STEPS[step.decision.command]
    milestone.state = target
    await step.db.flush()
    step.payload.update(milestone_id=str(milestone.id), milestone_state=target.value)


async def _accept_delivery(step: Step) -> None:
    agreement = step.loaded.signed_agreement
    if agreement is None or agreement.final_pdf_sha256 is None:  # the database's gate for DELIVERED
        raise sm.Conflict("no_signed_agreement", "There is no signed agreement.")
    document = documents.acceptance_certificate(
        ref=uuid7(),
        engagement_id=step.engagement.id,
        agreement_id=agreement.id,
        agreement_sha256=agreement.final_pdf_sha256,
        milestone_ids=[m.id for m in step.loaded.milestones],
    )
    step.payload.update(document_ref=str(document.ref), document_sha256=document.sha256.hex())


async def _record_payment(step: Step) -> None:
    payment = step.inputs.payment
    if payment is None:  # the router always sends one
        raise sm.Invalid("invalid_payment", "Give the amount, method and date of the payment.")
    if payment.paid_on > local_date(step.now):
        raise sm.Invalid("invalid_payment", "The payment date cannot be in the future.")
    reference = (payment.reference or "").strip() or None
    row = PaymentRecord(
        id=uuid7(),
        engagement_id=step.engagement.id,
        milestone_id=None,
        amount_kes_minor=payment.amount_kes_minor,
        method=payment.method,
        reference=reference,
        paid_on=payment.paid_on,
        recorded_by=step.party.user_id,
    )
    step.db.add(row)
    await step.db.flush()
    step.payload.update(payment_id=str(row.id), amount_kes_minor=payment.amount_kes_minor)


async def _confirm_payment(step: Step) -> None:
    row = step.loaded.final_payment
    assert row is not None  # decide(): a payment is recorded
    received = step.inputs.amount_received
    if received is None:  # the router always sends one
        raise sm.Invalid("invalid_payment", "Give the amount you received.")
    sm.check_payment(row.amount_kes_minor, received)
    row.confirmed_by = step.party.user_id
    row.confirmed_amount_kes_minor = received
    await step.db.flush()
    step.payload.update(payment_id=str(row.id), amount_kes_minor=received)


Effect = Callable[[Step], Awaitable[None]]
EFFECTS: Final[dict[sm.Command, Effect]] = {
    C.ACCEPT_INTEREST: _accept_interest,
    C.DECLINE_INTEREST: _decline,
    C.START_REVIEW: _nothing,
    C.DECLINE: _decline,
    C.APPROVE: _approve,
    C.WITHDRAW: _nothing,
    C.MARK_CONTACTED: _nothing,
    C.CONFIRM_CONTACT: _nothing,
    C.SEND_NDA: _send_nda,
    C.SIGN_NDA: _sign,
    C.PROPOSE_TERMS: _propose_terms,
    C.MARK_FINAL: _mark_final,
    C.REOPEN_NEGOTIATION: _reopen,
    C.SIGN_AGREEMENT: _sign,
    C.START_MILESTONE: _milestone_step,
    C.SUBMIT_MILESTONE: _milestone_step,
    C.ACCEPT_MILESTONE: _milestone_step,
    C.REQUEST_CHANGES: _milestone_step,
    C.DELIVER: _nothing,
    C.ACCEPT_DELIVERY: _accept_delivery,
    C.SIGN_CERTIFICATE: _sign,
    C.RECORD_PAYMENT: _record_payment,
    C.CONFIRM_PAYMENT: _confirm_payment,
}


# ------------------------------------------------------------------------------------------------ opening (P4)


class OpenRefused(Exception):
    """``open_engagement_for_tag`` refused: ``code`` is stable (``tag_not_found``, ``tag_not_delivered``,
    ``proposal_not_published``, ``engagement_exists``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def open_engagement_for_tag(db: AsyncSession, tag_id: UUID) -> Engagement:
    """Open the ``SUBMITTED`` engagement of a delivered tag (docs/spec/06 6.9 stage 1; AC-PROP-1/b). P4 (Pitch) calls
    it in the developer's own transaction (``bind_tenant(db, user_id=<the tag's developer>)``) right after it inserts a
    tag with status ``delivered`` (an E2 organisation), or when a held tag becomes delivered on the organisation's E2
    approval; the caller commits (and sends EM1).

    The engagement is for the proposal's current registered version, origin ``tagged``, with the ``SUBMITTED``
    deadline from policy.yaml on the business-day calendar; the database writes its genesis event (seq 1, the
    developer as actor) and refuses it unless the proposal is published and clear, the organisation E2, not
    suspended or delisted, and the developer's tag to it open and delivered (revision 0003). One engagement per
    proposal and organisation: a second call raises ``OpenRefused("engagement_exists")``.
    """
    user_id, _ = tenant_of(db)
    tag = await db.get(Tag, tag_id)
    if tag is None or user_id is None or tag.developer_id != user_id:
        raise OpenRefused("tag_not_found", "No tag of yours with that id.")
    if tag.status is not TagStatus.DELIVERED or tag.closed_at is not None:
        raise OpenRefused("tag_not_delivered", "Only an open, delivered tag opens an engagement.")
    version_id = await db.scalar(select(Proposal.current_version_id).where(Proposal.id == tag.proposal_id))
    if version_id is None:
        raise OpenRefused("proposal_not_published", "The proposal has no registered version.")
    existing = await db.scalar(
        select(Engagement.id).where(Engagement.proposal_id == tag.proposal_id, Engagement.org_id == tag.org_id)
    )
    if existing is not None:
        raise OpenRefused("engagement_exists", "This proposal already has an engagement with this organisation.")
    now = await app_now(db)
    deadline = sm.stage_deadline(S.SUBMITTED, now, await load_holidays(db, local_date(now)), get_policy())
    engagement = Engagement(
        id=uuid7(),
        proposal_id=tag.proposal_id,
        org_id=tag.org_id,
        developer_id=user_id,
        version_id=version_id,
        origin=EngagementOrigin.TAGGED,
        state=S.SUBMITTED,
        stage_deadline_at=deadline,
    )
    db.add(engagement)
    await db.flush()
    await db.refresh(engagement)
    return engagement
