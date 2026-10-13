"""REQ-TEN-02 (P28 track C): the invitation email, a fixed template in English and Swahili rendered from facts.

A name a person chose (the inviter's, the organisation's) is one line in the subject and escaped in the HTML part; the
link is the web app's ``/invitations/{token}`` on the public base URL; the roles are named in the glossary's order; the
date is the Nairobi date the link stops working.
"""

from __future__ import annotations

from datetime import date
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.auth.crypto import new_token
from bridge.models.enums import OrgRole
from bridge.notifications.email import FakeEmailProvider
from bridge.tenancy.invitation_email import InvitationFacts, deliver, link, locale_of, render, roles_text

TOKEN = new_token()


def facts(**changes: object) -> InvitationFacts:
    base: dict[str, object] = {
        "product": "Wazo",
        "inviter": "Grace Mwangi",
        "org_name": "Telco A (fixture)",
        "roles": [OrgRole.FINANCE, OrgRole.REVIEWER],
        "base_url": "https://wazo.example/",
        "token": TOKEN,
        "expires_on": date(2026, 10, 20),
    }
    base.update(changes)
    return InvitationFacts(**base)  # type: ignore[arg-type]


def test_the_english_email_names_the_inviter_the_organisation_the_roles_and_the_date() -> None:
    wording = render(facts(), "en")
    assert wording.subject == "Wazo: you have an invitation to join a team"
    first = "Grace Mwangi invited you to join the Telco A (fixture) team on Wazo as reviewer and finance."
    assert first in wording.text
    assert f"https://wazo.example/invitations/{TOKEN}" in wording.text
    assert "The link works until 20 October 2026 (7 days)." in wording.text
    assert wording.html is not None
    assert f"https://wazo.example/invitations/{TOKEN}" in wording.html


def test_the_swahili_email_is_the_same_facts_in_swahili() -> None:
    wording = render(facts(), "sw")
    assert wording.subject == "Wazo: una mwaliko wa kujiunga na timu"
    assert "Grace Mwangi amekualika ujiunge na timu ya Telco A (fixture) kwenye Wazo" in wording.text
    assert "kama mkaguzi na afisa wa fedha." in wording.text
    assert "Kiungo kinafanya kazi hadi 20 Oktoba 2026 (siku 7)." in wording.text
    assert f"https://wazo.example/invitations/{TOKEN}" in wording.text
    assert wording.html is not None
    assert "Kubali mwaliko" in wording.html


def test_chosen_names_are_one_line_and_escaped() -> None:
    wording = render(facts(inviter="Eve\r\nBcc: x@evil.test", org_name='<script>alert("x")</script>\nCo'), "en")
    assert wording.subject == "Wazo: you have an invitation to join a team"  # nothing a caller wrote
    assert "Eve Bcc: x@evil.test invited you" in wording.text  # one line, in the body only
    assert "Eve\r\n" not in wording.text
    assert wording.html is not None
    assert "<script>" not in wording.html
    assert "&lt;script&gt;" in wording.html


def test_a_blank_inviter_name_reads_someone() -> None:
    assert render(facts(inviter="  "), "en").text.startswith("Someone invited you")
    assert render(facts(inviter=""), "sw").text.startswith("Mtu amekualika")


@pytest.mark.parametrize(
    ("roles", "en", "sw"),
    [
        ([OrgRole.VIEWER], "viewer", "mtazamaji"),
        ([OrgRole.SIGNATORY, OrgRole.OWNER], "owner and signatory", "mmiliki na mtia sahihi"),
        ([OrgRole.VIEWER, OrgRole.ADMIN, OrgRole.OWNER], "owner, admin and viewer", "mmiliki, msimamizi na mtazamaji"),
    ],
)
def test_roles_are_named_in_the_glossary_s_order(roles: list[OrgRole], en: str, sw: str) -> None:
    assert roles_text(roles, "en") == en
    assert roles_text(roles, "sw") == sw


def test_the_language_is_swahili_only_for_a_swahili_account() -> None:
    assert locale_of("sw") == "sw"
    assert locale_of("sw-KE") == "sw"
    assert locale_of("en") == "en"
    assert locale_of(None) == "en"
    assert locale_of("fr") == "en"


def test_the_link_is_the_web_app_s_page_on_the_public_origin() -> None:
    assert link("https://wazo.example", "abc") == "https://wazo.example/invitations/abc"
    assert link("https://wazo.example///", "abc") == "https://wazo.example/invitations/abc"


async def test_a_failed_send_is_logged_and_never_raised() -> None:
    """The invitation committed before the email: a failure to send leaves it for a resend, nothing is raised."""

    def down() -> AsyncSession:
        raise RuntimeError("the database is down")

    factory = cast(async_sessionmaker[AsyncSession], down)
    sent = await deliver(
        factory,
        FakeEmailProvider(),
        org_id=uuid4(),
        inviter_id=uuid4(),
        address="a@example.com",
        wording=render(facts(), "en"),
    )
    assert sent is False
