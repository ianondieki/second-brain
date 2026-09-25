# ported from reminder/remind.py: compose_email (with Card, _make_card, _group_skipped, _text_card, _subject,
#   _day_stamp, _ago, _some, _risk_line, _marks_text, _marks_html, TONE_STYLE, RISK_MEANING, QUICK_NOTE, RULE, FONT,
#   MONO), template_notices (with REVIEW_GRACE_DAYS, _ordinal); the HTML of _html_card, _html_label and the email
#   body is templates/reminder_email.html.j2
"""The daily reminder email, worded once and rendered twice (plain text and HTML), ported from the companion.

Reading order, the same in both parts: at a glance -> heads-up (rare) -> projects that need you -> maybe finished
-> maybe not a project -> everything else -> how this works. Fixed wording may use **bold** and `code` marks.

The plain-text part and the subject are byte-for-byte what `reminder/remind.py` produces for the same inputs. The
HTML part is rendered by a Jinja2 template with autoescape on; it matches the companion's HTML byte for byte except
for the spelling of two escaped characters: markupsafe writes `&#34;` and `&#39;` where `html.escape` wrote
`&quot;` and `&#x27;` (the same characters once decoded). Escaping still happens before our own **bold**/`code`
marks become tags, so text from a project or an agent can never inject markup.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Final, NamedTuple

from jinja2 import Environment, PackageLoader, StrictUndefined
from jinja2.ext import Extension
from markupsafe import Markup, escape

from bridge.reminders.policy import (
    DAY,
    RISK_UNCOMMITTED,
    RISK_UNPUSHED,
    Flagged,
    Project,
    ReminderConfig,
    Verdict,
    _plural,
    actionable,
    verdict_for,
)

FONT: Final = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO: Final = "Consolas,'Courier New',monospace"
RULE: Final = "=" * 62
TONE_STYLE: Final = {  # tone -> (card border, card background, section colour)
    "work": ("#d4d4d8", "#ffffff", "#1d4ed8"),
    "done": ("#a6f4c5", "#f6fef9", "#027a48"),
    "ignore": ("#fedf89", "#fffcf5", "#b54708"),
}
RISK_MEANING: Final = (  # what each kind of work at risk means, in plain words
    (RISK_UNCOMMITTED, "This work is not saved in git yet."),
    (RISK_UNPUSHED, "This work is only on this laptop, not backed up online."),
)
QUICK_NOTE: Final = "Quick check only: the assistant did not look inside this project."
REVIEW_GRACE_DAYS: Final = 2  # Meta: a review takes up to 24 hours. "Still in review" is not news before this.
TEMPLATE: Final = "reminder_email.html.j2"

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`(.+?)`")
_CODE_TAG = (
    r'<code style="font-family:' + MONO + r';font-size:13px;background:#f4f4f5;border-radius:4px;padding:1px 4px">'
    r"\1</code>"
)
_LINE_BREAK = re.compile(r"[ \t]*\r?\n[ \t]*")


class EmailParts(NamedTuple):
    subject: str
    text: str
    html: str


@dataclass
class Card:
    """One project in the email, already worded. Rendered as plain text and as HTML."""

    name: str
    title: str
    tone: str  # work | done | ignore
    cold: bool  # gone quiet: then the first fact is the one to highlight
    facts: list[str]
    warnings: list[str]  # work at risk, each with its plain meaning
    left_label: str
    left_off: str
    quick: bool = False  # the wording comes from the scan, not from the assistant
    next_step: str = ""  # tone "work" only
    hint: str = ""  # tone done/ignore: what the assistant thinks
    action: str = ""  # tone done/ignore: what the owner can do about it
    details: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class _Section:
    title: str
    blurb: str
    colour: str
    cards: list[tuple[Card, int | None]]


class _JoinLines(Extension):
    """Drop every line break and the indentation after it when a template is loaded, so the readable template
    renders the one-line HTML the companion produced. Spaces that matter stay inside a line."""

    def preprocess(self, source: str, name: str | None, filename: str | None = None) -> str:
        return _LINE_BREAK.sub("", source)


def marks_html(s: str) -> Markup:
    """Escape first, then turn our own **bold** and `code` marks into tags (ported `_marks_html`)."""
    tagged = _CODE.sub(_CODE_TAG, _BOLD.sub(r"<b>\1</b>", str(escape(s))))
    return Markup(tagged)  # noqa: S704 - the text was escaped above; only our own <b>/<code> tags were added


_ENV: Final = Environment(
    loader=PackageLoader("bridge.reminders", "templates"),
    autoescape=True,
    undefined=StrictUndefined,
    extensions=[_JoinLines],
)
_ENV.filters["marks_html"] = marks_html
_ENV.globals.update(
    FONT=Markup(FONT),  # noqa: S704 - a fixed CSS font stack defined above, never user input
    MONO=Markup(MONO),  # noqa: S704 - likewise
    QUICK_NOTE=QUICK_NOTE,
    TONE_STYLE=TONE_STYLE,
)


def _ago(days: int) -> str:
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def _some(names: list[str], limit: int = 3) -> str:
    shown = ", ".join(names[:limit])
    return shown if len(names) <= limit else f"{shown} and {len(names) - limit} more"


def _risk_line(risk: str) -> str:
    return next((f"{risk}. {meaning}" for marker, meaning in RISK_MEANING if marker in risk), risk)


def _marks_text(s: str) -> str:
    return s.replace("**", "").replace("`", "")


def _make_card(f: Flagged, tone: str, verdicts: Mapping[str, Verdict], now: float) -> Card:
    p, g, v = f.project, f.project.git, verdict_for(f, verdicts)
    facts = [
        "Worked on today"
        if p.idle_days <= 0
        else "Last worked on yesterday"
        if p.idle_days == 1
        else f"No work for {p.idle_days} days"
    ]
    if p.open_todos:
        facts.append(_plural(p.open_todos, "open to-do item"))
    if g and g.last_commit:
        facts.append(f"Last commit {_ago(int((now - g.last_commit) // DAY))}")
    if not g:
        facts.append("Not in git")
    card = Card(
        name=p.name,
        title=p.readme_title,
        tone=tone,
        cold=f.cold,
        facts=facts,
        warnings=[_risk_line(r) for r in f.risks],
        left_label="Where you left off",
        left_off=v.left_off,
        quick=v.source != "agent",
    )
    if tone in ("done", "ignore"):
        what, where, result = (
            ("**finished**", "done", "You will not be reminded about it again.")
            if tone == "done"
            else ("**not a real project**", "ignore", "The reminder will stop checking this folder.")
        )
        card.left_label = "What the assistant found"
        card.hint = f"The assistant looked inside and thinks this is {what} ({v.confidence:.0%} sure)."
        card.action = (
            f"If you agree, open **reminders.json** (its full path is at the end of this email) and add "
            f'**"{p.name}"** to the **"{where}"** list, like this: `"{where}": ["{p.name}"]`. {result} '
            "If you do not agree, you do not need to do anything."
        )
    else:
        card.next_step = v.next_step
    if v.evidence:
        card.details.append(("Clues the assistant checked", list(v.evidence)))
    if g and g.recent_commits:
        card.details.append(("Recent commits", list(g.recent_commits)))
    if g and g.modified:
        card.details.append(
            ("Changed files not committed", [", ".join(g.modified[:8]) + (" …" if len(g.modified) > 8 else "")])
        )
    if p.recent_files:
        card.details.append(("Recently edited files", [", ".join(p.recent_files[:5])]))
    if p.todo_samples:
        card.details.append(("Open to-do items", list(p.todo_samples)))
    card.details.append(("Folder", [p.path]))
    return card


def _group_skipped(skipped: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    """Folders the scan left out, grouped by reason so eight backup copies read as one line."""
    ignored: list[str] = []
    hidden: list[str] = []
    copies: dict[str, list[str]] = {}
    other: list[str] = []
    for name, why in skipped:
        if why == "ignored":
            (hidden if name.startswith(".") else ignored).append(name)
        elif why.startswith("copy of "):
            copies.setdefault(why[len("copy of ") :], []).append(name)
        else:
            other.append(f"{name} ({why})")
    rows: list[tuple[str, str]] = []
    if ignored:
        rows.append(("Skipped (on your ignore list)", _some(ignored)))
    if hidden:
        rows.append(("Skipped (hidden folders)", _some(hidden)))
    for original, names in copies.items():
        noun = "copy" if len(names) == 1 else "copies"
        rows.append((f"Skipped ({len(names)} backup {noun} of {original})", _some(names)))
    if other:
        rows.append(("Skipped (could not be read)", _some(other)))
    return rows


def _text_card(c: Card, number: int | None) -> list[str]:
    out = [
        (f"{number}. " if number else "- ") + c.name + (f"  ({c.title})" if c.title else ""),
        "   " + "  |  ".join(c.facts),
    ]
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


def _day_stamp(today: date) -> str:
    """ "Mon 21 Sep". In every subject, so each day's email is its own conversation in Gmail."""
    return today.strftime("%a %d %b")


def _subject(act: list[Flagged], today: date) -> str:
    n = len(act)
    if not n:
        return f"Project check-in: no project needs work today · {_day_stamp(today)}"

    def tag(f: Flagged) -> str:
        if f.risks:
            return f"{f.name} (work at risk)"
        return f"{f.name} (no work for {_plural(f.project.idle_days, 'day')})"

    lead = ", ".join(tag(f) for f in act[:3]) + (f" and {n - 3} more" if n > 3 else "")
    return f"{_plural(n, 'project')} {'needs' if n == 1 else 'need'} you today: {lead} · {_day_stamp(today)}"


def compose_email(
    flagged: Sequence[Flagged],
    quiet: Sequence[Project],
    held: Sequence[tuple[Project, str]],
    skipped: Sequence[tuple[str, str]],
    verdicts: Mapping[str, Verdict],
    cfg: ReminderConfig,
    today: date,
    now: float,
    notices: Sequence[str] = (),
) -> EmailParts:
    """(subject, plain text, HTML). Both bodies come from the same cards in the same order.
    `notices` are heads-up lines about the reminder itself (see template_notices)."""
    act = actionable(flagged, verdicts)
    maybe_done = [f for f in flagged if verdict_for(f, verdicts).status == "probably_done"]
    not_proj = [f for f in flagged if verdict_for(f, verdicts).status == "not_a_project"]
    n = len(act)
    sections = [
        (
            "Projects that need you",
            "The most urgent one is first. Start with number 1, or pick another one."
            if n > 1
            else "It has one small next step. You can start now.",
            "work",
            act,
        ),
        (
            "Maybe finished",
            "The assistant thinks these are finished. If it is right, you can switch off their reminders.",
            "done",
            maybe_done,
        ),
        (
            "Maybe not a project",
            "The assistant thinks these folders are not something you are building.",
            "ignore",
            not_proj,
        ),
    ]
    if n:
        lead = f"**{_plural(n, 'project')}** {'needs' if n == 1 else 'need'} you today."
        tip = "Pick one below and do its next step. Each step takes about 15 minutes."
    else:
        lead = "**No project** needs work today."
        tip = (
            "Some quiet folders may be finished, or may not be projects at all. Tidy them up below and "
            "they will stop showing here."
        )
    helper = '"The assistant" in this email is an AI helper that looks inside your quiet project folders.'
    counts = [
        ("Need you", n),
        ("Maybe finished", len(maybe_done)),
        ("Maybe not projects", len(not_proj)),
        ("Going fine", len(quiet)),
    ]

    other: list[tuple[str, str]] = []
    if quiet:
        other.append(
            (
                f"Going fine (worked on in the last {_plural(cfg.cold_after_days, 'day')})",
                ", ".join(f"{p.name} ({_ago(p.idle_days)})" for p in quiet),
            )
        )
    if held:
        other.append(("Marked done or snoozed by you", ", ".join(f"{p.name} ({why})" for p, why in held)))
    other += _group_skipped(skipped)

    total = len(flagged)
    agent_n = sum(1 for f in flagged if verdict_for(f, verdicts).source == "agent")
    if not agent_n:
        checked = (
            "The assistant did not look inside any project this time. The text comes from a quick check "
            "of file dates and git."
        )
    elif agent_n == total:
        checked = (
            "The assistant looked inside **"
            + ("the listed project" if total == 1 else f"all {total} listed projects")
            + "**."
        )
    else:
        rest = total - agent_n
        checked = (
            f"The assistant looked inside **{agent_n} of the {total} listed projects**. The other "
            + ("one is" if rest == 1 else f"{rest} are")
            + ' marked "quick check".'
        )
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

    # ---- plain text, part by part; the HTML part gets the same pieces in the same order
    date_line = today.strftime("%A %d %B %Y")
    text = [
        "YOUR DAILY PROJECT CHECK-IN",
        date_line,
        "",
        "AT A GLANCE",
        f"  {_marks_text(lead)}",
        f"  {tip}",
        f"  {helper}",
    ]
    text += [f"  - {label}: {count}" for label, count in counts] + [""]
    if notices:
        text += ["HEADS-UP"] + [f"  ! {_marks_text(line)}" for line in notices] + [""]
    rendered: list[_Section] = []
    for title, blurb, tone, items in sections:
        if not items:
            continue
        text += [RULE, title.upper(), blurb, RULE, ""]
        section = _Section(title, blurb, TONE_STYLE[tone][2], [])
        for i, f in enumerate(items, 1):
            card = _make_card(f, tone, verdicts, now)
            number = i if tone == "work" and len(items) > 1 else None
            text += _text_card(card, number)
            section.cards.append((card, number))
        rendered.append(section)
    other_blurb = "Nothing to do here. This list shows your other folders, so you can see the whole picture."
    if other:
        text += [RULE, "EVERYTHING ELSE", other_blurb, RULE] + [f"  - {label}: {value}" for label, value in other]
        text += [""]
    text += [RULE, "HOW THIS WORKS", RULE] + [f"  - {_marks_text(line)}" for line in how]

    if act:
        preheader = f"Start with {act[0].name}: {verdict_for(act[0], verdicts).next_step}"
    else:
        preheader = _marks_text(lead) + " " + tip
    body_html = _ENV.get_template(TEMPLATE).render(
        preheader=preheader,
        date_line=date_line,
        lead=lead,
        tip=tip,
        helper=helper,
        counts=counts,
        notices=list(notices),
        sections=rendered,
        other=other,
        other_blurb=other_blurb,
        how=how,
    )
    return EmailParts(_subject(act, today), "\n".join(text), body_html)


# --------------------------------------------------------------------------- heads-up about the WhatsApp template


def _ordinal(d: object) -> int:
    try:
        return date.fromisoformat(str(d)).toordinal()
    except ValueError:
        return 0


def template_notices(state: Mapping[str, Any], today: date) -> list[str]:
    """Heads-up lines for the email. A template that is simply still in review is not news until the review has
    clearly overrun; anything else needs the owner. The email is written before the day's WhatsApp goes out, so the
    line reports the last send, with its date."""
    note = state.get("template_note")
    if not isinstance(note, dict) or not note.get("template"):
        return []
    waited = today.toordinal() - (_ordinal(note.get("since")) or today.toordinal())
    if note.get("kind") == "reviewing" and waited < REVIEW_GRACE_DAYS:
        return []
    return [
        f"On {note.get('last') or note.get('since')}, the WhatsApp reminder went out in the older layout, "
        f'**"{note.get("used")}"**, because the newer one, **"{note["template"]}"**, could not be used: '
        f"{note.get('why')}. To check it, run `python -m reminder --whatsapp-template-status` in the "
        "second-brain folder."
    ]
