"""REQ-DEV-03: a team-up note and a team message as the API takes them (NFKC, line breaks as ``\\n``, control and
format characters refused, never removed; the contact-details rule does not apply between developers)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bridge.teams.schemas import InvitationIn, TeamMessageIn
from bridge.teams.text import clean_message, clean_note

SOME = "01890000-0000-7000-8000-000000000000"


def test_a_note_is_normalised_and_trimmed() -> None:
    assert clean_note(None) is None
    assert clean_note("   \n ") is None
    assert clean_note("  \uff28ello\r\nthere\tfriend  ") == "Hello\nthere\tfriend"
    assert clean_note("Call 0712 345 678 or https://example.com") == "Call 0712 345 678 or https://example.com"
    assert clean_note("a" * 300) == "a" * 300


@pytest.mark.parametrize(
    "bad", ["a" * 301, "bell\x07", "esc\x1b[31m", "c1\x85x", "rtl\u202eoverride", "zw\u200bsp", "x\ufeffbom"]
)
def test_a_note_refuses_control_and_format_characters_and_length(bad: str) -> None:
    with pytest.raises(ValueError, match="note"):
        clean_note(bad)


def test_a_message_keeps_lines_and_joiners() -> None:
    assert clean_message("Line one\r\nline two\rthree") == "Line one\nline two\nthree"
    family = "\U0001f468‍\U0001f469‍\U0001f467"
    assert clean_message(f"Team {family}") == f"Team {family}"
    assert clean_message("\ufb01le") == "file"
    assert len(clean_message("x" * 4000)) == 4000


@pytest.mark.parametrize("bad", ["", "  \n\t ", "x" * 4001, "nul\x00", "bell\x07"])
def test_a_message_refuses_blank_long_and_control(bad: str) -> None:
    with pytest.raises(ValueError, match="message"):
        clean_message(bad)


def test_the_bodies_validate_and_never_echo_the_text() -> None:
    assert InvitationIn(to_user_id=SOME, problem_id=SOME, note=" hi ").note == "hi"
    with pytest.raises(ValidationError) as caught:
        TeamMessageIn(body="secret\x07")
    assert "control" in str(caught.value)
    with pytest.raises(ValidationError):
        InvitationIn(to_user_id=SOME, problem_id=SOME, note="x", extra=1)  # type: ignore[call-arg]
