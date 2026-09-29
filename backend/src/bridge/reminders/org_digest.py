"""The organisation's progress digest, the org version of EM7 (REQ-REM-02; docs/spec/06 6.10, 6.11; AC-REM-2).

Rendered by code from fact tuples only: no LLM is involved (this module imports none). For each active engagement of
the organisation: its stage, On track / At risk / Off track with the code-computed reasons (``bridge.reminders.health``,
the same ``assess`` the developer's reminder uses, AC-REM-3), open milestones due soon, what awaits the organisation,
and "No update from {developer} since {date}" when the developer has been quiet (never a guessed percentage). Also
the new tagged proposals of the period and every overdue item. Developer-written text (titles, deliverables, names)
is quoted, attributed and defanged (``bridge.reminders.render``); links are platform URLs only (AC-MAIL-5).

Cadence per plan (``plans.yaml`` ``progress_digest``): ``daily``, or ``weekly`` (one digest per ISO week, dated its
Monday). Copy is ``[[COPY-REVIEW]]``.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final, Literal
from uuid import UUID

from bridge.models.enums import EngagementParty, EngagementState, MilestoneState
from bridge.notifications.email import EmailMessage
from bridge.reminders.health import EngagementFact, Health, ReasonCode, assess, quiet_since
from bridge.reminders.render import (
    HEALTH_LABELS,
    STAGE_LABELS,
    TRACKER_PATH,
    Email,
    eat_date,
    name,
    organisation_action,
    plural,
    quote,
    reason_text,
    render_html,
    render_text,
    sections,
)
from bridge.reminders.thresholds import ReminderPolicy, get_reminder_policy

KIND: Final = "em7_org"
Cadence = Literal["daily", "weekly"]
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
M = MilestoneState
_OVERDUE: Final = frozenset({ReasonCode.MILESTONE_OVERDUE, ReasonCode.REVIEW_OVERDUE, ReasonCode.STAGE_OVERDUE})
_OPEN_WORK: Final = frozenset({M.PLANNED, M.IN_PROGRESS, M.CHANGES_REQUESTED})
CTA: Final = "Open your organisation's tracker"
IN_APP_TITLE: Final = "Progress digest"


@dataclass(frozen=True, slots=True)
class OrgFacts:
    """An organisation's active engagements (read as one of its members) on Nairobi date ``today``."""

    org_id: UUID
    org_name: str
    today: date
    cadence: Cadence
    engagements: tuple[EngagementFact, ...]


@dataclass(frozen=True, slots=True)
class DigestEntry:
    engagement_id: UUID
    health: Health
    line: str


@dataclass(frozen=True, slots=True)
class Digest:
    org_id: UUID
    org_name: str
    today: date
    cadence: Cadence
    needs_us: tuple[str, ...]
    new_tagged: tuple[str, ...]
    overdue: tuple[str, ...]
    entries: tuple[DigestEntry, ...]

    @property
    def empty(self) -> bool:
        return not self.entries and not self.new_tagged

    @property
    def period(self) -> date:
        return period_start(self.today, self.cadence)

    def health_of(self) -> dict[UUID, Health]:
        return {entry.engagement_id: entry.health for entry in self.entries}

    @property
    def summary(self) -> str:
        """The counts in a few words, code-rendered."""
        rows = [entry.health for entry in self.entries]
        parts = [plural(len(rows), "active engagement")]
        parts += [f"{rows.count(h)} {HEALTH_LABELS[h].lower()}" for h in Health if rows.count(h)]
        if self.needs_us:
            parts.append(f"{len(self.needs_us)} awaiting you")
        if self.new_tagged:
            parts.append(plural(len(self.new_tagged), "new tagged proposal"))
        return ", ".join(parts)


def period_start(today: date, cadence: Cadence) -> date:
    """The first day of the digest's period: the day itself, or the Monday of its ISO week."""
    return today if cadence == "daily" else today - timedelta(days=today.weekday())


def _title(e: EngagementFact) -> str:
    return f"{quote(e.title, fallback='a proposal')} by {_dev(e)}"


def _dev(e: EngagementFact) -> str:
    return name(e.developer_name, fallback="the developer")


def _due(day: date | None) -> str:
    return f" by {eat_date(day)}" if day else ""


def _needs_us(e: EngagementFact) -> list[str]:
    if ORG not in e.awaiting:
        return []
    submitted = [m for m in e.milestones if m.state is M.SUBMITTED_FOR_REVIEW]
    if submitted:
        return [f"Milestone {m.seq} {quote(m.deliverable)} of {_title(e)}: review it." for m in submitted]
    return [f"{_title(e)}: {organisation_action(e)}{_due(e.stage_deadline_on)}."]


def _entry(
    e: EngagementFact, today: date, holidays: Collection[date], policy: ReminderPolicy
) -> tuple[DigestEntry, list[str]]:
    a = assess(e, today, holidays, policy)
    stage = STAGE_LABELS.get(e.state, e.state.value)
    sentences = [f"{_title(e)} ({stage}): {HEALTH_LABELS[a.health]}."]
    sentences += [f"{reason_text(r, e, viewer=ORG)}." for r in a.reasons]
    named = {r.milestone_seq for r in a.reasons}
    due = sorted(
        (
            m
            for m in e.milestones
            if m.state in _OPEN_WORK and (m.due_on - today).days <= policy.upcoming_days and m.seq not in named
        ),
        key=lambda m: (m.due_on, m.seq),
    )
    if due:
        listed = "; ".join(f"milestone {m.seq} {quote(m.deliverable)} due {eat_date(m.due_on)}" for m in due)
        sentences.append(f"Milestones due: {listed}.")
    quiet = quiet_since(e, today, policy)
    if quiet is not None:
        sentences.append(f"No update from {_dev(e)} since {eat_date(quiet)}.")
    overdue = [f"{_title(e)}: {reason_text(r, e, viewer=ORG)}." for r in a.reasons if r.code in _OVERDUE]
    return DigestEntry(e.id, a.health, " ".join(sentences)), overdue


def compose_digest(facts: OrgFacts, holidays: Collection[date], policy: ReminderPolicy | None = None) -> Digest:
    policy = policy or get_reminder_policy()
    active = [e for e in facts.engagements if e.assessed]
    window = 1 if facts.cadence == "daily" else 7
    new_tagged = tuple(
        f"{_title(e)}, submitted {eat_date(e.created_on)}."
        for e in active
        if e.tagged and e.state is EngagementState.SUBMITTED and (facts.today - e.created_on).days < window
    )
    needs_us: list[str] = []
    overdue: list[str] = []
    entries: list[DigestEntry] = []
    for e in active:
        needs_us += _needs_us(e)
        entry, late = _entry(e, facts.today, holidays, policy)
        entries.append(entry)
        overdue += late
    entries.sort(key=lambda entry: -entry.health.rank)
    return Digest(
        facts.org_id,
        facts.org_name,
        facts.today,
        facts.cadence,
        tuple(needs_us),
        new_tagged,
        tuple(overdue),
        tuple(entries),
    )


def subject(digest: Digest) -> str:
    org = name(digest.org_name, fallback="Your organisation")
    if digest.cadence == "daily":
        return f"{org}: progress digest, {eat_date(digest.today)}"
    return f"{org}: weekly progress digest, week of {eat_date(digest.period)}"


def email(digest: Digest) -> Email:
    org = name(digest.org_name, fallback="your organisation")
    return Email(
        subject=subject(digest),
        headline=f"{digest.summary[:1].upper()}{digest.summary[1:]}.",
        sections=sections(
            ("Needs us", digest.needs_us),
            ("New tagged proposals", digest.new_tagged),
            ("Overdue", digest.overdue),
            ("Engagements", [entry.line for entry in digest.entries]),
        ),
        next_step=None,
        cta_label=CTA,
        cta_path=TRACKER_PATH,
        footer=f"You get this {digest.cadence} digest for {org} because you turned reminders on.",
    )


def render_digest(digest: Digest, *, to: str, base_url: str) -> EmailMessage:
    worded = email(digest)
    return EmailMessage(
        to=to,
        subject=worded.subject,
        text=render_text(worded, base_url),
        html=render_html(worded, base_url),
        tag=KIND,
    )
