"""AC-TRACK-2, the state machine's half (REQ-ENG-01): random sequences of (actor, command) applied through ``decide``
to a model of an engagement never reach a state off the main path or its two exits, never take a step the
database's backstop would refuse, and never leave a dual-endorsement stage or a signing stage without both parties.
(The chain's half, "always a verifiable chain", runs against the database in the integration suite.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path

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
REVISION_0003 = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260929_0003_schema_v3.py"


def _predecessors() -> dict[S, set[S]]:
    source = REVISION_0003.read_text(encoding="utf-8")
    body = source[source.index("CREATE FUNCTION engagement_main_path_predecessors") :]
    body = body[: body.index("$$;")]
    return {
        S(state): {S(s) for s in before.split(",") if s}
        for state, before in re.findall(r"WHEN '([A-Z_]+)' THEN '\{([A-Z_,]*)\}'", body)
    }


PREDECESSORS = _predecessors()


@dataclass
class Model:
    """What the service would load as facts, kept up to date by each accepted command's effect."""

    state: S
    facts: sm.Facts
    ip_terms: IpTerms = IpTerms.NON_EXCLUSIVE_LICENCE
    history: list[tuple[S, S]] = field(default_factory=list)

    def enter(self, state: S, **facts: object) -> None:
        if state is not self.state:  # a same-state event (a new terms version) is no transition
            self.history.append((self.state, state))
        self.state = state
        changes: dict[str, object] = {"endorsed": frozenset(), "signed": frozenset(), **facts}
        self.facts = replace(self.facts, **changes)  # type: ignore[arg-type]


def apply(model: Model, command: sm.Command, decision: sm.Decision, milestone: int, terms: IpTerms) -> None:
    f = model.facts
    party = decision.party
    if command is sm.Command.PROPOSE_TERMS:
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
    elif command is sm.Command.APPROVE:
        model.enter(S.INTEREST_CONFIRMED, contact_named=True)
    else:
        model.enter(decision.to_state)


EXITS = frozenset({sm.Command.WITHDRAW, sm.Command.DECLINE, sm.Command.DECLINE_INTEREST})
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
    apply(model, command, decision, milestone, terms)
    assert model.state in set(sm.MAIN_PATH) | {S.DECLINED, S.WITHDRAWN}


def check_history(model: Model) -> None:
    for before, after in model.history:
        if after in PREDECESSORS:
            assert before in PREDECESSORS[after], (before, after)
        else:
            assert after in {S.DECLINED, S.WITHDRAWN}


@settings(max_examples=400, deadline=None)
@given(start=st.sampled_from([S.SUBMITTED, S.ORG_INTEREST]), sequence=steps, d2=st.booleans())
def test_random_sequences_never_leave_the_legal_paths(
    start: S, sequence: list[tuple[int, int, sm.Command, int, int, IpTerms]], d2: bool
) -> None:
    model = Model(start, sm.Facts(contact_named=start is S.ORG_INTEREST, developer_d2=d2))
    for actor_index, choice, random_command, mode, milestone, terms in sequence:
        actor, command = ACTORS[actor_index], random_command
        if mode != 0:  # a legal step by anyone who has one (exits only now and then)
            legal = [
                (a, c) for a in ACTORS for c in sm.available(a, model.state, model.facts) if mode == 1 or c not in EXITS
            ]
            if not legal:
                continue
            actor, command = legal[choice % len(legal)]
        step_once(model, actor, command, milestone, terms, d2)
    event(f"ended in {model.state.value}")  # --hypothesis-show-statistics: how deep the sequences went
    check_history(model)


def test_following_the_pending_actions_reaches_closed() -> None:
    """The model and the table agree: taking each pending action in turn walks SUBMITTED to CLOSED."""
    model = Model(S.SUBMITTED, sm.Facts(developer_d2=True))
    for _ in range(60):
        if model.state is S.CLOSED:
            break
        pending = sm.pending(model.state, model.facts)[0]
        actor = next(a for a in ACTORS if pending.command in sm.available(a, model.state, model.facts))
        step_once(model, actor, pending.command, 0, IpTerms.NON_EXCLUSIVE_LICENCE, d2=True)
    assert model.state is S.CLOSED
    check_history(model)
