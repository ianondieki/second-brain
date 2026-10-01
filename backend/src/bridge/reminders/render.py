"""What both EM7 versions share (REQ-REM-01, REQ-REM-02; docs/spec/06 6.10 templates, 6.11; AC-MAIL-5).

Fixed layouts with code-filled values only: a text part built here line by line and an HTML part from
``templates/em7.html.j2`` (Jinja2, autoescape on), both from the same ``Email`` model, so they say the same thing.
Free text written by a party (proposal titles, milestone deliverables, names) goes through ``quote`` or ``plain``:
one line, NFKC, no markup tags, control or invisible characters, and defanged (``defang``): links, email addresses
and phone numbers are replaced by a placeholder and bare domains lose their dots ("example[.]com"), so no mail client
can turn them into a link or a call. Every link is a platform URL (``platform_url``). Dates are Nairobi dates
("5 Oct 2026"). Copy is ``[[COPY-REVIEW]]``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Final

from jinja2 import ChoiceLoader, Environment, PackageLoader, StrictUndefined, select_autoescape

from bridge.models.enums import EngagementParty, EngagementState, MilestoneState
from bridge.notifications.brand import PRODUCT_DEFAULT
from bridge.proposals.sanitise import PHONES
from bridge.reminders.health import EngagementFact, Health, Reason, ReasonCode

S, M = EngagementState, MilestoneState
DEV, ORG = EngagementParty.DEVELOPER, EngagementParty.ORG
SETTINGS_PATH: Final = "/settings/notifications"
HELP_PATH: Final = "/help"
PLACE: Final = "Nairobi, Kenya"
MAX_QUOTE_CHARS: Final = 120

# [[COPY-REVIEW]] stage labels (docs/spec/06 6.9 "Label" column, shortened for one line).
STAGE_LABELS: Final[dict[EngagementState, str]] = {
    S.ORG_INTEREST: "Organisation interested",
    S.SUBMITTED: "Proposal submitted",
    S.UNDER_REVIEW: "Under review",
    S.INTEREST_CONFIRMED: "Approved to proceed (non-binding)",
    S.PROCUREMENT_ROUTE: "Procurement route",
    S.CONTACT_MADE: "First contact",
    S.NDA_PENDING: "Mutual NDA: awaiting signatures",
    S.NDA_SIGNED: "Mutual NDA signed",
    S.NEGOTIATION: "Terms and agreement drafting",
    S.AGREEMENT_SIGNING: "Agreement signing",
    S.IN_IMPLEMENTATION: "Implementation",
    S.DELIVERED: "Final delivery submitted",
    S.SIGN_OFF: "Acceptance sign-off",
    S.PAYMENT_FINAL: "Final payment",
    S.CLOSED: "Closed",
    S.DECLINED: "Declined",
    S.WITHDRAWN: "Withdrawn",
    S.EXPIRED: "Expired",
    S.ON_HOLD: "On hold",
    S.DISPUTED: "Disputed",
    S.TERMINATED: "Terminated",
    S.INFO_REQUESTED: "Information requested",
}

_URL = re.compile(r"\b[a-z][a-z0-9+.-]{1,15}://\S*|\bwww\d{0,3}\.\S*|\b(?:mailto|tel|sms|callto|whatsapp):\S*", re.I)
_EMAIL = re.compile(r"[a-z0-9._%+-]+\s*@\s*[a-z0-9-]+(?:\.[a-z0-9-]+)+", re.I)
_DOMAIN = re.compile(r"(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?![\w-])", re.I)
_SPACE = re.compile(r"\s+")
_TAG = re.compile(r"</?[a-z!][^<>]*>", re.I)
_ENV: Final = Environment(
    # The branded frame (_brand.html.j2, _macros.html.j2) lives with the notification templates.
    loader=ChoiceLoader(
        [PackageLoader("bridge.reminders", "templates"), PackageLoader("bridge.notifications", "templates")]
    ),
    autoescape=select_autoescape(("html", "j2")),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def plain(text: str) -> str:
    """One line of plain text: NFKC, markup tags, control and invisible characters dropped, whitespace collapsed."""
    text = _TAG.sub(" ", unicodedata.normalize("NFKC", text))
    kept = "".join(" " if ch.isspace() else ch for ch in text if unicodedata.category(ch)[0] != "C" or ch.isspace())
    return _SPACE.sub(" ", kept).strip()


def defang(text: str) -> str:
    """``text`` with no auto-linkable contact route (AC-MAIL-5). [[COPY-REVIEW]] placeholders."""
    text = _URL.sub("[link removed]", plain(text))
    text = _EMAIL.sub("[email removed]", text)
    for pattern in PHONES:  # the Tier-1 sanitiser's phone patterns (mobiles, landlines, E.164)
        text = pattern.sub("[phone number removed]", text)
    text = _DOMAIN.sub(lambda m: m.group(0).replace(".", "[.]"), text)
    return text.replace("@", "[at]")


def quote(text: str | None, *, fallback: str = "Untitled") -> str:
    """A party's text, quoted, defanged and cut to ``MAX_QUOTE_CHARS``."""
    value = defang(text or "") or fallback
    if len(value) > MAX_QUOTE_CHARS:
        value = value[: MAX_QUOTE_CHARS - 1].rstrip() + "…"
    return f"“{value}”"


def name(text: str | None, *, fallback: str) -> str:
    """A person's or organisation's name, defanged, unquoted."""
    return defang(text or "")[:MAX_QUOTE_CHARS] or fallback


def eat_date(value: date) -> str:
    """A Nairobi calendar date as "5 Oct 2026"."""
    return f"{value.day} {value:%b %Y}"


def plural(n: int, word: str, words: str | None = None) -> str:
    return f"{n} {word if n == 1 else (words or word + 's')}"


def platform_url(base_url: str, path: str) -> str:
    if not path.startswith("/") or path.startswith("//"):
        raise ValueError("a link in a digest is a platform path")
    return base_url.rstrip("/") + path


@dataclass(frozen=True, slots=True)
class Section:
    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Email:
    """One EM7, worded. ``notes`` are small print under the headline (the "AI-drafted" label)."""

    subject: str
    headline: str
    sections: tuple[Section, ...]
    next_step: str | None
    cta_label: str
    cta_path: str
    footer: str
    notes: tuple[str, ...] = field(default=())


def render_text(email: Email, base_url: str) -> str:
    lines = [email.headline, *email.notes, ""]
    for section in email.sections:
        lines += [section.title.upper(), *(f"- {line}" for line in section.lines), ""]
    if email.next_step:
        lines += ["NEXT STEP", email.next_step, ""]
    lines += [f"{email.cta_label}: {platform_url(base_url, email.cta_path)}", "", "--", email.footer]
    lines.append(
        f"Manage notifications: {platform_url(base_url, SETTINGS_PATH)} · Help: {platform_url(base_url, HELP_PATH)}"
        f" · {PLACE}"
    )
    return "\n".join(lines) + "\n"


def render_html(email: Email, base_url: str, product: str = PRODUCT_DEFAULT) -> str:
    return _ENV.get_template("em7.html.j2").render(
        email=email,
        product=product,
        cta_url=platform_url(base_url, email.cta_path),
        settings_url=platform_url(base_url, SETTINGS_PATH),
        help_url=platform_url(base_url, HELP_PATH),
        place=PLACE,
    )


def sections(*pairs: tuple[str, Sequence[str]]) -> tuple[Section, ...]:
    """The non-empty sections, in order."""
    return tuple(Section(title, tuple(lines)) for title, lines in pairs if lines)


# [[COPY-REVIEW]] what each party does to move a stage on (docs/spec/06 6.9 "Next actor"), neutral so both
# versions can use it ("Waiting for Wanjiru to sign the mutual NDA", "Needs you: sign the mutual NDA").
DEVELOPER_ACTIONS: Final[dict[EngagementState, str]] = {
    S.ORG_INTEREST: "accept or decline the interest",
    S.CONTACT_MADE: "confirm first contact",
    S.NDA_PENDING: "sign the mutual NDA",
    S.NDA_SIGNED: "propose terms",
    S.NEGOTIATION: "respond to the latest terms",
    S.AGREEMENT_SIGNING: "sign the agreement",
    S.IN_IMPLEMENTATION: "work on the milestones",
    S.SIGN_OFF: "countersign the acceptance certificate",
    S.PAYMENT_FINAL: "confirm the payment received",
    S.INFO_REQUESTED: "answer the questions asked",
}
ORGANISATION_ACTIONS: Final[dict[EngagementState, str]] = {
    S.SUBMITTED: "start the review",
    S.UNDER_REVIEW: "decide on the proposal",
    S.INTEREST_CONFIRMED: "make first contact",
    S.PROCUREMENT_ROUTE: "choose the procurement route",
    S.CONTACT_MADE: "send the mutual NDA",
    S.NDA_PENDING: "sign the mutual NDA",
    S.NDA_SIGNED: "propose terms",
    S.NEGOTIATION: "respond to the latest terms",
    S.AGREEMENT_SIGNING: "sign the agreement",
    S.IN_IMPLEMENTATION: "review the submitted milestone",
    S.DELIVERED: "review the final delivery",
    S.SIGN_OFF: "sign the acceptance certificate",
    S.PAYMENT_FINAL: "record the final payment",
}
HEALTH_LABELS: Final[dict[Health, str]] = {
    Health.ON_TRACK: "On track",
    Health.AT_RISK: "At risk",
    Health.OFF_TRACK: "Off track",
}


def developer_action(e: EngagementFact) -> str:
    if e.state is S.CONTACT_MADE and ORG in e.awaiting:
        return "send the mutual NDA"  # first contact is confirmed: either party sends it
    if e.state is S.IN_IMPLEMENTATION and e.milestones and all(m.state is M.ACCEPTED for m in e.milestones):
        return "submit the final delivery"
    return DEVELOPER_ACTIONS.get(e.state, "take the next step")


def organisation_action(e: EngagementFact) -> str:
    return ORGANISATION_ACTIONS.get(e.state, "take the next step")


def milestone_label(e: EngagementFact, seq: int | None) -> str:
    found = next((m for m in e.milestones if m.seq == seq), None)
    return f"Milestone {seq} {quote(found.deliverable)}" if found else f"Milestone {seq}"


def reason_text(r: Reason, e: EngagementFact, *, viewer: EngagementParty) -> str:
    """One code-computed reason as a sentence (no full stop), from ``viewer``'s side."""
    due = eat_date(r.due_on) if r.due_on else ""
    late = f"was due {due} and is {plural(r.days, 'day')} overdue"
    if viewer is DEV:
        whose = "Your" if r.party is DEV else f"{name(e.org_name, fallback='The organisation')}'s"
    else:
        whose = "Your organisation's" if r.party is ORG else f"{name(e.developer_name, fallback='The developer')}'s"
    stage = STAGE_LABELS.get(e.state, e.state.value)
    code = r.code
    if code is ReasonCode.MILESTONE_DUE_SOON:
        when = f"today, {due}," if r.days == 0 else f"{due} ({plural(r.days, 'business day')} left)"
        return f"{milestone_label(e, r.milestone_seq)} is due {when} and not submitted yet"
    if code is ReasonCode.MILESTONE_OVERDUE:
        return f"{milestone_label(e, r.milestone_seq)} {late}"
    if code is ReasonCode.REVIEW_DUE_SOON:
        return f"The review of milestone {r.milestone_seq} is due {due}"
    if code is ReasonCode.REVIEW_OVERDUE:
        return f"The review of milestone {r.milestone_seq} {late}"
    if code is ReasonCode.STAGE_DUE_SOON:
        return f"{whose} step ({stage}) is due {due}"
    if code is ReasonCode.STAGE_OVERDUE:
        return f"{whose} step ({stage}) {late}"
    if code is ReasonCode.REWORK_LOOP:
        return f"Milestone {r.milestone_seq} has been sent back for changes {r.days} times"
    return f"No repository activity for {plural(r.days, 'business day')}"
