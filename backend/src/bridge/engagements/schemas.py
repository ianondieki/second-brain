"""Tracker API bodies and views (REQ-ENG-01..REQ-ENG-03, REQ-ENG-05, REQ-ENG-07..REQ-ENG-10 main path).

Every command body carries ``lock_version``: the engagement's version the caller last read (409 ``stale`` when it
moved on). Money is KES in minor units (cents). Views never carry a signer's IP address or user agent (evidence kept
for disputes), and the History (``HistoryOut``) is the same JSON for both parties (AC-TRACK-3).

The tracker's detail is one shape per side (P27, D-68): ``DeveloperEngagementDetail`` (the developer's: the
prior-knowledge declaration made on their proposal and the IP nudge) and ``OrgEngagementDetail`` (an organisation
member's: the team facts and the declaration window), told apart by ``my_party``. The organisation's own triage
(``TeamFacts``: who is assigned, the members' internal recommendations) is on organisation-side schemas only
(``OrgEngagementSummary``, ``OrgEngagementDetail``, the Inbox's engagement, the pipeline's items); the developer's
``EngagementSummary`` and ``DeveloperEngagementDetail`` have no ``team`` field at all.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
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
    OrgRole,
    PaymentMethod,
    ProcurementRoute,
    RecommendationStance,
    SignatureDocumentKind,
    StepUpMethod,
)

NO_NUL = r"^[^\x00]*$"  # PostgreSQL text cannot hold NUL
# One line of text: no C0 control (line breaks included) and no DEL, so a party's words cannot forge a line of a
# signed text or a record (security review P5, MINOR 1).
ONE_LINE = r"^[^\x00-\x1f\x7f]*$"
# Several lines: line feeds and tabs are the only control characters (no carriage return, escape or DEL), so a
# party's text renders as typed and cannot steer a terminal or a log viewer.
LINES = r"^[^\x00-\x08\x0b-\x1f\x7f]*$"
MAX_KES_MINOR = 10**13  # KES 100 billion: a typo guard, far above any engagement


class CommandBody(BaseModel):
    lock_version: int = Field(ge=0, description="The engagement's lock_version when the caller last read it")


class ApproveBody(CommandBody):
    """Approve to proceed (non-binding): the organisation's contact person, channel and contact-by date. A public
    entity's approval enters its procurement route (3b): the contact-by date is named with the route, and one sent
    here is not used."""

    contact_user_id: UUID
    contact_channel: ContactChannel
    contact_by: date | None = Field(
        default=None,
        description="Required for a private organisation (422 invalid_contact_by without it): from today to"
        " policy.yaml's contact_by_max_bd (5) business days ahead. Not used for a public entity, which names it with"
        " its procurement route",
    )


class ProcurementBody(BaseModel):
    """A public entity's procurement route (stage 3b; docs/spec/06 6.9), chosen by its owner or admin: how it will
    buy, the written justification (required for direct procurement) and the contact-by date of stage 3."""

    model_config = ConfigDict(extra="forbid")

    route: ProcurementRoute
    justification: str | None = Field(
        default=None,
        max_length=2000,
        pattern=LINES,
        description="Plain text, line breaks allowed; trimmed, empty is none. Direct procurement needs 20 to 1,000"
        " characters (422 justification_required); the other routes take none or at most 1,000 (422"
        " invalid_justification). No contact details or links before first contact (422 contains_contact). Both"
        " parties read it",
    )
    contact_by: date = Field(
        description="The date the named contact reaches the developer by: from today to policy.yaml's"
        " contact_by_max_bd (5) business days ahead (422 invalid_contact_by)"
    )
    lock_version: int | None = Field(
        default=None, ge=0, description="The engagement's lock_version when last read; when sent, 409 stale if it moved"
    )


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

    question: str = Field(min_length=1, max_length=2000, pattern=LINES)


class AnswerInfoBody(CommandBody):
    """The developer's answer: the engagement returns to the stage it was in, its deadline moved by the pause."""

    answer: str = Field(min_length=1, max_length=2000, pattern=LINES)


class PauseBody(CommandBody):
    """Put the engagement on hold before the agreement, with a reason and the date it resumes."""

    reason: str = Field(min_length=1, max_length=500, pattern=ONE_LINE)
    resume_at: date = Field(
        description="The Africa/Nairobi date it resumes: after today, at most policy.yaml's on_hold.max_days (60) ahead"
    )


class ResumeBody(CommandBody):
    """Resume a hold before its date, with a reason; due dates move by the business days on hold."""

    reason: str = Field(min_length=1, max_length=500, pattern=ONE_LINE)


def _due_at_optional_in_web_types(schema: dict[str, Any]) -> None:
    """``due_at`` is always sent; left out of ``required`` it stays optional in the generated web types, so clients
    adopt it at their own pace (the ``_without_default`` convention of the other always-sent fields)."""
    schema["required"] = [name for name in schema["required"] if name != "due_at"]


class DueOut(BaseModel):
    """The current step's deadline: by the end of ``due_on`` in Africa/Nairobi."""

    model_config = ConfigDict(json_schema_extra=_due_at_optional_in_web_types)

    due_on: date
    due_at: datetime = Field(
        description="The instant the window closes, for a countdown: the stage deadline (the end of due_on in"
        " Africa/Nairobi, 23:59:59 local), in UTC; overdue is true exactly once it has passed"
    )
    business_days_left: int
    overdue: bool


class PendingOut(BaseModel):
    command: Command
    party: EngagementParty


StageGroup = Literal["review", "contact_nda", "agreement", "implementation", "close"]


class StepOut(BaseModel):
    """One main-path stage of the engagement's stepper, in order."""

    state: EngagementState
    label: str
    group: StageGroup


class ProcurementOut(BaseModel):
    """A public entity's procurement route (3b), as both parties read it (R46: full transparency)."""

    route: ProcurementRoute
    justification: str | None = Field(description="The organisation's own words: plain text")
    decided_at: datetime
    decided_by_name: str = Field(description="The owner or admin who chose it ('Former member' once not readable)")


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
    # Always sent; optional in the generated web types (no default in the schema), so a client reads an older API as 0.
    unread_messages: int = Field(
        default_factory=int,
        ge=0,
        description="Messages of the engagement's thread by others that the caller has not read",
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
    seq: int | None = Field(
        default=None, description="The seq of the event the note explains (History pairs them); always set by the API"
    )


class SideLimitsOut(BaseModel):
    """What the policy's caps leave the engagement's current stage (the stage a side state returns to), each null
    where it does not apply."""

    questions_left: int | None = Field(description="Questions the organisation may still ask (stages 1-2 only)")
    holds_left: int | None = Field(description="Holds this stage may still have (before the agreement, from stage 2)")
    hold_days_left: int | None = Field(description="Calendar days on hold the engagement has left over all its holds")


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
    side_limits: SideLimitsOut | None = Field(
        default=None, description="The caps left for the current stage's side states; null once ended or none apply"
    )
    steps: list[StepOut] = Field(
        default_factory=list,
        description="The engagement's main-path stages in order (the stepper): stage 0 for an organisation's interest,"
        " stages 1-2 for a tagged proposal, PROCUREMENT_ROUTE (3b) only for a public entity (AC-TRACK-5)",
    )
    procurement: ProcurementOut | None = Field(
        default=None, description="A public entity's procurement route once chosen; null otherwise"
    )
    # Always sent; optional in the generated web types (no non-null default), so a client reads an older API as "no
    # day sent".
    today: date | None = Field(
        default=None,
        description="Today in Africa/Nairobi on the platform clock (the test clock where it is on): the day the"
        " side-state rules count from",
    )


# ---------------------------------------------------------------------------------------------------------------------
# Team triage (REQ-ENG-15, D-68; docs/spec/03 ``reviewer``: "may Recommend internally without changing state"). The
# organisation's own: on organisation-side responses only, never on a developer's.
# ---------------------------------------------------------------------------------------------------------------------

RAW_TEXT_MAX_CHARS = 1000  # a recommendation's note or an evidence title before trimming: longer is refused unread


class TeamPerson(BaseModel):
    """A member of the organisation as the team sheet names them ("Former member" once their name is not readable)."""

    user_id: UUID
    display_name: str


class StanceCounts(BaseModel):
    """How many of the organisation's members recommend each stance on the engagement (the header's tally)."""

    model_config = ConfigDict(validate_by_name=True, validate_by_alias=True, serialize_by_alias=True)

    pursue: int = Field(ge=0)
    pass_: int = Field(ge=0, alias="pass")
    discuss: int = Field(ge=0)


class MyRecommendationOut(BaseModel):
    """The caller's own recommendation on the engagement."""

    stance: RecommendationStance
    note: str | None


class TeamFacts(BaseModel):
    """The organisation's triage of one engagement, as one of its members reads it (D-68: never a developer)."""

    assignee: TeamPerson | None = Field(description="The member the engagement is assigned to; null when nobody")
    recommendations: StanceCounts
    mine: MyRecommendationOut | None = Field(description="The caller's own recommendation; null when they made none")


class TeamMemberOut(TeamPerson):
    role: OrgRole = Field(description="The member's first role of owner, admin, signatory and reviewer")


class RecommendationOut(BaseModel):
    """One member's internal recommendation: plain text, rendered as text; members of the organisation only."""

    user_id: UUID
    display_name: str
    stance: RecommendationStance
    note: str | None
    updated_at: datetime


class TeamOut(BaseModel):
    """The team sheet of one engagement (members of its organisation only)."""

    engagement_id: UUID
    members: list[TeamMemberOut] = Field(
        description="The members the engagement may be assigned to: active owners, admins, signatories and reviewers"
    )
    assignee: TeamPerson | None
    recommendations: list[RecommendationOut] = Field(description="Every member's recommendation, newest first")


class AssigneeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID | None = Field(
        description="The member to assign (an owner, admin, reviewer or signatory of the organisation); null unassigns"
    )


class RecommendationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stance: RecommendationStance
    note: str | None = Field(
        default=None,
        max_length=RAW_TEXT_MAX_CHARS,
        description="One line of plain text, at most 200 characters once trimmed; empty or null for none. Members of"
        " the organisation read it; the developer never does",
    )


class OrgEngagementSummary(EngagementSummary):
    """An engagement in the organisation's list: the summary and the organisation's own triage."""

    team: TeamFacts | None = Field(default=None, description="The organisation's triage (always sent to a member)")


class OrgEngagementList(BaseModel):
    items: list[OrgEngagementSummary]


# ---------------------------------------------------------------------------------------------------------------------
# The prior-knowledge declaration (REQ-PROV-06; docs/spec/06 6.4 pt 5).
# ---------------------------------------------------------------------------------------------------------------------


class DeclarationBody(BaseModel):
    """An organisation's prior-knowledge declaration: the SHA-256 of dated internal evidence (hashed in the browser;
    the file never leaves the device), the organisation's own title for it and the evidence's date."""

    model_config = ConfigDict(extra="forbid")

    evidence_sha256_hex: str = Field(pattern=r"^[0-9A-Fa-f]{64}$", description="The evidence's SHA-256: 64 hex digits")
    evidence_title: str = Field(
        min_length=1,
        max_length=RAW_TEXT_MAX_CHARS,
        description="One line of plain text, at most 200 characters once trimmed (the developer reads it)",
    )
    evidence_dated_on: date = Field(description="The evidence's date: no later than today in Africa/Nairobi")


class DeclarationOut(BaseModel):
    """A recorded declaration (append-only; hashed into the engagement's event chain)."""

    id: UUID
    engagement_id: UUID
    evidence_sha256_hex: str
    evidence_title: str
    evidence_dated_on: date
    declared_at: datetime
    first_tier2_view_at: datetime
    window_closes_on: date


class OrgPriorKnowledgeOut(BaseModel):
    """The organisation's declaration window on the engagement: it opens at the organisation's first Tier-2 view of the
    proposal and closes at the end of ``window_closes_on`` (the 10th Kenyan business day after that view's day) in
    Africa/Nairobi; null before any view."""

    first_tier2_view_at: datetime | None
    window_closes_on: date | None
    declared_at: datetime | None = Field(description="When the organisation declared; null while it has not")
    can_declare: bool = Field(
        description="The caller may declare now: a Tier-2 view exists, the window is open, no declaration yet, the"
        " engagement has not ended and the caller is an owner, admin or signatory"
    )


class DeveloperPriorKnowledgeOut(BaseModel):
    """The prior-knowledge declaration an organisation made on the developer's proposal, as the developer reads it."""

    org_name: str
    declared_at: datetime
    evidence_sha256_hex: str
    evidence_title: str = Field(description="The organisation's own words: plain text")
    evidence_dated_on: date


# ---------------------------------------------------------------------------------------------------------------------
# The tracker's detail, one shape per side (``my_party`` tells them apart).
# ---------------------------------------------------------------------------------------------------------------------


class DeveloperEngagementDetail(EngagementDetail):
    """The developer's tracker (no organisation triage: D-68)."""

    my_party: Literal[EngagementParty.DEVELOPER]
    prior_knowledge: DeveloperPriorKnowledgeOut | None = Field(
        default=None, description="The organisation's prior-knowledge declaration on this proposal; null when none"
    )
    ip_nudge: bool = Field(
        default=False,
        description="Show the one note about KIPI and KECOBO registration: the developer's next step is send_nda, the"
        " proposal has no Tier-2 view yet and the developer has not dismissed the note",
    )


class OrgEngagementDetail(EngagementDetail):
    """An organisation member's tracker: the organisation's triage and its declaration window."""

    my_party: Literal[EngagementParty.ORG]
    team: TeamFacts | None = Field(default=None, description="The organisation's triage (always sent to a member)")
    prior_knowledge: OrgPriorKnowledgeOut | None = Field(
        default=None, description="The organisation's declaration window (always sent to a member)"
    )


TrackerDetail = Annotated[DeveloperEngagementDetail | OrgEngagementDetail, Field(discriminator="my_party")]


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


class HistoryMessageOut(BaseModel):
    """A message of the thread as the History tab lists it (AC-TRACK-9): who wrote and when, never the text."""

    id: UUID
    sender_party: EngagementParty
    sender_name: str
    created_at: datetime


class HistoryOut(BaseModel):
    """The engagement's History tab: every event of the hash chain, every endorsement and every message of the
    thread (who and when; REQ-ENG-11), identical for both parties; ``chain_verified`` is the independent verifier's
    result over the events read (messages are not part of the chain)."""

    engagement_id: UUID
    chain_verified: bool
    events: list[HistoryEventOut]
    endorsements: list[EndorsementOut]
    messages: list[HistoryMessageOut] = Field(default_factory=list, description="The thread's messages, oldest first")


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


# ------------------------------------------------------------------------------------------- deadlines (REQ-ENG-13)


class DeadlineKind(StrEnum):
    """What a deadline is (docs/platform/tasks/P27.md track A): an engagement's stage deadline, the answer-by date of
    the organisation's question, a signed agreement's milestone, a Brief's closing day, an event's start."""

    STAGE = "stage"
    ANSWER = "answer"
    MILESTONE = "milestone"
    BRIEF = "brief"
    EVENT = "event"


class DeadlineOut(BaseModel):
    """One deadline the viewer carries. Titles, dates and names only (D-70): never a note, a message, a Brief's
    statement or a proposal's text."""

    key: str = Field(description="'{kind}:{id}': unique in the list, stable while the item lasts")
    kind: DeadlineKind
    title: str = Field(
        description="What falls due: the stage's label and the proposal's title (stage), 'Information requested' and"
        " the title (answer), 'Milestone n' and the title (milestone), the Brief's title (brief), the event's title"
        " (event)"
    )
    context: str = Field(
        description="The other party's name for an engagement's deadline (the developer's handle for an organisation"
        " until they are named); the organisation that posted a Brief or an event (the product's name for the"
        " platform's events)"
    )
    href: str = Field(description="The web app's page of the item, in the viewer's portal")
    due_at: datetime = Field(
        description="The instant it falls due, in UTC: the end of the Nairobi day of a stage, answer, milestone or"
        " Brief deadline; an event's start"
    )
    due_on: date = Field(description="The Africa/Nairobi date of due_at")
    business_days_left: int = Field(description="Kenyan business days from today (Nairobi) to due_on; negative past it")
    overdue: bool = Field(description="due_at has passed (never for an event: an event is not missed)")
    mine: bool = Field(
        description="The viewer's side acts: whose turn it is on an engagement's step; always true for a Brief or an"
        " event (the viewer's own entry)"
    )
    engagement_id: UUID | None = Field(description="The engagement of a stage, answer or milestone deadline")


class DeadlineList(BaseModel):
    """The viewer's deadlines sorted by ``due_at``; ``now`` is the platform clock they were read at."""

    items: list[DeadlineOut]
    now: datetime


class CalendarFeedOut(BaseModel):
    """A new private calendar feed (D-70): the URL is shown once; only its token's SHA-256 is kept."""

    url: str = Field(description="The absolute feed URL to subscribe to; treat it like a password")


class CalendarFeedStatus(BaseModel):
    """Whether the caller has a live feed (the URL itself cannot be shown again: create a new one to see it)."""

    active: bool
    created_at: datetime | None
    last_fetched_at: datetime | None = Field(description="The last time a calendar app read the live feed")


# -------------------------------------------------------------------------------------------- pipeline (REQ-ENG-14)


class PipelineItem(EngagementSummary):
    """An engagement on the organisation's board: its summary and how long it has been where it is."""

    stage_entered_at: datetime = Field(
        description="When the engagement entered the stage of its column from the main path: a side state"
        " (INFO_REQUESTED, ON_HOLD) does not restart it"
    )
    last_event_at: datetime = Field(description="The engagement's latest tracker event (its hash chain)")
    days_in_stage: int = Field(ge=0, description="Calendar days (Nairobi) since stage_entered_at")
    stalled: bool = Field(
        description="Active, not on hold, and no tracker event for stalled_after_bd Kenyan business days or more"
    )
    team: TeamFacts | None = Field(
        default=None,
        description="The organisation's triage facts (REQ-ENG-15): the assignee and the recommendations' tally",
    )


class PipelineColumn(BaseModel):
    group: StageGroup
    count: int = Field(ge=0)
    median_days_in_stage: float | None = Field(
        description="The median days_in_stage of the column's open engagements (CLOSED ones left out); null with none"
    )
    items: list[PipelineItem] = Field(description="Longest in the stage first")


class FunnelEntered(BaseModel):
    """Engagements whose first entry into each stage group fell inside the window."""

    review: int = Field(ge=0)
    contact_nda: int = Field(ge=0)
    agreement: int = Field(ge=0)
    implementation: int = Field(ge=0)
    close: int = Field(ge=0)


class FunnelOut(BaseModel):
    window_days: int
    entered: FunnelEntered
    closed: int = Field(ge=0, description="Engagements that reached CLOSED inside the window")
    ended: int = Field(ge=0, description="Engagements that ended DECLINED, WITHDRAWN, EXPIRED or TERMINATED inside it")


class PipelineOut(BaseModel):
    """The organisation's engagements by stage group (Review, Contact and NDA, Agreement, Implementation, Close; an
    engagement in a side state under the stage it left; ended ones in none, and Close only those closed inside the
    funnel's window) and the funnel of the last ``window_days`` days."""

    columns: list[PipelineColumn]
    funnel: FunnelOut
    stalled_after_bd: int
    now: datetime
