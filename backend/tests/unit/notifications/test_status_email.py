"""REQ-ENG-10 (part; ADR-004 "status change" layout): the email of a side state or a system event: a subject with the
stage and the title, one sentence, one link to the recipient's tracker, the engagement's ref in the footer; party text
made unlinkable and escaped; once per event and recipient."""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from bridge.notifications import status

ENGAGEMENT = UUID("01920000-0000-7000-8000-0000000000a1")
EVENT = UUID("01920000-0000-7000-8000-0000000000a2")
USER = UUID("01920000-0000-7000-8000-0000000000a3")


def facts(**overrides: object) -> status.StatusFacts:
    values: dict[str, object] = {
        "engagement_id": ENGAGEMENT,
        "label": "Information requested",
        "title": "Cold-chain alerts at dairy.example.com",
        "sentence": 'Telco A asked you a question about "Cold-chain alerts at dairy.example.com".',
        "path": f"/dev/engagements/{ENGAGEMENT}",
        "base_url": "https://bridge.example.test/",
        "product": "Wazo",
    }
    values.update(overrides)
    return status.StatusFacts(**values)  # type: ignore[arg-type]


def test_one_sentence_one_link_and_the_engagement_ref() -> None:
    rendered = status.render(facts())
    assert rendered.subject.startswith('Information requested: "Cold-chain alerts at dairy')
    url = f"https://bridge.example.test/dev/engagements/{ENGAGEMENT}"
    for part in (rendered.text, rendered.html):
        assert "Telco A asked you a question about" in part
        assert "dairy.example.com" not in part  # a party's text never becomes a link
        assert f"Engagement ref {ENGAGEMENT}" in part
        assert url in part
        assert "https://bridge.example.test/settings/notifications" in part
    assert rendered.text.startswith("Telco A asked you a question")
    assert f"Open your tracker: {url}" in rendered.text
    hrefs = re.findall(r'href="([^"]+)"', rendered.html)
    assert all(h.startswith("https://bridge.example.test/") for h in hrefs)
    assert rendered.html.count('data-cta="') == 1
    assert status.dedupe_key(EVENT, USER) == f"status:{EVENT}:{USER}"


def test_markup_is_escaped_and_the_link_is_a_platform_path() -> None:
    rendered = status.render(facts(sentence="<b>Bold</b> & co paused it."))
    assert "<b>Bold</b>" not in rendered.html
    assert "&lt;b&gt;Bold&lt;/b&gt; &amp; co" in rendered.html
    for wrong in ("https://elsewhere.example/x", "//elsewhere.example/x"):
        with pytest.raises(ValueError, match="platform path"):
            status.render(facts(path=wrong))
