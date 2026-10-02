"""Running a tracker command (REQ-ENG-01..REQ-ENG-10 main path; docs/spec/06 6.9).

``execute`` is the one way the API changes an engagement:

1. lock the engagement (``FOR UPDATE``, until commit) and check the caller's party and roles (403, the state
   machine), the fresh second factor where the command signs or endorses (403, ADR-002), and ``lock_version`` against
   the version the caller last read (409 ``stale``);
2. ask the state machine (``decide``) with the engagement's facts: a command not in the table for this state is 409;
3. apply the command's own effects (the contact, a decline's details, an NDA, an agreement version, a signature, a
   milestone step, a payment, a side state's text and dates), then record the party's endorsement and append the
   event: the database projects the state, sets the times and extends the hash chain (revision 0003); a side-state
   command's note follows its event (revision 0006: the event's seq read back, written as its actor); the engagement
   is re-read;
4. close the tag when the engagement ends, and queue the other party's notification (outbox, same transaction).

Side states (REQ-ENG-10 part): entering ``INFO_REQUESTED`` or ``ON_HOLD`` records the date of the deadline it pauses in
the event's payload (``paused_due_on``; a hold also its ``resume_at``); leaving it for the state it was entered from
sets that deadline moved by the business days paused (``state_machine.resumed_deadline``). A note's text never enters
the payload, a log or an audit detail.

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
    EngagementNote,
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
    entering_event,
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
    ModerationState,
    NdaKind,
    OrgRole,
    OrgVerification,
    PaymentMethod,
    ProposalStatus,
    SignatureDocumentKind,
    StepUpMethod,
    TagStatus,
)
from bridge.proposals.models import Proposal, Tag
from bridge.tenancy.models import Organization
from bridge.tenancy.service import membership_of

C = sm.Command
S = EngagementState
UNKNOWN_CONTACT_ROLE: Final = "member"  # a contact whose role the developer cannot read (stage 0)
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
    review_window_bd: int | None = None  # None: policy.yaml's milestones.review_window_bd_default

    def window(self, policy: TrackerPolicy) -> int:
        return policy.review_window_bd_default if self.review_window_bd is None else self.review_window_bd


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
    note: str | None = None  # a question, an answer or a reason (side states)
    resume_at: date | None = None  # a hold's resume date


@dataclass(frozen=True, slots=True)
class NoteInput:
    """The note a side-state command writes after its event (``engagement_notes``)."""

    kind: str
    body: str
    resume_at: date | None = None


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
    sets_deadline: bool = False  # the effect chose the event's stage deadline (``deadline``), not the policy
    deadline: datetime | None = None
    note: NoteInput | None = None


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
    if step.note is not None:
        await _write_note(step, event, step.note)
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


ENDORSEMENT_METHODS: Final = {
    StepUpMethod.TOTP: EndorsementMethod.TOTP,
    StepUpMethod.PASSKEY: EndorsementMethod.PASSKEY,
}


async def _endorse(step: Step, endorsement_id: UUID, stage: EngagementState) -> None:
    """The party's endorsement, its method the second factor this request verified (never assumed)."""
    party, decision = step.party, step.decision
    if step.step_up is None:  # the table makes every endorsing row require the step-up; refuse rather than guess
        raise RuntimeError("an endorsement needs the step-up this request verified")
    step.db.add(
        EngagementEndorsement(
            id=endorsement_id,
            engagement_id=step.engagement.id,
            stage=stage,
            milestone_id=step.milestone.id if step.milestone else None,
            party=party.actor.party,
            user_id=party.user_id,
            role=decision.role,
            method=ENDORSEMENT_METHODS[step.step_up],
        )
    )
    await step.db.flush()


async def _append(step: Step) -> EngagementEvent:
    decision = step.decision
    deadline = None
    if step.sets_deadline:
        deadline = step.deadline
    elif decision.changes_state or decision.renews_deadline:
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


async def _write_note(step: Step, event: EngagementEvent, note: NoteInput) -> None:
    """The note of a side-state event, right after it (revision 0006): its seq is the database's, read back; written
    as the event's actor, its time the database's clock."""
    seq = await step.db.scalar(select(EngagementEvent.seq).where(EngagementEvent.id == event.id))
    if seq is None:  # the event was just flushed in this transaction
        raise RuntimeError("the event of a note is not readable")
    step.db.add(
        EngagementNote(
            id=uuid7(),
            engagement_id=step.engagement.id,
            event_seq=seq,
            kind=note.kind,
            body=note.body,
            resume_at=note.resume_at,
            created_by=step.party.user_id,
        )
    )
    await step.db.flush()


async def open_tag(db: AsyncSession, engagement: Engagement) -> Tag | None:
    """The developer's open tag behind a ``tagged`` engagement (an organisation's interest has none)."""
    if engagement.origin is not EngagementOrigin.TAGGED:
        return None
    found: Tag | None = await db.scalar(
        select(Tag).where(
            Tag.proposal_id == engagement.proposal_id,
            Tag.org_id == engagement.org_id,
            Tag.developer_id == engagement.developer_id,
            Tag.closed_at.is_(None),
        )
    )
    return found


async def close_tag(db: AsyncSession, engagement: Engagement) -> None:
    """The engagement ended (DECLINED, EXPIRED or CLOSED): its tag closes (``app_close_tag``), freeing the developer's
    one open tag with this organisation."""
    tag = await open_tag(db, engagement)
    if tag is not None:
        await db.execute(_CLOSE_TAG, {"tag_id": tag.id})


async def _open_tag(step: Step) -> Tag | None:
    return await open_tag(step.db, step.engagement)


async def _withdraw_tag(step: Step) -> None:
    """The developer withdraws their tag with the engagement (the tag closes; Tier-2 access stops with the
    engagement's WITHDRAWN state in ``app_tier2_granted``)."""
    tag = await _open_tag(step)
    if tag is not None:
        tag.status = TagStatus.WITHDRAWN
        await step.db.flush()


async def _close_tag(step: Step) -> None:
    await close_tag(step.db, step.engagement)


# ------------------------------------------------------------------------------------------------ the effects


async def _nothing(step: Step) -> None:
    return None


async def _accept_interest(step: Step) -> None:
    """The contact the organisation named when it expressed interest, recorded like an approval's. The developer
    cannot read the organisation's roster: the role is the one an earlier event recorded, else ``member`` (the
    database holds the contact to be an active member)."""
    engagement = step.engagement
    if engagement.contact_user_id is None or engagement.contact_channel is None or engagement.contact_by is None:
        raise sm.Conflict("contact_not_named", "The organisation has not named its contact person yet.")
    role = await step.db.scalar(
        select(EngagementEvent.payload["contact_role"].astext)
        .where(EngagementEvent.engagement_id == engagement.id, EngagementEvent.payload.has_key("contact_role"))
        .order_by(EngagementEvent.seq.desc())
        .limit(1)
    )
    step.named_deadline = engagement.contact_by
    step.payload.update(
        contact_user_id=str(engagement.contact_user_id),
        contact_role=role or UNKNOWN_CONTACT_ROLE,
        contact_channel=engagement.contact_channel.value,
        contact_by=engagement.contact_by.isoformat(),
    )


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
        if not 1 <= m.window(policy) <= policy.review_window_bd_max or m.due_date < today:
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
                review_window_bd=m.window(step.policy),
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


def _paused_deadline(step: Step) -> None:
    """Entering a side state: the stage's deadline is paused; its date stays in the chain for the return."""
    deadline = step.engagement.stage_deadline_at
    if deadline is not None:
        step.payload["paused_due_on"] = local_date(deadline).isoformat()


def _iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:  # the chain holds what _paused_deadline wrote; anything else reads as no deadline
        return None


async def returning_deadline(db: AsyncSession, engagement: Engagement, now: datetime) -> datetime | None:
    """The deadline the stage an engagement in a side state returns to has on ``now``'s Nairobi date: the one it had
    when it was paused, moved by the business days since (the side state's entering event and its payload)."""
    paused = await entering_event(db, engagement.id, engagement.state)
    if paused is None:  # every side state has its entering event; refuse rather than guess
        raise sm.Conflict("no_return_state", "The state this engagement returns to is not known. Reload and retry.")
    paused_on, today = local_date(paused.created_at), local_date(now)
    due_on = _iso_date(dict(paused.payload).get("paused_due_on"))
    holidays = await load_holidays(db, today, since=min(paused_on, due_on or paused_on))
    return sm.resumed_deadline(due_on, paused_on, today, holidays)


async def _request_info(step: Step) -> None:
    question = sm.check_note(step.inputs.note, sm.QUESTION_MAX_CHARS)
    _paused_deadline(step)
    step.sets_deadline, step.deadline = True, None  # the clock is paused until the answer
    step.note = NoteInput("info_request", question)


async def _hold(step: Step) -> None:
    reason = sm.check_note(step.inputs.note, sm.REASON_MAX_CHARS)
    resume_at = step.inputs.resume_at
    if resume_at is None:  # the router always sends one
        raise sm.Invalid("invalid_resume_at", "Choose the date the engagement resumes.")
    sm.check_resume_at(resume_at, step.now, step.policy)
    _paused_deadline(step)
    step.payload["resume_at"] = resume_at.isoformat()
    step.sets_deadline, step.deadline = True, sm.end_of_day(resume_at)  # "due" reads the resume date
    step.note = NoteInput("hold", reason, resume_at)


async def _return(step: Step) -> None:
    """Answering the organisation's question, or resuming a hold early: back to the state it was entered from."""
    answer = step.decision.command is C.ANSWER_INFO
    text = sm.check_note(step.inputs.note, sm.QUESTION_MAX_CHARS if answer else sm.REASON_MAX_CHARS)
    step.sets_deadline = True
    step.deadline = await returning_deadline(step.db, step.engagement, step.now)
    step.note = NoteInput("info_answer" if answer else "resume", text)


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
    C.REQUEST_INFO: _request_info,
    C.ANSWER_INFO: _return,
    C.PAUSE: _hold,
    C.RESUME: _return,
}


# ------------------------------------------------------------------------------------------------ opening (P4)


class OpenRefused(Exception):
    """``open_engagement_for_tag`` refused: ``code`` is stable (``tag_not_found``, ``tag_not_delivered``,
    ``proposal_not_published``, ``org_unavailable``, ``own_organisation``, ``engagement_exists``, ``refused``)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def _existing_engagement(db: AsyncSession, proposal_id: UUID, org_id: UUID) -> UUID | None:
    found: UUID | None = await db.scalar(
        select(Engagement.id).where(Engagement.proposal_id == proposal_id, Engagement.org_id == org_id)
    )
    return found


async def _organisation_refusal(db: AsyncSession, org_id: UUID) -> OpenRefused | None:
    """The organisation must be E2, not suspended and not delisted (a delisted one is not even readable)."""
    org = (
        await db.execute(
            select(Organization.verification, Organization.suspended_at, Organization.delisted_at).where(
                Organization.id == org_id
            )
        )
    ).one_or_none()
    if org is None or org.verification is not OrgVerification.E2 or org.suspended_at or org.delisted_at:
        return OpenRefused(
            "org_unavailable", "The organisation cannot receive engagements now (not verified, suspended or delisted)."
        )
    return None


async def open_engagement_for_tag(db: AsyncSession, tag_id: UUID) -> Engagement:
    """Open the ``SUBMITTED`` engagement of a delivered tag (docs/spec/06 6.9 stage 1; AC-PROP-1/b). P4 (Pitch) calls
    it in the developer's own transaction (``bind_tenant(db, user_id=<the tag's developer>)``) right after it inserts a
    tag with status ``delivered`` (an E2 organisation), or when a held tag becomes delivered on the organisation's E2
    approval; the caller commits (and sends EM1).

    The engagement is for the proposal's current registered version, origin ``tagged``, with the ``SUBMITTED``
    deadline from policy.yaml on the business-day calendar; the database writes its genesis event. Every refusal is an
    ``OpenRefused`` with a code, checked here first (the tag, the proposal published and clear, the organisation E2 and
    neither suspended nor delisted, the developer not one of its members, one engagement per proposal and
    organisation), with the database's refusals of the insert as the backstop (a concurrent duplicate is
    ``engagement_exists``, a policy refusal ``refused``). The insert runs in a savepoint, so after a refusal the
    caller's transaction is still usable.
    """
    user_id, _ = tenant_of(db)
    tag = await db.get(Tag, tag_id)
    if tag is None or user_id is None or tag.developer_id != user_id:
        raise OpenRefused("tag_not_found", "No tag of yours with that id.")
    if tag.status is not TagStatus.DELIVERED or tag.closed_at is not None:
        raise OpenRefused("tag_not_delivered", "Only an open, delivered tag opens an engagement.")
    proposal = (
        await db.execute(
            select(Proposal.status, Proposal.moderation_state, Proposal.current_version_id).where(
                Proposal.id == tag.proposal_id
            )
        )
    ).one_or_none()
    if (
        proposal is None
        or proposal.status is not ProposalStatus.PUBLISHED
        or proposal.moderation_state is not ModerationState.CLEAR
        or proposal.current_version_id is None
    ):
        raise OpenRefused("proposal_not_published", "The proposal is not published and clear of moderation holds.")
    refusal = await _organisation_refusal(db, tag.org_id)
    if refusal is not None:
        raise refusal
    if await membership_of(db, tag.org_id, user_id) is not None:
        raise OpenRefused("own_organisation", "You belong to this organisation, so it cannot receive your proposal.")
    if await _existing_engagement(db, tag.proposal_id, tag.org_id) is not None:
        raise OpenRefused("engagement_exists", "This proposal already has an engagement with this organisation.")
    now = await app_now(db)
    deadline = sm.stage_deadline(S.SUBMITTED, now, await load_holidays(db, local_date(now)), get_policy())
    engagement = Engagement(
        id=uuid7(),
        proposal_id=tag.proposal_id,
        org_id=tag.org_id,
        developer_id=user_id,
        version_id=proposal.current_version_id,
        origin=EngagementOrigin.TAGGED,
        state=S.SUBMITTED,
        stage_deadline_at=deadline,
    )
    try:
        async with db.begin_nested():
            db.add(engagement)
            await db.flush()
    except DBAPIError as exc:
        sqlstate = getattr(exc.orig, "sqlstate", None)
        if sqlstate == "23505":
            raise OpenRefused(
                "engagement_exists", "This proposal already has an engagement with this organisation."
            ) from exc
        if sqlstate in ("42501", "23514"):
            raise OpenRefused("refused", "The engagement could not be opened for this tag.") from exc
        raise
    await db.refresh(engagement)
    return engagement
