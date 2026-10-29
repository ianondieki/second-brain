"""The status-change email (ADR-004; REQUIREMENTS.md §5 "Status email"): the fixed layout for a tracker event without a
numbered EM template, here the side states and the system's events (REQ-ENG-10 part: N01, N03, N05, N17 expiry; N03
information requested and answered; N20 on hold and resumed).

Subject, one sentence (the in-app notice's, code-written), one link to the recipient's tracker, and the footer with the
engagement's ref. Mutable: the recipient's email preference for the notice's kind (``engagement.n03`` ...), checked by
the caller. Once per event and recipient (dedupe key ``status:<event>:<user>``). Fixed templates
(``templates/status.*.j2``, the HTML one the short branded frame of ``simple.html.j2``); the sentence and the title are
made unlinkable (``em1.unlinkable``), and the only link is the platform's. A note's text (a question, an answer, a
reason) is never in the email: the recipient reads it on the tracker. Nothing here is worded by an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, NamedTuple
from uuid import UUID

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from bridge.notifications.em1 import unlinkable

CTA: Final = "Open your tracker"  # [[COPY-REVIEW]]
_ENV: Final = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False, default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True, slots=True)
class StatusFacts:
    engagement_id: UUID
    label: str  # the stage the event entered ("Information requested", "On hold", "Expired", ...)
    title: str  # the proposal's title
    sentence: str  # what happened, from the recipient's side (the in-app notice's body)
    path: str  # the recipient's tracker (a platform path)
    base_url: str
    product: str


class Rendered(NamedTuple):
    subject: str
    text: str
    html: str


def dedupe_key(event_id: UUID, user_id: UUID) -> str:
    return f"status:{event_id}:{user_id}"


def render(facts: StatusFacts) -> Rendered:
    if not facts.path.startswith("/") or facts.path.startswith("//"):
        raise ValueError("a status email links to a platform path")
    base = facts.base_url.rstrip("/")
    subject = f'{unlinkable(facts.label)}: "{unlinkable(facts.title)}"'
    values = {
        "subject": subject,
        "sentence": unlinkable(facts.sentence),
        "paragraphs": [unlinkable(facts.sentence)],
        "button_label": CTA,
        "button_url": base + facts.path,
        "settings_url": f"{base}/settings/notifications",
        "help_url": f"{base}/help",
        "engagement_ref": str(facts.engagement_id),
        "product": unlinkable(facts.product),
    }
    return Rendered(
        subject, _ENV.get_template("status.txt.j2").render(values), _ENV.get_template("status.html.j2").render(values)
    )
