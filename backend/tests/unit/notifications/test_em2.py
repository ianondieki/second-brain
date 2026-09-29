"""AC-MAIL-1 (REQ-NOT-04): EM2 renders the spec's copy with the named contact, the contact-by date and a computed
tier2_status; HTML values are escaped; the EM2 templates pass the copy-lint."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest

from bridge.models.enums import ContactChannel
from bridge.notifications import em2

REPO = Path(__file__).resolve().parents[4]
ENGAGEMENT = UUID("01900000-0000-7000-8000-00000000000a")


def facts(**changes: object) -> em2.Em2Facts:
    values: dict[str, object] = {
        "engagement_id": ENGAGEMENT,
        "company_name": "Telco A (fixture)",
        "title": "Cold-chain alerts",
        "contact_person_name": "Wanjiru Kamau",
        "contact_person_role": "signatory",
        "contact_channel": ContactChannel.VIDEO_CALL,
        "contact_by": date(2026, 10, 6),
        "receipt_id": "c-0192ab",
        "registered_at": datetime(2026, 9, 23, 11, 5, tzinfo=UTC),
        "viewers": 0,
        "shared": False,
        "public_entity": False,
        "base_url": "https://bridge.example/",
    }
    values.update(changes)
    return em2.Em2Facts(**values)  # type: ignore[arg-type]


def test_em2_has_the_spec_copy() -> None:
    rendered = em2.render(facts())
    assert rendered.subject == 'Good news: Telco A (fixture) approved "Cold-chain alerts" to proceed (non-binding)'
    text = rendered.text
    assert text.startswith(
        'Telco A (fixture) has approved your proposal "Cold-chain alerts" and will contact you shortly to agree on'
        " pursuing the project.\n"
    )
    assert "Your contact: Wanjiru Kamau, Signatory, via video call before 6 Oct 2026." in text
    assert (
        "This approval is an expression of interest, not a contract or a commitment to buy; nothing is binding"
        " until you both sign an agreement." in text
    )
    assert "What happens next: first contact → NDA → agreement → implementation, all visible on your tracker." in text
    assert "Your disclosure record c-0192ab (23 Sep 2026, 14:05 EAT) is attached to this engagement." in text
    assert "Your full proposal has not been shared yet." in text
    assert "If nobody contacts you by 6 Oct 2026, we follow up with Telco A (fixture) automatically." in text
    assert f"Open your tracker: https://bridge.example/engagements/{ENGAGEMENT}" in text
    assert f"Engagement ref {ENGAGEMENT}" in text
    assert "Nairobi, Kenya" in text
    assert "Public bodies" not in text
    assert "<strong>6 Oct 2026</strong>" in rendered.html
    assert rendered.html.count(">Open your tracker</a>") == 1


@pytest.mark.parametrize(
    ("viewers", "shared", "expected"),
    [
        (0, False, "Your full proposal has not been shared yet."),
        (0, True, "Your full proposal is shared with Telco A (fixture) under NDA; nobody there has opened it yet."),
        (1, True, "1 named, verified person at Telco A (fixture) has viewed your full proposal under NDA"),
        (3, True, "3 named, verified people at Telco A (fixture) have viewed your full proposal under NDA"),
    ],
)
def test_tier2_status_follows_the_access_log(viewers: int, shared: bool, expected: str) -> None:
    assert expected in em2.render(facts(viewers=viewers, shared=shared)).text


def test_values_are_escaped_in_html_and_kept_on_one_line_in_the_subject() -> None:
    rendered = em2.render(
        facts(company_name="Evil <script>alert(1)</script>\nCo", contact_person_role="", public_entity=True)
    )
    assert "<script>" not in rendered.html
    assert "&lt;script&gt;" in rendered.html
    assert "\n" not in rendered.subject
    assert "Public bodies may need to run a competitive process, and you may be asked to bid." in rendered.text
    assert ", Member, via" in rendered.text  # an unknown role reads as a member
    assert em2.dedupe_key(ENGAGEMENT) == f"em2:{ENGAGEMENT}"


def test_every_contact_channel_has_a_label() -> None:
    assert set(em2.CHANNEL_LABELS) == set(ContactChannel)


def test_the_em2_templates_pass_the_copy_lint(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-MAIL-1: every "approve" in an EM2 template carries its non-binding qualifier (scripts/copy_lint.py)."""
    spec = importlib.util.spec_from_file_location("copy_lint", REPO / "scripts" / "copy_lint.py")
    assert spec is not None
    assert spec.loader is not None
    lint = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "copy_lint", lint)  # its dataclasses look their module up
    spec.loader.exec_module(lint)
    rules = lint.load_rules(REPO / "copy" / "banned_claims.txt")
    templates = sorted((REPO / "backend" / "src" / "bridge" / "notifications" / "templates").glob("em2*.j2"))
    assert len(templates) == 3
    for path in templates:
        assert lint.scan_text(rules, path, path.name, template=True) == [], path.name
