"""REQ-ENG-04 (REQUIREMENTS.md §5 N17): the developer's email when an organisation expresses interest: fixed copy,
the organisation and title made unlinkable, the respond-by date, one platform link, nothing binding promised."""

from __future__ import annotations

import re
from datetime import date
from uuid import UUID

from bridge.models.enums import EngagementOrigin
from bridge.notifications import n17

ENGAGEMENT = UUID("01920000-0000-7000-8000-00000000000e")


def facts(**overrides: object) -> n17.N17Facts:
    values: dict[str, object] = {
        "engagement_id": ENGAGEMENT,
        "company_name": "Telco A (fixture)",
        "title": "Cold-chain alerts at dairy.example.com",
        "origin": EngagementOrigin.ORG_AGENT_MATCH,
        "respond_by": date(2026, 10, 6),
        "base_url": "https://bridge.example.test",
        "product": "Bridge",
    }
    values.update(overrides)
    return n17.N17Facts(**values)  # type: ignore[arg-type]


def test_the_email_says_who_what_and_by_when() -> None:
    rendered = n17.render(facts())
    assert rendered.subject.startswith("Telco A (fixture) is interested in")
    for part in (rendered.text, rendered.html):
        assert "through its scout" in part
        assert "by 6 Oct 2026" in part
        assert "not a contract or a commitment to buy" in part
        assert "dairy.example.com" not in part  # a party's text never becomes a link
        assert "approve" not in part.lower()
    assert "https://bridge.example.test/dev/engagements/" + str(ENGAGEMENT) in rendered.text  # the developer's
    hrefs = re.findall(r'href="([^"]+)"', rendered.html)
    assert all(h.startswith("https://bridge.example.test/") for h in hrefs)
    assert rendered.html.count('data-cta="') == 1


def test_browse_and_a_missing_deadline_have_their_own_words() -> None:
    rendered = n17.render(facts(origin=EngagementOrigin.ORG_BROWSE, respond_by=None))
    assert "while browsing proposals" in rendered.text
    assert "within 5 business days" in rendered.text
    assert n17.dedupe_key(ENGAGEMENT) == f"n17:{ENGAGEMENT}"


def test_markup_in_a_title_is_escaped_in_html() -> None:
    rendered = n17.render(facts(title="<b>Bold</b> & co"))
    assert "<b>Bold</b>" not in rendered.html
    assert "&lt;b&gt;Bold&lt;/b&gt; &amp; co" in rendered.html
