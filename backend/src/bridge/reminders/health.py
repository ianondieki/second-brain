"""Engagement health, computed by code only (REQ-REM-01, REQ-REM-02; docs/spec/06 6.11; AC-REM-1, AC-REM-3, AC-REM-4/b).

Both reminders (the developer's EM7 and the organisation's progress digest) build their health from the same
``EngagementFact`` through ``assess``, so they agree for the same rows (AC-REM-3). Pure code: no database, no clock, no
I/O. Dates are Nairobi calendar dates (``nairobi_today``) and "BD" are Kenyan business days
(``bridge.engagements.calendar``, holidays passed in as their observed dates).

The rules (docs/spec/06 6.11), for the engagement's main-path stages only (side and terminal states are not assessed):

- an item is the developer's milestone (from the **signed** agreement, not yet submitted or accepted), the
  organisation's review of a submitted milestone (due its review window in BD after submission), or the current
  stage's deadline for each party awaited;
- ``at_risk``: an item due within ``DUE_SOON_BD`` (2) BD with no action, an item overdue by 1 to 7 days, or (only
  with a linked repository, during ``IN_IMPLEMENTATION``, never on a weekend or holiday) no repository activity for
  ``COLD_AFTER_BD`` (3) BD; Release 1 links no repository, so the repo-cold rule never fires yet;
- ``off_track``: an item overdue by more than ``OFF_TRACK_AFTER_DAYS`` (7) days, or a milestone sent back for changes
  ``REWORK_LOOPS_OFF_TRACK`` (2) or more times;
- otherwise ``on_track``. Each reason is a code tuple (code, party, date, days, milestone), never prose and never a
  percentage: the renderers word it.

``whose_turn`` mirrors ``bridge.engagements.state_machine.pending`` (P5, parallel branch) from the tracker's rows;
once P5 merges, the fact loader calls the state machine instead and this table goes.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from bridge.engagements.calendar import add_business_days, business_days_between, is_business_day, local_date
from bridge.models.enums import EngagementParty, EngagementState, MilestoneState

DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
S, M = EngagementState, MilestoneState

DUE_SOON_BD: Final = 2  # "due within 2 BD with no action"
OFF_TRACK_AFTER_DAYS: Final = 7  # "overdue >7 days"
REWORK_LOOPS_OFF_TRACK: Final = 2  # "a rework loop >= 2"
COLD_AFTER_BD: Final = 3  # repo-cold rule (Release 2: a linked repository)
QUIET_AFTER_DAYS: Final = 5  # "No update from {party} since {date}" once a party has been quiet this long
DEFAULT_REVIEW_WINDOW_BD: Final = 5  # docs/spec/06 6.9 milestone sub-tracker

# Main-path stages (docs/spec/06 6.9). Side branches pause or freeze the clock; terminal states have nothing due.
ASSESSED_STATES: Final = frozenset(
    {
        S.ORG_INTEREST,
        S.SUBMITTED,
        S.UNDER_REVIEW,
        S.INTEREST_CONFIRMED,
        S.PROCUREMENT_ROUTE,
        S.CONTACT_MADE,
        S.NDA_PENDING,
        S.NDA_SIGNED,
        S.NEGOTIATION,
        S.AGREEMENT_SIGNING,
        S.IN_IMPLEMENTATION,
        S.DELIVERED,
        S.SIGN_OFF,
        S.PAYMENT_FINAL,
    }
)
_DEVELOPER_WORK: Final = frozenset({M.PLANNED, M.IN_PROGRESS, M.CHANGES_REQUESTED})


class Health(StrEnum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OFF_TRACK = "off_track"

    @property
    def rank(self) -> int:
        return (Health.ON_TRACK, Health.AT_RISK, Health.OFF_TRACK).index(self)


class ReasonCode(StrEnum):
    MILESTONE_DUE_SOON = "milestone_due_soon"  # days = business days left
    MILESTONE_OVERDUE = "milestone_overdue"  # days = calendar days late
    REVIEW_DUE_SOON = "review_due_soon"
    REVIEW_OVERDUE = "review_overdue"
    STAGE_DUE_SOON = "stage_due_soon"
    STAGE_OVERDUE = "stage_overdue"
    REWORK_LOOP = "rework_loop"  # days = times sent back for changes
    REPO_COLD = "repo_cold"  # days = business days without repository activity


@dataclass(frozen=True, slots=True)
class Reason:
    """One code-computed reason: whose item, when it is due, and a count whose meaning the code names."""

    code: ReasonCode
    health: Health
    party: EngagementParty
    due_on: date | None = None
    days: int = 0
    milestone_seq: int | None = None


@dataclass(frozen=True, slots=True)
class MilestoneFact:
    """A milestone of the engagement's signed agreement. ``submitted_on`` is the Nairobi date of its latest submission
    for review (the tracker's ``submit_milestone`` event), when known; ``rework_loops`` counts its ``request_changes``
    events."""

    seq: int
    deliverable: str
    due_on: date
    state: MilestoneState
    rework_loops: int = 0
    submitted_on: date | None = None
    review_window_bd: int = DEFAULT_REVIEW_WINDOW_BD


@dataclass(frozen=True, slots=True)
class EngagementFact:
    """What both reminders know about one engagement, read from the tracker's rows. Text fields (``title``,
    ``org_name``, ``developer_name``, milestone deliverables) are data for the renderers, never read by the rules."""

    id: UUID
    org_id: UUID
    state: EngagementState
    title: str
    org_name: str
    developer_name: str
    created_on: date
    entered_on: date  # when the current stage was entered
    stage_deadline_on: date | None
    awaiting: frozenset[EngagementParty]
    milestones: tuple[MilestoneFact, ...] = ()
    last_developer_update_on: date | None = None
    tagged: bool = False  # origin "tagged" (the developer pitched it)
    repo_linked: bool = False  # Release 2 (GitHub App); always False in Release 1
    last_repo_activity_on: date | None = None

    @property
    def assessed(self) -> bool:
        return self.state in ASSESSED_STATES


@dataclass(frozen=True, slots=True)
class Assessment:
    health: Health
    reasons: tuple[Reason, ...]


def nairobi_today(now: datetime) -> date:
    """The Nairobi calendar date of an aware timestamp (a naive one raises ``ValueError``)."""
    return local_date(now)


def _item(
    party: EngagementParty,
    due: date,
    today: date,
    holidays: Collection[date],
    *,
    soon: ReasonCode,
    late: ReasonCode,
    seq: int | None = None,
) -> Reason | None:
    if due < today:
        days = (today - due).days
        health = Health.OFF_TRACK if days > OFF_TRACK_AFTER_DAYS else Health.AT_RISK
        return Reason(late, health, party, due, days, seq)
    left = business_days_between(today, due, holidays)
    if left <= DUE_SOON_BD:
        return Reason(soon, Health.AT_RISK, party, due, left, seq)
    return None


def _milestone_reasons(m: MilestoneFact, today: date, holidays: Collection[date]) -> list[Reason]:
    reasons: list[Reason] = []
    if m.state is M.ACCEPTED:
        return reasons
    if m.rework_loops >= REWORK_LOOPS_OFF_TRACK:
        reasons.append(Reason(ReasonCode.REWORK_LOOP, Health.OFF_TRACK, DEV, m.due_on, m.rework_loops, m.seq))
    if m.state is M.SUBMITTED_FOR_REVIEW:
        if m.submitted_on is not None:
            review_due = add_business_days(m.submitted_on, m.review_window_bd, holidays)
            found = _item(
                ORG,
                review_due,
                today,
                holidays,
                soon=ReasonCode.REVIEW_DUE_SOON,
                late=ReasonCode.REVIEW_OVERDUE,
                seq=m.seq,
            )
            reasons.extend([found] if found else [])
        return reasons
    if m.state in _DEVELOPER_WORK:
        found = _item(
            DEV,
            m.due_on,
            today,
            holidays,
            soon=ReasonCode.MILESTONE_DUE_SOON,
            late=ReasonCode.MILESTONE_OVERDUE,
            seq=m.seq,
        )
        reasons.extend([found] if found else [])
    return reasons


def repo_cold(e: EngagementFact, today: date, holidays: Collection[date]) -> Reason | None:
    """AC-REM-4/b: only with a linked repository, during implementation, on a business day."""
    if not e.repo_linked or e.state is not S.IN_IMPLEMENTATION or not is_business_day(today, holidays):
        return None
    idle = business_days_between(e.last_repo_activity_on or e.entered_on, today, holidays)
    if idle >= COLD_AFTER_BD:
        return Reason(ReasonCode.REPO_COLD, Health.AT_RISK, DEV, None, idle)
    return None


def assess(e: EngagementFact, today: date, holidays: Collection[date]) -> Assessment:
    """The engagement's health on ``today`` and the reasons, worst first, then by due date and milestone."""
    if not e.assessed:
        return Assessment(Health.ON_TRACK, ())
    reasons: list[Reason] = []
    for m in e.milestones:
        reasons.extend(_milestone_reasons(m, today, holidays))
    if e.stage_deadline_on is not None:
        for party in (DEV, ORG):
            if party in e.awaiting:
                found = _item(
                    party,
                    e.stage_deadline_on,
                    today,
                    holidays,
                    soon=ReasonCode.STAGE_DUE_SOON,
                    late=ReasonCode.STAGE_OVERDUE,
                )
                reasons.extend([found] if found else [])
    cold = repo_cold(e, today, holidays)
    reasons.extend([cold] if cold else [])
    reasons.sort(key=lambda r: (-r.health.rank, r.due_on or today, r.milestone_seq or 0, r.party.value))
    health = max((r.health for r in reasons), key=lambda h: h.rank, default=Health.ON_TRACK)
    return Assessment(health, tuple(reasons))


def quiet_since(e: EngagementFact, today: date) -> date | None:
    """The date of the developer's last update when it is at least ``QUIET_AFTER_DAYS`` old (the engagement's start
    when they never acted), for "No update from {developer} since {date}"; None while they are active."""
    if not e.assessed:
        return None
    last = e.last_developer_update_on or e.created_on
    return last if (today - last).days >= QUIET_AFTER_DAYS else None


def whose_turn(
    state: EngagementState,
    *,
    signed: frozenset[EngagementParty] = frozenset(),
    contact_confirmed: bool = False,
    milestones: tuple[MilestoneState, ...] = (),
    payment_recorded: bool = False,
    terms_by: EngagementParty | None = None,
) -> frozenset[EngagementParty]:
    """The parties whose action moves the engagement on (docs/spec/06 6.9 "Next actor"). ``signed`` holds the parties
    that signed the stage's document (mutual NDA, final agreement or acceptance certificate); ``terms_by`` is the
    party that proposed the latest terms."""
    both = frozenset({DEV, ORG})
    if state is S.ORG_INTEREST or state is S.INFO_REQUESTED:
        return frozenset({DEV})
    if state in (S.SUBMITTED, S.UNDER_REVIEW, S.INTEREST_CONFIRMED, S.PROCUREMENT_ROUTE, S.DELIVERED):
        return frozenset({ORG})
    if state is S.CONTACT_MADE:
        return both if contact_confirmed else frozenset({DEV})
    if state in (S.NDA_PENDING, S.AGREEMENT_SIGNING):
        return both - signed
    if state is S.NDA_SIGNED:
        return both
    if state is S.NEGOTIATION:
        return both if terms_by is None else both - {terms_by}
    if state is S.IN_IMPLEMENTATION:
        if milestones and all(m is M.ACCEPTED for m in milestones):
            return frozenset({DEV})  # the final delivery
        parties = {DEV} if any(m in _DEVELOPER_WORK for m in milestones) else set()
        parties |= {ORG} if M.SUBMITTED_FOR_REVIEW in milestones else set()
        return frozenset(parties)
    if state is S.SIGN_OFF:
        return frozenset({DEV}) if ORG in signed else frozenset({ORG})  # the organisation signs first
    if state is S.PAYMENT_FINAL:
        return frozenset({DEV}) if payment_recorded else frozenset({ORG})
    return frozenset()
