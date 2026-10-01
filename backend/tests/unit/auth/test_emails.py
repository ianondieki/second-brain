"""The auth emails' HTML parts (D-52): escaped, one button, the same link as the text part and no other address."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest

from bridge.auth import emails
from bridge.auth.emails import Wording

PRODUCT = 'Acme & <Co> "Ltd"'
LINK = "https://wazo.test/auth/confirm?token=abc&x=1"
URLS = re.compile(r"https?://[^\s\"'<>]+")

WORDINGS: list[tuple[str, Callable[[], Wording]]] = [
    ("verify_email", lambda: emails.verify_email(PRODUCT, LINK, 15)),
    ("login_link", lambda: emails.login_link(PRODUCT, LINK, 15)),
    ("account_exists", lambda: emails.account_exists(PRODUCT, LINK)),
    ("security_notice", lambda: emails.security_notice(PRODUCT, "Your <password> was changed & more.")),
]


@pytest.mark.parametrize(("name", "make"), WORDINGS, ids=[name for name, _ in WORDINGS])
def test_html_part_escapes_every_value(name: str, make: Callable[[], Wording]) -> None:
    html = make().html
    assert html is not None
    assert "<Co>" not in html, name
    assert "&lt;Co&gt;" in html, name
    assert '"Ltd"' not in html, name
    assert "&#34;Ltd&#34;" in html, name
    assert "&amp; " in html, name
    if name == "security_notice":
        assert "<password>" not in html
        assert "&lt;password&gt;" in html


@pytest.mark.parametrize(("name", "make"), WORDINGS[:3], ids=[name for name, _ in WORDINGS[:3]])
def test_linked_emails_carry_one_button_to_the_text_parts_link(name: str, make: Callable[[], Wording]) -> None:
    wording = make()
    assert wording.html is not None
    assert wording.html.count("data-cta=") == 1, name
    # The address is escaped in the attribute; the text part carries it raw.
    assert f'href="{LINK.replace("&", "&amp;")}"' in wording.html, name
    assert LINK in wording.text, name
    # The address under the button, for clients that drop buttons.
    assert "Or open this address:" in wording.html


def test_security_notice_has_no_link() -> None:
    wording = emails.security_notice(PRODUCT, "Your password was changed.")
    assert wording.html is not None
    assert "data-cta=" not in wording.html
    assert URLS.findall(wording.html) == []


@pytest.mark.parametrize(("name", "make"), WORDINGS, ids=[name for name, _ in WORDINGS])
def test_html_part_links_nothing_the_text_part_lacks(name: str, make: Callable[[], Wording]) -> None:
    wording = make()
    assert wording.html is not None
    in_html = {url.replace("&amp;", "&").rstrip(".,") for url in URLS.findall(wording.html)}
    in_text = {url.rstrip(".,") for url in URLS.findall(wording.text)}
    assert in_html <= in_text, (name, in_html - in_text)
    unescaped = wording.html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#34;", '"')
    assert wording.subject in unescaped
