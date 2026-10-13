"""REQ-NOT-05, REQ-NOT-03, REQ-ENG-05 (P28 track B): the nudge job's rules, pure.

Each kind falls due at its moment on Kenyan business days from the stage's main-path entry (a milestone: its latest
submission), paused by holds and requests for information exactly as the expiry job counts (the business days the
stage's deadline moved by are added back); its key makes it fire once per stage entry (a milestone: per submission);
only the latest NDA reminder due is sent. Who hears each one: the admins and the escalation contact for an escalation,
EM6 to the named contact, the admins and the developer, EM5 to each signer who has not signed, the milestone reminder
to the organisation's reviewers of the engagement."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

import pytest

from bridge.engagements import nudges
from bridge.engagements import state_machine as sm
from bridge.engagements.calendar import NAIROBI
from bridge.engagements.policy import load_policy
from bridge.models.enums import EngagementParty, EngagementState, NudgeKind, OrgRole

S = EngagementState
K = NudgeKind
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
POLICY = load_policy()
MONDAY = date(2026, 10, 5)
MASHUJAA = date(2026, 10, 20)  # Mashujaa Day 2026, a Tuesday
MILESTONE = UUID("01900000-0000-7000-8000-0000000000aa")


def at(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=NAIROBI)


def clock(due_on: date | None, *, now_due: date | None = None, seq: int = 4) -> nudges.StageClock:
    """Entered on Monday 5 Oct 2026 by event ``seq`` with deadline ``due_on``; the deadline now ``now_due`` (a hold
    moved it) or the same."""
    deadline = now_due or due_on
    return nudges.StageClock(
        entered_seq=seq,
        entered_on=MONDAY,
        entered_due_on=due_on,
        deadline=sm.end_of_day(deadline) if deadline else None,
    )


def kinds(found: list[nudges.Due]) -> list[tuple[NudgeKind, str]]:
    return [(d.kind, d.key) for d in found]


def due(state: S, now: datetime, stage: nudges.StageClock | None, **extra: object) -> list[nudges.Due]:
    holidays = extra.pop("holidays", frozenset())
    submissions = extra.pop("submissions", ())
    assert not extra
    return nudges.due_nudges(state, now, stage, submissions, holidays, POLICY)  # type: ignore[arg-type]


def test_contact_escalation_falls_due_past_the_third_business_day_and_em6_past_the_contact_by_date() -> None:
    """AT-B-1 and AT-B-2's moments: entered Monday with a Friday contact-by date, the escalation is due once Thursday
    (the 3rd business day) has ended, EM6 once Friday has; EM6 names the date missed and the expiry day (10 BD)."""
    friday = date(2026, 10, 9)
    stage = clock(friday)
    assert due(S.INTEREST_CONFIRMED, at(date(2026, 10, 8), 23, 59), stage) == []
    assert kinds(due(S.INTEREST_CONFIRMED, at(friday, 0, 1), stage)) == [(K.CONTACT_ESCALATION, "e4:bd3")]
    late = due(S.INTEREST_CONFIRMED, at(date(2026, 10, 10)), stage)
    assert kinds(late) == [(K.CONTACT_ESCALATION, "e4:bd3"), (K.CONTACT_OVERDUE, "e4:overdue")]
    escalation, overdue = late
    assert (escalation.days, escalation.on) == (3, friday)
    assert (overdue.on, overdue.expires) == (friday, date(2026, 10, 19))  # Mon + 10 BD
    with_holiday = due(S.INTEREST_CONFIRMED, at(date(2026, 10, 10)), stage, holidays=frozenset({MASHUJAA}))
    assert with_holiday[1].expires == date(2026, 10, 19)  # the holiday falls after the tenth business day


def test_a_hold_delays_each_count_by_the_business_days_paused() -> None:
    """AT-B-1's third clause: a hold that moved the contact-by deadline by two business days (Fri 9 -> Tue 13) moves
    the escalation by two as well (end of Thu 8 -> end of Mon 12), as the expiry job counts."""
    stage = clock(date(2026, 10, 9), now_due=date(2026, 10, 13))
    assert due(S.INTEREST_CONFIRMED, at(date(2026, 10, 12), 23), stage) == []
    assert kinds(due(S.INTEREST_CONFIRMED, at(date(2026, 10, 13), 9), stage)) == [(K.CONTACT_ESCALATION, "e4:bd3")]
    late = due(S.INTEREST_CONFIRMED, at(date(2026, 10, 14), 9), stage)
    assert (late[1].key, late[1].on) == ("e4:overdue", date(2026, 10, 13))
    assert late[1].expires == date(2026, 10, 21)  # 10 BD + 2 paused


def test_nda_reminders_fall_due_at_two_and_four_business_days_only_the_latest_sent() -> None:
    """AT-B-3's moments: entered Monday, the 2-BD reminder once Wednesday has ended, the 4-BD one once Friday has; a
    run after both sends only the latest (one email), keyed by the stage entry and the count."""
    stage = clock(date(2026, 10, 12), seq=7)
    assert due(S.NDA_PENDING, at(date(2026, 10, 7), 23), stage) == []
    first = due(S.NDA_PENDING, at(date(2026, 10, 8)), stage)
    assert kinds(first) == [(K.NDA_REMINDER, "e7:bd2")]
    assert (first[0].days, first[0].on) == (2, date(2026, 10, 12))
    assert kinds(due(S.NDA_PENDING, at(date(2026, 10, 10)), stage)) == [(K.NDA_REMINDER, "e7:bd4")]
    holiday = frozenset({date(2026, 10, 7)})
    assert due(S.NDA_PENDING, at(date(2026, 10, 8)), stage, holidays=holiday) == []  # Wed off: Thu is the 2nd BD


def test_the_procurement_route_is_escalated_past_its_fifth_business_day() -> None:
    """3b: 10 business days to choose, escalated once the 5th has ended (policy.yaml escalate_bd)."""
    stage = clock(date(2026, 10, 19), seq=3)
    assert due(S.PROCUREMENT_ROUTE, at(date(2026, 10, 12), 23), stage) == []
    found = due(S.PROCUREMENT_ROUTE, at(date(2026, 10, 13)), stage)
    assert kinds(found) == [(K.PROCUREMENT_ESCALATION, "e3:bd5")]
    assert (found[0].days, found[0].on) == (5, date(2026, 10, 19))


def test_a_milestone_under_review_is_reminded_at_three_and_escalated_at_five() -> None:
    """N12: a milestone submitted on Monday is reminded once Thursday has ended and escalated once the next Monday
    has; the key is the milestone and its submission (a resubmission starts again)."""
    waiting = nudges.Submission(MILESTONE, seq=2, event_seq=31, submitted_on=MONDAY)
    key = f"{MILESTONE}:e31"
    assert due(S.IN_IMPLEMENTATION, at(date(2026, 10, 8), 23), None, submissions=[waiting]) == []
    reminded = due(S.IN_IMPLEMENTATION, at(date(2026, 10, 9)), None, submissions=[waiting])
    assert kinds(reminded) == [(K.MILESTONE_REMINDER, key)]
    assert (reminded[0].days, reminded[0].milestone) == (3, waiting)
    both = due(S.IN_IMPLEMENTATION, at(date(2026, 10, 13)), None, submissions=[waiting])
    assert kinds(both) == [(K.MILESTONE_REMINDER, key), (K.MILESTONE_ESCALATION, key)]
    again = nudges.Submission(MILESTONE, seq=2, event_seq=40, submitted_on=date(2026, 10, 13))
    assert due(S.IN_IMPLEMENTATION, at(date(2026, 10, 14)), None, submissions=[again]) == []


@pytest.mark.parametrize("state", [S.SUBMITTED, S.UNDER_REVIEW, S.CONTACT_MADE, S.ON_HOLD, S.CLOSED, S.EXPIRED])
def test_nothing_is_due_outside_the_nudged_stages(state: S) -> None:
    late = at(date(2026, 12, 31))
    assert due(state, late, clock(date(2026, 10, 9))) == []
    assert due(S.INTEREST_CONFIRMED, late, None) == []  # no entering event read: nothing guessed


def test_contact_overdue_needs_a_deadline() -> None:
    stage = nudges.StageClock(entered_seq=4, entered_on=MONDAY, entered_due_on=None, deadline=None)
    assert kinds(due(S.INTEREST_CONFIRMED, at(date(2026, 10, 30)), stage)) == [(K.CONTACT_ESCALATION, "e4:bd3")]


def test_every_key_fits_the_ledger_and_the_dedupe_key() -> None:
    """Keys are codes (revision 0015's CHECK: [A-Za-z0-9_.:+-], 1-120); a notice's dedupe key fits its 200."""
    import re

    waiting = nudges.Submission(MILESTONE, seq=2, event_seq=123456, submitted_on=MONDAY)
    found = [
        *due(S.INTEREST_CONFIRMED, at(date(2026, 10, 30)), clock(date(2026, 10, 9), seq=999999)),
        *due(S.NDA_PENDING, at(date(2026, 10, 30)), clock(date(2026, 10, 12), seq=999999)),
        *due(S.PROCUREMENT_ROUTE, at(date(2026, 10, 30)), clock(date(2026, 10, 19), seq=999999)),
        *due(S.IN_IMPLEMENTATION, at(date(2026, 10, 30)), None, submissions=[waiting]),
    ]
    assert {d.kind for d in found} == set(NudgeKind)
    for item in found:
        assert re.fullmatch(r"[A-Za-z0-9_.:+-]{1,120}", item.key), item.key
        assert len(nudges.dedupe_key("email", MILESTONE, item.kind, item.key, MILESTONE)) <= 200


# ------------------------------------------------------------------------------------------------ recipients

OWNER, ADMIN, SIGNATORY, REVIEWER, FINANCE, CONTACT, ESCALATION = (
    UUID(f"01900000-0000-7000-8000-00000000000{n}") for n in range(1, 8)
)
ROSTER = nudges.Roster(
    roles={
        OWNER: frozenset({OrgRole.OWNER, OrgRole.ADMIN}),
        ADMIN: frozenset({OrgRole.ADMIN}),
        SIGNATORY: frozenset({OrgRole.SIGNATORY}),
        REVIEWER: frozenset({OrgRole.REVIEWER}),
        FINANCE: frozenset({OrgRole.FINANCE}),
        CONTACT: frozenset({OrgRole.REVIEWER}),
        ESCALATION: frozenset({OrgRole.VIEWER}),
    },
    escalation_contact=ESCALATION,
    contact=CONTACT,
    on_engagement=frozenset({CONTACT, FINANCE}),
)


def nudge(kind: NudgeKind) -> nudges.Due:
    return nudges.Due(kind, "e1:bd1")


def test_escalations_reach_the_admins_and_the_escalation_contact() -> None:
    for kind in (K.CONTACT_ESCALATION, K.PROCUREMENT_ESCALATION, K.MILESTONE_ESCALATION):
        assert nudges.recipients(nudge(kind), ROSTER) == (sorted({OWNER, ADMIN, ESCALATION}), False), kind
    no_contact = nudges.Roster(roles=ROSTER.roles)
    assert nudges.recipients(nudge(K.CONTACT_ESCALATION), no_contact) == (sorted({OWNER, ADMIN}), False)
    assert nudges.recipients(nudge(K.CONTACT_ESCALATION), nudges.Roster()) == ([], False)
    escalations = {K.CONTACT_ESCALATION, K.CONTACT_OVERDUE, K.PROCUREMENT_ESCALATION, K.MILESTONE_ESCALATION}
    assert escalations == nudges.ESCALATIONS


def test_em6_reaches_the_named_contact_the_admins_and_the_developer() -> None:
    """AT-B-2: both sides, two versions."""
    assert nudges.recipients(nudge(K.CONTACT_OVERDUE), ROSTER) == (sorted({OWNER, ADMIN, CONTACT}), True)
    assert nudges.recipients(nudge(K.CONTACT_OVERDUE), nudges.Roster()) == ([], True)
    rule = nudges.RULES[K.CONTACT_OVERDUE]
    assert (rule.org_copy, rule.developer_copy, rule.tag) == ("contact_overdue_org", "contact_overdue_developer", "em6")


def test_nda_reminders_reach_only_the_signers_who_have_not_signed() -> None:
    """AT-B-3: the developer when they have not signed, the organisation's signatories when it has not."""
    reminder = nudge(K.NDA_REMINDER)
    assert nudges.recipients(reminder, ROSTER) == ([SIGNATORY], True)
    assert nudges.recipients(reminder, ROSTER, signed={DEV}) == ([SIGNATORY], False)
    assert nudges.recipients(reminder, ROSTER, signed={ORG}) == ([], True)
    assert nudges.recipients(reminder, ROSTER, signed={DEV, ORG}) == ([], False)


def test_milestone_reminders_reach_the_engagements_reviewers() -> None:
    """The members who may accept a milestone among those on the engagement; else every reviewer; else every member
    who may accept one."""
    reminder = nudge(K.MILESTONE_REMINDER)
    assert nudges.recipients(reminder, ROSTER) == ([CONTACT], False)  # finance acted on it but reviews nothing
    nobody_on_it = nudges.Roster(roles=ROSTER.roles)
    assert nudges.recipients(reminder, nobody_on_it) == (sorted({REVIEWER, CONTACT}), False)
    no_reviewers = nudges.Roster(roles={OWNER: ROSTER.roles[OWNER], SIGNATORY: ROSTER.roles[SIGNATORY]})
    assert nudges.recipients(reminder, no_reviewers) == (sorted({OWNER, SIGNATORY}), False)


def test_the_matrix_rules_follow_requirements_section_5() -> None:
    """N05 (escalations, EM6: mutable), N07 (EM5: 🔒), N12 (the reminder in-app only, the escalation by email)."""
    rules = nudges.RULES
    assert set(rules) == set(NudgeKind)
    assert {kind: (r.matrix_kind, r.mutable, r.email) for kind, r in rules.items()} == {
        K.CONTACT_ESCALATION: ("engagement.n05", True, True),
        K.CONTACT_OVERDUE: ("engagement.n05", True, True),
        K.NDA_REMINDER: ("engagement.n07", False, True),
        K.PROCUREMENT_ESCALATION: ("engagement.n05", True, True),
        K.MILESTONE_REMINDER: ("engagement.n12", True, False),
        K.MILESTONE_ESCALATION: ("engagement.n12", True, True),
    }
    assert rules[K.NDA_REMINDER].tag == "em5"


def test_em6_is_keyed_on_the_stage_entry_so_a_moved_date_never_sends_it_twice() -> None:
    """The reviewer's case: the contact-by date passed (EM6 sent), then a hold and a resume moved the deadline to a date
    that has passed too: the key is the same, so the ledger refuses a second EM6."""
    before = due(S.INTEREST_CONFIRMED, at(date(2026, 10, 12)), clock(date(2026, 10, 9)))
    after = due(S.INTEREST_CONFIRMED, at(date(2026, 10, 20)), clock(date(2026, 10, 9), now_due=date(2026, 10, 13)))
    overdue = [d for d in (*before, *after) if d.kind is K.CONTACT_OVERDUE]
    assert [d.key for d in overdue] == ["e4:overdue", "e4:overdue"]
    assert [d.on for d in overdue] == [date(2026, 10, 9), date(2026, 10, 13)]  # the notice names the date missed
