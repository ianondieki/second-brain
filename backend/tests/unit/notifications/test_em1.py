"""EM1 "Proposal submitted + disclosure record" (REQ-NOT-02; docs/spec/06 6.10, the AC-PROP-1/a EM1 clause):
subject, receipt id, hash or "Timestamp pending", sent-to and saved-for groups, one call to action, a plain-text
part, the footer, escaped fields and nothing auto-linkable (AC-MAIL-5)."""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from bridge.models.enums import TagStatus
from bridge.notifications import em1
from bridge.notifications.em1 import Em1Facts, HeldOrg
from bridge.notifications.email import EmailMessage

BASE = "https://bridge.example.test"


def facts(**overrides: object) -> Em1Facts:
    values: dict[str, object] = {
        "title": "Cold-chain alerts",
        "cert_id": "ABCDEFGHJKMNPQRS",
        "content_sha256": None,
        "timestamped": False,
        "sent_to": ("Safaricom PLC", "Airtel Networks Kenya Limited"),
        "saved_for": (
            HeldOrg("Telkom Kenya Limited", TagStatus.HELD_UNCLAIMED),
            HeldOrg("Claimed Co", TagStatus.HELD_PENDING_VERIFICATION),
        ),
        "proposal_url": f"{BASE}/dev/ideas/0192",
        "settings_url": f"{BASE}/settings/notifications",
        "help_url": f"{BASE}/help",
        "product": "Bridge (working name)",
    }
    return Em1Facts(**(values | overrides))  # type: ignore[arg-type]


def test_subject_and_counts() -> None:
    parts = em1.render(facts())
    assert parts.subject == 'Your proposal "Cold-chain alerts" is registered and sent to 2 organisations'
    one = em1.render(facts(sent_to=("Safaricom PLC",), saved_for=()))
    assert one.subject == 'Your proposal "Cold-chain alerts" is registered and sent to 1 organisation'
    EmailMessage(to="dev@example.test", subject=parts.subject, text=parts.text, html=parts.html)  # a valid message


def test_the_subject_is_one_line_whatever_the_title() -> None:
    parts = em1.render(facts(title="Cold-chain\nalerts \t now"))
    assert parts.subject == 'Your proposal "Cold-chain alerts now" is registered and sent to 2 organisations'


def test_receipt_and_timestamp_pending_until_the_token_is_stored() -> None:
    pending = em1.render(facts(content_sha256="ab" * 32, timestamped=False))
    for part in (pending.text, pending.html):
        assert "ABCDEFGHJKMNPQRS" in part
        assert "Timestamp pending" in part
        assert "ab" * 32 not in part
    stamped = em1.render(facts(content_sha256="ab" * 32, timestamped=True))
    for part in (stamped.text, stamped.html):
        assert "ab" * 32 in part
        assert "Timestamp pending" not in part
    # Timestamped but the hash not read: still pending (never an empty hash line).
    assert "Timestamp pending" in em1.render(facts(content_sha256=None, timestamped=True)).text


def test_sent_and_saved_groups() -> None:
    text = em1.render(facts()).text
    assert "Sent to (2 organisations, verified):\n- Safaricom PLC\n- Airtel Networks Kenya Limited\n" in text
    assert "Saved for (2 organisations):" in text
    assert (
        "- Telkom Kenya Limited isn't on the platform yet. Your proposal is saved and they'll see it if they join"
        " and verify. We don't email them on your behalf." in text
    )
    assert "- Claimed Co is still verifying its details." in text
    html = em1.render(facts()).html
    assert html.count("<li>") == 4
    none_saved = em1.render(facts(saved_for=()))
    assert "Saved for" not in none_saved.text
    assert "Saved for" not in none_saved.html


def test_one_call_to_action_a_plain_text_part_and_the_footer() -> None:
    parts = em1.render(facts())
    assert len(re.findall(r"data-cta=", parts.html)) == 1
    assert parts.html.count(f'href="{BASE}/dev/ideas/0192"') == 1
    assert f"Open your proposal: {BASE}/dev/ideas/0192" in parts.text
    for part in (parts.text, parts.html):
        assert "Manage notifications" in part
        assert "Help" in part
        assert "Nairobi, Kenya" in part
    assert "<" not in parts.text  # plain text, not markup


def test_fields_are_escaped_in_html() -> None:
    parts = em1.render(facts(title='<script>alert("x")</script>', sent_to=("A & B <b>Ltd</b>",)))
    assert "<script>" not in parts.html
    assert "&lt;script&gt;" in parts.html
    assert "A &amp; B &lt;b&gt;Ltd&lt;/b&gt;" in parts.html
    assert '<script>alert("x")</script>' in parts.text  # the plain-text part shows the text as it is


def test_nothing_people_wrote_is_auto_linkable() -> None:
    parts = em1.render(
        facts(
            title="Pay via example.com or https://evil.example.org now",
            sent_to=("Mail info@jumia.co.ke Ltd",),
            saved_for=(HeldOrg("www.telkom.co.ke", TagStatus.HELD_UNCLAIMED),),
        )
    )
    visible_html = re.sub(r"<[^>]*>", " ", parts.html)  # what a reader sees (CSS numbers such as 1.5 are not text)
    for part in (parts.subject, parts.text, visible_html):
        body = part.replace(BASE, "")  # the platform's own links are the only links
        assert not re.search(r"\w\.\w", body), body
        assert "@" not in body
        assert "://" not in body
    assert f"example{em1.DOT}com" in parts.text
    assert f"info{em1.AT}jumia{em1.DOT}co{em1.DOT}ke" in parts.text


def test_em1_needs_a_delivered_organisation() -> None:
    with pytest.raises(ValueError, match="at least one organisation"):
        em1.render(facts(sent_to=()))


def test_the_dedupe_key_is_one_per_pitch() -> None:
    proposal = UUID(int=7)
    first, second = UUID(int=3), UUID(int=9)
    assert em1.dedupe_key(proposal, [second, first]) == em1.dedupe_key(proposal, [first, second])
    assert em1.dedupe_key(proposal, [first, second]) == f"em1:{proposal}:{first}"
    assert len(em1.dedupe_key(proposal, [first])) <= 200
