"""AC-REM-1 and AC-REM-4/b (REQ-REM-01, REQ-REM-00; docs/spec/06 6.11): engagement health is computed by code only,
on Nairobi calendar dates and Kenyan business days, against the signed agreement's milestones.

Frozen time: every test passes its own "now" or "today"; nothing reads the wall clock. 2026-10-05 is a Monday.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from bridge.models.enums import EngagementParty, EngagementState, MilestoneState
from bridge.reminders.health import (
    COLD_AFTER_BD,
    QUIET_AFTER_DAYS,
    EngagementFact,
    Health,
    MilestoneFact,
    ReasonCode,
    assess,
    nairobi_today,
    quiet_since,
    repo_cold,
    whose_turn,
)

DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
S, M = EngagementState, MilestoneState
MONDAY = date(2026, 10, 5)
TUESDAY = MONDAY + timedelta(days=1)
SATURDAY = MONDAY + timedelta(days=5)
NO_HOLIDAYS: frozenset[date] = frozenset()


def milestone(due: date, state: MilestoneState = M.IN_PROGRESS, **kwargs: object) -> MilestoneFact:
    values: dict[str, object] = {"seq": 1, "deliverable": "Pilot for one county", "due_on": due, "state": state}
    values.update(kwargs)
    return MilestoneFact(**values)  # type: ignore[arg-type]


def engagement(state: EngagementState = S.IN_IMPLEMENTATION, **kwargs: object) -> EngagementFact:
    values: dict[str, object] = {
        "id": uuid4(),
        "org_id": uuid4(),
        "state": state,
        "title": "Solar cold rooms",
        "org_name": "Telco A (fixture)",
        "developer_name": "Wanjiru",
        "created_on": MONDAY - timedelta(days=60),
        "entered_on": MONDAY - timedelta(days=20),
        "stage_deadline_on": None,
        "awaiting": frozenset({DEV}),
    }
    values.update(kwargs)
    return EngagementFact(**values)  # type: ignore[arg-type]


# ------------------------------------------------------------------------------------------------------- AC-REM-1


def test_a_milestone_due_tomorrow_with_no_submission_is_at_risk() -> None:
    e = engagement(milestones=(milestone(TUESDAY),))
    result = assess(e, MONDAY, NO_HOLIDAYS)
    assert result.health is Health.AT_RISK
    (reason,) = result.reasons
    assert (reason.code, reason.party, reason.due_on, reason.days, reason.milestone_seq) == (
        ReasonCode.MILESTONE_DUE_SOON,
        DEV,
        TUESDAY,
        1,
        1,
    )


def test_a_milestone_overdue_by_eight_days_is_off_track() -> None:
    e = engagement(milestones=(milestone(MONDAY - timedelta(days=8)),))
    result = assess(e, MONDAY, NO_HOLIDAYS)
    assert result.health is Health.OFF_TRACK
    assert [(r.code, r.days) for r in result.reasons] == [(ReasonCode.MILESTONE_OVERDUE, 8)]


def test_today_is_the_nairobi_date_not_the_utc_date() -> None:
    """00:30 EAT on Tuesday is still Monday in UTC: the milestone due on Tuesday is due today, not tomorrow."""
    now = datetime(2026, 10, 5, 21, 30, tzinfo=UTC)
    assert nairobi_today(now) == TUESDAY
    with pytest.raises(ValueError, match="timezone-aware"):
        nairobi_today(datetime(2026, 10, 5, 21, 30))  # noqa: DTZ001
    result = assess(engagement(milestones=(milestone(TUESDAY),)), nairobi_today(now), NO_HOLIDAYS)
    assert [(r.code, r.days) for r in result.reasons] == [(ReasonCode.MILESTONE_DUE_SOON, 0)]


@pytest.mark.parametrize(
    ("days_late", "health"),
    [(1, Health.AT_RISK), (7, Health.AT_RISK), (8, Health.OFF_TRACK), (30, Health.OFF_TRACK)],
)
def test_overdue_is_at_risk_up_to_seven_days_and_off_track_after(days_late: int, health: Health) -> None:
    result = assess(engagement(milestones=(milestone(MONDAY - timedelta(days=days_late)),)), MONDAY, NO_HOLIDAYS)
    assert result.health is health


def test_due_soon_counts_business_days_and_skips_weekends_and_holidays() -> None:
    friday = MONDAY + timedelta(days=4)
    next_monday, next_tuesday, next_wednesday = (MONDAY + timedelta(days=d) for d in (7, 8, 9))
    due_monday = assess(engagement(milestones=(milestone(next_monday),)), friday, NO_HOLIDAYS)
    assert [(r.code, r.days) for r in due_monday.reasons] == [(ReasonCode.MILESTONE_DUE_SOON, 1)]
    assert assess(engagement(milestones=(milestone(next_tuesday),)), friday, NO_HOLIDAYS).health is Health.AT_RISK
    assert assess(engagement(milestones=(milestone(next_wednesday),)), friday, NO_HOLIDAYS).health is Health.ON_TRACK
    # A holiday on Monday pushes Wednesday within two business days of Friday.
    held = assess(engagement(milestones=(milestone(next_wednesday),)), friday, frozenset({next_monday}))
    assert held.health is Health.AT_RISK


@pytest.mark.parametrize("state", [M.SUBMITTED_FOR_REVIEW, M.ACCEPTED])
def test_a_submitted_or_accepted_milestone_is_not_the_developers_risk(state: MilestoneState) -> None:
    e = engagement(milestones=(milestone(TUESDAY, state), milestone(MONDAY - timedelta(days=9), state, seq=2)))
    assert assess(e, MONDAY, NO_HOLIDAYS).health is Health.ON_TRACK


def test_a_review_past_its_window_is_the_organisations_overdue_item() -> None:
    """A milestone submitted on 21 September with a 5 BD review window is due for review on the 28th."""
    submitted = milestone(TUESDAY, M.SUBMITTED_FOR_REVIEW, submitted_on=date(2026, 9, 21), review_window_bd=5)
    result = assess(engagement(milestones=(submitted,), awaiting=frozenset({ORG})), MONDAY, NO_HOLIDAYS)
    assert [(r.code, r.party, r.due_on, r.days) for r in result.reasons] == [
        (ReasonCode.REVIEW_OVERDUE, ORG, date(2026, 9, 28), 7)
    ]
    assert result.health is Health.AT_RISK


def test_a_rework_loop_of_two_is_off_track() -> None:
    once = milestone(MONDAY + timedelta(days=30), M.IN_PROGRESS, rework_loops=1)
    twice = replace(once, rework_loops=2)
    assert assess(engagement(milestones=(once,)), MONDAY, NO_HOLIDAYS).health is Health.ON_TRACK
    result = assess(engagement(milestones=(twice,)), MONDAY, NO_HOLIDAYS)
    assert result.health is Health.OFF_TRACK
    assert [(r.code, r.days) for r in result.reasons] == [(ReasonCode.REWORK_LOOP, 2)]


def test_a_stage_past_its_deadline_is_at_risk_for_each_awaited_party_then_off_track() -> None:
    e = engagement(S.NDA_PENDING, stage_deadline_on=MONDAY - timedelta(days=2), awaiting=frozenset({DEV, ORG}))
    result = assess(e, MONDAY, NO_HOLIDAYS)
    assert result.health is Health.AT_RISK
    assert {(r.code, r.party, r.days) for r in result.reasons} == {
        (ReasonCode.STAGE_OVERDUE, DEV, 2),
        (ReasonCode.STAGE_OVERDUE, ORG, 2),
    }
    late = replace(e, stage_deadline_on=MONDAY - timedelta(days=8), awaiting=frozenset({ORG}))
    assert assess(late, MONDAY, NO_HOLIDAYS).health is Health.OFF_TRACK
    soon = replace(e, stage_deadline_on=TUESDAY + timedelta(days=1))
    assert {r.code for r in assess(soon, MONDAY, NO_HOLIDAYS).reasons} == {ReasonCode.STAGE_DUE_SOON}
    far = replace(e, stage_deadline_on=MONDAY + timedelta(days=10))
    assert assess(far, MONDAY, NO_HOLIDAYS).health is Health.ON_TRACK
    nobody = replace(late, awaiting=frozenset())
    assert assess(nobody, MONDAY, NO_HOLIDAYS).health is Health.ON_TRACK


def test_reasons_are_ordered_worst_first_then_by_date() -> None:
    e = engagement(
        milestones=(
            milestone(TUESDAY, seq=3),
            milestone(MONDAY - timedelta(days=2), seq=2),
            milestone(MONDAY - timedelta(days=9), seq=1),
        )
    )
    assert [r.milestone_seq for r in assess(e, MONDAY, NO_HOLIDAYS).reasons] == [1, 2, 3]


@pytest.mark.parametrize("state", [S.ON_HOLD, S.DISPUTED, S.INFO_REQUESTED, S.CLOSED, S.DECLINED, S.EXPIRED])
def test_side_and_terminal_states_are_not_assessed(state: EngagementState) -> None:
    e = engagement(state, milestones=(milestone(MONDAY - timedelta(days=20)),), stage_deadline_on=MONDAY)
    assert assess(e, MONDAY, NO_HOLIDAYS).reasons == ()


# ----------------------------------------------------------------------------------------------------- AC-REM-4/b


def test_repo_cold_never_on_weekend_or_no_repo() -> None:
    """AC-REM-4/b: a weekend fixture and a developer with no repo linked never yield at_risk from the repo-cold rule."""
    idle = MONDAY - timedelta(days=30)
    no_repo = engagement(last_repo_activity_on=idle)
    assert repo_cold(no_repo, MONDAY, NO_HOLIDAYS) is None
    assert assess(no_repo, MONDAY, NO_HOLIDAYS).health is Health.ON_TRACK
    linked = replace(no_repo, repo_linked=True)
    for weekend_day in (SATURDAY, SATURDAY + timedelta(days=1)):
        assert repo_cold(linked, weekend_day, NO_HOLIDAYS) is None
        assert assess(linked, weekend_day, NO_HOLIDAYS).health is Health.ON_TRACK
    assert repo_cold(linked, MONDAY, frozenset({MONDAY})) is None  # a holiday is no working day either


def test_repo_cold_on_a_business_day_with_a_linked_repo_in_implementation() -> None:
    linked = engagement(repo_linked=True, last_repo_activity_on=MONDAY - timedelta(days=7))  # the Monday before
    reason = repo_cold(linked, MONDAY, NO_HOLIDAYS)
    assert reason is not None
    assert (reason.code, reason.health, reason.days) == (ReasonCode.REPO_COLD, Health.AT_RISK, 5)
    assert assess(linked, MONDAY, NO_HOLIDAYS).health is Health.AT_RISK
    fresh = replace(linked, last_repo_activity_on=MONDAY - timedelta(days=3))  # Friday: one business day
    assert COLD_AFTER_BD > 1
    assert repo_cold(fresh, MONDAY, NO_HOLIDAYS) is None
    assert repo_cold(replace(linked, state=S.NEGOTIATION), MONDAY, NO_HOLIDAYS) is None
    never = replace(linked, last_repo_activity_on=None, entered_on=MONDAY - timedelta(days=14))
    assert repo_cold(never, MONDAY, NO_HOLIDAYS) is not None  # counted from entering implementation


# -------------------------------------------------------------------------------------------------- quiet parties


def test_quiet_since_names_the_developers_last_update_once_it_is_old_enough() -> None:
    last = MONDAY - timedelta(days=QUIET_AFTER_DAYS)
    assert quiet_since(engagement(last_developer_update_on=last), MONDAY) == last
    assert quiet_since(engagement(last_developer_update_on=last + timedelta(days=1)), MONDAY) is None
    never = engagement(last_developer_update_on=None, created_on=MONDAY - timedelta(days=9))
    assert quiet_since(never, MONDAY) == MONDAY - timedelta(days=9)
    assert quiet_since(engagement(S.CLOSED, last_developer_update_on=last), MONDAY) is None


# ------------------------------------------------------------------------------------------------------ whose turn


@pytest.mark.parametrize(
    ("state", "facts", "expected"),
    [
        (S.ORG_INTEREST, {}, {DEV}),
        (S.SUBMITTED, {}, {ORG}),
        (S.UNDER_REVIEW, {}, {ORG}),
        (S.INTEREST_CONFIRMED, {}, {ORG}),
        (S.PROCUREMENT_ROUTE, {}, {ORG}),
        (S.CONTACT_MADE, {}, {DEV}),
        (S.CONTACT_MADE, {"contact_confirmed": True}, {DEV, ORG}),
        (S.NDA_PENDING, {}, {DEV, ORG}),
        (S.NDA_PENDING, {"signed": frozenset({DEV})}, {ORG}),
        (S.NDA_SIGNED, {}, {DEV, ORG}),
        (S.NEGOTIATION, {}, {DEV, ORG}),
        (S.NEGOTIATION, {"terms_by": DEV}, {ORG}),
        (S.NEGOTIATION, {"terms_by": ORG}, {DEV}),
        (S.AGREEMENT_SIGNING, {"signed": frozenset({ORG})}, {DEV}),
        (S.IN_IMPLEMENTATION, {"milestones": (M.PLANNED,)}, {DEV}),
        (S.IN_IMPLEMENTATION, {"milestones": (M.SUBMITTED_FOR_REVIEW,)}, {ORG}),
        (S.IN_IMPLEMENTATION, {"milestones": (M.CHANGES_REQUESTED, M.SUBMITTED_FOR_REVIEW)}, {DEV, ORG}),
        (S.IN_IMPLEMENTATION, {"milestones": (M.ACCEPTED, M.ACCEPTED)}, {DEV}),
        (S.IN_IMPLEMENTATION, {}, set()),
        (S.DELIVERED, {}, {ORG}),
        (S.SIGN_OFF, {}, {ORG}),
        (S.SIGN_OFF, {"signed": frozenset({ORG})}, {DEV}),
        (S.PAYMENT_FINAL, {}, {ORG}),
        (S.PAYMENT_FINAL, {"payment_recorded": True}, {DEV}),
        (S.INFO_REQUESTED, {}, {DEV}),
        (S.ON_HOLD, {}, set()),
        (S.CLOSED, {}, set()),
    ],
)
def test_whose_turn_follows_the_tracker_table(
    state: EngagementState, facts: dict[str, object], expected: set[EngagementParty]
) -> None:
    assert whose_turn(state, **facts) == frozenset(expected)  # type: ignore[arg-type]
