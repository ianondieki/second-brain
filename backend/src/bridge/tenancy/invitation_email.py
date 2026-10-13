"""The invitation email (REQ-TEN-02): a fixed template in English and Swahili, rendered by code from facts only.

The organisation's name and the inviter's name are the only words a person chose; each is collapsed to one line and
cut to its column's length, and the HTML part is autoescaped (``bridge.notifications.brand.simple_html``). The link is
the web app's ``/invitations/{token}`` on ``PUBLIC_BASE_URL``: the token is in the email and nowhere else (the
database keeps its SHA-256). The language is the invitee's account's when the address already has one, else the
inviter's. All wording is ordinary product copy, ``[[COPY-REVIEW]]`` (Swahili included).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.emails import Wording
from bridge.db import bind_tenant
from bridge.logging import get_logger
from bridge.models.enums import DeliveryStatus, OrgRole
from bridge.notifications.brand import simple_html
from bridge.notifications.deliveries import send_email
from bridge.notifications.em2 import one_line
from bridge.notifications.email import EmailMessage, EmailProvider
from bridge.web_paths import invitation_path

Locale = Literal["en", "sw"]
KIND: Final = "org.invitation"
VALID_DAYS: Final = 7
MAX_ORG_CHARS: Final = 200  # organizations.legal_name
MAX_NAME_CHARS: Final = 120  # users.display_name

# [[COPY-REVIEW]] role names as an invitation states them.
ROLE_NAMES: Final[dict[Locale, dict[OrgRole, str]]] = {
    "en": {
        OrgRole.OWNER: "owner",
        OrgRole.ADMIN: "admin",
        OrgRole.REVIEWER: "reviewer",
        OrgRole.SIGNATORY: "signatory",
        OrgRole.FINANCE: "finance",
        OrgRole.VIEWER: "viewer",
    },
    "sw": {
        OrgRole.OWNER: "mmiliki",
        OrgRole.ADMIN: "msimamizi",
        OrgRole.REVIEWER: "mkaguzi",
        OrgRole.SIGNATORY: "mtia sahihi",
        OrgRole.FINANCE: "afisa wa fedha",
        OrgRole.VIEWER: "mtazamaji",
    },
}
ROLE_ORDER: Final = tuple(OrgRole)
MONTHS_SW: Final = (
    "Januari",
    "Februari",
    "Machi",
    "Aprili",
    "Mei",
    "Juni",
    "Julai",
    "Agosti",
    "Septemba",
    "Oktoba",
    "Novemba",
    "Desemba",
)


@dataclass(frozen=True, slots=True)
class InvitationFacts:
    product: str
    inviter: str
    org_name: str
    roles: Sequence[OrgRole]
    base_url: str
    token: str
    expires_on: date  # the Nairobi date the link stops working


def locale_of(value: str | None) -> Locale:
    """``sw`` for a Swahili account, ``en`` for anything else."""
    return "sw" if (value or "").lower().startswith("sw") else "en"


def link(base_url: str, token: str) -> str:
    """The web app's invitation page for ``token`` (absolute)."""
    base = base_url.rstrip("/")
    return f"{base}{invitation_path(token)}"


def _list(items: Sequence[str], conjunction: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {conjunction} {items[-1]}"


def roles_text(roles: Sequence[OrgRole], locale: Locale) -> str:
    """The roles in the glossary's order in ``locale``'s words ("reviewer and finance", "mkaguzi na afisa wa fedha")."""
    held = set(roles)
    names = [ROLE_NAMES[locale][role] for role in ROLE_ORDER if role in held]
    return _list(names, "and" if locale == "en" else "na")


def date_text(day: date, locale: Locale) -> str:
    if locale == "sw":
        return f"{day.day} {MONTHS_SW[day.month - 1]} {day.year}"
    return f"{day.day} {day:%B %Y}"


def render(facts: InvitationFacts, locale: Locale) -> Wording:
    """The email in ``locale`` (subject, text and HTML parts). [[COPY-REVIEW]]"""
    inviter = one_line(facts.inviter)[:MAX_NAME_CHARS] or ("Someone" if locale == "en" else "Mtu")
    org = one_line(facts.org_name)[:MAX_ORG_CHARS]
    roles = roles_text(facts.roles, locale)
    until = date_text(facts.expires_on, locale)
    url = link(facts.base_url, facts.token)
    product = one_line(facts.product)
    if locale == "sw":
        subject = f"{inviter} amekualika ujiunge na {org} kwenye {product}"
        paragraphs = [
            f"{inviter} amekualika ujiunge na timu ya {org} kwenye {product} kama {roles}.",
            "Fungua kiungo ili ukubali. Utaombwa kuingia, au kufungua akaunti, kwa anwani hii ya barua pepe.",
            f"Kiungo kinafanya kazi hadi {until} (siku {VALID_DAYS}). Kama hukutarajia mwaliko huu, puuza barua pepe"
            " hii.",
        ]
        button = "Kubali mwaliko"
    else:
        subject = f"{inviter} invited you to join {org} on {product}"
        paragraphs = [
            f"{inviter} invited you to join the {org} team on {product} as {roles}.",
            "Open the link to accept. You will be asked to sign in, or to create an account, with this email address.",
            f"The link works until {until} ({VALID_DAYS} days). If you were not expecting this invitation, you can"
            " ignore this email.",
        ]
        button = "Accept the invitation"
    text = f"{paragraphs[0]}\n\n{paragraphs[1]}\n{url}\n\n{paragraphs[2]}"
    html = simple_html(product=product, subject=subject, paragraphs=paragraphs, button=(button, url))
    return Wording(subject[:300], text, html)


async def deliver(
    factory: async_sessionmaker[AsyncSession],
    provider: EmailProvider,
    *,
    org_id: UUID,
    inviter_id: UUID,
    address: str,
    wording: Wording,
) -> bool:
    """Send the invitation through the delivery ledger (REQ-NOT-01), after the invitation committed, in a session bound
    to the inviter and the organisation (the ledger's row is the organisation's). Never raises: a failed send is the
    ledger's ``failed`` row or a log line with the error's type, and the inviter can resend."""
    try:
        async with factory() as db:
            await bind_tenant(db, user_id=inviter_id, org_id=org_id)
            message = EmailMessage(to=address, subject=wording.subject, text=wording.text, html=wording.html, tag=KIND)
            row = await send_email(db, provider, message=message, kind=KIND, org_id=org_id)
            await db.commit()
            return row.status == DeliveryStatus.SENT
    except Exception as exc:  # a background send has no caller to report to
        get_logger(__name__).error("org.invitation_email_failed", org_id=str(org_id), error_type=type(exc).__name__)
        return False
