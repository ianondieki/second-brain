"""N17, an organisation's interest (REQUIREMENTS.md §5 N17; docs/spec/06 6.9 stage 0; REQ-ENG-04).

The developer's email when an organisation's signatory expresses interest in their proposal (from a scout match or
the Browse repo): who, which proposal, how it was found and the date to accept or decline by (the stage's deadline,
5 business days). Mutable (email default on: the ``n17`` email preference), once per engagement (dedupe key
``n17:<engagement>``), queued with the in-app notice by the engagement's creation (``bridge.engagements.notify``).
Fixed templates (``templates/n17.*.j2``); the HTML one autoescapes, and the title and the organisation's name are
made unlinkable (``em1.unlinkable``). The only link is the platform's tracker. Nothing here is worded by an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final, NamedTuple
from uuid import UUID

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from bridge.models.enums import EngagementOrigin, EngagementParty
from bridge.notifications.em1 import unlinkable
from bridge.notifications.em2 import eat_date
from bridge.web_paths import engagement_path

KIND: Final = "n17"
# [[COPY-REVIEW]] how the organisation found the proposal.
FOUND_BY: Final = {
    EngagementOrigin.ORG_AGENT_MATCH: "through its scout",
    EngagementOrigin.ORG_BROWSE: "while browsing proposals",
}
_ENV: Final = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False, default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True, slots=True)
class N17Facts:
    engagement_id: UUID
    company_name: str
    title: str
    origin: EngagementOrigin
    respond_by: date | None
    base_url: str
    product: str


class Rendered(NamedTuple):
    subject: str
    text: str
    html: str


def dedupe_key(engagement_id: UUID) -> str:
    return f"{KIND}:{engagement_id}"


def render(facts: N17Facts) -> Rendered:
    company, title = unlinkable(facts.company_name), unlinkable(facts.title)
    base = facts.base_url.rstrip("/")
    values = {
        "company_name": company,
        "title": title,
        "found_by": FOUND_BY.get(facts.origin, "on the platform"),
        "respond_by": f"by {eat_date(facts.respond_by)}" if facts.respond_by else "within 5 business days",
        "tracker_url": base + engagement_path(EngagementParty.DEVELOPER, facts.engagement_id),
        "settings_url": f"{base}/settings/notifications",
        "help_url": f"{base}/help",
        "engagement_ref": str(facts.engagement_id),
        "product": unlinkable(facts.product),
    }
    subject = f'{company} is interested in "{title}"'
    return Rendered(
        subject, _ENV.get_template("n17.txt.j2").render(values), _ENV.get_template("n17.html.j2").render(values)
    )
