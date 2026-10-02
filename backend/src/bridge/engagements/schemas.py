"""Tracker API bodies and views (REQ-ENG-01..REQ-ENG-03, REQ-ENG-05, REQ-ENG-07..REQ-ENG-10 main path).

Every command body carries ``lock_version``: the engagement's version the caller last read (409 ``stale`` when it
moved on). Money is KES in minor units (cents). Views never carry a signer's IP address or user agent (evidence kept
for disputes), and the History (``HistoryOut``) is the same JSON for both parties (AC-TRACK-3).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from bridge.engagements.state_machine import Command
from bridge.models.enums import (
    AgreementStatus,
    ContactChannel,
    EndorsementMethod,
    EngagementActorRole,
    EngagementEndReason,
    EngagementOrigin,
    EngagementParty,
    EngagementState,
    GrantSource,
    IpTerms,
    MilestoneState,
    PaymentMethod,
    SignatureDocumentKind,
    StepUpMethod,
)

NO_NUL = r"^[^\x00]*$"  # PostgreSQL text cannot hold NUL
# One line of text: no C0 control (line breaks included) and no DEL, so a party's words cannot forge a line of a
# signed text or a record (security review P5, MINOR 1).
ONE_LINE = r"^[^\x00-\x1f\x7f]*$"
MAX_KES_MINOR = 10**13  # KES 100 billion: a typo guard, far above any engagement


class CommandBody(BaseModel):
    lock_version: int = Field(ge=0, description="The engagement's lock_version when the caller last read it")


class ApproveBody(CommandBody):
    """Approve to proceed (non-binding): the organisation's contact person, channel and contact-by date."""

    contact_user_id: UUID
    contact_channel: ContactChannel
    contact_by: date


class DeclineBody(CommandBody):
    reason: EngagementEndReason
    other_text: str | None = Field(default=None, max_length=1000, pattern=NO_NUL)
    internal_start_date: date | None = None
    attested: bool = False


class MilestoneBody(BaseModel):
    deliverable: str = Field(min_length=1, max_length=500, pattern=ONE_LINE)
    amount_kes_minor: int = Field(gt=0, le=MAX_KES_MINOR)
    due_date: date
    review_window_bd: int | None = Field(
        default=None, ge=1, le=60, description="business days; omitted: policy.yaml's review_window_bd_default"
    )


class TermsBody(CommandBody):
    ip_terms: IpTerms
    deemed_acceptance_days: int = Field(ge=0, le=90, description="0: milestones are never deemed accepted")
    exclusivity: str | None = Field(default=None, max_length=500, pattern=ONE_LINE)
    milestones: list[MilestoneBody] = Field(min_length=1, max_length=20)


class PaymentBody(CommandBody):
    amount_kes_minor: int = Field(gt=0, le=MAX_KES_MINOR)
    method: PaymentMethod
    reference: str | None = Field(default=None, max_length=64, pattern=ONE_LINE)
    paid_on: date


class ConfirmPaymentBody(CommandBody):
    amount_received_kes_minor: int = Field(ge=0, le=MAX_KES_MINOR)


# Side states (REQ-ENG-10 part; docs/spec/06 6.9 side branches). Each text becomes the event's note
# (engagement_notes): read by both parties on the tracker, never in the hash chain. Blank text is 422 invalid_note.
class RequestInfoBody(CommandBody):
    """The organisation's question (stages 1-2): the review clock pauses until the developer answers."""

    question: str = Field(min_length=1, max_length=2000, pattern=NO_NUL)


class AnswerInfoBody(CommandBody):
    """The developer's answer: the engagement returns to the stage it was in, its deadline moved by the pause."""

    answer: str = Field(min_length=1, max_length=2000, pattern=NO_NUL)


class PauseBody(CommandBody):
    """Put the engagement on hold before the agreement, with a reason and the date it resumes."""

    reason: str = Field(min_length=1, max_length=500, pattern=ONE_LINE)
    resume_at: date = Field(
        description="The Africa/Nairobi date it resumes: after today, at most policy.yaml's on_hold.max_days (60) ahead"
    )


class ResumeBody(CommandBody):
    """Resume a hold before its date, with a reason; due dates move by the business days on hold."""

    reason: str = Field(min_length=1, max_length=500, pattern=ONE_LINE)


class DueOut(BaseModel):
    due_on: date
    business_days_left: int
    overdue: bool


class PendingOut(BaseModel):
    command: Command
    party: EngagementParty


class EngagementSummary(BaseModel):
    id: UUID
    proposal_id: UUID
    version_id: UUID
    proposal_title: str
    org_id: UUID
    org_name: str
    developer_id: UUID | None = Field(
        description="The developer's user id; null for the organisation until the developer is named"
    )
    developer_name: str = Field(
        description="The developer's display name; for the organisation, their pseudonymous handle until the"
        " engagement reaches INTEREST_CONFIRMED (docs/spec/06 6.1)"
    )
    developer_named: bool = Field(description="False while developer_name is the pseudonymous handle")
    origin: EngagementOrigin
    state: EngagementState
    stage_label: str
    stage_group: str | None
    end_reason: EngagementEndReason | None
    stage_entered_at: datetime
    stage_deadline_at: datetime | None
    due: DueOut | None
    ended_at: datetime | None
    lock_version: int
    whose_turn: list[EngagementParty]
    updated_at: datetime
    paused_from: EngagementState | None = Field(
        description="In a side state (INFO_REQUESTED, ON_HOLD): the stage it was entered from and returns to"
    )


class EngagementList(BaseModel):
    items: list[EngagementSummary]


class ContactOut(BaseModel):
    user_id: UUID
    name: str | None
    role: str | None
    channel: ContactChannel
    contact_by: date


class EndorsementOut(BaseModel):
    id: UUID
    stage: EngagementState
    stage_round: int
    milestone_id: UUID | None
    party: EngagementParty
    user_id: UUID | None
    name: str | None
    role: EngagementActorRole
    method: EndorsementMethod
    endorsed_at: datetime


class MilestoneOut(BaseModel):
    id: UUID
    seq: int
    deliverable: str
    amount_kes_minor: int
    due_date: date
    review_window_bd: int
    state: MilestoneState
    review_due_on: date | None = Field(
        default=None, description="while submitted for review: the submission's Nairobi date plus the review window"
    )


class AgreementOut(BaseModel):
    id: UUID
    version: int
    status: AgreementStatus
    ip_terms: IpTerms | None
    exclusivity: str | None
    deemed_acceptance_days: int | None
    document_sha256: str | None
    drafted_by: EngagementParty
    milestones: list[MilestoneOut]
    created_at: datetime


class SignatureOut(BaseModel):
    id: UUID
    document_kind: SignatureDocumentKind
    document_ref: UUID
    document_sha256: str
    party: EngagementParty
    signer_user_id: UUID
    signer_name: str | None
    step_up_method: StepUpMethod
    signed_at: datetime


class PaymentOut(BaseModel):
    id: UUID
    milestone_id: UUID | None
    amount_kes_minor: int
    method: PaymentMethod
    reference: str | None
    paid_on: date
    recorded_by: UUID
    recorded_at: datetime
    confirmed_by: UUID | None
    confirmed_at: datetime | None
    confirmed_amount_kes_minor: int | None


class NoteOut(BaseModel):
    """The text a side-state command carried, in event order: the organisation's question (``info_request``), the
    developer's answer (``info_answer``), a hold's reason with its resume date (``hold``), an early resume's reason
    (``resume``). ``by`` is the party that wrote it."""

    kind: Literal["info_request", "info_answer", "hold", "resume"]
    body: str
    resume_at: date | None
    by: EngagementParty
    at: datetime


class DocumentRefOut(BaseModel):
    kind: SignatureDocumentKind
    ref: UUID
    sha256: str


class EngagementDetail(EngagementSummary):
    my_party: EngagementParty
    my_roles: list[EngagementActorRole]
    actions: list[Command] = Field(description="The commands the caller may run now (the action buttons)")
    awaiting: list[PendingOut] = Field(description="What moves the engagement on, and whose turn each is")
    contact: ContactOut | None
    endorsements: list[EndorsementOut] = Field(description="The current stage's endorsements (this round)")
    agreements: list[AgreementOut]
    signatures: list[SignatureOut]
    payments: list[PaymentOut]
    documents: list[DocumentRefOut]
    notes: list[NoteOut] = Field(description="The side states' questions, answers and reasons, in event order")


class HistoryEventOut(BaseModel):
    id: UUID
    seq: int
    created_at: datetime
    actor_user_id: UUID | None
    actor_name: str | None
    actor_role: EngagementActorRole
    command: str
    from_state: EngagementState | None
    to_state: EngagementState
    end_reason: EngagementEndReason | None
    stage_deadline_at: datetime | None
    payload: dict[str, Any]
    prev_hash: str
    hash: str


class HistoryOut(BaseModel):
    """The engagement's History tab: every event of the hash chain and every endorsement, identical for both
    parties; ``chain_verified`` is the independent verifier's result over the events read."""

    engagement_id: UUID
    chain_verified: bool
    events: list[HistoryEventOut]
    endorsements: list[EndorsementOut]


class DocumentOut(BaseModel):
    kind: SignatureDocumentKind
    ref: UUID
    sha256: str = Field(description="The recorded SHA-256 (hex) that signatures refer to")
    text: str
    intact: bool = Field(description="The re-rendered text still hashes to the recorded SHA-256")


class ContactRevealOut(BaseModel):
    """The developer's contact details, for the organisation's named contact once the engagement reached
    INTEREST_CONFIRMED (docs/spec/06 6.9 stage 3)."""

    developer_name: str
    email: str | None
    phone: str | None = Field(description="Not revealed in the prototype (the verified phone is the developer's)")


class InterestBody(BaseModel):
    """Express interest (docs/spec/06 6.9 stage 0; REQ-ENG-04): the proposal, where the organisation found it (a
    scout match, which ``match_id`` names, or the Browse repo) and the contact it names with a channel and a
    contact-by date."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID
    origin: Literal[EngagementOrigin.ORG_AGENT_MATCH, EngagementOrigin.ORG_BROWSE]
    match_id: UUID | None = Field(default=None, description="The scout match (required for org_agent_match only).")
    contact_user_id: UUID
    channel: ContactChannel
    contact_by: date


class Tier2ShareOut(BaseModel):
    """Whether the developer shared the full proposal (Tier 2) with the engagement's organisation: a live grant."""

    engagement_id: UUID
    shared: bool
    grant_id: UUID | None
    source: GrantSource | None
    shared_at: datetime | None
    counts_as_unlock: bool = Field(description="True for a proposal not tagged to the organisation (REQ-BIL-03).")
