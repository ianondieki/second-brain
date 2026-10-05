"""P21 track C (REQ-PERS-03, D-57 (7)): the saved-search digest email lists the searches' names and counts only, with
one link to Discover and the footer's settings link; a name cannot become a link; once per person and Nairobi day."""

from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from bridge.notifications import saved_search_digest as digest
from bridge.notifications.em1 import AT, DOT

FACTS = digest.DigestFacts(
    matches=[
        digest.Match("Agriculture in Nakuru", "problems", 3),
        digest.Match("Water <b>Briefs</b>", "briefs", 1),
        digest.Match("see evil.example.com or mail me@evil.example", "problems", 1),
    ],
    base_url="https://wazo.example.test/",
    product="Wazo",
)


def test_names_and_counts_with_one_link_to_discover() -> None:
    rendered = digest.render(FACTS)
    assert rendered.subject == "New matches for your saved searches"
    assert rendered.text.splitlines()[:5] == [
        "Your saved Discover searches found new matches:",
        "",
        "- Agriculture in Nakuru: 3 new problems",
        "- Water <b>Briefs</b>: 1 new Brief",
        f"- see evil{DOT}example{DOT}com or mail me{AT}evil{DOT}example: 1 new problem",
    ]
    assert "Open Discover: https://wazo.example.test/dev/discover" in rendered.text
    assert "https://wazo.example.test/settings/notifications" in rendered.text
    assert "Agriculture in Nakuru: 3 new problems" in rendered.html
    assert "Water &lt;b&gt;Briefs&lt;/b&gt;: 1 new Brief" in rendered.html  # autoescaped
    assert 'href="https://wazo.example.test/dev/discover"' in rendered.html
    assert 'href="https://wazo.example.test/settings/notifications"' in rendered.html
    assert "evil.example.com" not in rendered.text + rendered.html


def test_an_empty_digest_is_never_rendered_and_the_key_is_daily() -> None:
    with pytest.raises(ValueError, match="at least one"):
        digest.render(digest.DigestFacts([], base_url="https://x.test", product="Wazo"))
    user = UUID("01a10000-0000-7000-8000-000000000002")
    assert digest.dedupe_key(user, date(2026, 10, 5)) == f"saved_search_digest:email:{user}:2026-10-05"
    assert digest.new_items(2, "briefs") == "2 new Briefs"
