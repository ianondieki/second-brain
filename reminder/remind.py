"""Daily project reminder: the deterministic half.

Config, `.env`, state, the cold/at-risk policy, wording fallbacks, email
composition and the once-a-day delivery with retries all live here and are plain
stdlib Python. The agentic half (a LangGraph workflow whose investigator agent
inspects each flagged project with tools) is in graph.py and calls into this
module; nothing in here can send twice or skip a day because of what the agent
says.

    python -m reminder --dry-run      # scan + investigate + compose, print, send nothing
    python -m reminder --force        # send now, ignoring the hour/once-a-day guard
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import logging.handlers
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import notify
from .scan import DAY, Project, discover

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_ATTEMPTS = 3            # hard failures per channel per day before giving up
KEEP_DAYS = 14
FEATURED_KEEP_DAYS = 90     # rotation memory; older entries only matter for projects long gone
LOCK_STALE_SECONDS = 15 * 60
CHANNELS = ("email", "whatsapp")
ACTIONABLE = ("unfinished", "unclear")
RISK_UNCOMMITTED = "not committed"      # the words that mark each kind of at-risk work; fallback_text()
RISK_UNPUSHED = "not pushed"            # looks for them, so the wording and the check stay together

log = logging.getLogger("reminder")


# --------------------------------------------------------------------------- env / config / state

def load_env(path: str) -> dict:
    env: dict[str, str] = {}
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key, value = key.strip(), value.strip()
        if value[:1] in ("'", '"'):
            end = value.find(value[0], 1)                 # quoted: keep everything inside, drop the rest
            value = value[1:end] if end != -1 else value[1:]
        else:
            value = re.sub(r"\s+#.*$", "", value)
        env[key] = value
    for key in list(env):                      # a real environment variable wins when set
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    path: str
    projects_roots: list[str]
    cold_after_days: int = 3
    at_risk_after_days: int = 3
    send_after_hour: int = 8
    max_investigate: int = 4         # projects the agent inspects per run (~1 min each on the free tier)
    ignore: list[str] = field(default_factory=list)
    track: list[str] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    snooze: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)


def load_config(base_dir: str) -> Config:
    path = os.path.join(base_dir, "reminders.json")
    if not os.path.exists(path):
        shutil.copyfile(os.path.join(base_dir, "reminders.example.json"), path)
        log.warning("Created %s from the example. Set projects_roots in it.", path)
    try:
        with open(path, encoding="utf-8-sig") as fh:
            raw = json.load(fh)
    except ValueError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}   # "_help" keys are comments
    known = set(Config.__dataclass_fields__) - {"path"}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{path}: unknown setting(s) {sorted(unknown)}")
    cfg = Config(path=path, **raw)

    def need(cond, msg):
        if not cond:
            raise ConfigError(f"{path}: {msg}")

    need(isinstance(cfg.projects_roots, list) and cfg.projects_roots, "projects_roots must be a non-empty list")
    for root in cfg.projects_roots:
        need(isinstance(root, str) and os.path.isdir(root), f"projects root not found: {root!r}")
    for name in ("cold_after_days", "at_risk_after_days", "max_investigate"):
        v = getattr(cfg, name)
        need(isinstance(v, int) and not isinstance(v, bool) and v >= 1, f"{name} must be a whole number >= 1")
    need(isinstance(cfg.send_after_hour, int) and 0 <= cfg.send_after_hour <= 23, "send_after_hour must be 0-23")
    for name in ("ignore", "track", "done"):
        v = getattr(cfg, name)
        need(isinstance(v, list) and all(isinstance(x, str) for x in v), f"{name} must be a list of folder names")
    need(isinstance(cfg.notes, dict), "notes must map folder name -> text")
    need(isinstance(cfg.snooze, dict), 'snooze must map folder name -> "YYYY-MM-DD"')
    for name, until in cfg.snooze.items():
        try:
            date.fromisoformat(str(until))
        except ValueError:
            raise ConfigError(f'{path}: snooze date for {name!r} must be "YYYY-MM-DD", got {until!r}') from None
    return cfg


def state_path(base_dir: str) -> str:
    return os.path.join(base_dir, ".state", "state.json")


def load_state(base_dir: str) -> dict:
    try:
        with open(state_path(base_dir), encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    st.setdefault("days", {})
    st.setdefault("featured", {})
    return st


def save_state(base_dir: str, st: dict) -> None:
    path = state_path(base_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    days = st.get("days", {})
    for old in sorted(days)[:-KEEP_DAYS]:
        del days[old]
    featured = st.get("featured", {})
    cutoff = (date.fromisoformat(max(days)) if days else date.today()).toordinal() - FEATURED_KEEP_DAYS
    for name in [n for n, d in featured.items() if not _ordinal(d) or _ordinal(d) < cutoff]:
        del featured[name]
    tmp = path + ".tmp"
    for attempt in range(5):                   # antivirus / indexer may hold the file for a moment
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(st, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2 * (attempt + 1))


def save_state_quietly(base_dir: str, st: dict) -> bool:
    """save_state for use after a send has already happened: a state file that cannot be
    written must not turn into a crash (which would hide the send and cause a resend
    anyway); log loudly and carry on."""
    try:
        save_state(base_dir, st)
        return True
    except Exception:
        log.exception("Could not write %s; the next run may repeat today's sends", state_path(base_dir))
        return False


def _ordinal(d) -> int:
    try:
        return date.fromisoformat(str(d)).toordinal()
    except ValueError:
        return 0


class Lock:
    def __init__(self, base_dir: str):
        self.path = os.path.join(base_dir, ".state", "remind.lock")
        self.fd = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        try:
            if time.time() - os.path.getmtime(self.path) > LOCK_STALE_SECONDS:
                os.remove(self.path)
        except OSError:
            pass
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            try:
                os.remove(self.path)
            except OSError:
                pass


# --------------------------------------------------------------------------- deciding

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
        """Why the project is listed, as one line for the WhatsApp message: work at risk first.
        No full stop and a lower-case start, because the first template puts it inside a sentence."""
        parts = [f"work at risk: {', '.join(self.risks)}"] if self.risks else []
        if self.cold:
            parts.append(f"no work for {_plural(self.project.idle_days, 'day')}")
        return "; ".join(parts)


@dataclass
class Verdict:
    """What the investigator agent concluded about one flagged project."""
    status: str = "unclear"             # unfinished | probably_done | not_a_project | unclear
    left_off: str = ""
    next_step: str = ""
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)   # tool calls made, for the dry-run printout
    source: str = "agent"               # agent | fallback


def classify(projects: list[Project], cfg: Config, now: float, today: date):
    """Split scanned projects into (flagged, quiet, held) where held = done/snoozed."""
    done = {n.lower() for n in cfg.done}
    snoozed = {n.lower(): date.fromisoformat(str(d)) for n, d in cfg.snooze.items()}
    flagged, quiet, held = [], [], []
    for p in projects:
        low = p.name.lower()
        if low in done:
            held.append((p, "done"))
            continue
        if low in snoozed and today < snoozed[low]:
            held.append((p, f"snoozed until {snoozed[low].isoformat()}"))
            continue
        risks, g = [], p.git
        if g and g.modified:
            age = int((now - (g.modified_newest or p.last_work)) // DAY)
            if age >= cfg.at_risk_after_days:
                risks.append(f"{_plural(len(g.modified), 'changed file')} {RISK_UNCOMMITTED} for "
                             f"{_plural(age, 'day')}")
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


def pick_featured(flagged: list[Flagged], featured_log: dict) -> Flagged | None:
    """WhatsApp shows one project a day: rotate so the same one doesn't repeat daily."""
    if not flagged:
        return None
    order = {f.name: i for i, f in enumerate(flagged)}
    return min(flagged, key=lambda f: (featured_log.get(f.name, ""), order[f.name]))


def actionable(flagged: list[Flagged], verdicts: dict) -> list[Flagged]:
    """Projects still worth nagging about: the agent didn't judge them finished or non-projects."""
    return [f for f in flagged if verdict_for(f, verdicts).status in ACTIONABLE]


# --------------------------------------------------------------------------- wording

def fallback_text(f: Flagged) -> Verdict:
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


def clean_line(s, limit: int) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip().strip('"')
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def verdict_for(f: Flagged, verdicts: dict) -> Verdict:
    v = verdicts.get(f.name)
    if not isinstance(v, Verdict) or not v.left_off.strip() or not v.next_step.strip():
        return fallback_text(f)
    return v


def whatsapp_params(f: Flagged, verdicts: dict) -> list[str]:
    v = verdict_for(f, verdicts)
    return [f.name, f.headline(), v.left_off, v.next_step]


# --------------------------------------------------------------------------- email: worded once, rendered twice
#
# Reading order, the same in the plain-text and the HTML part:
#   at a glance -> heads-up (rare) -> projects that need you -> maybe finished -> maybe not a project
#   -> everything else -> how this works
# Written for a reader who has never seen the code: short sentences, everyday words, one
# highlighted action per project, and every technical word explained once ("How this works").
# Fixed wording may use **bold** and `code` marks; _marks_text / _marks_html render them.

FONT = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "Consolas,'Courier New',monospace"
RULE = "=" * 62
TONE_STYLE = {                          # tone -> (card border, card background, section colour)
    "work": ("#d4d4d8", "#ffffff", "#1d4ed8"),
    "done": ("#a6f4c5", "#f6fef9", "#027a48"),
    "ignore": ("#fedf89", "#fffcf5", "#b54708"),
}
RISK_MEANING = (                        # what each kind of work at risk means, in plain words
    (RISK_UNCOMMITTED, "This work is not saved in git yet."),
    (RISK_UNPUSHED, "This work is only on this laptop, not backed up online."),
)
QUICK_NOTE = "Quick check only: the assistant did not look inside this project."


def _ago(days: int) -> str:
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def _some(names: list[str], limit: int = 3) -> str:
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown} and {len(names) - limit} more"


def _risk_line(risk: str) -> str:
    return next((f"{risk}. {meaning}" for marker, meaning in RISK_MEANING if marker in risk), risk)


def _marks_text(s: str) -> str:
    return s.replace("**", "").replace("`", "")


def _marks_html(s: str) -> str:
    """Escape first, then turn our own **bold** and `code` marks into tags. Because escaping comes
    first, text that came from a project or from the agent can never inject markup."""
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(s))
    return re.sub(r"`(.+?)`", r'<code style="font-family:' + MONO + r';font-size:13px;background:#f4f4f5;'
                  r'border-radius:4px;padding:1px 4px">\1</code>', s)


@dataclass
class Card:
    """One project in the email, already worded. Rendered as plain text and as HTML."""
    name: str
    title: str
    tone: str                                   # work | done | ignore
    cold: bool                                  # gone quiet: then the first fact is the one to highlight
    facts: list[str]
    warnings: list[str]                         # work at risk, each with its plain meaning
    left_label: str
    left_off: str
    quick: bool = False                         # the wording comes from the scan, not from the assistant
    next_step: str = ""                         # tone "work" only
    hint: str = ""                              # tone done/ignore: what the assistant thinks
    action: str = ""                            # tone done/ignore: what the owner can do about it
    details: list[tuple[str, list[str]]] = field(default_factory=list)


def _make_card(f: Flagged, tone: str, verdicts: dict, now: float) -> Card:
    p, g, v = f.project, f.project.git, verdict_for(f, verdicts)
    facts = ["Worked on today" if p.idle_days <= 0 else
             "Last worked on yesterday" if p.idle_days == 1 else f"No work for {p.idle_days} days"]
    if p.open_todos:
        facts.append(_plural(p.open_todos, "open to-do item"))
    if g and g.last_commit:
        facts.append(f"Last commit {_ago(int((now - g.last_commit) // DAY))}")
    if not g:
        facts.append("Not in git")
    card = Card(name=p.name, title=p.readme_title, tone=tone, cold=f.cold, facts=facts,
                warnings=[_risk_line(r) for r in f.risks], left_label="Where you left off", left_off=v.left_off,
                quick=v.source != "agent")
    if tone in ("done", "ignore"):
        what, where, result = (("**finished**", "done", "You will not be reminded about it again.") if tone == "done"
                               else ("**not a real project**", "ignore", "The reminder will stop checking this folder."))
        card.left_label = "What the assistant found"
        card.hint = f"The assistant looked inside and thinks this is {what} ({v.confidence:.0%} sure)."
        card.action = (f'If you agree, open **reminders.json** (its full path is at the end of this email) and add '
                       f'**"{p.name}"** to the **"{where}"** list, like this: `"{where}": ["{p.name}"]`. {result} '
                       "If you do not agree, you do not need to do anything.")
    else:
        card.next_step = v.next_step
    if v.evidence:
        card.details.append(("Clues the assistant checked", list(v.evidence)))
    if g and g.recent_commits:
        card.details.append(("Recent commits", list(g.recent_commits)))
    if g and g.modified:
        card.details.append(("Changed files not committed",
                             [", ".join(g.modified[:8]) + (" …" if len(g.modified) > 8 else "")]))
    if p.recent_files:
        card.details.append(("Recently edited files", [", ".join(p.recent_files[:5])]))
    if p.todo_samples:
        card.details.append(("Open to-do items", list(p.todo_samples)))
    card.details.append(("Folder", [p.path]))
    return card


def _group_skipped(skipped) -> list[tuple[str, str]]:
    """Folders the scan left out, grouped by reason so eight backup copies read as one line."""
    ignored, hidden, copies, other = [], [], {}, []
    for name, why in skipped:
        if why == "ignored":
            (hidden if name.startswith(".") else ignored).append(name)
        elif why.startswith("copy of "):
            copies.setdefault(why[len("copy of "):], []).append(name)
        else:
            other.append(f"{name} ({why})")
    rows = []
    if ignored:
        rows.append(("Skipped (on your ignore list)", _some(ignored)))
    if hidden:
        rows.append(("Skipped (hidden folders)", _some(hidden)))
    for original, names in copies.items():
        rows.append((f"Skipped ({len(names)} backup {'copy' if len(names) == 1 else 'copies'} of {original})",
                     _some(names)))
    if other:
        rows.append(("Skipped (could not be read)", _some(other)))
    return rows


def _text_card(c: Card, number: int | None) -> list[str]:
    out = [(f"{number}. " if number else "- ") + c.name + (f"  ({c.title})" if c.title else ""),
           "   " + "  |  ".join(c.facts)]
    if c.quick:
        out.append(f"   ({QUICK_NOTE})")
    if c.warnings:
        out += ["", "   !! WORK AT RISK:"] + [f"      - {w}" for w in c.warnings]
    if c.hint:
        out += ["", f"   {_marks_text(c.hint)}"]
    out += ["", f"   {c.left_label}:", f"      {c.left_off}"]
    if c.next_step:
        out += ["", "   >> YOUR NEXT STEP (about 15 minutes):", f"      {c.next_step}"]
    if c.action:
        out += ["", "   >> WHAT YOU CAN DO:", f"      {_marks_text(c.action)}"]
    out += ["", "   More details:"]
    for label, values in c.details:
        if len(values) == 1:
            out.append(f"      - {label}: {values[0]}")
        else:
            out.append(f"      - {label}:")
            out += [f"          * {v}" for v in values]
    out.append("")
    return out


def _html_label(text: str, colour: str) -> str:
    return ('<div style="font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;'
            f'color:{colour}">{html.escape(text)}</div>')


def _html_card(c: Card, number: int | None) -> str:
    e = html.escape
    border, bg, colour = TONE_STYLE[c.tone]
    badge = ""
    if number:
        badge = ('<span style="display:inline-block;width:24px;height:24px;line-height:24px;border-radius:12px;'
                 'background:#1d4ed8;color:#ffffff;font-size:13px;font-weight:700;text-align:center;'
                 f'margin-right:8px">{number}</span>')
    parts = [f'<div style="border:1px solid {border};background:{bg};border-radius:10px;padding:16px;'
             'margin:0 0 16px">',
             f'<div style="font-size:19px;font-weight:700;line-height:1.3">{badge}{e(c.name)}</div>']
    if c.title:
        parts.append(f'<div style="color:#71717a;font-size:13px;margin:2px 0 0">{e(c.title)}</div>')
    pills = []
    for i, fact in enumerate(c.facts):
        # Only "No work for N days" is news. On a card listed for work at risk, "Worked on today" is not.
        look = ("background:#fef3c7;color:#92400e;font-weight:700" if i == 0 and c.cold
                else "background:#f4f4f5;color:#3f3f46")
        pills.append(f'<span style="display:inline-block;{look};border-radius:12px;padding:3px 10px;'
                     f'margin:0 6px 6px 0;font-size:13px">{e(fact)}</span>')
    parts.append('<div style="margin:10px 0 2px">' + "".join(pills) + "</div>")
    if c.quick:
        parts.append(f'<div style="color:#71717a;font-size:13px;margin:0 0 6px">{e(QUICK_NOTE)}</div>')
    if c.warnings:
        items = "".join(f'<li style="margin:3px 0 0">{e(w)}</li>' for w in c.warnings)
        parts.append('<div style="background:#fef3f2;border-left:4px solid #d92d20;color:#912018;'
                     'padding:8px 12px;margin:6px 0 8px;font-size:14px"><b>&#9888; Work at risk</b>'
                     f'<ul style="margin:2px 0 0;padding-left:18px">{items}</ul></div>')
    if c.hint:
        parts.append(f'<div style="color:{colour};margin:8px 0 0">{_marks_html(c.hint)}</div>')
    parts.append('<div style="margin:12px 0 0"><div style="font-weight:700;font-size:14px;color:#3f3f46">'
                 f'{e(c.left_label)}</div><div>{e(c.left_off)}</div></div>')
    if c.next_step:
        parts.append('<div style="background:#fffbeb;border:1px solid #fde68a;border-left:5px solid #f59e0b;'
                     'border-radius:6px;padding:10px 14px;margin:14px 0 0">'
                     + _html_label("Your next step · about 15 minutes", "#92400e")
                     + f'<div style="font-size:16px;font-weight:700;margin:3px 0 0">{e(c.next_step)}</div></div>')
    if c.action:
        parts.append(f'<div style="background:#ffffff;border:1px dashed {border};border-left:5px solid {colour};'
                     'border-radius:6px;padding:10px 14px;margin:14px 0 0">'
                     + _html_label("What you can do", colour)
                     + f'<div style="margin:3px 0 0">{_marks_html(c.action)}</div></div>')
    rows = []
    for label, values in c.details:
        mono = f' style="font-family:{MONO};font-size:12px"' if label == "Folder" else ""
        if len(values) == 1:
            rows.append(f'<li style="margin:0 0 4px"><b>{e(label)}:</b> <span{mono}>{e(values[0])}</span></li>')
        else:
            inner = "".join(f'<li style="margin:0 0 2px">{e(v)}</li>' for v in values)
            rows.append(f'<li style="margin:0 0 4px"><b>{e(label)}:</b>'
                        f'<ul style="margin:2px 0 0;padding-left:18px">{inner}</ul></li>')
    parts.append('<div style="margin:14px 0 0;padding:10px 0 0;border-top:1px solid #e4e4e7;font-size:13px;'
                 'color:#52525b"><div style="font-weight:700;color:#3f3f46;margin:0 0 4px">More details</div>'
                 '<ul style="margin:0;padding-left:18px">' + "".join(rows) + "</ul></div></div>")
    return "".join(parts)


def _day_stamp(today: date) -> str:
    """"Mon 21 Sep". In every subject, so each day's email is its own conversation in Gmail."""
    return today.strftime("%a %d %b")


def _subject(act: list[Flagged], today: date) -> str:
    n = len(act)
    if not n:
        return f"Project check-in: no project needs work today · {_day_stamp(today)}"

    def tag(f: Flagged) -> str:
        return f"{f.name} (work at risk)" if f.risks else f"{f.name} (no work for {_plural(f.project.idle_days, 'day')})"
    lead = ", ".join(tag(f) for f in act[:3]) + (f" and {n - 3} more" if n > 3 else "")
    return f"{_plural(n, 'project')} {'needs' if n == 1 else 'need'} you today: {lead} · {_day_stamp(today)}"


def compose_email(flagged, quiet, held, skipped, verdicts, cfg: Config, today: date, now: float, notices=()):
    """(subject, plain text, HTML). Both bodies come from the same cards in the same order.
    `notices` are heads-up lines about the reminder itself (see template_notices)."""
    e = html.escape
    act = actionable(flagged, verdicts)
    maybe_done = [f for f in flagged if verdict_for(f, verdicts).status == "probably_done"]
    not_proj = [f for f in flagged if verdict_for(f, verdicts).status == "not_a_project"]
    n = len(act)
    sections = [
        ("Projects that need you", "The most urgent one is first. Start with number 1, or pick another one."
         if n > 1 else "It has one small next step. You can start now.", "work", act),
        ("Maybe finished", "The assistant thinks these are finished. If it is right, you can switch off their "
                           "reminders.", "done", maybe_done),
        ("Maybe not a project", "The assistant thinks these folders are not something you are building.", "ignore",
         not_proj),
    ]
    if n:
        lead = f"**{_plural(n, 'project')}** {'needs' if n == 1 else 'need'} you today."
        tip = "Pick one below and do its next step. Each step takes about 15 minutes."
    else:
        lead = "**No project** needs work today."
        tip = ("Some quiet folders may be finished, or may not be projects at all. Tidy them up below and "
               "they will stop showing here.")
    helper = '"The assistant" in this email is an AI helper that looks inside your quiet project folders.'
    counts = [("Need you", n), ("Maybe finished", len(maybe_done)), ("Maybe not projects", len(not_proj)),
              ("Going fine", len(quiet))]

    other: list[tuple[str, str]] = []
    if quiet:
        other.append((f"Going fine (worked on in the last {_plural(cfg.cold_after_days, 'day')})",
                      ", ".join(f"{p.name} ({_ago(p.idle_days)})" for p in quiet)))
    if held:
        other.append(("Marked done or snoozed by you", ", ".join(f"{p.name} ({why})" for p, why in held)))
    other += _group_skipped(skipped)

    total = len(flagged)
    agent_n = sum(1 for f in flagged if verdict_for(f, verdicts).source == "agent")
    if not agent_n:
        checked = ("The assistant did not look inside any project this time. The text comes from a quick check "
                   "of file dates and git.")
    elif agent_n == total:
        checked = ("The assistant looked inside **" + ("the listed project" if total == 1
                                                          else f"all {total} listed projects") + "**.")
    else:
        rest = total - agent_n
        checked = (f"The assistant looked inside **{agent_n} of the {total} listed projects**. The other "
                   + ("one is" if rest == 1 else f"{rest} are") + ' marked "quick check".')
    snooze_example = (today + timedelta(days=14)).isoformat()
    how = [
        "This email is sent **once a day** from your laptop.",
        f"You see a project here when none of its files have changed for **{_plural(cfg.cold_after_days, 'day')}**,"
        f" or when it has changes that you have not committed or pushed for {_plural(cfg.at_risk_after_days, 'day')}.",
        "Words used here: **git** keeps the history of your project. To **commit** means to save a snapshot of "
        "your changes in git. To **push** means to copy those snapshots online (for example to GitHub), so they "
        "are backed up.",
        f"Your settings file is `{cfg.path}`. To stop reminders for a project for good, add its name to the "
        '**"done"** list. For a folder that is not a project, use the **"ignore"** list. To pause a project until '
        f'a date, add it to **"snooze"** like this: `"snooze": {{"project-name": "{snooze_example}"}}`.',
        checked,
    ]

    # ---- both bodies, part by part
    date_line = today.strftime("%A %d %B %Y")
    text = ["YOUR DAILY PROJECT CHECK-IN", date_line, "", "AT A GLANCE", f"  {_marks_text(lead)}", f"  {tip}",
            f"  {helper}"]
    text += [f"  - {label}: {count}" for label, count in counts] + [""]
    blocks = []
    if notices:
        text += ["HEADS-UP"] + [f"  ! {_marks_text(line)}" for line in notices] + [""]
        blocks.append('<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;'
                      'padding:12px 16px;margin:14px 0 0">' + _html_label("Heads-up", "#92400e")
                      + "".join(f'<div style="margin:4px 0 0">{_marks_html(line)}</div>' for line in notices)
                      + "</div>")
    for title, blurb, tone, items in sections:
        if not items:
            continue
        text += [RULE, title.upper(), blurb, RULE, ""]
        colour = TONE_STYLE[tone][2]
        blocks.append(f'<h2 style="font-size:18px;margin:28px 0 2px;color:{colour}">{e(title)}</h2>'
                      '<div style="color:#52525b;font-size:14px;margin:0 0 12px;padding:0 0 8px;'
                      f'border-bottom:2px solid {colour}">{e(blurb)}</div>')
        for i, f in enumerate(items, 1):
            card = _make_card(f, tone, verdicts, now)
            number = i if tone == "work" and len(items) > 1 else None
            text += _text_card(card, number)
            blocks.append(_html_card(card, number))
    if other:
        blurb = "Nothing to do here. This list shows your other folders, so you can see the whole picture."
        text += [RULE, "EVERYTHING ELSE", blurb, RULE] + [f"  - {label}: {value}" for label, value in other] + [""]
        rows = "".join(f'<li style="margin:0 0 6px"><b>{e(label)}:</b> {e(value)}</li>' for label, value in other)
        blocks.append('<h2 style="font-size:18px;margin:28px 0 2px;color:#3f3f46">Everything else</h2>'
                      '<div style="color:#52525b;font-size:14px;margin:0 0 12px;padding:0 0 8px;'
                      f'border-bottom:2px solid #d4d4d8">{e(blurb)}</div>'
                      '<ul style="margin:0;padding-left:20px;font-size:14px">' + rows + "</ul>")
    text += [RULE, "HOW THIS WORKS", RULE] + [f"  - {_marks_text(line)}" for line in how]

    cells = ""
    for i, (label, count) in enumerate(counts):
        colour = "#b45309" if i == 0 and count else "#18181b"
        cells += ('<td style="padding:8px 4px;text-align:center;vertical-align:top;width:25%">'
                  f'<div style="font-size:24px;font-weight:700;color:{colour}">{count}</div>'
                  f'<div style="font-size:12px;color:#52525b">{e(label)}</div></td>')
    if act:
        preheader = f"Start with {act[0].name}: {verdict_for(act[0], verdicts).next_step}"
    else:
        preheader = _marks_text(lead) + " " + tip
    how_rows = "".join(f'<li style="margin:0 0 5px">{_marks_html(line)}</li>' for line in how)
    body_html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>Project check-in</title></head>'
        '<body style="margin:0;padding:0;background:#f4f4f5">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent">{e(preheader)}</div>'
        f'<div style="max-width:640px;margin:0 auto;padding:24px 18px;background:#ffffff;font-family:{FONT};'
        'font-size:15px;line-height:1.5;color:#18181b;overflow-wrap:anywhere;word-break:break-word">'
        '<h1 style="font-size:23px;margin:0 0 2px">Your daily project check-in</h1>'
        f'<div style="color:#71717a;font-size:14px;margin:0 0 18px">{e(date_line)}</div>'
        '<div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px 16px">'
        + _html_label("At a glance", "#1d4ed8")
        + f'<div style="font-size:18px;margin:4px 0 2px">{_marks_html(lead)}</div>'
        f'<div style="color:#3f3f46;margin:0 0 2px">{e(tip)}</div>'
        f'<div style="color:#52525b;font-size:13px;margin:0 0 8px">{e(helper)}</div>'
        '<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;'
        f'background:#ffffff;border-radius:8px"><tr>{cells}</tr></table></div>'
        + "".join(blocks)
        + '<h2 style="font-size:15px;margin:28px 0 6px;color:#52525b">How this works</h2>'
        f'<ul style="margin:0;padding-left:20px;font-size:13px;color:#52525b">{how_rows}</ul>'
        "</div></body></html>"
    )
    return _subject(act, today), "\n".join(text), body_html


# --------------------------------------------------------------------------- delivery (once a day, retries)

def configured_channels(env: dict) -> dict:
    ch = {}
    if env.get("GMAIL_ADDRESS") and env.get("GMAIL_APP_PASSWORD"):
        ch["email"] = True
    wa_to = env.get("WA_TO") or env.get("WA_TARGET_NUMBER")
    if env.get("WA_ACCESS_TOKEN") and env.get("WA_PHONE_NUMBER_ID") and wa_to and env.get("WA_TEMPLATE_NAME"):
        ch["whatsapp"] = True
    return ch


def template_names(env: dict) -> list[str]:
    """WA_TEMPLATE_NAME may list several templates, best first ("new_look,old_look"). They all
    take the same four variables, so a template Meta has not approved yet is skipped and the
    next one carries the same message."""
    names = [n.strip() for n in (env.get("WA_TEMPLATE_NAME") or "").split(",")]
    return list(dict.fromkeys(n for n in names if n)) or ["project_checkin"]


def _gave_up(entry: dict | None) -> bool:
    return bool(entry) and entry.get("status") == "failed" and entry.get("hard_failures", 0) >= MAX_ATTEMPTS


def _finished(entry: dict | None) -> bool:
    return bool(entry) and (entry.get("status") in ("sent", "nothing") or _gave_up(entry))


def _record(day: dict, channel: str, ok: bool, now: datetime, detail: str, transient: bool, force: bool,
            status: str = "sent"):
    """Update the day's entry for a channel. A forced run never rewrites a finished
    entry (that would re-arm the automatic sends or erase a give-up); it's logged under
    "forced". `status` is what a success is recorded as ("sent", or "nothing" when there
    was nothing to send)."""
    entry = dict(day.get(channel) or {})
    stamp = now.isoformat(timespec="seconds")
    if force and _finished(entry):
        entry.setdefault("forced", []).append({"at": stamp, "status": status if ok else "failed",
                                               "ref" if ok else "error": detail})
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
    day[channel] = entry


@dataclass
class Deps:
    """Everything with side effects, swappable in tests."""
    discover: object = discover
    investigate: object = None          # (flagged, cfg, env, out) -> {name: Verdict}; None = graph default
    send_email: object = notify.send_email
    send_whatsapp: object = notify.send_whatsapp
    template_status: object = notify.template_status


def send_whatsapp_with_fallback(deps: Deps, env: dict, payload: dict, fallbacks=()):
    """Send with the payload's template. If Meta answers, for certain, that this template cannot
    be used (not approved yet, paused or disabled), try the next name with the same variables.
    A transient failure (5xx, 429, network) never moves on to the next name: Meta may already have
    accepted the first message, and the next scheduled run retries anyway. Any other error, or
    running out of names, is raised as usual, so the retry budget and the alert email behave
    exactly as they do with a single template.
    Returns (message id, template that worked, templates Meta refused before it)."""
    version = env.get("WA_GRAPH_VERSION") or notify.DEFAULT_GRAPH_VERSION
    names = list(dict.fromkeys([payload["template"]["name"], *fallbacks]))
    skipped = []
    for i, name in enumerate(names):
        attempt = {**payload, "template": {**payload["template"], "name": name}}
        try:
            ref = deps.send_whatsapp(env["WA_ACCESS_TOKEN"], env["WA_PHONE_NUMBER_ID"], attempt, version)
        except notify.DeliveryError as exc:
            if exc.transient or getattr(exc, "code", None) not in notify.TEMPLATE_UNAVAILABLE or i == len(names) - 1:
                raise
            log.info("WhatsApp template '%s' cannot be used yet (%s). Trying '%s'.", name, exc, names[i + 1])
            skipped.append(name)
            continue
        if i:
            log.info("WhatsApp reminder went out with template '%s'.", name)
        return ref, name, skipped
    raise notify.DeliveryError("No WhatsApp template name is configured.")


REVIEW_GRACE_DAYS = 2       # Meta: a review takes up to 24 hours. "Still in review" is not news before this.


def why_template_unusable(deps: Deps, env: dict, name: str) -> tuple[str, str]:
    """(kind, plain words) for a template Meta refused to send. "Not approved yet" and "the name or
    language is wrong" are the same error code, so ask Meta for the template's real status.
    Best effort: the reminder has already gone out with another template, so nothing here raises."""
    lang = env.get("WA_TEMPLATE_LANG") or "en"
    if not env.get("WA_BUSINESS_ACCOUNT_ID"):
        return "unknown", "Meta refused it (add WA_BUSINESS_ACCOUNT_ID to .env to find out why)"
    try:
        rows = deps.template_status(env["WA_ACCESS_TOKEN"], env["WA_BUSINESS_ACCOUNT_ID"], name,
                                    env.get("WA_GRAPH_VERSION") or notify.DEFAULT_GRAPH_VERSION)
        rows = [r for r in rows if isinstance(r, dict) and r.get("name") == name]   # Meta also returns longer names
    except Exception as exc:
        return "unknown", f"Meta refused it, and its status could not be read ({clean_line(exc, 120)})"
    if not rows:
        return "missing", "no template with that name exists in your WhatsApp account"
    row = next((r for r in rows if r.get("language") == lang), None)
    if row is None:
        have = ", ".join(sorted(str(r.get("language")) for r in rows))
        return "language", f"it exists in the language {have}, but WA_TEMPLATE_LANG in .env says {lang}"
    status = str(row.get("status") or "").upper()
    if status in ("PENDING", "IN_REVIEW"):
        return "reviewing", "Meta is still reviewing it"
    if status == "REJECTED":
        reason = row.get("rejected_reason")
        return "rejected", "Meta rejected it" + (f" (reason: {reason})" if reason not in (None, "", "NONE") else "")
    if status in ("PAUSED", "DISABLED"):
        return status.lower(), f"Meta has {status.lower()} it because people rated it poorly"
    if status == "APPROVED":
        return "mismatch", "Meta lists it as approved but still refused it, so check the name and language in .env"
    return "unknown", f"its status at Meta is {status or 'unknown'}"


def remember_template_problem(st: dict, deps: Deps, env: dict, today: date, skipped: list, used: str) -> None:
    """Keep (or clear) the note that the next email turns into a heads-up. Never raises."""
    try:
        if not skipped:
            st.pop("template_note", None)
            return
        kind, why = why_template_unusable(deps, env, skipped[0])
        prev = st.get("template_note") if isinstance(st.get("template_note"), dict) else {}
        since = prev.get("since") if prev.get("template") == skipped[0] and _ordinal(prev.get("since")) else None
        st["template_note"] = {"template": skipped[0], "used": used, "kind": kind, "why": why,
                               "since": since or today.isoformat(), "last": today.isoformat()}
        log.info("WhatsApp template '%s' was skipped: %s.", skipped[0], why)
    except Exception:
        log.exception("Could not record why the WhatsApp template was skipped")


def template_notices(st: dict, today: date) -> list[str]:
    """Heads-up lines for the email. A template that is simply still in review is not news until
    the review has clearly overrun; anything else needs the owner. The email is written before
    the day's WhatsApp goes out, so the line reports the last send, with its date."""
    note = st.get("template_note")
    if not isinstance(note, dict) or not note.get("template"):
        return []
    waited = today.toordinal() - (_ordinal(note.get("since")) or today.toordinal())
    if note.get("kind") == "reviewing" and waited < REVIEW_GRACE_DAYS:
        return []
    return [f'On {note.get("last") or note.get("since")}, the WhatsApp reminder went out in the older layout, '
            f'**"{note.get("used")}"**, because the newer one, **"{note["template"]}"**, could not be used: '
            f'{note.get("why")}. To check it, run `python -m reminder --whatsapp-template-status` in the '
            "second-brain folder."]


CHANNEL_NAMES = {"email": "Email", "whatsapp": "WhatsApp"}
FIX_HINTS = [   # (text found in the error, what usually fixes it, a command to run or ""); see the docs' table
    ("code 190", "The WhatsApp access token has expired or was removed. Create a new System User token in Meta "
                 "Business settings and save it as WA_ACCESS_TOKEN in the .env file.", ""),
    ("code 131030", "Your phone number is not on the test number's list of allowed numbers. Add it, and confirm "
                    "the code WhatsApp sends you, under WhatsApp > API Setup in the Meta developer dashboard.", ""),
    ("code 131042", "Meta needs a payment method on the WhatsApp Business account before it will send. Add one "
                    "in Meta Business settings.", ""),
    ("code 132001", "WhatsApp only sends this kind of reminder in a fixed layout, called a template, and Meta "
                    "(the company behind WhatsApp) must approve it first. Meta has no approved template with the "
                    "name and language in the .env file (WA_TEMPLATE_NAME and WA_TEMPLATE_LANG). Run the command "
                    "below in the second-brain folder. If it says PENDING, wait: approval can take up to 24 hours. "
                    "If the template is missing or REJECTED, fix it and submit it again with "
                    "--whatsapp-create-template.", "python -m reminder --whatsapp-template-status"),
    ("code 132015", "Meta has paused the WhatsApp template because people rated it poorly. Check its status with "
                    "the command below, then edit it in WhatsApp Manager or create a new one.",
     "python -m reminder --whatsapp-template-status"),
    ("code 132016", "Meta has switched the WhatsApp template off for good. Create a new template under a new name "
                    "and put that name first in WA_TEMPLATE_NAME.", "python -m reminder --whatsapp-create-template"),
]


def fix_hint(err: str) -> tuple[str, str]:
    """(what usually fixes it, a command to run or "") for an error message."""
    for needle, hint, command in FIX_HINTS:
        if needle in err:
            return hint, command
    return "Open the log file named below and read its last lines. They show the full error.", ""


def compose_alert(channel: str, entry: dict, log_path: str, today: date):
    """(subject, plain text, HTML) for the one email sent when a channel gives up for the day.
    Order: what happened, how to fix it (highlighted), then the technical details."""
    e = html.escape
    name = CHANNEL_NAMES.get(channel, channel)
    err = str(entry.get("error") or "(no error text was recorded)")
    hint, command = fix_hint(err)
    what = (f"Second Brain tried {_plural(int(entry.get('hard_failures') or 0), 'time')} today to send the {name} "
            "reminder, and every try failed, so it has stopped for today. Your daily email was sent as normal. "
            "It will try again tomorrow, but this kind of problem usually does not fix itself, so please follow "
            "the steps below.")
    title = f"The {name} reminder did not go out today"
    text = [title.upper(), "", "WHAT HAPPENED", f"  {what}", "", "HOW TO FIX IT", f"  {hint}"]
    if command:
        text += ["", f"      {command}"]
    text += ["", "TECHNICAL DETAILS (only needed if the steps above do not work)", f"  Error: {err}",
             f"  Log file: {log_path}"]
    code_html = ""
    if command:
        code_html = (f'<div style="font-family:{MONO};font-size:14px;background:#18181b;color:#fafafa;'
                     f'border-radius:6px;padding:8px 12px;margin:8px 0 0">{e(command)}</div>')
    body_html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        '<body style="margin:0;padding:0;background:#f4f4f5">'
        f'<div style="max-width:640px;margin:0 auto;padding:24px 18px;background:#ffffff;font-family:{FONT};'
        'font-size:15px;line-height:1.5;color:#18181b;overflow-wrap:anywhere;word-break:break-word">'
        f'<h1 style="font-size:21px;margin:0;color:#b42318">{e(title)}</h1>'
        f'<div style="margin:14px 0 0">{_html_label("What happened", "#3f3f46")}'
        f'<div style="margin:3px 0 0">{e(what)}</div></div>'
        '<div style="background:#fffbeb;border:1px solid #fde68a;border-left:5px solid #f59e0b;border-radius:6px;'
        f'padding:10px 14px;margin:16px 0 0">{_html_label("How to fix it", "#92400e")}'
        f'<div style="margin:3px 0 0">{e(hint)}</div>{code_html}</div>'
        f'<div style="margin:18px 0 0;color:#52525b;font-size:13px">'
        f'{_html_label("Technical details (only needed if the steps above do not work)", "#71717a")}'
        f'<div style="margin:3px 0 0"><b>Error:</b> <span style="font-family:{MONO}">{e(err)}</span></div>'
        f'<div style="margin:3px 0 0"><b>Log file:</b> <span style="font-family:{MONO}">{e(log_path)}</span></div>'
        "</div></div></body></html>")
    return f"Second Brain: the {name} reminder did not go out today · {_day_stamp(today)}", "\n".join(text), body_html


def deliver(base_dir: str, st: dict, day: dict, pending: list[str], now: datetime, env: dict, email_parts,
            wa_payload, featured_name: str | None, deps: Deps, force: bool, wa_fallbacks=()) -> int:
    """Send each pending channel once; record the outcome per channel as it happens.
    `wa_fallbacks` are template names to try when Meta cannot use the payload's template yet."""
    subject, text, body_html = email_parts
    failures = 0
    for c in pending:
        try:
            if c == "email":
                to = env.get("REMINDER_EMAIL_TO") or env["GMAIL_ADDRESS"]
                deps.send_email(env["GMAIL_ADDRESS"], env["GMAIL_APP_PASSWORD"],
                                notify.build_email(env["GMAIL_ADDRESS"], to, subject, text, body_html))
                _record(day, c, True, now, to, False, force)
            elif wa_payload is None:
                _record(day, c, True, now, "nothing actionable", False, force, status="nothing")
            else:
                ref, used, skipped = send_whatsapp_with_fallback(deps, env, wa_payload, wa_fallbacks)
                _record(day, c, True, now, ref, False, force)
                if featured_name:
                    st["featured"][featured_name] = now.date().isoformat()
                remember_template_problem(st, deps, env, now.date(), skipped, used)
            log.info("Sent %s reminder (%s).", c, day[c].get("ref"))
        except notify.DeliveryError as exc:
            failures += 1
            _record(day, c, False, now, str(exc), exc.transient, force)
            log.error("%s reminder failed (%s, hard failures %d/%d): %s", c,
                      "transient" if exc.transient else "hard", day[c].get("hard_failures", 0), MAX_ATTEMPTS, exc)
        except Exception as exc:  # a bug or an unmapped error must still count as an attempt
            failures += 1
            _record(day, c, False, now, f"{type(exc).__name__}: {exc}", False, force)
            log.exception("%s reminder crashed", c)
        if not save_state_quietly(base_dir, st):
            failures += 1

    # One alert email per channel that has given up for the day, once email itself works.
    if day.get("email", {}).get("status") == "sent":
        for c, entry in day.items():
            if c == "email" or not _gave_up(entry) or entry.get("alerted"):
                continue
            try:
                alert = notify.build_email(
                    env["GMAIL_ADDRESS"], env.get("REMINDER_EMAIL_TO") or env["GMAIL_ADDRESS"],
                    *compose_alert(c, entry, os.path.join(base_dir, ".state", "remind.log"), now.date()))
                deps.send_email(env["GMAIL_ADDRESS"], env["GMAIL_APP_PASSWORD"], alert)
                entry["alerted"] = True
                save_state_quietly(base_dir, st)
            except Exception as exc:
                log.error("Could not send the failure alert email: %s", exc)
    return 1 if failures else 0


def save_briefing(base_dir: str, now: datetime, flagged: list[Flagged], verdicts: dict,
                  featured: str | None, day: dict) -> bool:
    """What this reminder told the owner, for the WhatsApp adviser (adviser/) to talk about when
    they reply. Written only after a send; a failure here never affects the reminder."""
    wa = day.get("whatsapp") or {}
    data = {"sent_at": now.isoformat(timespec="seconds"), "featured": featured,
            "whatsapp_ref": wa.get("ref") if wa.get("status") == "sent" else None,
            "projects": []}
    for f in flagged:
        v = verdict_for(f, verdicts)
        data["projects"].append({"name": f.name, "status": v.status, "why": f.headline(),
                                 "left_off": v.left_off, "next_step": v.next_step, "evidence": v.evidence[:3]})
    path = os.path.join(base_dir, ".state", "briefing.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(path + ".tmp", path)
        return True
    except Exception:
        log.exception("Could not write %s (the adviser will not know today's reminder)", path)
        return False


def run(base_dir: str, now: datetime, env: dict, *, force=False, dry_run=False, only=None,
        use_llm=True, deps: Deps | None = None, out=print) -> int:
    """Entry point: guards, lock, then the LangGraph workflow (graph.py)."""
    deps = deps or Deps()
    cfg = load_config(base_dir)
    today = now.date()
    channels = [c for c in CHANNELS if configured_channels(env).get(c) and (not only or c in only)]
    if not channels and not dry_run:
        log.error("No delivery channel is configured. Fill the Gmail and/or WA_* values in .env.")
        return 1

    st = load_state(base_dir)
    day = st["days"].setdefault(today.isoformat(), {})
    if force or dry_run:
        pending = channels
    else:
        if now.hour < cfg.send_after_hour:
            log.debug("Before %02d:00, nothing to do.", cfg.send_after_hour)
            return 0
        pending = [c for c in channels if not _finished(day.get(c))]
        if not pending:
            return 0

    with Lock(base_dir) as lock:
        if lock is None:
            log.info("Another reminder run is in progress; skipping.")
            return 0
        from .graph import build_workflow
        workflow = build_workflow(base_dir, cfg, env, st, day, deps, out)
        result = workflow.invoke({"now": now, "pending": pending, "force": force, "dry_run": dry_run,
                                  "use_llm": use_llm})
        return int(result.get("exit_code", 0))


# --------------------------------------------------------------------------- CLI

def setup_logging(base_dir: str, verbose: bool) -> None:
    os.makedirs(os.path.join(base_dir, ".state"), exist_ok=True)
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.getLogger("reminder.scan").setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.handlers.RotatingFileHandler(os.path.join(base_dir, ".state", "remind.log"),
                                              maxBytes=512_000, backupCount=2, encoding="utf-8")
    fh.setFormatter(fmt)
    log.addHandler(fh)                           # "reminder.scan" propagates to this one
    if sys.stderr is not None:                   # pythonw.exe has no console
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)


def whatsapp_setup(env: dict, args, out) -> int:
    version = env.get("WA_GRAPH_VERSION") or notify.DEFAULT_GRAPH_VERSION
    names = template_names(env)
    name = names[0]                                  # the one to create; the others are what is live meanwhile
    lang = env.get("WA_TEMPLATE_LANG") or "en"
    need = {"WA_ACCESS_TOKEN": env.get("WA_ACCESS_TOKEN")}
    if args.whatsapp_hello:
        need.update(WA_PHONE_NUMBER_ID=env.get("WA_PHONE_NUMBER_ID"),
                    WA_TARGET_NUMBER=env.get("WA_TO") or env.get("WA_TARGET_NUMBER"))
    if args.whatsapp_create_template or args.whatsapp_template_status:
        need["WA_BUSINESS_ACCOUNT_ID"] = env.get("WA_BUSINESS_ACCOUNT_ID")
    missing = [k for k, v in need.items() if not v]
    if missing:
        out(f"Missing in .env: {', '.join(missing)}")
        return 2
    try:
        if args.whatsapp_hello:
            to = env.get("WA_TO") or env["WA_TARGET_NUMBER"]
            mid = notify.send_whatsapp(env["WA_ACCESS_TOKEN"], env["WA_PHONE_NUMBER_ID"],
                                       notify.build_hello_world(to), version)
            out(f"Meta accepted hello_world (id {mid}). Check WhatsApp on {to}.")
        if args.whatsapp_create_template:
            res = notify.create_template(env["WA_ACCESS_TOKEN"], env["WA_BUSINESS_ACCOUNT_ID"], name, lang, version)
            out(f"Submitted template '{name}' ({lang}): status {res.get('status')}, category {res.get('category')}. "
                "Approval can take up to 24 hours.")
            if res.get("category") not in (None, "UTILITY"):
                out(f"  Careful: Meta filed it as {res.get('category')}, not UTILITY. Marketing messages cost more, "
                    "and Meta limits how many a person gets, so a daily reminder may not arrive. Do not put this "
                    "name in WA_TEMPLATE_NAME. Reword the template as a plain status update and submit it under "
                    "a new name.")
        if args.whatsapp_template_status:
            approved = []
            for wanted in names:
                # Meta's name filter also returns longer names that contain it: keep exact matches only.
                rows = [r for r in notify.template_status(env["WA_ACCESS_TOKEN"], env["WA_BUSINESS_ACCOUNT_ID"],
                                                          wanted, version) if r.get("name") == wanted]
                if not rows:
                    out(f"No template named '{wanted}' found. Run --whatsapp-create-template first.")
                for r in rows:
                    out(f"{r.get('name')} ({r.get('language')}): {r.get('status')}, category {r.get('category')}"
                        + (f", rejected: {r['rejected_reason']}" if r.get("rejected_reason") not in (None, "NONE")
                           else ""))
                    if r.get("category") == "MARKETING":
                        out("  Meta filed it as MARKETING (pricier, and delivery can be limited). "
                            "You can request a category review in WhatsApp Manager.")
                    if r.get("status") == "APPROVED" and r.get("language") == lang:
                        approved.append(wanted)
            if len(names) > 1:
                out(f"Reminders will go out with: {approved[0] if approved else 'none of them yet'}"
                    f" (order tried: {', '.join(names)})")
    except notify.DeliveryError as exc:
        out(f"WhatsApp setup call failed: {exc}")
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reminder", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="scan, investigate and compose; print; send nothing")
    ap.add_argument("--force", action="store_true", help="send now, ignoring the hour and once-a-day guard")
    ap.add_argument("--channel", action="append", choices=CHANNELS, help="limit to one channel (repeatable)")
    ap.add_argument("--no-llm", action="store_true", help="skip the investigator agent; plain wording from the scan")
    ap.add_argument("--verbose", action="store_true")
    setup = ap.add_argument_group("one-time WhatsApp setup")
    setup.add_argument("--whatsapp-hello", action="store_true",
                       help="send Meta's hello_world test template to check token, number id and recipient")
    setup.add_argument("--whatsapp-create-template", action="store_true",
                       help="submit the reminder template to Meta for approval")
    setup.add_argument("--whatsapp-template-status", action="store_true", help="show the template's approval status")
    args = ap.parse_args(argv)
    setup_logging(BASE_DIR, args.verbose)
    printer = print if sys.stdout is not None else (lambda *a, **k: None)
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.whatsapp_hello or args.whatsapp_create_template or args.whatsapp_template_status:
        return whatsapp_setup(load_env(os.path.join(BASE_DIR, ".env")), args, printer)
    try:
        return run(BASE_DIR, datetime.now(), load_env(os.path.join(BASE_DIR, ".env")), force=args.force,
                   dry_run=args.dry_run, only=args.channel, use_llm=not args.no_llm, out=printer)
    except ConfigError as exc:
        log.error("%s", exc)
        return 2
    except Exception:
        log.exception("Reminder run crashed")
        return 3
