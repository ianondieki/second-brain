"""AC-TRACK-2, the state machine's half (REQ-ENG-01): random sequences of (actor, command) applied through ``decide``
to a model of an engagement never reach a state off the main path, its two exits and the two side states built
(REQ-ENG-10 part: INFO_REQUESTED, ON_HOLD), never take a step the database's backstop would refuse (a side state is
entered from the main path and always left for the state it was entered from), and never leave a dual-endorsement
stage or a signing stage without both parties (a pause keeps what the stage had: endorsements and signatures).
(The chain's half, "always a verifiable chain", runs against the database in the integration suite.) REQ-ENG-06
(AC-TRACK-5): a public entity's engagement reaches stage 3 only through PROCUREMENT_ROUTE (3b), a private
organisation's never enters it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

from bridge.engagements import state_machine as sm
from bridge.models.enums import (
    AgreementStatus,
    EngagementActorRole,
    EngagementEndReason,
    EngagementParty,
    EngagementState,
    IpTerms,
    MilestoneState,
)
from tests.unit.engagements.backstop import database_predecessors

S = EngagementState
R = EngagementActorRole
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
ACTORS = (
    sm.Actor(DEV, sm.DEVELOPER),
    sm.Actor(ORG, frozenset({R.OWNER, R.ADMIN})),
    sm.Actor(ORG, frozenset({R.SIGNATORY})),
    sm.Actor(ORG, frozenset({R.REVIEWER})),
    sm.Actor(ORG, frozenset({R.FINANCE})),
    sm.Actor(ORG, frozenset()),
)


def _predecessors() -> dict[S, set[S]]:
    return {S(state): {S(s) for s in before} for state, before in database_predecessors().items()}


PREDECESSORS = _predecessors()


@dataclass
class Model:
    """What the service would load as facts, kept up to date by each accepted command's effect."""

    state: S
    facts: sm.Facts
    ip_terms: IpTerms = IpTerms.NON_EXCLUSIVE_LICENCE
    history: list[tuple[S, S]] = field(default_factory=list)
    paused: sm.Facts | None = None  # the facts of the stage a side state was entered from (the service reloads them)

    def enter(self, state: S, **facts: object) -> None:
        if state is not self.state:  # a same-state event (a new terms version) is no transition
            self.history.append((self.state, state))
        self.state = state
        changes: dict[str, object] = {"endorsed": frozenset(), "signed": frozenset(), "paused_from": None, **facts}
        self.facts = replace(self.facts, **changes)  # type: ignore[arg-type]


def apply(model: Model, command: sm.Command, decision: sm.Decision, milestone: int, terms: IpTerms) -> None:
    f = model.facts
    party = decision.party
    if decision.to_state in sm.PAUSED:  # a question or a hold: the stage's facts wait for the return
        model.paused = f
        model.enter(decision.to_state, paused_from=model.state)
    elif decision.resumes:
        assert model.paused is not None
        assert decision.to_state is f.paused_from  # back to the state it was entered from (revision 0003)
        model.history.append((model.state, decision.to_state))
        model.state, model.facts, model.paused = decision.to_state, model.paused, None
    elif command is sm.Command.PROPOSE_TERMS:
        model.ip_terms = terms
        model.enter(S.NEGOTIATION, draft_by=party, draft_status=AgreementStatus.DRAFT, ip_terms=terms)
    elif command is sm.Command.MARK_FINAL:
        model.enter(S.AGREEMENT_SIGNING, draft_status=AgreementStatus.FINAL)
    elif command is sm.Command.REOPEN_NEGOTIATION:
        model.enter(S.NEGOTIATION)  # the latest version is the final one: a new draft is needed to mark final
    elif command in (sm.Command.CONFIRM_CONTACT,):
        model.facts = replace(f, endorsed=f.endorsed | {party})
    elif command in sm.SIGNING_COMMANDS:
        signed = f.signed | {party}
        if decision.to_state is decision.from_state:
            model.facts = replace(f, signed=signed)
        elif decision.to_state is S.IN_IMPLEMENTATION:
            model.enter(S.IN_IMPLEMENTATION, milestones=(MilestoneState.PLANNED, MilestoneState.PLANNED))
        else:
            model.enter(decision.to_state)
        if decision.to_state is not decision.from_state:
            assert signed == sm.BOTH, (command, signed)  # never left before both signed
    elif command in sm.MILESTONE_STEPS:
        states = list(f.milestones)
        states[milestone % len(states)] = sm.MILESTONE_STEPS[command][1]
        model.facts = replace(f, milestones=tuple(states))
    elif command is sm.Command.RECORD_PAYMENT:
        model.facts = replace(f, payment_recorded=True)
    elif command is sm.Command.MARK_CONTACTED:
        model.enter(S.CONTACT_MADE, endorsed=frozenset({ORG}))  # the organisation's endorsement comes with it
    elif command is sm.Command.APPROVE:  # stage 3, or a public entity's 3b
        model.enter(decision.to_state, contact_named=True)
    else:
        model.enter(decision.to_state)


EXITS = frozenset({sm.Command.WITHDRAW, sm.Command.DECLINE, sm.Command.DECLINE_INTEREST})
# Side branches are taken now and then (mode 1, like the exits), so the sequences still walk deep into the path.
DETOURS = frozenset({sm.Command.REQUEST_INFO, sm.Command.PAUSE})
steps = st.lists(
    st.tuples(
        st.integers(0, len(ACTORS) - 1),
        st.integers(0, 50),  # which of the actor's available commands (a legal step)
        st.sampled_from(list(sm.Command)),  # or any command at all (mostly refused)
        st.integers(0, 9),  # 0: a random command; 1: an exit is allowed; else a legal step that is not an exit
        st.integers(0, 1),
        st.sampled_from(list(IpTerms)),
    ),
    min_size=30,
    max_size=150,
)


def step_once(model: Model, actor: sm.Actor, command: sm.Command, milestone: int, terms: IpTerms, d2: bool) -> None:
    """One attempt: refused, or accepted with the invariants checked and the effect applied to the model."""
    state_before = model.state
    milestone_state = model.facts.milestones[milestone % 2] if model.facts.milestones else None
    if command in sm.MILESTONE_STEPS and model.facts.milestones:  # a legal step names a milestone it fits
        fitting = [i for i, m in enumerate(model.facts.milestones) if m in sm.MILESTONE_STEPS[command][0]]
        if fitting:
            milestone = fitting[milestone % len(fitting)]
            milestone_state = model.facts.milestones[milestone]
    try:
        decision = sm.decide(
            command, actor, model.state, model.facts, milestone=milestone_state, reason=EngagementEndReason.BUDGET
        )
    except sm.TrackerError:
        return
    assert state_before not in sm.TERMINAL  # nothing follows a terminal state
    if command is sm.Command.SEND_NDA:
        assert model.facts.endorsed == sm.BOTH  # stage 4's dual endorsement before the NDA
    if command is sm.Command.SIGN_AGREEMENT:
        assert model.ip_terms not in sm.OUTSIDE_SIGNATURE_TERMS
        assert actor.party is ORG or d2
    if command is sm.Command.DELIVER:
        assert model.facts.milestones
        assert all(m is MilestoneState.ACCEPTED for m in model.facts.milestones)
    if command is sm.Command.CONFIRM_PAYMENT:
        assert model.facts.payment_recorded
    if state_before in sm.PAUSED:  # a side state only resumes, or the developer withdraws
        assert decision.resumes or decision.to_state is S.WITHDRAWN, (state_before, command)
    apply(model, command, decision, milestone, terms)
    assert model.state in set(sm.MAIN_PATH) | {S.DECLINED, S.WITHDRAWN} | sm.PAUSED
    assert (model.state in sm.PAUSED) is (model.facts.paused_from is not None)


def check_history(model: Model) -> None:
    entered_from: S | None = None
    for before, after in model.history:
        if model.facts.public_entity:  # AC-TRACK-5: stage 3 through 3b only (revision 0015's guard)
            assert not (after is S.INTEREST_CONFIRMED and before in {S.UNDER_REVIEW, S.ORG_INTEREST}), (before, after)
        else:
            assert after is not S.PROCUREMENT_ROUTE, before
        if after in sm.PAUSED:
            assert before in set(sm.MAIN_PATH) - sm.TERMINAL, (before, after)
            entered_from = before
        elif before in sm.PAUSED and after not in sm.TERMINAL:
            assert after is entered_from, (before, after, entered_from)  # the chain's return-to-origin rule
        elif after in PREDECESSORS:
            assert before in PREDECESSORS[after], (before, after)
        else:
            assert after in {S.DECLINED, S.WITHDRAWN}


@settings(max_examples=400, deadline=None)
@given(start=st.sampled_from([S.SUBMITTED, S.ORG_INTEREST]), sequence=steps, d2=st.booleans(), public=st.booleans())
def test_random_sequences_never_leave_the_legal_paths(
    start: S, sequence: list[tuple[int, int, sm.Command, int, int, IpTerms]], d2: bool, public: bool
) -> None:
    model = Model(start, sm.Facts(contact_named=start is S.ORG_INTEREST, developer_d2=d2, public_entity=public))
    for actor_index, choice, random_command, mode, milestone, terms in sequence:
        actor, command = ACTORS[actor_index], random_command
        if mode != 0:  # a legal step by anyone who has one (exits only now and then)
            legal = [
                (a, c)
                for a in ACTORS
                for c in sm.available(a, model.state, model.facts)
                if mode == 1 or c not in EXITS | DETOURS
            ]
            if not legal:
                continue
            actor, command = legal[choice % len(legal)]
        step_once(model, actor, command, milestone, terms, d2)
    event(f"ended in {model.state.value}")  # --hypothesis-show-statistics: how deep the sequences went
    check_history(model)


@pytest.mark.parametrize("public", [False, True])
def test_following_the_pending_actions_reaches_closed(public: bool) -> None:
    """The model and the table agree: taking each pending action in turn walks SUBMITTED to CLOSED (a public entity's
    engagement through its procurement route)."""
    model = Model(S.SUBMITTED, sm.Facts(developer_d2=True, public_entity=public))
    for _ in range(60):
        if model.state is S.CLOSED:
            break
        pending = sm.pending(model.state, model.facts)[0]
        actor = next(a for a in ACTORS if pending.command in sm.available(a, model.state, model.facts))
        step_once(model, actor, pending.command, 0, IpTerms.NON_EXCLUSIVE_LICENCE, d2=True)
    assert model.state is S.CLOSED
    assert ((S.PROCUREMENT_ROUTE, S.INTEREST_CONFIRMED) in model.history) is public
    check_history(model)
