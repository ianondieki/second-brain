"""EM2, the approval email (REQ-NOT-04; docs/spec/06 6.10; AC-MAIL-1).

Sent to the developer once per engagement when it enters ``INTEREST_CONFIRMED`` (dedupe key ``em2:<engagement>``,
``bridge.engagements.notify``). The copy is the spec's, verbatim, in ``templates/em2*.j2`` (plain text and HTML, one
CTA, the engagement ref in the footer); the copy-lint checks that every "approve" there carries its non-binding
qualifier. Values are plain data rendered by Jinja2 (autoescape on for HTML); nothing here is worded by an LLM.

``tier2_status`` is computed, never assumed (AC-MAIL-1): the number of named, verified people at the organisation who
opened the full proposal under NDA (``document_views``), else whether a Tier-2 grant is live (``disclosure_grants``),
else "not shared yet".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from uuid import UUID

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from bridge.engagements.calendar import NAIROBI
from bridge.models.enums import ContactChannel

KIND: Final = "em2"
CHANNEL_LABELS: Final = {
    ContactChannel.EMAIL: "email",
    ContactChannel.PHONE: "phone",
    ContactChannel.WHATSAPP: "WhatsApp",
    ContactChannel.VIDEO_CALL: "video call",
    ContactChannel.IN_PERSON: "in person",
}
ROLE_LABELS: Final = {  # docs/spec/03 organisation roles. [[COPY-REVIEW]]
    "owner": "Owner",
    "admin": "Admin",
    "reviewer": "Reviewer",
    "signatory": "Signatory",
    "finance": "Finance",
    "viewer": "Member",
}
_SPACES = re.compile(r"\s+")
_ENV = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False, default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def one_line(value: str) -> str:
    """Collapse whitespace (names and titles never break a subject or a line)."""
    return _SPACES.sub(" ", value).strip()


def dedupe_key(engagement_id: UUID) -> str:
    return f"{KIND}:{engagement_id}"


def tier2_status(company: str, viewers: int, *, shared: bool) -> str:
    """The spec's two sentences, plus the case in between: shared under NDA but not opened yet ([[COPY-REVIEW]])."""
    if viewers > 0:
        people, have = ("person", "has") if viewers == 1 else ("people", "have")
        return (
            f"{viewers} named, verified {people} at {company} {have} viewed your full proposal under NDA (see Who has"
            " seen this)."
        )
    if shared:
        return f"Your full proposal is shared with {company} under NDA; nobody there has opened it yet."
    return "Your full proposal has not been shared yet."


def eat_date(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


def eat_time(value: datetime) -> str:
    """``23 Sep 2026, 14:05 EAT`` (docs/spec/06 6.9 Rendering)."""
    local = value.astimezone(NAIROBI)
    return f"{local.day} {local:%b %Y, %H:%M} EAT"


@dataclass(frozen=True, slots=True)
class Em2Facts:
    engagement_id: UUID
    company_name: str
    title: str
    contact_person_name: str
    contact_person_role: str
    contact_channel: ContactChannel
    contact_by: date
    receipt_id: str
    registered_at: datetime
    viewers: int
    shared: bool
    public_entity: bool
    base_url: str


@dataclass(frozen=True, slots=True)
class Rendered:
    subject: str
    text: str
    html: str


def render(facts: Em2Facts) -> Rendered:
    company = one_line(facts.company_name)
    base = facts.base_url.rstrip("/")
    values = {
        "company_name": company,
        "title": one_line(facts.title),
        "contact_person_name": one_line(facts.contact_person_name),
        "contact_person_role": ROLE_LABELS.get(facts.contact_person_role, "Member"),
        "contact_channel": CHANNEL_LABELS[facts.contact_channel],
        "contact_by_date": eat_date(facts.contact_by),
        "receipt_id": facts.receipt_id,
        "registered_at_eat": eat_time(facts.registered_at),
        "tier2_status": tier2_status(company, facts.viewers, shared=facts.shared),
        "public_entity": facts.public_entity,
        "tracker_url": f"{base}/engagements/{facts.engagement_id}",
        "notifications_url": f"{base}/settings/notifications",
        "help_url": f"{base}/help",
        "engagement_ref": str(facts.engagement_id),
    }
    subject = one_line(_ENV.get_template("em2_subject.txt.j2").render(values))
    return Rendered(
        subject=subject,
        text=_ENV.get_template("em2.txt.j2").render(values),
        html=_ENV.get_template("em2.html.j2").render(values),
    )
