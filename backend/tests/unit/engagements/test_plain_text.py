"""P27 (REQ-ENG-15, REQ-PROV-06, REQ-DEV-04; the security review of revision 0013): one line of plain text a person
typed (a recommendation's note, an evidence title, a KECOBO or KIPI reference) is stored as typed, trimmed of ASCII
spaces, or refused (``bridge.models.text``, the database's rule too): never rewritten or stripped of a character
silently."""

from __future__ import annotations

import pytest

from bridge.engagements.plain import one_line
from bridge.models.text import is_one_line


def test_plain_text_is_kept_as_typed_and_trimmed() -> None:
    assert one_line("  Pursue: fits the Q3 rural pilot  ", 200) == "Pursue: fits the Q3 rural pilot"
    typed = "Ksh 25,000 \u2013 \u201cpilot\u201d \U0001f680 \u00f1"  # a dash, quotes, an emoji, an accent
    assert one_line(typed, 200) == typed
    assert one_line("x" * 200, 200) == "x" * 200


@pytest.mark.parametrize("value", [None, "", "   "])
def test_nothing_left_is_no_text(value: str | None) -> None:
    assert one_line(value, 200) is None


@pytest.mark.parametrize(
    "value",
    [
        "two\nlines",
        "carriage\rreturn",
        "a\ttab",
        "nul\x00",
        "del\x7f",
        "zero\u200bwidth",
        "joiner\u200d",
        "mark\u200e",
        "embed\u202aing",
        "over\u202eride",
        "iso\u2066late",
        "\ufeffbom",
        "no\u00a0break",
        "thin\u2009space",
        "ideographic\u3000space",
        "line\u2028separator",
        "para\u2029separator",
        "soft\u00adhyphen",
        "word\u2060joiner",
        "tag\U000e0041",
        "c1\u0085control",
    ],
)
def test_control_format_and_non_ascii_space_characters_are_refused(value: str) -> None:
    assert not is_one_line(value, 200)
    with pytest.raises(ValueError, match="one line of plain text") as refused:
        one_line(value, 200)
    assert value not in str(refused.value)  # the rule is named, never the text


def test_the_cap_counts_the_trimmed_text() -> None:
    assert one_line(" " * 50 + "x" * 200 + " " * 50, 200) == "x" * 200
    with pytest.raises(ValueError, match="at most 200"):
        one_line("x" * 201, 200)
