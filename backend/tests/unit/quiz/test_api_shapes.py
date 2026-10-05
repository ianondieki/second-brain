"""REQ-DEV-01 (D-59; P22 card A test A3, the code half): the quiz API's mapping of the database's refusals of an
attempt, and the one-line notes and reasons of flags and pulls (whitespace collapsed, no control character, at most
300 characters)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from bridge.admin.quiz import QuizPullIn
from bridge.quiz.router import ATTEMPT_UNIQUE, QuizFlagIn, _attempt_refusal


class Refused(Exception):
    def __init__(self, sqlstate: str, constraint: str | None = None) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate
        self.diag = SimpleNamespace(constraint_name=constraint)


def refusal(sqlstate: str, constraint: str | None = None) -> tuple[int, str] | None:
    found = _attempt_refusal(DBAPIError("INSERT", {}, Refused(sqlstate, constraint)))
    return None if found is None else (found.status_code, found.detail["code"])  # type: ignore[index]


def test_the_attempts_refusals_map_to_their_codes() -> None:
    assert refusal("23505", ATTEMPT_UNIQUE) == (409, "already_played")
    assert refusal("42501") == (409, "set_closed")  # the insert policy: the set's day ended since it was read
    assert refusal("55000") == (404, "no_quiz")  # the scoring trigger: not an approved set
    assert refusal("23505", "another_key") is None
    assert refusal("40001") is None


def test_a_flags_note_is_one_line_of_at_most_300_characters() -> None:
    assert QuizFlagIn(reason="other", note="  two\n\tlines  ").note == "two lines"
    assert QuizFlagIn(reason="other", note=" \n ").note is None
    assert QuizFlagIn(reason="other").note is None
    assert QuizFlagIn(reason="other", note="x" * 300).note == "x" * 300
    for note in ("x" * 301, "a\u0000b", "bell\u0007", "c1\u0085x\u0090"):
        with pytest.raises(ValidationError):
            QuizFlagIn(reason="other", note=note)
    with pytest.raises(ValidationError):
        QuizFlagIn(reason="spam")


def test_a_pulls_reason_is_one_line_of_1_to_300_characters() -> None:
    assert QuizPullIn(reason=" The key\nis wrong. ").reason == "The key is wrong."
    for reason in ("", "   ", "x" * 301, "a\u0001b"):
        with pytest.raises(ValidationError):
            QuizPullIn(reason=reason)
