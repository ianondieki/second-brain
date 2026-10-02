"""The engagement state machine: the only transition table of the tracker (REQ-ENG-01; docs/spec/06 6.9).

Pure code: no database, no clock, no I/O. The service (``bridge.engagements.commands``) loads the facts, asks
``decide`` whether a command may run, applies its effects and appends the event; the API guards, the "whose turn"
banner, the caller's next actions, the notifications (``Transition.notice``) and the deadlines are all read from the
table below. The database (revision 0003) is the backstop: it refuses a main-path state entered from anything but its
legal predecessors (``engagement_main_path_predecessors``) and the evidence gates of AC-TRACK-10 and AC-TRACK-7, so
every transition here stays inside that set (``tests/unit/engagements/test_state_machine.py`` checks it).

Prototype scope (``PLAN.md`` §8 P5): the main path ``SUBMITTED`` -> ... -> ``CLOSED``, ``DECLINED`` (organisation
reason codes, and ``BY_DEVELOPER`` from stage 0), ``WITHDRAWN`` (the developer, before the agreement is signed) and
stage 0 ``ORG_INTEREST`` -> ``INTEREST_CONFIRMED`` | ``DECLINED``. P19 (REQ-ENG-10 part) adds the side states
``INFO_REQUESTED`` (the organisation asks from stages 1-2, the developer answers) and ``ON_HOLD`` before the agreement
(either party, with a reason and a resume date), each left for the state it was entered from with the deadline moved
by the business days paused, and ``EXPIRED`` (``EXPIRY``: the system's, written by the expiry job, not a row of the
table). ``DISPUTED``, ``TERMINATED``, ``PROCUREMENT_ROUTE`` and ``ON_HOLD`` after the agreement come later.

Refusals, in this order: the actor's party or role may not run the command (403 ``Forbidden``); the deals flag is off
for a deal-stage command (403, AC-SEC-7); the engagement is not in a state the command starts from (409
``Conflict``: every transition not in the table); a precondition of the command is not met (409, or 403 when it is
about who acts). Input that can never be right (an unknown decline reason, a contact-by date out of range) is 422
``Invalid``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Final

from bridge.engagements.calendar import NAIROBI, add_business_days, business_days_between, local_date
from bridge.engagements.policy import TrackerPolicy
from bridge.models.enums import (
    AgreementStatus,
    EngagementActorRole,
    EngagementEndReason,
    EngagementParty,
    EngagementState,
    IpTerms,
    MilestoneState,
)

S = EngagementState
R = EngagementActorRole
DEV: Final = EngagementParty.DEVELOPER
ORG: Final = EngagementParty.ORG
BOTH: Final = frozenset({DEV, ORG})


class TrackerError(Exception):
    """A refused command: ``status`` (403, 409 or 422), a stable ``code`` and a plain-English ``message``."""

    status = 409

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Forbidden(TrackerError):
    status = 403


class Conflict(TrackerError):
    status = 409


class Invalid(TrackerError):
    status = 422


class Command(StrEnum):
    ACCEPT_INTEREST = "accept_interest"
    DECLINE_INTEREST = "decline_interest"
    START_REVIEW = "start_review"
    DECLINE = "decline"
    APPROVE = "approve"
    WITHDRAW = "withdraw"
    MARK_CONTACTED = "mark_contacted"
    CONFIRM_CONTACT = "confirm_contact"
    SEND_NDA = "send_nda"
    SIGN_NDA = "sign_nda"
    PROPOSE_TERMS = "propose_terms"
    MARK_FINAL = "mark_final"
    REOPEN_NEGOTIATION = "reopen_negotiation"
    SIGN_AGREEMENT = "sign_agreement"
    START_MILESTONE = "start_milestone"
    SUBMIT_MILESTONE = "submit_milestone"
    ACCEPT_MILESTONE = "accept_milestone"
    REQUEST_CHANGES = "request_changes"
    DELIVER = "deliver"
    ACCEPT_DELIVERY = "accept_delivery"
    SIGN_CERTIFICATE = "sign_certificate"
    RECORD_PAYMENT = "record_payment"
    CONFIRM_PAYMENT = "confirm_payment"
    REQUEST_INFO = "request_info"
    ANSWER_INFO = "answer_info"
    CANCEL_REQUEST = "cancel_request"
    PAUSE = "pause"
    RESUME = "resume"


class Endorse(StrEnum):
    """When a command records its party's endorsement: of the stage it starts from (``BEFORE`` the event) or of the
    stage it enters (``AFTER``)."""

    BEFORE = "before"
    AFTER = "after"


# Organisation role sets (who may act for the organisation; the database's policies agree, revision 0003).
DECIDERS: Final = frozenset({R.OWNER, R.ADMIN, R.SIGNATORY, R.REVIEWER})
EDITORS: Final = frozenset({R.OWNER, R.ADMIN, R.SIGNATORY})  # agreements and milestones are planned by these
SIGNATORY: Final = frozenset({R.SIGNATORY})
PAYERS: Final = frozenset({R.OWNER, R.ADMIN, R.SIGNATORY, R.FINANCE})
DEVELOPER: Final = frozenset({R.DEVELOPER})
# The role an organisation member acts in when they hold several the command allows.
ROLE_PREFERENCE: Final = (R.SIGNATORY, R.OWNER, R.ADMIN, R.REVIEWER, R.FINANCE)

TERMINAL: Final = frozenset({S.DECLINED, S.WITHDRAWN, S.EXPIRED, S.TERMINATED, S.CLOSED})
BEFORE_AGREEMENT: Final = frozenset(
    {
        S.SUBMITTED,
        S.UNDER_REVIEW,
        S.INTEREST_CONFIRMED,
        S.CONTACT_MADE,
        S.NDA_PENDING,
        S.NDA_SIGNED,
        S.NEGOTIATION,
        S.AGREEMENT_SIGNING,
    }
)
ORG_DECLINE_REASONS: Final = frozenset(
    {
        EngagementEndReason.NOT_PRIORITY,
        EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY,
        EngagementEndReason.BUDGET,
        EngagementEndReason.NOT_RELEVANT,
        EngagementEndReason.NEEDS_MATURITY,
        EngagementEndReason.OTHER,
    }
)
# Side states an engagement leaves only for the state it entered them from (revision 0003's chain trigger), and the
# ones built so far (REQ-ENG-10 part), in which the stage clock is paused.
RETURNING: Final = frozenset({S.ON_HOLD, S.DISPUTED, S.INFO_REQUESTED})
PAUSED: Final = frozenset({S.INFO_REQUESTED, S.ON_HOLD})
# docs/spec/06 6.9: either party pauses before the agreement, except while the proposal is only submitted (the
# organisation has not looked at it yet); after the agreement a hold needs the other party's acknowledgement (later).
PAUSABLE: Final = BEFORE_AGREEMENT - {S.SUBMITTED}
# The stages an engagement expires from when nobody acts (docs/spec/06 6.9 Due rule; policy.yaml expire_bd), with
# the reason and the notification-matrix row both parties get. The expiry job writes these events as the system.
EXPIRY: Final[Mapping[EngagementState, EngagementEndReason]] = {
    S.ORG_INTEREST: EngagementEndReason.NO_DEV_RESPONSE,
    S.SUBMITTED: EngagementEndReason.NO_REVIEW,
    S.UNDER_REVIEW: EngagementEndReason.NO_DECISION,
    S.INTEREST_CONFIRMED: EngagementEndReason.CONTACT_NOT_MADE,
}
EXPIRY_NOTICE: Final[Mapping[EngagementState, str]] = {
    S.ORG_INTEREST: "N17",
    S.SUBMITTED: "N01",
    S.UNDER_REVIEW: "N03",
    S.INTEREST_CONFIRMED: "N05",
    S.INFO_REQUESTED: "N03",  # a question left unanswered past its answer-by date (policy.yaml info_requested)
}
EXPIRE: Final = "expire"  # the command code of the system's expiry event (no party runs it: not a row)
RESUME_NOTICE: Final = "N20"  # the system's resume of a hold at its date tells both parties
# The longest text a note carries (engagement_notes' body CHECK, revision 0006), and a reason's.
QUESTION_MAX_CHARS: Final = 2000
REASON_MAX_CHARS: Final = 500
# IP terms the internal simple e-signature refuses (docs/spec/06 6.9 Instruments; AC-TRACK-10).
OUTSIDE_SIGNATURE_TERMS: Final = frozenset({IpTerms.ASSIGNMENT, IpTerms.EXCLUSIVE_LICENCE})
# The main path in order (the stepper, and the reveal of contact details from INTEREST_CONFIRMED on).
MAIN_PATH: Final = (
    S.ORG_INTEREST,
    S.SUBMITTED,
    S.UNDER_REVIEW,
    S.INTEREST_CONFIRMED,
    S.CONTACT_MADE,
    S.NDA_PENDING,
    S.NDA_SIGNED,
    S.NEGOTIATION,
    S.AGREEMENT_SIGNING,
    S.IN_IMPLEMENTATION,
    S.DELIVERED,
    S.SIGN_OFF,
    S.PAYMENT_FINAL,
    S.CLOSED,
)
CONTACT_REVEALED: Final = frozenset(MAIN_PATH[MAIN_PATH.index(S.INTEREST_CONFIRMED) :])
# Until first contact is made only the named contact may learn the developer's details (AC-TRACK-9), so the text the
# side states carry (read by every member) may hold no contact details in these stages (THREAT_MODEL I).
BEFORE_CONTACT: Final = frozenset({*MAIN_PATH[: MAIN_PATH.index(S.CONTACT_MADE)], S.PROCUREMENT_ROUTE})
# Stage labels (docs/spec/06 6.9 "Label"). [[COPY-REVIEW]]
STAGE_LABELS: Final[Mapping[EngagementState, str]] = {
    S.ORG_INTEREST: "Organisation interested",
    S.SUBMITTED: "Proposal submitted",
    S.UNDER_REVIEW: "Under review",
    S.INTEREST_CONFIRMED: "Approved to proceed (non-binding)",
    S.CONTACT_MADE: "First contact",
    S.NDA_PENDING: "Mutual NDA: awaiting both signatures",
    S.NDA_SIGNED: "Mutual NDA signed",
    S.NEGOTIATION: "Terms and agreement drafting",
    S.AGREEMENT_SIGNING: "Agreement signing",
    S.IN_IMPLEMENTATION: "Agreement signed: implementation",
    S.DELIVERED: "Final delivery submitted",
    S.SIGN_OFF: "Acceptance",
    S.PAYMENT_FINAL: "Final payment",
    S.CLOSED: "Project closed",
    S.DECLINED: "Declined",
    S.WITHDRAWN: "Withdrawn",
    S.EXPIRED: "Expired",
    S.ON_HOLD: "On hold",
    S.INFO_REQUESTED: "Information requested",
}
# The 5-group stepper (docs/spec/06 6.9 Rendering).
STAGE_GROUPS: Final[Mapping[EngagementState, str]] = {
    S.ORG_INTEREST: "review",
    S.SUBMITTED: "review",
    S.UNDER_REVIEW: "review",
    S.INTEREST_CONFIRMED: "contact_nda",
    S.CONTACT_MADE: "contact_nda",
    S.NDA_PENDING: "contact_nda",
    S.NDA_SIGNED: "contact_nda",
    S.NEGOTIATION: "agreement",
    S.AGREEMENT_SIGNING: "agreement",
    S.IN_IMPLEMENTATION: "implementation",
    S.DELIVERED: "implementation",
    S.SIGN_OFF: "close",
    S.PAYMENT_FINAL: "close",
    S.CLOSED: "close",
}


@dataclass(frozen=True, slots=True)
class Transition:
    """One row of the table. ``target`` None: the engagement stays where it is (a same-state event, such as one
    party's endorsement or signature), unless the command completes a dual step, when it enters ``completes``."""

    command: Command
    actors: Mapping[EngagementParty, frozenset[EngagementActorRole]]
    sources: frozenset[EngagementState]
    target: EngagementState | None = None
    completes: EngagementState | None = None
    end_reason: EngagementEndReason | None = None
    step_up: bool = False  # ADR-002: signing, endorsements and payment confirmations need a fresh second factor
    deals: bool = False  # AC-SEC-7: refused while FEATURE_DEALS_ENABLED is false
    endorse: Endorse | None = None
    renews_deadline: bool = False  # a same-state event that sets a new stage deadline (a new terms version)
    notice: str | None = None  # the notification-matrix row the other party gets (REQUIREMENTS.md §5)
    resumes: bool = False  # leaves a side state for the state it was entered from (``Facts.paused_from``)


def _t(
    command: Command,
    actors: Mapping[EngagementParty, frozenset[EngagementActorRole]],
    sources: Iterable[EngagementState],
    *,
    target: EngagementState | None = None,
    completes: EngagementState | None = None,
    end_reason: EngagementEndReason | None = None,
    step_up: bool = False,
    deals: bool = False,
    endorse: Endorse | None = None,
    renews_deadline: bool = False,
    notice: str | None = None,
    resumes: bool = False,
) -> Transition:
    return Transition(
        command,
        actors,
        frozenset(sources),
        target=target,
        completes=completes,
        end_reason=end_reason,
        step_up=step_up,
        deals=deals,
        endorse=endorse,
        renews_deadline=renews_deadline,
        notice=notice,
        resumes=resumes,
    )


_DEV = {DEV: DEVELOPER}
TABLE: Final[Mapping[Command, Transition]] = {
    t.command: t
    for t in (
        # Stage 0 (M2's scout creates ORG_INTEREST): the developer accepts (their endorsement; EM2) or declines.
        _t(
            Command.ACCEPT_INTEREST,
            _DEV,
            {S.ORG_INTEREST},
            target=S.INTEREST_CONFIRMED,
            step_up=True,
            endorse=Endorse.BEFORE,
            notice="N17",
        ),
        _t(
            Command.DECLINE_INTEREST,
            _DEV,
            {S.ORG_INTEREST},
            target=S.DECLINED,
            end_reason=EngagementEndReason.BY_DEVELOPER,
            notice="N17",
        ),
        # Stages 1-2.
        _t(Command.START_REVIEW, {ORG: DECIDERS}, {S.SUBMITTED}, target=S.UNDER_REVIEW, notice="N03"),
        _t(Command.DECLINE, {ORG: DECIDERS}, {S.SUBMITTED, S.UNDER_REVIEW}, target=S.DECLINED, notice="N03"),
        _t(Command.APPROVE, {ORG: SIGNATORY}, {S.UNDER_REVIEW}, target=S.INTEREST_CONFIRMED, notice="N04"),
        _t(Command.WITHDRAW, _DEV, BEFORE_AGREEMENT | PAUSED, target=S.WITHDRAWN, notice="WITHDRAWN"),
        # Stages 3-4: the organisation marks first contact (its endorsement of stage 4); the developer confirms.
        _t(
            Command.MARK_CONTACTED,
            {ORG: DECIDERS},
            {S.INTEREST_CONFIRMED},
            target=S.CONTACT_MADE,
            step_up=True,
            endorse=Endorse.AFTER,
            notice="N06",
        ),
        _t(Command.CONFIRM_CONTACT, _DEV, {S.CONTACT_MADE}, step_up=True, endorse=Endorse.BEFORE, notice="N06"),
        # Stages 5-6: the platform mutual NDA, signed by both (the second signature enters NDA_SIGNED).
        _t(
            Command.SEND_NDA,
            {DEV: DEVELOPER, ORG: EDITORS},
            {S.CONTACT_MADE},
            target=S.NDA_PENDING,
            deals=True,
            notice="N07",
        ),
        _t(
            Command.SIGN_NDA,
            {DEV: DEVELOPER, ORG: SIGNATORY},
            {S.NDA_PENDING},
            completes=S.NDA_SIGNED,
            step_up=True,
            deals=True,
            endorse=Endorse.BEFORE,
            notice="N08",
        ),
        # Stages 7-8: terms versions, the counterparty marks the latest one final, either side reopens before signing.
        _t(
            Command.PROPOSE_TERMS,
            {DEV: DEVELOPER, ORG: EDITORS},
            {S.NDA_SIGNED, S.NEGOTIATION},
            target=S.NEGOTIATION,
            deals=True,
            renews_deadline=True,
            notice="N09",
        ),
        _t(
            Command.MARK_FINAL,
            {DEV: DEVELOPER, ORG: EDITORS},
            {S.NEGOTIATION},
            target=S.AGREEMENT_SIGNING,
            deals=True,
            notice="N10",
        ),
        _t(
            Command.REOPEN_NEGOTIATION,
            {DEV: DEVELOPER, ORG: EDITORS},
            {S.AGREEMENT_SIGNING},
            target=S.NEGOTIATION,
            deals=True,
            notice="N09",
        ),
        _t(
            Command.SIGN_AGREEMENT,
            {DEV: DEVELOPER, ORG: SIGNATORY},
            {S.AGREEMENT_SIGNING},
            completes=S.IN_IMPLEMENTATION,
            step_up=True,
            deals=True,
            endorse=Endorse.BEFORE,
            notice="N11",
        ),
        # Stage 9: the milestone sub-tracker (same-state events), then the final delivery.
        _t(Command.START_MILESTONE, _DEV, {S.IN_IMPLEMENTATION}, deals=True),
        _t(
            Command.SUBMIT_MILESTONE,
            _DEV,
            {S.IN_IMPLEMENTATION},
            step_up=True,
            deals=True,
            endorse=Endorse.BEFORE,
            notice="N19",
        ),
        _t(
            Command.ACCEPT_MILESTONE,
            {ORG: DECIDERS},
            {S.IN_IMPLEMENTATION},
            step_up=True,
            deals=True,
            endorse=Endorse.BEFORE,
            notice="N19",
        ),
        _t(Command.REQUEST_CHANGES, {ORG: DECIDERS}, {S.IN_IMPLEMENTATION}, deals=True, notice="N19"),
        _t(Command.DELIVER, _DEV, {S.IN_IMPLEMENTATION}, target=S.DELIVERED, deals=True, notice="N13"),
        # Stages 10-11: the organisation accepts the delivery and signs the acceptance certificate; the developer
        # countersigns (the second signature enters PAYMENT_FINAL).
        _t(Command.ACCEPT_DELIVERY, {ORG: DECIDERS}, {S.DELIVERED}, target=S.SIGN_OFF, deals=True, notice="N14"),
        _t(
            Command.SIGN_CERTIFICATE,
            {DEV: DEVELOPER, ORG: SIGNATORY},
            {S.SIGN_OFF},
            completes=S.PAYMENT_FINAL,
            step_up=True,
            deals=True,
            endorse=Endorse.BEFORE,
            notice="N15",
        ),
        # Stages 12-13: the organisation records the payment, the developer confirms it (never automatically). The
        # platform never holds or moves money.
        _t(
            Command.RECORD_PAYMENT,
            {ORG: PAYERS},
            {S.PAYMENT_FINAL},
            step_up=True,
            deals=True,
            endorse=Endorse.BEFORE,
            notice="N15",
        ),
        _t(
            Command.CONFIRM_PAYMENT,
            _DEV,
            {S.PAYMENT_FINAL},
            target=S.CLOSED,
            step_up=True,
            deals=True,
            endorse=Endorse.BEFORE,
            notice="N16",
        ),
        # Side branches (docs/spec/06 6.9; REQ-ENG-10 part), each with a note (engagement_notes): the organisation
        # asks from stages 1-2 and the stage clock pauses until the developer answers; either party pauses before the
        # agreement with a reason and a resume date, and either resumes early (or the expiry job, at the date). Each
        # returns to the state it left, its deadline moved by the business days paused.
        _t(Command.REQUEST_INFO, {ORG: DECIDERS}, {S.SUBMITTED, S.UNDER_REVIEW}, target=S.INFO_REQUESTED, notice="N03"),
        _t(Command.ANSWER_INFO, _DEV, {S.INFO_REQUESTED}, resumes=True, notice="N03"),
        # The organisation withdraws its own question (no note: the History shows the command).
        _t(Command.CANCEL_REQUEST, {ORG: DECIDERS}, {S.INFO_REQUESTED}, resumes=True, notice="N03"),
        _t(Command.PAUSE, {DEV: DEVELOPER, ORG: DECIDERS}, PAUSABLE, target=S.ON_HOLD, notice="N20"),
        _t(Command.RESUME, {DEV: DEVELOPER, ORG: DECIDERS}, {S.ON_HOLD}, resumes=True, notice="N20"),
    )
}

# The milestone sub-tracker (docs/spec/06 6.9): which milestone states each command moves from, and to.
MILESTONE_STEPS: Final[Mapping[Command, tuple[frozenset[MilestoneState], MilestoneState]]] = {
    Command.START_MILESTONE: (
        frozenset({MilestoneState.PLANNED, MilestoneState.CHANGES_REQUESTED}),
        MilestoneState.IN_PROGRESS,
    ),
    Command.SUBMIT_MILESTONE: (frozenset({MilestoneState.IN_PROGRESS}), MilestoneState.SUBMITTED_FOR_REVIEW),
    Command.ACCEPT_MILESTONE: (frozenset({MilestoneState.SUBMITTED_FOR_REVIEW}), MilestoneState.ACCEPTED),
    Command.REQUEST_CHANGES: (frozenset({MilestoneState.SUBMITTED_FOR_REVIEW}), MilestoneState.CHANGES_REQUESTED),
}
SIGNING_COMMANDS: Final = frozenset({Command.SIGN_NDA, Command.SIGN_AGREEMENT, Command.SIGN_CERTIFICATE})


@dataclass(frozen=True, slots=True)
class Actor:
    """Who asks: the developer (roles ``{developer}``) or an organisation member in the roles they hold."""

    party: EngagementParty
    roles: frozenset[EngagementActorRole]


@dataclass(frozen=True, slots=True)
class Facts:
    """What the guards and the "whose turn" banner need to know about an engagement, loaded by the service.

    ``endorsed``: the parties that endorsed the current stage in its current round (not a milestone); ``signed``:
    the parties that signed the current stage's document (the NDA, the final agreement or the acceptance
    certificate); ``draft_by``/``draft_status``/``ip_terms``: the latest agreement version; ``milestones``: the
    states of the signed agreement's milestones; ``paused_from``: in a side state, the state it was entered from
    (where it returns); ``questions_left`` and ``hold_days_left``: what the policy's caps leave this stage's questions
    and the engagement's holds (None: these facts do not limit them)."""

    endorsed: frozenset[EngagementParty] = frozenset()
    signed: frozenset[EngagementParty] = frozenset()
    contact_named: bool = False
    draft_by: EngagementParty | None = None
    draft_status: AgreementStatus | None = None
    ip_terms: IpTerms | None = None
    milestones: tuple[MilestoneState, ...] = ()
    developer_d2: bool = False
    payment_recorded: bool = False
    deals_enabled: bool = True
    paused_from: EngagementState | None = None
    questions_left: int | None = None
    hold_days_left: int | None = None


@dataclass(frozen=True, slots=True)
class Decision:
    command: Command
    party: EngagementParty
    role: EngagementActorRole
    from_state: EngagementState
    to_state: EngagementState
    end_reason: EngagementEndReason | None
    endorse: Endorse | None
    step_up: bool
    renews_deadline: bool
    notice: str | None
    resumes: bool = False

    @property
    def changes_state(self) -> bool:
        return self.to_state is not self.from_state


@dataclass(frozen=True, slots=True)
class Pending:
    """An action that moves the engagement on, and the party whose turn it is."""

    command: Command
    party: EngagementParty


def other(party: EngagementParty) -> EngagementParty:
    return ORG if party is DEV else DEV


def acting_role(transition: Transition, actor: Actor) -> EngagementActorRole:
    """The role ``actor`` runs ``transition`` in, or ``Forbidden`` when their party or roles may not run it."""
    allowed = transition.actors.get(actor.party)
    if allowed is None:
        side = "the developer" if actor.party is DEV else "the organisation"
        raise Forbidden("not_your_action", f"This step is not for {side} to take.")
    for role in (R.DEVELOPER, *ROLE_PREFERENCE):
        if role in allowed and role in actor.roles:
            return role
    names = ", ".join(sorted(role.value for role in allowed))
    raise Forbidden("role_required", f"This step needs one of these roles in the organisation: {names}.")


def authorize(command: Command, actor: Actor, *, deals_enabled: bool) -> tuple[Transition, EngagementActorRole]:
    """The 403 checks alone (who may run the command at all), before any state is read."""
    transition = TABLE[command]
    role = acting_role(transition, actor)
    if transition.deals and not deals_enabled:
        raise Forbidden("deals_disabled", "Deal steps (NDA, agreement, signatures, payments) are not enabled yet.")
    return transition, role


def check_source(command: Command, state: EngagementState) -> None:
    """409 ``illegal_transition`` unless ``command`` starts from ``state`` (every transition not in the table)."""
    if state not in TABLE[command].sources:
        raise Conflict(
            "illegal_transition", f"'{command.value}' is not possible while the engagement is {state.value}."
        )


def decide(
    command: Command,
    actor: Actor,
    state: EngagementState,
    facts: Facts,
    *,
    milestone: MilestoneState | None = None,
    reason: EngagementEndReason | None = None,
) -> Decision:
    """Whether ``actor`` may run ``command`` on an engagement in ``state``; raises ``Forbidden``, ``Conflict`` or
    ``Invalid`` otherwise. ``milestone`` is the state of the milestone a sub-tracker command names; ``reason`` the
    decline reason code."""
    transition, role = authorize(command, actor, deals_enabled=facts.deals_enabled)
    check_source(command, state)
    if command is Command.WITHDRAW and state in PAUSED and facts.paused_from not in BEFORE_AGREEMENT:
        raise Conflict("illegal_transition", "Withdrawing is possible only before the agreement is signed.")
    _guard(command, actor.party, facts, milestone)
    to_state = transition.target or state
    if transition.completes is not None and facts.signed | {actor.party} == BOTH:
        to_state = transition.completes
    if transition.resumes:
        if facts.paused_from is None:  # loaded facts always name it; never guess a state to return to
            raise Conflict("no_return_state", "The state this engagement returns to is not known. Reload and retry.")
        to_state = facts.paused_from
    end_reason = transition.end_reason
    if command is Command.DECLINE:
        if reason not in ORG_DECLINE_REASONS:
            raise Invalid("invalid_reason", "Choose one of the organisation's decline reasons.")
        end_reason = reason
    return Decision(
        command=command,
        party=actor.party,
        role=role,
        from_state=state,
        to_state=to_state,
        end_reason=end_reason,
        endorse=transition.endorse,
        step_up=transition.step_up,
        renews_deadline=transition.renews_deadline,
        notice=transition.notice,
        resumes=transition.resumes,
    )


def _guard(command: Command, party: EngagementParty, facts: Facts, milestone: MilestoneState | None) -> None:
    """The command's preconditions beyond its source states."""
    if command is Command.ACCEPT_INTEREST and not facts.contact_named:
        raise Conflict("contact_not_named", "The organisation has not named its contact person yet.")
    if command is Command.CONFIRM_CONTACT:
        if ORG not in facts.endorsed:
            raise Conflict("awaiting_contact", "The organisation has not marked first contact yet.")
        if DEV in facts.endorsed:
            raise Conflict("already_confirmed", "You already confirmed first contact.")
    if command is Command.SEND_NDA and facts.endorsed != BOTH:
        raise Conflict("awaiting_confirmation", "First contact needs both parties' confirmation before the NDA.")
    if command is Command.SIGN_AGREEMENT and party is DEV and not facts.developer_d2:
        raise Forbidden("d2_required", "Signing an agreement needs identity verification (D2).")
    if command in SIGNING_COMMANDS and party in facts.signed:
        raise Conflict("already_signed", "You already signed this document.")
    if command is Command.SIGN_AGREEMENT:
        if facts.draft_status is not AgreementStatus.FINAL:
            raise Conflict("no_final_agreement", "There is no final agreement version to sign.")
        if facts.ip_terms in OUTSIDE_SIGNATURE_TERMS:
            raise Conflict(
                "sign_outside_platform",
                "An assignment or exclusive licence cannot be signed with the platform's simple e-signature. Sign it"
                " outside the platform with an advanced e-signature or on paper, or reopen the terms.",
            )
    if command is Command.SIGN_CERTIFICATE and party is DEV and ORG not in facts.signed:
        raise Conflict("awaiting_enterprise_signature", "The organisation signs the acceptance certificate first.")
    if command is Command.MARK_FINAL:
        if facts.draft_status is not AgreementStatus.DRAFT:
            raise Conflict("no_draft", "There is no draft version to mark final.")
        if facts.draft_by is party:
            raise Forbidden("counterparty_marks_final", "The other party marks your latest version final.")
    if command in MILESTONE_STEPS:
        sources, _ = MILESTONE_STEPS[command]
        if milestone not in sources:
            raise Conflict("milestone_step", "That milestone cannot take this step now.")
    if command is Command.DELIVER and (
        not facts.milestones or any(m is not MilestoneState.ACCEPTED for m in facts.milestones)
    ):
        raise Conflict("milestones_open", "Every milestone must be accepted before the final delivery.")
    if command is Command.RECORD_PAYMENT and facts.payment_recorded:
        raise Conflict("payment_recorded", "The final payment is already recorded.")
    if command is Command.CONFIRM_PAYMENT and not facts.payment_recorded:
        raise Conflict("no_payment_recorded", "The organisation has not recorded the final payment yet.")
    if command is Command.REQUEST_INFO and facts.questions_left is not None and facts.questions_left <= 0:
        raise Conflict(
            "info_request_limit", "Your organisation asked all the questions this stage allows: decide, or decline."
        )
    if command is Command.PAUSE and facts.hold_days_left is not None and facts.hold_days_left <= 0:
        raise Conflict("hold_limit", "This engagement has used all the days on hold it may have.")


def pending(state: EngagementState, facts: Facts) -> tuple[Pending, ...]:
    """The actions that move the engagement on from ``state``, with the party whose turn each is (withdrawing and
    declining are always there for their party and are not a turn)."""
    found: list[Pending] = []
    if state is S.ORG_INTEREST:
        found = [Pending(Command.ACCEPT_INTEREST, DEV)]
    elif state is S.SUBMITTED:
        found = [Pending(Command.START_REVIEW, ORG)]
    elif state is S.UNDER_REVIEW:
        found = [Pending(Command.APPROVE, ORG)]
    elif state is S.INTEREST_CONFIRMED:
        found = [Pending(Command.MARK_CONTACTED, ORG)]
    elif state is S.CONTACT_MADE:
        if DEV not in facts.endorsed:
            found = [Pending(Command.CONFIRM_CONTACT, DEV)]
        else:
            found = [Pending(Command.SEND_NDA, DEV), Pending(Command.SEND_NDA, ORG)]
    elif state in (S.NDA_PENDING, S.AGREEMENT_SIGNING):
        command = Command.SIGN_NDA if state is S.NDA_PENDING else Command.SIGN_AGREEMENT
        found = [Pending(command, p) for p in (DEV, ORG) if p not in facts.signed]
    elif state is S.NDA_SIGNED:
        found = [Pending(Command.PROPOSE_TERMS, DEV), Pending(Command.PROPOSE_TERMS, ORG)]
    elif state is S.NEGOTIATION:
        if facts.draft_status is AgreementStatus.DRAFT and facts.draft_by is not None:
            found = [Pending(Command.MARK_FINAL, other(facts.draft_by))]  # the party who did not draft it
        else:  # no draft yet, or a reopen left the latest version final: a new version, by either party
            found = [Pending(Command.PROPOSE_TERMS, DEV), Pending(Command.PROPOSE_TERMS, ORG)]
    elif state is S.IN_IMPLEMENTATION:
        found = _implementation(facts.milestones)
    elif state is S.DELIVERED:
        found = [Pending(Command.ACCEPT_DELIVERY, ORG)]
    elif state is S.SIGN_OFF:
        found = [Pending(Command.SIGN_CERTIFICATE, ORG if ORG not in facts.signed else DEV)]
    elif state is S.PAYMENT_FINAL:
        found = [
            Pending(Command.CONFIRM_PAYMENT, DEV) if facts.payment_recorded else Pending(Command.RECORD_PAYMENT, ORG)
        ]
    elif state is S.INFO_REQUESTED:
        found = [Pending(Command.ANSWER_INFO, DEV)]  # the organisation waits for the answer (ON_HOLD: for the date)
    return tuple(found)


def _implementation(milestones: tuple[MilestoneState, ...]) -> list[Pending]:
    if milestones and all(m is MilestoneState.ACCEPTED for m in milestones):
        return [Pending(Command.DELIVER, DEV)]
    found: list[Pending] = []
    for command, party in (
        (Command.START_MILESTONE, DEV),
        (Command.SUBMIT_MILESTONE, DEV),
        (Command.ACCEPT_MILESTONE, ORG),
    ):
        sources, _ = MILESTONE_STEPS[command]
        if any(m in sources for m in milestones):
            found.append(Pending(command, party))
    return found


def whose_turn(state: EngagementState, facts: Facts) -> tuple[EngagementParty, ...]:
    parties = {p.party for p in pending(state, facts)}
    return tuple(p for p in (DEV, ORG) if p in parties)


def available(actor: Actor, state: EngagementState, facts: Facts) -> tuple[Command, ...]:
    """The commands ``actor`` may run now (the action buttons): every row ``decide`` accepts, a sub-tracker command
    when at least one milestone can take it, and a decline with any valid reason."""
    found: list[Command] = []
    for command in TABLE:
        milestones: Collection[MilestoneState | None] = facts.milestones if command in MILESTONE_STEPS else (None,)
        for milestone in milestones:
            try:
                decide(command, actor, state, facts, milestone=milestone, reason=EngagementEndReason.NOT_PRIORITY)
            except TrackerError:
                continue
            found.append(command)
            break
    return tuple(found)


# ------------------------------------------------------------------------------------------------ deadlines (BD)


def end_of_day(day: date) -> datetime:
    """A deadline falls at the end of its Nairobi day."""
    return datetime.combine(day, time(23, 59, 59), tzinfo=NAIROBI)


def stage_deadline(
    state: EngagementState,
    now: datetime,
    holidays: Collection[date],
    policy: TrackerPolicy,
    *,
    named: date | None = None,
) -> datetime | None:
    """The deadline of ``state`` entered at ``now``: the end of the ``due_bd``-th Kenyan business day after the entry
    day (policy.yaml), or of a date the organisation named (the contact-by date) while it has not passed. None for a
    stage without one (terminal states, IN_IMPLEMENTATION: its milestones carry their own dates)."""
    due_bd = policy.stage(state).due_bd
    if due_bd is None:
        return None
    today = local_date(now)
    if named is not None and named >= today:
        return end_of_day(named)
    return end_of_day(add_business_days(today, due_bd, holidays))


def resumed_deadline(
    paused_due_on: date | None, paused_on: date, today: date, holidays: Collection[date]
) -> datetime | None:
    """The deadline of a stage resumed from a side state on ``today``: the one it had when it was paused (its Nairobi
    date ``paused_due_on``; None: it had none), moved by the business days from ``paused_on`` (the Nairobi date the
    side state was entered) to ``today`` (docs/spec/06 6.9: "clock paused", "due dates shift by hold duration")."""
    if paused_due_on is None:
        return None
    paused = max(0, business_days_between(paused_on, today, holidays))
    return end_of_day(add_business_days(paused_due_on, paused, holidays) if paused else paused_due_on)


def question_deadline(now: datetime, holidays: Collection[date], policy: TrackerPolicy) -> datetime:
    """The answer-by date of a question asked at ``now`` (policy.yaml ``info_requested.expire_bd``): the stage's clock
    is paused, and past this date the engagement expires (``expiry_reason``)."""
    return end_of_day(add_business_days(local_date(now), policy.info_expire_bd, holidays))


def expiry_reason(state: EngagementState) -> EngagementEndReason | None:
    """Why an engagement the clock ends in ``state`` expired: the stage's reason (``EXPIRY``), or the developer's
    silence for an unanswered question."""
    if state is S.INFO_REQUESTED:
        return EngagementEndReason.NO_DEV_RESPONSE
    return EXPIRY.get(state)


def expires_at(
    state: EngagementState,
    entered_on: date,
    entered_due_on: date | None,
    due_on: date | None,
    holidays: Collection[date],
    policy: TrackerPolicy,
) -> datetime | None:
    """When an engagement left in ``state`` expires (``EXPIRY``; policy.yaml ``expire_bd``): the end of the
    ``expire_bd``-th business day after ``entered_on``, the Nairobi date it entered the stage from the main path,
    plus the business days its deadline has been moved by pauses since (``due_on``, the deadline's date now, against
    ``entered_due_on``, the one it entered with). It expires once that moment has passed. None for any other state."""
    expire_bd = policy.stage(state).expire_bd
    if state not in EXPIRY or expire_bd is None:
        return None
    paused = 0
    if entered_due_on is not None and due_on is not None:
        paused = max(0, business_days_between(entered_due_on, due_on, holidays))
    return end_of_day(add_business_days(entered_on, expire_bd + paused, holidays))


@dataclass(frozen=True, slots=True)
class Due:
    due_on: date
    business_days_left: int  # negative once overdue
    overdue: bool


def due(deadline: datetime, now: datetime, holidays: Collection[date]) -> Due:
    """The countdown to ``deadline`` in business days, from the Nairobi date of ``now``."""
    due_on, today = local_date(deadline), local_date(now)
    return Due(due_on, business_days_between(today, due_on, holidays), now > deadline)


# ------------------------------------------------------------------------------------------------ input checks


def check_contact_by(contact_by: date, now: datetime, holidays: Collection[date], policy: TrackerPolicy) -> None:
    """The contact-by date named with an approval: from today to ``contact_by_max_bd`` business days ahead."""
    today = local_date(now)
    latest = add_business_days(today, policy.contact_by_max_bd, holidays)
    if not today <= contact_by <= latest:
        raise Invalid(
            "invalid_contact_by",
            f"Choose a contact-by date from today to {latest:%d %b %Y} ({policy.contact_by_max_bd} business days).",
        )


def check_resume_at(resume_at: date, now: datetime, policy: TrackerPolicy, *, days_left: int | None = None) -> None:
    """A hold's resume date (docs/spec/06 6.9 ON_HOLD): after today and at most ``on_hold_max_days`` days ahead (422),
    and within the ``days_left`` the engagement's earlier holds left (policy.yaml ``hold_days_total``; 409)."""
    today = local_date(now)
    latest = today + timedelta(days=policy.on_hold_max_days)
    if not today < resume_at <= latest:
        raise Invalid(
            "invalid_resume_at",
            f"Choose a resume date from tomorrow to {latest:%d %b %Y} (at most {policy.on_hold_max_days} days ahead).",
        )
    if days_left is not None and (resume_at - today).days > days_left:
        raise Conflict(
            "hold_limit",
            f"This engagement may be on hold {days_left} more days: choose a resume date by"
            f" {today + timedelta(days=max(days_left, 0)):%d %b %Y}.",
        )


def check_note(text: str | None, limit: int) -> str:
    """The text a side-state command carries (a question, an answer, a reason), trimmed: 1 to ``limit`` characters."""
    value = (text or "").strip()
    if not 0 < len(value) <= limit:
        raise Invalid("invalid_note", f"Write 1 to {limit} characters.")
    return value


@dataclass(frozen=True, slots=True)
class DeclineDetails:
    reason: EngagementEndReason
    other_text: str | None = None
    internal_start_date: date | None = None
    attested: bool = False


def check_decline(details: DeclineDetails, now: datetime, policy: TrackerPolicy) -> None:
    """docs/spec/06 6.9 Codes: ``ALREADY_IN_PROGRESS_INTERNALLY`` needs the internal start date (not in the future)
    and the attestation; ``OTHER`` a written reason of ``other_min_chars``..``other_max_chars`` characters; no other
    reason carries either."""
    if details.reason not in ORG_DECLINE_REASONS:
        raise Invalid("invalid_reason", "Choose one of the organisation's decline reasons.")
    internal = details.reason is EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY
    if internal:
        if details.internal_start_date is None or not details.attested:
            raise Invalid(
                "attestation_required", "Give the date the internal work started and confirm the attestation."
            )
        if details.internal_start_date > local_date(now):
            raise Invalid("attestation_required", "The internal work's start date cannot be in the future.")
    elif details.internal_start_date is not None or details.attested:
        raise Invalid("unexpected_attestation", "Only 'already in progress internally' carries a start date.")
    text = (details.other_text or "").strip()
    if details.reason is EngagementEndReason.OTHER:
        if not policy.decline_other_min_chars <= len(text) <= policy.decline_other_max_chars:
            raise Invalid(
                "reason_text_required",
                f"Explain the reason in {policy.decline_other_min_chars} to {policy.decline_other_max_chars}"
                " characters.",
            )
    elif text:
        raise Invalid("unexpected_reason_text", "Only the reason 'other' carries a written explanation.")


def kes(minor: int) -> str:
    """KES from minor units (cents), as people read it: ``KES 250,000.00``."""
    return f"KES {minor // 100:,}.{minor % 100:02d}"


def check_payment(recorded_minor: int, received_minor: int) -> None:
    """The developer confirms the amount received; a different amount is refused (the dispute flow of AC-TRACK-7
    comes after the prototype), and nothing is recorded."""
    if received_minor != recorded_minor:
        raise Conflict(
            "payment_amount_mismatch",
            f"You received {kes(received_minor)} but the organisation recorded {kes(recorded_minor)}. Nothing was"
            " confirmed: contact the organisation about the difference (disputes come after the prototype).",
        )
