"""The developer's daily reminder, EM7/N23 (REQ-REM-01; docs/spec/06 6.10, 6.11): composed by code from fact tuples.

``compose_nudge`` turns a developer's ``DeveloperFacts`` into a ``Nudge``: Needs you (each engagement awaiting the
developer, each open milestone), Waiting on the other party, Health (every active engagement, with its code-computed
reasons), drafts not published, and one featured next step. Everything is code-rendered; party text is quoted and
defanged (``bridge.reminders.render``). ``Nudge.fact_lines`` is all an LLM may see (``bridge.reminders.wording``):
counts, codes, dates, milestone numbers and the developer's own proposal titles, never an organisation's text or a
milestone's deliverable. ``Wording`` is what the email says above and below the facts: the LLM's rewording or the
fixed fallback (``fallback_wording``), marked either way.

A nudge is ``empty`` (nothing is sent) when nothing needs the developer, every engagement is on track and no draft
waits: waiting on the other party alone is quiet.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal
from uuid import UUID

from bridge.models.enums import EngagementParty, MilestoneState
from bridge.notifications.email import EmailMessage
from bridge.reminders.health import Assessment, EngagementFact, Health, Reason, ReasonCode, assess
from bridge.reminders.render import (
    HEALTH_LABELS,
    TRACKER_PATH,
    Email,
    developer_action,
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

KIND: Final = "em7"
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
M = MilestoneState
WORDING_HEADER: Final = "X-Bridge-Wording"  # "model" or "fallback": which wording the email carries
# [[COPY-REVIEW]]
AI_LABEL: Final = "AI-drafted: an AI model worded the first line and the next step from the facts below."
FOOTER: Final = "You get this daily reminder because you turned reminders on."
CTA: Final = "Open your tracker"
IN_APP_TITLE: Final = "Your daily update"
UPCOMING_DAYS: Final = 14  # open milestones due within this many days are listed one by one under Needs you
_OPEN_WORK: Final = frozenset({M.PLANNED, M.IN_PROGRESS, M.CHANGES_REQUESTED})
OVERDUE_CODES: Final = frozenset({ReasonCode.MILESTONE_OVERDUE, ReasonCode.REVIEW_OVERDUE, ReasonCode.STAGE_OVERDUE})


@dataclass(frozen=True, slots=True)
class DeveloperFacts:
    """A developer's active engagements (read as them) and the titles of their drafts, on Nairobi date ``today``."""

    user_id: UUID
    today: date
    engagements: tuple[EngagementFact, ...]
    drafts: tuple[str | None, ...] = ()


@dataclass(frozen=True, slots=True)
class HealthRow:
    engagement_id: UUID
    health: Health
    line: str


@dataclass(frozen=True, slots=True)
class Nudge:
    user_id: UUID
    today: date
    needs_you: tuple[str, ...]
    waiting: tuple[str, ...]
    health: tuple[HealthRow, ...]
    drafts: tuple[str, ...]
    next_step: str
    fact_lines: tuple[str, ...]

    @property
    def watch(self) -> int:
        """Engagements at risk or off track."""
        return sum(1 for row in self.health if row.health is not Health.ON_TRACK)

    @property
    def empty(self) -> bool:
        return not self.needs_you and not self.drafts and self.watch == 0

    def health_of(self) -> dict[UUID, Health]:
        return {row.engagement_id: row.health for row in self.health}

    @property
    def fallback_headline(self) -> str:
        """The fixed first line (code, from the counts). [[COPY-REVIEW]]"""
        needs, watch = len(self.needs_you), self.watch
        attention = f"{plural(watch, 'engagement')} need{'s' if watch == 1 else ''} attention"
        if needs:
            first = f"{plural(needs, 'thing')} need{'s' if needs == 1 else ''} you today"
            return f"{first}, and {attention}." if watch else f"{first}."
        if watch:
            return f"Nothing needs you today, but {attention}."
        return f"You have {plural(len(self.drafts), 'draft')} not published yet."


@dataclass(frozen=True, slots=True)
class Wording:
    """The email's first line and next step. ``source`` is "model" (an LLM worded it from ``fact_lines``; labelled
    "AI-drafted") or "fallback" (the fixed text); ``reason`` says why the fallback was used."""

    headline: str
    next_step: str
    source: Literal["model", "fallback"]
    reason: str | None = None

    @property
    def ai_drafted(self) -> bool:
        return self.source == "model"


def fallback_wording(nudge: Nudge, reason: str) -> Wording:
    return Wording(nudge.fallback_headline, nudge.next_step, "fallback", reason)


def _first_upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _title(e: EngagementFact) -> str:
    return quote(e.title, fallback="your proposal")


def _org(e: EngagementFact) -> str:
    return name(e.org_name, fallback="the organisation")


def _due(day: date | None) -> str:
    return f" (due {eat_date(day)})" if day else ""


def _needs_you(e: EngagementFact, today: date) -> list[str]:
    """What the developer does next on ``e``: each open milestone overdue or due within ``UPCOMING_DAYS``, else one
    line for the stage (with the next milestone's date during implementation)."""
    if DEV not in e.awaiting:
        return []
    open_work = sorted((m for m in e.milestones if m.state in _OPEN_WORK), key=lambda m: (m.due_on, m.seq))
    soon = [m for m in open_work if (m.due_on - today).days <= UPCOMING_DAYS]
    if soon:
        return [
            f"Milestone {m.seq} {quote(m.deliverable)} of {_title(e)}: submit it for review by {eat_date(m.due_on)}."
            for m in soon
        ]
    due = open_work[0].due_on if open_work else e.stage_deadline_on
    return [f"{_title(e)} with {_org(e)}: {developer_action(e)}{_due(due)}."]


def _next_step(pairs: list[tuple[EngagementFact, Assessment]], drafts: tuple[str, ...]) -> str:
    """The one featured step (code): the developer's most urgent item, else the first thing that needs them."""
    mine = [(r, e) for e, a in pairs for r in a.reasons if r.party is DEV]
    mine.sort(key=lambda pair: (-pair[0].health.rank, pair[0].due_on or date.max))
    if mine:
        return _step_for(*mine[0])
    for e, _ in pairs:
        if DEV in e.awaiting:
            return f"{_first_upper(developer_action(e))} for {_title(e)}."
    if drafts:
        return f"Finish and publish your draft {drafts[0]}."
    return "Nothing needs you today: look over your tracker when you have a moment."


def _step_for(r: Reason, e: EngagementFact) -> str:
    title, due = _title(e), eat_date(r.due_on) if r.due_on else ""
    if r.code is ReasonCode.MILESTONE_OVERDUE:
        return f"Submit milestone {r.milestone_seq} of {title} for review: it was due {due}."
    if r.code is ReasonCode.MILESTONE_DUE_SOON:
        return f"Submit milestone {r.milestone_seq} of {title} for review by {due}."
    if r.code is ReasonCode.REWORK_LOOP:
        return f"Agree what milestone {r.milestone_seq} of {title} still needs before you resubmit it."
    if r.code is ReasonCode.STAGE_OVERDUE:
        return f"{_first_upper(developer_action(e))} for {title}: it was due {due}."
    if r.code is ReasonCode.STAGE_DUE_SOON:
        return f"{_first_upper(developer_action(e))} for {title} by {due}."
    return f"Pick up {title} where you left off."


def compose_nudge(facts: DeveloperFacts, holidays: Collection[date]) -> Nudge:
    pairs = [(e, assess(e, facts.today, holidays)) for e in facts.engagements if e.assessed]
    needs_you: list[str] = []
    waiting: list[str] = []
    health: list[HealthRow] = []
    for e, a in pairs:
        needs_you += _needs_you(e, facts.today)
        if ORG in e.awaiting:
            waiting.append(
                f"{_title(e)}: waiting for {_org(e)} to {organisation_action(e)}{_due(e.stage_deadline_on)}."
            )
        why = "; ".join(reason_text(r, e, viewer=DEV) for r in a.reasons)
        line = f"{_title(e)} with {_org(e)}: {HEALTH_LABELS[a.health]}" + (f". {why}." if why else ".")
        health.append(HealthRow(e.id, a.health, line))
    drafts = tuple(quote(title, fallback="Untitled draft") for title in facts.drafts)
    step = _next_step(pairs, drafts)
    counts = [health_row.health for health_row in health]
    status = ", ".join(
        f"{HEALTH_LABELS[h].lower()} {counts.count(h)}"
        for h in (Health.OFF_TRACK, Health.AT_RISK, Health.ON_TRACK)
        if counts.count(h)
    )
    overdue = sum(1 for _, a in pairs for r in a.reasons if r.code in OVERDUE_CODES)
    fact_lines = (
        f"Date: {eat_date(facts.today)}",
        f"Things that need the developer: {len(needs_you)}",
        f"Engagements waiting on the other party: {len(waiting)}",
        *([f"Engagement health: {status}"] if status else []),
        *([f"Overdue items: {overdue}"] if overdue else []),
        f"Drafts not published: {len(drafts)}",
        f"Suggested next step: {step}",
    )
    return Nudge(facts.user_id, facts.today, tuple(needs_you), tuple(waiting), tuple(health), drafts, step, fact_lines)


def summary(nudge: Nudge) -> str:
    """The counts in a few words ("2 need you, 1 at risk"), code-rendered. [[COPY-REVIEW]]"""
    parts = [f"{len(nudge.needs_you)} need{'s' if len(nudge.needs_you) == 1 else ''} you"] if nudge.needs_you else []
    rows = [row.health for row in nudge.health]
    for health, label in ((Health.OFF_TRACK, "off track"), (Health.AT_RISK, "at risk")):
        if rows.count(health):
            parts.append(f"{rows.count(health)} {label}")
    if nudge.drafts:
        parts.append(plural(len(nudge.drafts), "draft"))
    return ", ".join(parts) or "an update"


def subject(nudge: Nudge) -> str:
    return f"Your day on Bridge ({eat_date(nudge.today)}): {summary(nudge)}"


def email(nudge: Nudge, wording: Wording) -> Email:
    return Email(
        subject=subject(nudge),
        headline=wording.headline,
        notes=(AI_LABEL,) if wording.ai_drafted else (),
        sections=sections(
            ("Needs you", nudge.needs_you),
            ("Waiting on the other party", nudge.waiting),
            ("Health", [row.line for row in nudge.health]),
            ("Drafts not published", nudge.drafts),
        ),
        next_step=wording.next_step,
        cta_label=CTA,
        cta_path=TRACKER_PATH,
        footer=FOOTER,
    )


def render_nudge(nudge: Nudge, wording: Wording, *, to: str, base_url: str) -> EmailMessage:
    worded = email(nudge, wording)
    return EmailMessage(
        to=to,
        subject=worded.subject,
        text=render_text(worded, base_url),
        html=render_html(worded, base_url),
        tag=KIND,
        headers={WORDING_HEADER: wording.source},
    )


def in_app_body(nudge: Nudge) -> str:
    """The in-app summary on Home: code-rendered counts, never the LLM's words. [[COPY-REVIEW]]"""
    return f"{_first_upper(summary(nudge))}. Next step: {nudge.next_step}"
