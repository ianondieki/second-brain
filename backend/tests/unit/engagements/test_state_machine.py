"""AC-TRACK-1 (REQ-ENG-01): the transition table of ``bridge.engagements.state_machine``.

Every (command, state, actor) combination is run through ``decide``: an actor whose party or roles may not run the
command gets 403, a state the command does not start from gets 409, and the rest pass. The expected table below is
written from docs/spec/06 6.9 independently of the module, and every transition is checked against the database's
backstop (revision 0003's ``engagement_main_path_predecessors``). Guards, "whose turn", the caller's actions, the
business-day deadlines and the input checks are covered branch by branch (100% branch coverage of the module).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import NAIROBI
from bridge.engagements.policy import load_policy
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
C = sm.Command
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
POLICY = load_policy()
REVISION_0003 = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "20260929_0003_schema_v3.py"

DECIDERS = {R.OWNER, R.ADMIN, R.SIGNATORY, R.REVIEWER}
EDITORS = {R.OWNER, R.ADMIN, R.SIGNATORY}
PAYERS = {R.OWNER, R.ADMIN, R.SIGNATORY, R.FINANCE}
BEFORE_AGREEMENT = {
    S.SUBMITTED,
    S.UNDER_REVIEW,
    S.INTEREST_CONFIRMED,
    S.CONTACT_MADE,
    S.NDA_PENDING,
    S.NDA_SIGNED,
    S.NEGOTIATION,
    S.AGREEMENT_SIGNING,
}
# command: (developer may run it, organisation roles that may, source states, target, completes, deals gate)
EXPECTED: dict[sm.Command, tuple[bool, set[R], set[S], S | None, S | None, bool]] = {
    C.ACCEPT_INTEREST: (True, set(), {S.ORG_INTEREST}, S.INTEREST_CONFIRMED, None, False),
    C.DECLINE_INTEREST: (True, set(), {S.ORG_INTEREST}, S.DECLINED, None, False),
    C.START_REVIEW: (False, DECIDERS, {S.SUBMITTED}, S.UNDER_REVIEW, None, False),
    C.DECLINE: (False, DECIDERS, {S.SUBMITTED, S.UNDER_REVIEW}, S.DECLINED, None, False),
    C.APPROVE: (False, {R.SIGNATORY}, {S.UNDER_REVIEW}, S.INTEREST_CONFIRMED, None, False),
    C.WITHDRAW: (True, set(), BEFORE_AGREEMENT, S.WITHDRAWN, None, False),
    C.MARK_CONTACTED: (False, DECIDERS, {S.INTEREST_CONFIRMED}, S.CONTACT_MADE, None, False),
    C.CONFIRM_CONTACT: (True, set(), {S.CONTACT_MADE}, None, None, False),
    C.SEND_NDA: (True, EDITORS, {S.CONTACT_MADE}, S.NDA_PENDING, None, True),
    C.SIGN_NDA: (True, {R.SIGNATORY}, {S.NDA_PENDING}, None, S.NDA_SIGNED, True),
    C.PROPOSE_TERMS: (True, EDITORS, {S.NDA_SIGNED, S.NEGOTIATION}, S.NEGOTIATION, None, True),
    C.MARK_FINAL: (True, EDITORS, {S.NEGOTIATION}, S.AGREEMENT_SIGNING, None, True),
    C.REOPEN_NEGOTIATION: (True, EDITORS, {S.AGREEMENT_SIGNING}, S.NEGOTIATION, None, True),
    C.SIGN_AGREEMENT: (True, {R.SIGNATORY}, {S.AGREEMENT_SIGNING}, None, S.IN_IMPLEMENTATION, True),
    C.START_MILESTONE: (True, set(), {S.IN_IMPLEMENTATION}, None, None, True),
    C.SUBMIT_MILESTONE: (True, set(), {S.IN_IMPLEMENTATION}, None, None, True),
    C.ACCEPT_MILESTONE: (False, DECIDERS, {S.IN_IMPLEMENTATION}, None, None, True),
    C.REQUEST_CHANGES: (False, DECIDERS, {S.IN_IMPLEMENTATION}, None, None, True),
    C.DELIVER: (True, set(), {S.IN_IMPLEMENTATION}, S.DELIVERED, None, True),
    C.ACCEPT_DELIVERY: (False, DECIDERS, {S.DELIVERED}, S.SIGN_OFF, None, True),
    C.SIGN_CERTIFICATE: (True, {R.SIGNATORY}, {S.SIGN_OFF}, None, S.PAYMENT_FINAL, True),
    C.RECORD_PAYMENT: (False, PAYERS, {S.PAYMENT_FINAL}, None, None, True),
    C.CONFIRM_PAYMENT: (True, set(), {S.PAYMENT_FINAL}, S.CLOSED, None, True),
}
ORG_ROLES = (R.OWNER, R.ADMIN, R.SIGNATORY, R.REVIEWER, R.FINANCE)
ACTORS = (
    sm.Actor(DEV, frozenset({R.DEVELOPER})),
    sm.Actor(ORG, frozenset()),  # a viewer: no role the tracker lets act
    *(sm.Actor(ORG, frozenset({role})) for role in ORG_ROLES),
)
# Facts under which every guard passes for the command's party (so only the table decides).
MILESTONE_FOR = {
    C.START_MILESTONE: MilestoneState.PLANNED,
    C.SUBMIT_MILESTONE: MilestoneState.IN_PROGRESS,
    C.ACCEPT_MILESTONE: MilestoneState.SUBMITTED_FOR_REVIEW,
    C.REQUEST_CHANGES: MilestoneState.SUBMITTED_FOR_REVIEW,
}


def permissive(command: sm.Command, party: EngagementParty) -> sm.Facts:
    endorsed = frozenset({ORG}) if command is C.CONFIRM_CONTACT else sm.BOTH
    return sm.Facts(
        endorsed=endorsed,
        contact_named=True,
        draft_by=sm.other(party),
        draft_status=AgreementStatus.FINAL if command is C.SIGN_AGREEMENT else AgreementStatus.DRAFT,
        ip_terms=IpTerms.NON_EXCLUSIVE_LICENCE,
        signed=frozenset({ORG}) if command is C.SIGN_CERTIFICATE and party is DEV else frozenset(),
        milestones=(MilestoneState.ACCEPTED,),
        developer_d2=True,
        payment_recorded=command is C.CONFIRM_PAYMENT,
    )


def attempt(command: sm.Command, actor: sm.Actor, state: S, facts: sm.Facts) -> sm.Decision:
    """``decide`` with the milestone state and decline reason the command needs to pass its guards."""
    return sm.decide(
        command, actor, state, facts, milestone=MILESTONE_FOR.get(command), reason=EngagementEndReason.BUDGET
    )


def allowed_role(expected: tuple[bool, set[R], set[S], S | None, S | None, bool], actor: sm.Actor) -> bool:
    developer, roles, *_ = expected
    return developer if actor.party is DEV else bool(roles & actor.roles)


def test_the_table_is_the_spec_table() -> None:
    assert set(sm.TABLE) == set(EXPECTED) == set(sm.Command)
    for command, (developer, roles, sources, target, completes, deals) in EXPECTED.items():
        row = sm.TABLE[command]
        assert (DEV in row.actors) is developer, command
        assert set(row.actors.get(ORG, set())) == roles, command
        assert row.sources == sources, command
        assert (row.target, row.completes, row.deals) == (target, completes, deals), command
        if row.target is None and row.completes is None:
            assert not row.sources & sm.TERMINAL  # a same-state event never follows a terminal state


@pytest.mark.parametrize("command", list(sm.Command))
def test_every_actor_and_state_gets_403_409_or_passes(command: sm.Command) -> None:
    expected = EXPECTED[command]
    for actor in ACTORS:
        facts = permissive(command, actor.party)
        for state in EngagementState:
            if not allowed_role(expected, actor):
                with pytest.raises(sm.Forbidden) as refused:
                    attempt(command, actor, state, facts)
                assert refused.value.status == 403
                assert refused.value.code in {"not_your_action", "role_required"}
            elif state not in expected[2]:
                with pytest.raises(sm.Conflict) as conflict:
                    attempt(command, actor, state, facts)
                assert (conflict.value.status, conflict.value.code) == (409, "illegal_transition")
            else:
                decision = attempt(command, actor, state, facts)
                assert decision.party is actor.party
                assert decision.role in actor.roles
                assert decision.from_state is state


def test_an_organisation_member_acts_in_their_strongest_allowed_role() -> None:
    member = sm.Actor(ORG, frozenset({R.REVIEWER, R.OWNER, R.SIGNATORY, R.FINANCE}))
    facts = permissive(C.START_REVIEW, ORG)
    assert sm.decide(C.START_REVIEW, member, S.SUBMITTED, facts).role is R.SIGNATORY
    payer = sm.Actor(ORG, frozenset({R.REVIEWER, R.FINANCE}))
    assert sm.decide(C.RECORD_PAYMENT, payer, S.PAYMENT_FINAL, permissive(C.RECORD_PAYMENT, ORG)).role is R.FINANCE


def test_deal_steps_are_refused_while_the_deals_flag_is_off() -> None:
    """AC-SEC-7: entering NDA_PENDING or later, any signature and any payment record: 403 while the flag is off."""
    for command, expected in EXPECTED.items():
        actor = ACTORS[0] if expected[0] else sm.Actor(ORG, frozenset(expected[1]))
        facts = permissive(command, actor.party)
        off = sm.Facts(**{**{f: getattr(facts, f) for f in facts.__slots__}, "deals_enabled": False})
        state = next(iter(expected[2]))
        if expected[5]:
            with pytest.raises(sm.Forbidden, match="not enabled"):
                attempt(command, actor, state, off)
        else:
            attempt(command, actor, state, off)
    withdraw = sm.Facts(deals_enabled=False)
    assert sm.decide(C.WITHDRAW, ACTORS[0], S.AGREEMENT_SIGNING, withdraw).to_state is S.WITHDRAWN


def _database_predecessors() -> dict[str, set[str]]:
    """revision 0003's engagement_main_path_predecessors(): WHEN '<state>' THEN '{<states>}'."""
    source = REVISION_0003.read_text(encoding="utf-8")
    body = source[source.index("CREATE FUNCTION engagement_main_path_predecessors") :]
    body = body[: body.index("$$;")]
    found = re.findall(r"WHEN '([A-Z_]+)' THEN '\{([A-Z_,]*)\}'", body)
    assert len(found) == 15
    return {state: set(filter(None, before.split(","))) for state, before in found}


def test_every_transition_stays_inside_the_database_backstop() -> None:
    predecessors = _database_predecessors()
    for row in sm.TABLE.values():
        for target in filter(None, (row.target, row.completes)):
            for source in row.sources:
                if target is source:
                    continue
                if target.value in predecessors:
                    assert source.value in predecessors[target.value], (row.command, source, target)
                else:
                    assert target in {S.DECLINED, S.WITHDRAWN}, (row.command, target)


def test_a_signing_command_completes_only_with_the_second_signature() -> None:
    developer = ACTORS[0]
    signatory = sm.Actor(ORG, frozenset({R.SIGNATORY}))
    nothing = sm.Facts(signed=frozenset())
    assert sm.decide(C.SIGN_NDA, developer, S.NDA_PENDING, nothing).to_state is S.NDA_PENDING
    decision = sm.decide(C.SIGN_NDA, signatory, S.NDA_PENDING, sm.Facts(signed=frozenset({DEV})))
    assert (decision.to_state, decision.changes_state) == (S.NDA_SIGNED, True)
    agreement = sm.Facts(draft_status=AgreementStatus.FINAL, developer_d2=True, signed=frozenset({ORG}))
    assert sm.decide(C.SIGN_AGREEMENT, developer, S.AGREEMENT_SIGNING, agreement).to_state is S.IN_IMPLEMENTATION
    assert not sm.decide(
        C.CONFIRM_CONTACT, developer, S.CONTACT_MADE, sm.Facts(endorsed=frozenset({ORG}))
    ).changes_state


def test_guards_refuse_with_their_codes() -> None:
    developer = ACTORS[0]
    signatory = sm.Actor(ORG, frozenset({R.SIGNATORY}))
    owner = sm.Actor(ORG, frozenset({R.OWNER}))

    def code(
        command: sm.Command, actor: sm.Actor, state: S, facts: sm.Facts, milestone: MilestoneState | None = None
    ) -> tuple[int, str]:
        with pytest.raises(sm.TrackerError) as refused:
            sm.decide(command, actor, state, facts, milestone=milestone)
        return refused.value.status, refused.value.code

    assert code(C.ACCEPT_INTEREST, developer, S.ORG_INTEREST, sm.Facts()) == (409, "contact_not_named")
    assert code(C.CONFIRM_CONTACT, developer, S.CONTACT_MADE, sm.Facts()) == (409, "awaiting_contact")
    assert code(C.CONFIRM_CONTACT, developer, S.CONTACT_MADE, sm.Facts(endorsed=sm.BOTH)) == (409, "already_confirmed")
    only_org = sm.Facts(endorsed=frozenset({ORG}))
    assert code(C.SEND_NDA, owner, S.CONTACT_MADE, only_org) == (409, "awaiting_confirmation")
    assert code(C.SIGN_NDA, developer, S.NDA_PENDING, sm.Facts(signed=frozenset({DEV}))) == (409, "already_signed")
    final = sm.Facts(draft_status=AgreementStatus.FINAL, developer_d2=True)
    assert code(C.SIGN_AGREEMENT, developer, S.AGREEMENT_SIGNING, sm.Facts()) == (403, "d2_required")
    assert code(C.SIGN_AGREEMENT, signatory, S.AGREEMENT_SIGNING, sm.Facts()) == (409, "no_final_agreement")
    for terms in (IpTerms.ASSIGNMENT, IpTerms.EXCLUSIVE_LICENCE):
        outside = sm.Facts(draft_status=AgreementStatus.FINAL, ip_terms=terms)
        assert code(C.SIGN_AGREEMENT, signatory, S.AGREEMENT_SIGNING, outside) == (409, "sign_outside_platform")
    assert sm.decide(C.SIGN_AGREEMENT, developer, S.AGREEMENT_SIGNING, final).to_state is S.AGREEMENT_SIGNING
    first = code(C.SIGN_CERTIFICATE, developer, S.SIGN_OFF, sm.Facts())
    assert first == (409, "awaiting_enterprise_signature")
    assert sm.decide(C.SIGN_CERTIFICATE, signatory, S.SIGN_OFF, sm.Facts()).to_state is S.SIGN_OFF
    assert code(C.MARK_FINAL, owner, S.NEGOTIATION, sm.Facts()) == (409, "no_draft")
    by_org = sm.Facts(draft_status=AgreementStatus.DRAFT, draft_by=ORG)
    assert code(C.MARK_FINAL, owner, S.NEGOTIATION, by_org) == (403, "counterparty_marks_final")
    assert sm.decide(C.MARK_FINAL, developer, S.NEGOTIATION, by_org).to_state is S.AGREEMENT_SIGNING
    reviewer = sm.Actor(ORG, frozenset({R.REVIEWER}))
    for command, ok in MILESTONE_FOR.items():
        actor = developer if command in (C.START_MILESTONE, C.SUBMIT_MILESTONE) else reviewer
        for state in MilestoneState:
            if state in sm.MILESTONE_STEPS[command][0]:
                sm.decide(command, actor, S.IN_IMPLEMENTATION, sm.Facts(), milestone=state)
            else:
                assert code(command, actor, S.IN_IMPLEMENTATION, sm.Facts(), milestone=state) == (409, "milestone_step")
        assert ok in sm.MILESTONE_STEPS[command][0]
        assert code(command, actor, S.IN_IMPLEMENTATION, sm.Facts()) == (409, "milestone_step")  # none named
    assert sm.decide(
        C.START_MILESTONE, developer, S.IN_IMPLEMENTATION, sm.Facts(), milestone=MilestoneState.CHANGES_REQUESTED
    )
    assert code(C.DELIVER, developer, S.IN_IMPLEMENTATION, sm.Facts()) == (409, "milestones_open")
    mixed = sm.Facts(milestones=(MilestoneState.ACCEPTED, MilestoneState.IN_PROGRESS))
    assert code(C.DELIVER, developer, S.IN_IMPLEMENTATION, mixed) == (409, "milestones_open")
    finance = sm.Actor(ORG, frozenset({R.FINANCE}))
    recorded = sm.Facts(payment_recorded=True)
    assert code(C.RECORD_PAYMENT, finance, S.PAYMENT_FINAL, recorded) == (409, "payment_recorded")
    assert code(C.CONFIRM_PAYMENT, developer, S.PAYMENT_FINAL, sm.Facts()) == (409, "no_payment_recorded")


def test_declines_carry_an_organisation_reason_and_stage_0_is_declined_by_the_developer() -> None:
    reviewer = sm.Actor(ORG, frozenset({R.REVIEWER}))
    for reason in EngagementEndReason:
        if reason in sm.ORG_DECLINE_REASONS:
            decision = sm.decide(C.DECLINE, reviewer, S.UNDER_REVIEW, sm.Facts(), reason=reason)
            assert (decision.to_state, decision.end_reason) == (S.DECLINED, reason)
        else:
            with pytest.raises(sm.Invalid, match="decline reasons"):
                sm.decide(C.DECLINE, reviewer, S.SUBMITTED, sm.Facts(), reason=reason)
    with pytest.raises(sm.Invalid):
        sm.decide(C.DECLINE, reviewer, S.SUBMITTED, sm.Facts())
    by_developer = sm.decide(C.DECLINE_INTEREST, ACTORS[0], S.ORG_INTEREST, sm.Facts())
    assert by_developer.end_reason is EngagementEndReason.BY_DEVELOPER


def test_whose_turn_and_the_pending_actions_follow_the_stage() -> None:
    def turn(state: S, facts: sm.Facts | None = None) -> tuple[EngagementParty, ...]:
        return sm.whose_turn(state, facts or sm.Facts())

    assert turn(S.ORG_INTEREST) == (DEV,)
    assert turn(S.SUBMITTED) == turn(S.UNDER_REVIEW) == turn(S.INTEREST_CONFIRMED) == (ORG,)
    assert turn(S.CONTACT_MADE, sm.Facts(endorsed=frozenset({ORG}))) == (DEV,)
    assert turn(S.CONTACT_MADE, sm.Facts(endorsed=sm.BOTH)) == (DEV, ORG)
    assert turn(S.NDA_PENDING) == (DEV, ORG)
    assert turn(S.NDA_PENDING, sm.Facts(signed=frozenset({DEV}))) == (ORG,)
    assert turn(S.AGREEMENT_SIGNING, sm.Facts(signed=frozenset({ORG}))) == (DEV,)
    assert turn(S.NDA_SIGNED) == (DEV, ORG)
    assert turn(S.NEGOTIATION, sm.Facts(draft_by=DEV)) == (ORG,)
    assert turn(S.NEGOTIATION) == (DEV, ORG)
    assert turn(S.IN_IMPLEMENTATION) == ()
    started = sm.Facts(milestones=(MilestoneState.ACCEPTED, MilestoneState.SUBMITTED_FOR_REVIEW))
    assert turn(S.IN_IMPLEMENTATION, started) == (ORG,)
    both = sm.Facts(milestones=(MilestoneState.PLANNED, MilestoneState.SUBMITTED_FOR_REVIEW))
    assert [p.command for p in sm.pending(S.IN_IMPLEMENTATION, both)] == [C.START_MILESTONE, C.ACCEPT_MILESTONE]
    working = sm.Facts(milestones=(MilestoneState.IN_PROGRESS,))
    assert [p.command for p in sm.pending(S.IN_IMPLEMENTATION, working)] == [C.SUBMIT_MILESTONE]
    done = sm.Facts(milestones=(MilestoneState.ACCEPTED,))
    assert [p.command for p in sm.pending(S.IN_IMPLEMENTATION, done)] == [C.DELIVER]
    assert turn(S.DELIVERED) == (ORG,)
    assert turn(S.SIGN_OFF) == (ORG,)
    assert turn(S.SIGN_OFF, sm.Facts(signed=frozenset({ORG}))) == (DEV,)
    assert turn(S.PAYMENT_FINAL) == (ORG,)
    assert turn(S.PAYMENT_FINAL, sm.Facts(payment_recorded=True)) == (DEV,)
    for state in sm.TERMINAL:
        assert turn(state) == ()


def test_the_callers_actions_are_what_decide_accepts() -> None:
    developer = ACTORS[0]
    owner = sm.Actor(ORG, frozenset({R.OWNER, R.ADMIN}))
    viewer = sm.Actor(ORG, frozenset())
    assert sm.available(developer, S.SUBMITTED, sm.Facts()) == (C.WITHDRAW,)
    assert sm.available(owner, S.SUBMITTED, sm.Facts()) == (C.START_REVIEW, C.DECLINE)
    assert sm.available(viewer, S.SUBMITTED, sm.Facts()) == ()
    implementation = sm.Facts(milestones=(MilestoneState.PLANNED, MilestoneState.SUBMITTED_FOR_REVIEW))
    assert sm.available(developer, S.IN_IMPLEMENTATION, implementation) == (C.START_MILESTONE,)
    assert sm.available(owner, S.IN_IMPLEMENTATION, implementation) == (C.ACCEPT_MILESTONE, C.REQUEST_CHANGES)
    assert sm.available(owner, S.CLOSED, sm.Facts()) == ()


def test_contact_details_are_revealed_from_interest_confirmed_on_the_main_path() -> None:
    assert S.INTEREST_CONFIRMED in sm.CONTACT_REVEALED
    assert S.CLOSED in sm.CONTACT_REVEALED
    assert not {S.ORG_INTEREST, S.SUBMITTED, S.UNDER_REVIEW, S.DECLINED, S.WITHDRAWN} & sm.CONTACT_REVEALED
    assert set(sm.STAGE_GROUPS) == set(sm.MAIN_PATH)
    assert set(sm.MAIN_PATH) <= set(sm.STAGE_LABELS)


# ------------------------------------------------------------------------------------------------ deadlines (BD)


def at(day: date, hour: int = 10) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=NAIROBI)


def test_deadlines_count_kenyan_business_days_from_policy() -> None:
    """REQ-BD-01: weekends and gazetted holidays are skipped; the deadline is the end of the due day (EAT)."""
    friday = date(2026, 10, 16)  # Mashujaa Day, 20 Oct 2026, is a Tuesday
    holidays = {date(2026, 10, 20)}
    # SUBMITTED: 10 BD. Mon 19 .. Fri 30 Oct is 9 BD without the holiday, so the 10th is Mon 2 Nov.
    deadline = sm.stage_deadline(S.SUBMITTED, at(friday), holidays, POLICY)
    assert deadline == datetime(2026, 11, 2, 23, 59, 59, tzinfo=NAIROBI)
    # Without the holiday, the 10th business day is Fri 30 Oct.
    assert sm.stage_deadline(S.SUBMITTED, at(friday), set(), POLICY) == datetime(
        2026, 10, 30, 23, 59, 59, tzinfo=NAIROBI
    )
    # Entered on a Saturday: the count starts on Monday.
    saturday = date(2026, 10, 3)
    assert sm.stage_deadline(S.NDA_PENDING, at(saturday), set(), POLICY) == datetime(
        2026, 10, 9, 23, 59, 59, tzinfo=NAIROBI
    )
    # Late on a UTC day that is already the next day in Nairobi.
    utc_evening = datetime(2026, 10, 2, 22, 30, tzinfo=UTC)  # Sat 3 Oct 01:30 EAT
    assert sm.stage_deadline(S.NDA_PENDING, utc_evening, set(), POLICY) == datetime(
        2026, 10, 9, 23, 59, 59, tzinfo=NAIROBI
    )


def test_a_named_date_sets_the_deadline_until_it_has_passed() -> None:
    monday = date(2026, 10, 5)
    named = date(2026, 10, 7)
    assert sm.stage_deadline(S.INTEREST_CONFIRMED, at(monday), set(), POLICY, named=named) == sm.end_of_day(named)
    past = date(2026, 10, 1)
    assert sm.stage_deadline(S.INTEREST_CONFIRMED, at(monday), set(), POLICY, named=past) == sm.end_of_day(
        date(2026, 10, 12)
    )


def test_stages_without_a_due_rule_have_no_deadline() -> None:
    now = at(date(2026, 10, 5))
    for state in (S.IN_IMPLEMENTATION, *sm.TERMINAL):
        assert sm.stage_deadline(state, now, set(), POLICY) is None


def test_the_countdown_is_in_business_days() -> None:
    deadline = sm.end_of_day(date(2026, 10, 9))  # a Friday
    running = sm.due(deadline, at(date(2026, 10, 5)), set())
    assert running == sm.Due(date(2026, 10, 9), 4, False)
    late = sm.due(deadline, at(date(2026, 10, 13)), set())
    assert late == sm.Due(date(2026, 10, 9), -2, True)


def test_the_contact_by_date_is_from_today_to_five_business_days_ahead() -> None:
    thursday = at(date(2026, 10, 1))
    sm.check_contact_by(date(2026, 10, 1), thursday, set(), POLICY)
    sm.check_contact_by(date(2026, 10, 8), thursday, set(), POLICY)  # Thu + 5 BD = Thu 8 Oct
    for wrong in (date(2026, 9, 30), date(2026, 10, 9)):
        with pytest.raises(sm.Invalid) as refused:
            sm.check_contact_by(wrong, thursday, set(), POLICY)
        assert (refused.value.status, refused.value.code) == (422, "invalid_contact_by")


def test_decline_details_follow_the_reason_code() -> None:
    now = at(date(2026, 10, 5))
    ok = [
        sm.DeclineDetails(EngagementEndReason.BUDGET),
        sm.DeclineDetails(EngagementEndReason.OTHER, other_text="  We are restructuring this unit.  "),
        sm.DeclineDetails(
            EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY, internal_start_date=date(2026, 5, 1), attested=True
        ),
    ]
    for details in ok:
        sm.check_decline(details, now, POLICY)
    refused = {
        "invalid_reason": sm.DeclineDetails(EngagementEndReason.BY_DEVELOPER),
        "attestation_required": sm.DeclineDetails(EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY, attested=True),
        "unexpected_attestation": sm.DeclineDetails(EngagementEndReason.BUDGET, attested=True),
        "reason_text_required": sm.DeclineDetails(EngagementEndReason.OTHER, other_text="Too short"),
        "unexpected_reason_text": sm.DeclineDetails(EngagementEndReason.BUDGET, other_text="Not now, thanks."),
    }
    for expected, details in refused.items():
        with pytest.raises(sm.Invalid) as error:
            sm.check_decline(details, now, POLICY)
        assert error.value.code == expected
    unattested = sm.DeclineDetails(
        EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY, internal_start_date=date(2026, 5, 1)
    )
    future = sm.DeclineDetails(
        EngagementEndReason.ALREADY_IN_PROGRESS_INTERNALLY, internal_start_date=date(2026, 10, 6), attested=True
    )
    long_text = sm.DeclineDetails(EngagementEndReason.OTHER, other_text="x" * (POLICY.decline_other_max_chars + 1))
    dated_budget = sm.DeclineDetails(EngagementEndReason.BUDGET, internal_start_date=date(2026, 5, 1))
    for details in (unattested, future, long_text, dated_budget):
        with pytest.raises(sm.Invalid):
            sm.check_decline(details, now, POLICY)


def test_a_payment_is_confirmed_only_at_the_recorded_amount() -> None:
    sm.check_payment(25_000_000, 25_000_000)
    with pytest.raises(sm.Conflict) as refused:
        sm.check_payment(25_000_000, 24_999_999)
    assert refused.value.code == "payment_amount_mismatch"
    assert "KES 249,999.99" in refused.value.message
    assert "KES 250,000.00" in refused.value.message
    assert sm.kes(5) == "KES 0.05"


def test_the_errors_carry_their_status() -> None:
    assert (sm.Forbidden("a", "b").status, sm.Conflict("a", "b").status, sm.Invalid("a", "b").status) == (403, 409, 422)
    assert sm.other(DEV) is ORG
    assert sm.other(ORG) is DEV
