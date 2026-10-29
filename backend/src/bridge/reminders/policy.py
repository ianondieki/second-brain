# ported from reminder/scan.py: DAY, GitState, Project
# ported from reminder/remind.py: MAX_ATTEMPTS, ACTIONABLE, RISK_UNCOMMITTED, RISK_UNPUSHED, _plural, _and_list,
#   Config (the fields these functions read, as ReminderConfig), Flagged (with headline), Verdict, classify,
#   pick_featured, actionable, fallback_text, verdict_for, _gave_up (gave_up), _finished (finished),
#   _record (record) and the once-a-day guard inside run() (pending_channels)
"""The deterministic reminder policy, ported from the local companion (REQ-REM-00).

Plain code decides here: which projects are cold or have work at risk, which one is featured, what the fallback
wording says, and whether a channel still needs today's send. Behaviour is identical to `reminder/remind.py` for the
same inputs (backend/tests/unit/reminders/test_parity.py checks it against fixtures generated from reminder/), with
two deliberate differences in form only: nothing here does I/O or keeps state (the caller passes the day's delivery
record in and gets the new one back; `record` never mutates its input), and the flags of `record` are keyword-only.
The backend never imports reminder/ (ADR-001).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Final, Literal

DAY: Final = 86400.0
MAX_ATTEMPTS: Final = 3  # hard failures per channel per day before giving up
ACTIONABLE: Final = ("unfinished", "unclear")
RISK_UNCOMMITTED: Final = "not committed"  # the words that mark each kind of work at risk; fallback_text()
RISK_UNPUSHED: Final = "not pushed"  # looks for them, so the wording and the check stay together

VerdictStatus = Literal["unfinished", "probably_done", "not_a_project", "unclear"]
VerdictSource = Literal["agent", "fallback"]
ChannelEntry = dict[str, Any]  # one channel's delivery record for a day (attempts, at, status, ref/error, ...)
DayRecord = dict[str, ChannelEntry]  # channel name -> ChannelEntry


@dataclass
class GitState:
    branch: str | None
    has_remote: bool
    unpushed: int | None  # None = could not determine
    last_commit: float  # epoch seconds, 0 if none
    recent_commits: list[str]
    modified: list[str] | None  # None = index unreadable
    modified_partial: bool
    modified_newest: float  # newest mtime among modified files, 0 if none


@dataclass
class Project:
    name: str
    path: str
    last_work: float  # epoch seconds
    idle_days: int
    files: int
    truncated: bool
    recent_files: list[str]
    readme_title: str
    open_todos: int
    todo_samples: list[str]
    git: GitState | None = None
    skipped_copy_of: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class ReminderConfig:
    """The settings the ported policy and email read (the companion's reminders.json, minus discovery settings)."""

    path: str  # where the settings live, quoted in the email's "How this works"
    cold_after_days: int = 3
    at_risk_after_days: int = 3
    send_after_hour: int = 8
    done: list[str] = field(default_factory=list)
    snooze: dict[str, str] = field(default_factory=dict)  # name -> "YYYY-MM-DD"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _and_list(items: list[str]) -> str:
    """["a"] -> "a"; ["a", "b", "c"] -> "a, b and c"."""
    return ", ".join(items[:-1]) + (" and " if len(items) > 1 else "") + "".join(items[-1:])


@dataclass
class Flagged:
    project: Project
    cold: bool
    risks: list[str]

    @property
    def name(self) -> str:
        return self.project.name

    def headline(self) -> str:
        """Why the project is listed, as one line: work at risk first, lower-case start, no full stop."""
        parts = [f"work at risk: {', '.join(self.risks)}"] if self.risks else []
        if self.cold:
            parts.append(f"no work for {_plural(self.project.idle_days, 'day')}")
        return "; ".join(parts)


@dataclass
class Verdict:
    """What the investigator concluded about one flagged project (or the deterministic fallback)."""

    status: VerdictStatus = "unclear"
    left_off: str = ""
    next_step: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    source: VerdictSource = "agent"


def classify(
    projects: Sequence[Project], cfg: ReminderConfig, now: float, today: date
) -> tuple[list[Flagged], list[Project], list[tuple[Project, str]]]:
    """Split scanned projects into (flagged, quiet, held) where held = done/snoozed."""
    done = {n.lower() for n in cfg.done}
    snoozed = {n.lower(): date.fromisoformat(str(d)) for n, d in cfg.snooze.items()}
    flagged: list[Flagged] = []
    quiet: list[Project] = []
    held: list[tuple[Project, str]] = []
    for p in projects:
        low = p.name.lower()
        if low in done:
            held.append((p, "done"))
            continue
        if low in snoozed and today < snoozed[low]:
            held.append((p, f"snoozed until {snoozed[low].isoformat()}"))
            continue
        risks: list[str] = []
        g = p.git
        if g and g.modified:
            age = int((now - (g.modified_newest or p.last_work)) // DAY)
            if age >= cfg.at_risk_after_days:
                risks.append(f"{_plural(len(g.modified), 'changed file')} {RISK_UNCOMMITTED} for {_plural(age, 'day')}")
        if g and g.unpushed:
            age = int((now - g.last_commit) // DAY)
            if age >= cfg.at_risk_after_days:
                risks.append(f"{_plural(g.unpushed, 'commit')} {RISK_UNPUSHED} for {_plural(age, 'day')}")
        cold = p.idle_days >= cfg.cold_after_days
        if cold or risks:
            flagged.append(Flagged(p, cold, risks))
        else:
            quiet.append(p)
    # Work at risk first, then the most recently dropped (easiest to pick back up).
    flagged.sort(key=lambda f: (not f.risks, f.project.idle_days, f.name.lower()))
    return flagged, quiet, held


def pick_featured(flagged: Sequence[Flagged], featured_log: Mapping[str, str]) -> Flagged | None:
    """One project a day for the short message: rotate so the same one doesn't repeat daily."""
    if not flagged:
        return None
    order = {f.name: i for i, f in enumerate(flagged)}
    return min(flagged, key=lambda f: (featured_log.get(f.name, ""), order[f.name]))


def fallback_text(f: Flagged) -> Verdict:
    """Deterministic "where you left off" and next step, used when there is no usable agent verdict."""
    p, g = f.project, f.project.git
    if g and g.recent_commits:
        left = f'Last commit: "{g.recent_commits[0]}".'
    elif p.recent_files:
        left = "Last edited: " + ", ".join(p.recent_files[:3]) + "."
    else:
        left = "No recent activity details were found."
    if g and g.modified and any(RISK_UNCOMMITTED in r for r in f.risks):
        step = "Look over your changes in " + _and_list(g.modified[:3]) + ", then commit them."
    elif g and g.unpushed and any(RISK_UNPUSHED in r for r in f.risks):
        step = f"Push your {_plural(g.unpushed, 'commit')} so the work is backed up."
    elif p.todo_samples:
        step = f"Start the first open to-do item: {p.todo_samples[0]}"
    elif p.recent_files:
        step = f"Open {p.recent_files[0]} and write the next step at the top of the README."
    else:
        step = "Open the project and write the next step at the top of its README."
    return Verdict(status="unclear", left_off=left, next_step=step, source="fallback")


def verdict_for(f: Flagged, verdicts: Mapping[str, Verdict]) -> Verdict:
    """The agent's verdict when it has both a left-off line and a next step, else the fallback."""
    v = verdicts.get(f.name)
    if not isinstance(v, Verdict) or not v.left_off.strip() or not v.next_step.strip():
        return fallback_text(f)
    return v


def actionable(flagged: Sequence[Flagged], verdicts: Mapping[str, Verdict]) -> list[Flagged]:
    """Projects still worth nagging about: not judged finished or a non-project."""
    return [f for f in flagged if verdict_for(f, verdicts).status in ACTIONABLE]


# --------------------------------------------------------------------------- delivery (once a day, retries)


def gave_up(entry: Mapping[str, Any] | None) -> bool:
    """The channel failed hard MAX_ATTEMPTS times today and stops until tomorrow."""
    if not entry:
        return False
    return bool(entry.get("status") == "failed" and entry.get("hard_failures", 0) >= MAX_ATTEMPTS)


def finished(entry: Mapping[str, Any] | None) -> bool:
    """Nothing more to do on this channel today: sent, nothing to send, or given up."""
    if not entry:
        return False
    return entry.get("status") in ("sent", "nothing") or gave_up(entry)


def record(
    day: Mapping[str, ChannelEntry],
    channel: str,
    *,
    ok: bool,
    now: datetime,
    detail: str,
    transient: bool,
    force: bool,
    status: str = "sent",
) -> DayRecord:
    """The day's record with `channel`'s entry updated for one attempt; `day` itself is left unchanged.

    A forced run never rewrites a finished entry (that would re-arm the automatic sends or erase a give-up); it is
    logged under "forced". `status` is what a success is recorded as ("sent", or "nothing" when there was nothing
    to send). Only hard (non-transient) failures count towards MAX_ATTEMPTS.
    """
    entry: ChannelEntry = dict(day.get(channel) or {})
    stamp = now.isoformat(timespec="seconds")
    if force and finished(entry):
        logged = {"at": stamp, "status": status if ok else "failed", ("ref" if ok else "error"): detail}
        entry["forced"] = [*entry.get("forced", []), logged]
    else:
        entry["attempts"] = entry.get("attempts", 0) + 1
        entry["at"] = stamp
        if ok:
            entry.update(status=status, ref=detail)
            entry.pop("error", None)
        else:
            entry.update(status="failed", error=detail)
            if not transient:
                entry["hard_failures"] = entry.get("hard_failures", 0) + 1
    return {**day, channel: entry}


def pending_channels(
    day: Mapping[str, ChannelEntry],
    channels: Sequence[str],
    now: datetime,
    send_after_hour: int,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """The once-a-day guard: which of `channels` still need today's reminder.

    Nothing before `send_after_hour` (read from `now.hour`, so pass local time); after it, every channel that is not
    finished for the day. A forced or dry run takes every channel regardless.
    """
    if force or dry_run:
        return list(channels)
    if now.hour < send_after_hour:
        return []
    return [c for c in channels if not finished(day.get(c))]
