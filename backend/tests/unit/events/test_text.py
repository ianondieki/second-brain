"""REQ-DEV-02 (D-60; the 0010 security review's MINOR): an event's text is NFKC-normalised and loses its format and
other invisible characters before it is stored; a control character left refuses the field, a title empty after
cleaning is blank, and a link is an https URL on an ASCII host of at most 400 characters. Errors never quote the
text."""

from __future__ import annotations

from typing import Any

import pytest

from bridge.events import text
from bridge.proposals.sanitise import FieldError


def clean(field: str, value: str) -> tuple[str, list[str]]:
    errors: list[FieldError] = []
    cleaned = text.text_field(field, value, errors)
    return cleaned, [e.code for e in errors]


def test_a_title_is_nfkc_one_line_and_loses_bidi_and_zero_width_characters() -> None:
    fullwidth_n, no_break, zero_width, rtl = chr(0xFF2E), chr(0xA0), chr(0x200B), chr(0x202E)
    title = f"  {fullwidth_n}airobi{no_break}Python{zero_width} meetup {rtl}\n"
    assert clean("title", title) == ("Nairobi Python meetup", [])
    assert clean("title", f"{zero_width}{chr(0x2060)}{chr(0xFEFF)} \t") == ("", ["blank"])
    assert clean("title", "Bell \x07 ringing") == ("Bell \x07 ringing", ["control_character"])
    assert clean("title", "x" * 121)[1] == ["too_long"]
    assert clean("title", "x" * 120)[1] == []


def test_a_description_keeps_its_lines_and_tabs_but_no_other_control() -> None:
    raw = "Talks\r\n\r\n\r\n\r\nand\ta workshop.   \nBring a laptop." + chr(0x202D)
    cleaned, codes = clean("description", raw)
    assert (cleaned, codes) == ("Talks\n\nand\ta workshop.\nBring a laptop.", [])
    assert clean("description", "Escape \x1b[31m red")[1] == ["control_character"]
    assert clean("description", "C1 " + chr(0x85) + " control")[1] == ["control_character"]
    assert clean("description", "y" * 1001)[1] == ["too_long"]


def test_a_venue_is_one_line() -> None:
    assert clean("venue", "iHub,\nSenteu Plaza") == ("iHub, Senteu Plaza", [])
    assert clean("venue", "v" * 161)[1] == ["too_long"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/event",
        "https://user@example.com/event",
        "https://exa mple.com/",
        "https://example.com/caf" + chr(0xE9),
        "https://example.com?x=1",
        "javascript:alert(1)",
        "https://" + "a" * 400 + ".com",
    ],
)
def test_a_link_that_breaks_the_rule_is_invalid(url: str) -> None:
    errors: list[FieldError] = []
    text.link("link", url, errors)
    assert [(e.field, e.code) for e in errors] == [("link", "invalid_url")]
    assert url not in errors[0].message


def test_a_good_link_is_kept_and_a_blank_one_is_none() -> None:
    errors: list[FieldError] = []
    joined = " https://meet.example.test:8443/abc-defg?x=1#y" + chr(0x200B) + " "
    assert text.link("join_url", joined, errors) == "https://meet.example.test:8443/abc-defg?x=1#y"
    assert text.link("link", "  ", errors) is None
    assert text.link("link", None, errors) is None
    assert errors == []


def test_the_refusal_names_fields_and_codes_only() -> None:
    refused = text.invalid([text.error("title", "blank"), text.error("venue", "too_long")])
    detail: Any = refused.detail
    assert refused.status_code == 422
    assert detail["code"] == "invalid_event"
    assert [(e["field"], e["code"]) for e in detail["errors"]] == [("title", "blank"), ("venue", "too_long")]
    assert detail["errors"][1]["message"] == "Keep this to 160 characters or fewer."
