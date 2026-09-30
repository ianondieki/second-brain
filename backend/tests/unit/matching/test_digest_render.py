"""REQ-SCOUT-03 (AC-REPO-4/b, AC-MAIL-5 re-run on EM3): the scout digest is rendered by code from a fixed template,
escaped and defanged, with a niche label on every item and only platform links."""

from __future__ import annotations

import re
from uuid import UUID, uuid4

import pytest

from bridge.matching.digest import MAX_ITEMS, WHY_LABELS, Digest, Item, render, subject

BASE = "https://bridge.example.test"
ORG = UUID("01920000-0000-7000-8000-000000000001")
HOSTILE_TITLE = "Pay <script>alert(1)</script> at pay.example.com or ops@evil.example.org, call +254 712 345 678"
HOSTILE_WHY = "Visit https://evil.example/login and www.phish.example then email me at a.b@c.example or 0712345678"


def item(**overrides: object) -> Item:
    values: dict[str, object] = {
        "match_id": uuid4(),
        "title": "Mobile money savings for SACCOs",
        "niche": "Finance › Microfinance & SACCOs",
        "score": 84,
        "why": "Fits the savings focus.",
        "why_source": "model",
        "maturity": "mvp",
        "county": "Nairobi",
    }
    values.update(overrides)
    return Item(**values)  # type: ignore[arg-type]


def digest(*items: Item, total: int | None = None) -> Digest:
    return Digest(ORG, "Telco A (fixture)", items, len(items) if total is None else total)


def test_niche_label() -> None:
    """AC-REPO-4/b: the niche label renders on every digest item (both parts)."""
    parts = render(digest(item(), item(niche="Agriculture › Dairy", title="Milk")), base_url=BASE, product="Bridge")
    for part in (parts.text, parts.html):
        assert "Finance › Microfinance &amp; SACCOs" in part or "Finance › Microfinance & SACCOs" in part
        assert "Agriculture › Dairy" in part
    missing = render(digest(item(niche=None)), base_url=BASE, product="Bridge")
    assert "Niche not given" in missing.text


def test_party_and_model_text_is_escaped_and_defanged() -> None:
    parts = render(digest(item(title=HOSTILE_TITLE, why=HOSTILE_WHY)), base_url=BASE, product="Bridge")
    for part in (parts.text, parts.html):
        assert "<script" not in part
        assert "pay.example.com" not in part
        assert "pay[.]example[.]com" in part
        assert "evil.example.org" not in part
        assert "ops@" not in part
        assert "712 345 678" not in part
        assert "0712345678" not in part
        assert "https://evil.example" not in part
        assert "www.phish.example" not in part
        assert "a.b@c.example" not in part
    assert "[link removed]" in parts.text
    assert "[email removed]" in parts.text
    assert "[phone number removed]" in parts.text


def test_every_link_is_a_platform_page() -> None:
    parts = render(digest(item(why=HOSTILE_WHY), item()), base_url=BASE, product="Bridge")
    hrefs = re.findall(r'href="([^"]+)"', parts.html)
    assert hrefs
    assert all(h.startswith(f"{BASE}/") for h in hrefs)
    urls = re.findall(r"https?://\S+", parts.text)
    assert all(u.startswith(f"{BASE}/") for u in urls)
    assert f"{BASE}/org/inbox?org={ORG}&amp;tab=matches" in parts.html  # the one call to action
    assert f"{BASE}/org/inbox?org={ORG}&tab=matches" in parts.text
    assert parts.html.count('data-cta="') == 1


def test_items_are_capped_and_the_rest_summarised() -> None:
    shown = [item(score=90 - i) for i in range(3)]
    parts = render(digest(*shown, total=14), base_url=BASE, product="Bridge")
    assert parts.subject == "Scout digest: 14 new matching proposals for Telco A (fixture)"
    assert "11 more matches in your inbox." in parts.text
    assert "The top 3 are below." in parts.text
    assert parts.text.index("Fit: 90/100") < parts.text.index("Fit: 88/100")
    with pytest.raises(ValueError, match="1 to 10"):
        render(digest(*[item() for _ in range(MAX_ITEMS + 1)]), base_url=BASE, product="Bridge")
    with pytest.raises(ValueError, match="1 to 10"):
        render(digest(), base_url=BASE, product="Bridge")


def test_the_why_says_who_wrote_it() -> None:
    parts = render(
        digest(item(why_source="model"), item(why_source="code"), item(why_source="demo_fallback")),
        base_url=BASE,
        product="Bridge",
    )
    for label in WHY_LABELS.values():
        assert label in parts.text
    one = render(digest(item()), base_url=BASE, product="Bridge")
    assert subject(digest(item())) == one.subject == "Scout digest: 1 new matching proposal for Telco A (fixture)"


def test_the_digest_is_deterministic() -> None:
    items = (item(match_id=UUID(int=1)), item(match_id=UUID(int=2), title="Other"))
    assert render(digest(*items), base_url=BASE, product="Bridge") == render(
        digest(*items), base_url=BASE, product="Bridge"
    )
