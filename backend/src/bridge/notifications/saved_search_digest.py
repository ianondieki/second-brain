"""The saved-search digest email (P21 track C; REQ-PERS-03, REQ-TREND-02; D-57 (7)): the day's new matches of a
developer's saved Discover searches, in one status email, for those who turned it on (``saved_search_digest``, email,
off by default: ``bridge.notifications.preferences``).

Names and counts only ("Agriculture in Nakuru: 3 new problems"), never a problem's or Brief's text, and one link, to
Discover. Once per person and Nairobi day (``daily_key``). The HTML part is the short branded frame
(``templates/simple.html.j2``); the names are the person's own words, made unlinkable (``em1.unlinkable``). Fixed
wording ([[COPY-REVIEW]]); nothing here is worded by an LLM.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, NamedTuple
from uuid import UUID

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from bridge.models.enums import NotificationChannel
from bridge.notifications.deliveries import daily_key
from bridge.notifications.em1 import unlinkable
from bridge.notifications.preferences import SAVED_SEARCH_DIGEST
from bridge.web_paths import DEV_DISCOVER

KIND: Final = SAVED_SEARCH_DIGEST
# [[COPY-REVIEW]] the email's fixed words.
SUBJECT: Final = "New matches for your saved searches"
INTRO: Final = "Your saved Discover searches found new matches:"
CTA: Final = "Open Discover"
NOUNS: Final = {"problems": ("problem", "problems"), "briefs": ("Brief", "Briefs")}
_ENV: Final = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    autoescape=select_autoescape(enabled_extensions=("html.j2",), default_for_string=False, default=False),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def new_items(count: int, view: str) -> str:
    """'1 new problem', '3 new Briefs' ([[COPY-REVIEW]])."""
    one, many = NOUNS.get(view, NOUNS["problems"])
    return f"{count} new {one if count == 1 else many}"


@dataclass(frozen=True, slots=True)
class Match:
    name: str  # the saved search's name, as its owner wrote it
    view: str  # problems | briefs
    count: int


@dataclass(frozen=True, slots=True)
class DigestFacts:
    matches: Sequence[Match]
    base_url: str
    product: str


class Rendered(NamedTuple):
    subject: str
    text: str
    html: str


def dedupe_key(user_id: UUID, day: date) -> str:
    return daily_key(KIND, NotificationChannel.EMAIL, user_id, day)


def render(facts: DigestFacts) -> Rendered:
    if not facts.matches:
        raise ValueError("a saved-search digest lists at least one search")
    base = facts.base_url.rstrip("/")
    lines = [f"{unlinkable(m.name)}: {new_items(m.count, m.view)}" for m in facts.matches]
    discover, settings, help_url = base + DEV_DISCOVER, f"{base}/settings/notifications", f"{base}/help"
    product = unlinkable(facts.product)
    text = "\n".join(
        [
            INTRO,
            "",
            *(f"- {line}" for line in lines),
            "",
            f"{CTA}: {discover}",
            "",
            "--",
            product,
            f"Manage notifications: {settings} · Help: {help_url} · Nairobi, Kenya",
            "",
        ]
    )
    html = _ENV.get_template("simple.html.j2").render(
        product=product,
        subject=SUBJECT,
        paragraphs=[INTRO, *lines],
        button_label=CTA,
        button_url=discover,
        settings_url=settings,
        help_url=help_url,
    )
    return Rendered(SUBJECT, text, html)
