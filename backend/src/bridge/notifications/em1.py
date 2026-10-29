"""EM1 "Proposal submitted + disclosure record" (REQ-NOT-02; docs/spec/06 6.10, REQUIREMENTS.md §5 N01).

The developer's receipt when a Pitch delivers their proposal to at least one verified (E2) organisation: the receipt
id (the certificate id), the version's hash once it is timestamped ("Timestamp pending" until the TSA token is stored),
the organisations it was sent to (delivered tags) and those it is saved for (held tags, with the reason). One call to
action (open the proposal), a plain-text part and the footer (Manage notifications · Help · Nairobi, Kenya). A Pitch
that only holds tags sends no EM1 and no other email (AC-DIR-1).

Rendering: fixed Jinja templates (``templates/em1.*.j2``); the HTML one autoescapes. Text that came from people
(the title, organisation names) is neutralised so no mail client turns it into a link (``unlinkable``); the only
links are the platform's own. Sending: ``deliver`` runs after the HTTP response in its own transaction, scoped to the
developer, through the delivery ledger with a dedupe key per Pitch, so a Pitch sends EM1 at most once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, NamedTuple
from uuid import UUID

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.db import bind_tenant
from bridge.logging import get_logger
from bridge.models.enums import TagStatus
from bridge.notifications.deliveries import send_email
from bridge.notifications.email import EmailMessage, EmailProvider

KIND: Final = "em1"
TAG: Final = "em1"
TIMESTAMP_PENDING: Final = "Timestamp pending"
# [[COPY-REVIEW]] Why a tag is held. The E0 sentence is docs/spec/06 6.2's.
HELD_REASONS: Final = {
    TagStatus.HELD_UNCLAIMED: (
        "{org} isn't on the platform yet. Your proposal is saved and they'll see it if they join and verify."
        " We don't email them on your behalf."
    ),
    TagStatus.HELD_PENDING_VERIFICATION: (
        "{org} is still verifying its details. Your proposal is saved and they'll see it once they are verified."
    ),
}

_ENV: Final = Environment(
    loader=PackageLoader("bridge.notifications", "templates"),
    # The HTML part escapes; the plain-text part is text, where an entity would show as written.
    autoescape=select_autoescape(
        enabled_extensions=("html.j2",), disabled_extensions=("txt.j2",), default_for_string=True, default=True
    ),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)
# A dot or an at sign between two word characters is what mail clients read as a domain or an address. ONE DOT LEADER
# (U+2024) and FULLWIDTH COMMERCIAL AT (U+FF20) look the same and are never linked.
DOT: Final = "\N{ONE DOT LEADER}"
AT: Final = "\N{FULLWIDTH COMMERCIAL AT}"
_LINKABLE_DOT = re.compile(r"(?<=\w)\.(?=\w)")
_ONE_LINE = re.compile(r"\s+")


def unlinkable(text: str) -> str:
    """``text`` on one line, with nothing a mail client would turn into a link or a mailto (AC-MAIL-5)."""
    one_line = _ONE_LINE.sub(" ", text).strip()
    return _LINKABLE_DOT.sub(DOT, one_line).replace("@", AT).replace("://", ":")


@dataclass(frozen=True, slots=True)
class HeldOrg:
    name: str
    status: TagStatus


@dataclass(frozen=True, slots=True)
class Em1Facts:
    """What EM1 states; every value is the database's (code decides, nothing is generated)."""

    title: str
    cert_id: str
    content_sha256: str | None  # hex; shown once the version is timestamped
    timestamped: bool
    sent_to: tuple[str, ...]
    saved_for: tuple[HeldOrg, ...]
    proposal_url: str
    settings_url: str
    help_url: str
    product: str


class EmailParts(NamedTuple):
    subject: str
    text: str
    html: str


def _count(n: int) -> str:
    return f"{n} organisation" if n == 1 else f"{n} organisations"


def render(facts: Em1Facts) -> EmailParts:
    if not facts.sent_to:
        raise ValueError("EM1 is sent only when the proposal reached at least one organisation")
    title = unlinkable(facts.title)
    stamped = facts.timestamped and facts.content_sha256 is not None
    context = {
        "title": title,
        "sent_count": _count(len(facts.sent_to)),
        "saved_count": _count(len(facts.saved_for)),
        "cert_id": facts.cert_id,
        "hash": facts.content_sha256 if stamped else TIMESTAMP_PENDING,
        "sent_to": [unlinkable(name) for name in facts.sent_to],
        "saved_for": [HELD_REASONS[org.status].format(org=unlinkable(org.name)) for org in facts.saved_for],
        "proposal_url": facts.proposal_url,
        "settings_url": facts.settings_url,
        "help_url": facts.help_url,
        "product": unlinkable(facts.product),
    }
    subject = f'Your proposal "{title}" is registered and sent to {context["sent_count"]}'
    return EmailParts(
        subject=subject,
        text=_ENV.get_template("em1.txt.j2").render(context),
        html=_ENV.get_template("em1.html.j2").render(context),
    )


@dataclass(frozen=True, slots=True)
class PendingEm1:
    developer_id: UUID
    address: str
    parts: EmailParts
    dedupe_key: str


def dedupe_key(proposal_id: UUID, delivered_tag_ids: list[UUID]) -> str:
    """One EM1 per Pitch: the proposal and the first tag the Pitch delivered (tags are never reused)."""
    return f"{KIND}:{proposal_id}:{min(delivered_tag_ids)}"


async def deliver(factory: async_sessionmaker[AsyncSession], provider: EmailProvider, pending: PendingEm1) -> None:
    """Send EM1 through the delivery ledger (REQ-NOT-01) in a transaction of its own, scoped to the developer; a
    failure is recorded there (or logged without the address), never raised: the Pitch has already committed."""
    log = get_logger("bridge.notifications.em1")
    try:
        async with factory() as db:
            await bind_tenant(db, user_id=pending.developer_id)
            message = EmailMessage(
                to=pending.address,
                subject=pending.parts.subject,
                text=pending.parts.text,
                html=pending.parts.html,
                tag=TAG,
            )
            await send_email(
                db, provider, message=message, kind=KIND, user_id=pending.developer_id, dedupe_key=pending.dedupe_key
            )
            await db.commit()
    except DBAPIError as exc:  # DB messages can carry addresses: log the constraint only
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        log.error("em1.not_recorded", constraint=constraint)
    except Exception as exc:  # a background task has no caller to report to
        log.error("em1.not_recorded", error_type=type(exc).__name__)
