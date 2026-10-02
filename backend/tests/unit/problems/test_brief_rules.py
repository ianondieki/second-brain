"""REQ-DIR-05 (docs/spec/06 6.2, 6.5): the plain-code rules of a Problem Brief.

- Its label is "Posted by <organisation>" (the organisation the reader may see; none when it is hidden).
- Its state for the organisation's list is decided from the Brief's and its problem's states.
- Its text is public: cleaned to plain text, no contact details (the sanitiser's rule, in a Brief's words), within
  the ProblemCard's lengths, title and statement not blank.
- Its budget band is a code from ``weights_v1.yaml``; an unknown stored code shows no band.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from sqlalchemy.exc import DBAPIError

from bridge.matching.config import get_weights
from bridge.models.enums import BriefStatus, ModerationState, ProblemSource, ProblemStatus
from bridge.problems.brief_rules import MAX_LENGTHS, MESSAGES, band_out, brief_state, is_open, text_errors
from bridge.problems.briefs import _db_refusal
from bridge.problems.service import label_for
from bridge.proposals import sanitise

PUBLISHED = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def test_a_brief_is_posted_by_its_organisation() -> None:
    label = label_for(ProblemSource.ORG_BRIEF, ProblemStatus.PUBLISHED, PUBLISHED, False, org_name="Telco A (fixture)")
    assert label == "Posted by Telco A (fixture)"
    assert label_for(ProblemSource.ORG_BRIEF, ProblemStatus.PUBLISHED, PUBLISHED, False) is None  # hidden org
    assert label_for(ProblemSource.DEVELOPER, ProblemStatus.PUBLISHED, None, False, org_name="X") == (
        "Developer-reported"
    )


@pytest.mark.parametrize(
    ("status", "problem", "moderation", "state"),
    [
        (BriefStatus.PUBLISHED, ProblemStatus.PENDING_REVIEW, ModerationState.CLEAR, "in_review"),
        (BriefStatus.PUBLISHED, ProblemStatus.PENDING_REVIEW, ModerationState.HELD, "in_review"),
        (BriefStatus.DRAFT, ProblemStatus.PUBLISHED, ModerationState.CLEAR, "in_review"),
        (BriefStatus.PUBLISHED, ProblemStatus.PUBLISHED, ModerationState.HELD, "in_review"),
        (BriefStatus.PUBLISHED, ProblemStatus.PUBLISHED, ModerationState.CLEAR, "published"),
        (BriefStatus.PUBLISHED, ProblemStatus.REJECTED, ModerationState.REJECTED, "rejected"),
        (BriefStatus.PUBLISHED, ProblemStatus.PUBLISHED, ModerationState.REJECTED, "rejected"),
        (BriefStatus.CLOSED, ProblemStatus.PUBLISHED, ModerationState.CLEAR, "closed"),
        (BriefStatus.CLOSED, ProblemStatus.REJECTED, ModerationState.REJECTED, "closed"),
        (BriefStatus.PUBLISHED, ProblemStatus.ARCHIVED, ModerationState.CLEAR, "closed"),
    ],
)
def test_the_state_the_organisation_sees(
    status: BriefStatus, problem: ProblemStatus, moderation: ModerationState, state: str
) -> None:
    assert brief_state(status, problem, moderation) == state


def test_brief_text_is_cleaned_and_checked() -> None:
    cleaned, errors = text_errors(
        {"title": " <b>Towers</b> go dark ", "statement": "Diesel runs out at night.", "affected_group": None}
    )
    assert cleaned == {"title": "Towers go dark", "statement": "Diesel runs out at night.", "affected_group": None}
    assert errors == []


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        ({"statement": "Call 0712 345 678 today."}, [("statement", "contains_phone")]),
        ({"title": "Mail briefs@telco.example.com"}, [("title", "contains_email")]),
        ({"affected_group": "See https://telco.example.com"}, [("affected_group", "contains_url")]),
        ({"title": "T" * (MAX_LENGTHS["title"] + 1)}, [("title", "too_long")]),
        ({"statement": "S" * (MAX_LENGTHS["statement"] + 1)}, [("statement", "too_long")]),
        ({"statement": "word " * 121}, [("statement", "too_long")]),  # 605 characters, 121 words (docs/spec/06 6.5)
        ({"affected_group": "A" * (MAX_LENGTHS["affected_group"] + 1)}, [("affected_group", "too_long")]),
        ({"title": "<p> </p>"}, [("title", "blank")]),
        ({"affected_group": "<i></i>"}, []),  # optional: blank means none
    ],
)
def test_brief_text_refusals(fields: dict[str, str], expected: list[tuple[str, str]]) -> None:
    base = {"title": "Towers go dark", "statement": "Diesel runs out at night.", "affected_group": None}
    cleaned, errors = text_errors(base | fields)
    assert [(e.field, e.code) for e in errors] == expected
    for error in errors:
        assert "teaser" not in error.message  # a Brief's own words, not the proposal editor's
        assert "0712" not in error.message
    if not expected and "affected_group" in fields:
        assert cleaned["affected_group"] is None


def test_the_lengths_are_the_problem_cards() -> None:
    assert MAX_LENGTHS == {"title": 90, "statement": 1200, "affected_group": 200}


def test_a_band_is_shown_by_its_code_and_label() -> None:
    weights = get_weights()
    band = band_out("500k_2m", weights)
    assert band is not None
    assert (band.code, band.label) == ("500k_2m", "KES 500,000 to 2 million")
    assert band_out(None, weights) is None
    assert band_out("retired_band", weights) is None


def test_every_contact_code_has_a_brief_sentence() -> None:
    assert set(sanitise.CODES) <= set(MESSAGES)


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("sqlstate", "status", "code"),
    [("55000", 409, "brief_frozen"), ("23503", 422, "invalid_brief"), ("23514", 422, "invalid_brief")],
)
def test_database_refusals_answer_as_the_api(sqlstate: str, status: int, code: str) -> None:
    refusal = _db_refusal(DBAPIError("INSERT", None, _Orig(sqlstate)))
    assert refusal is not None
    assert (refusal.status_code, cast(dict[str, Any], refusal.detail)["code"]) == (status, code)


@pytest.mark.parametrize("sqlstate", ["40001", "42501"])
def test_other_database_errors_are_not_mapped(sqlstate: str) -> None:
    """42501 is worded verification_required only on a write to problem_briefs (``_write_brief``), never here."""
    assert _db_refusal(DBAPIError("INSERT", None, _Orig(sqlstate))) is None


def test_a_statement_is_at_most_120_words() -> None:
    _, fine = text_errors({"title": "T", "statement": "word " * 120, "affected_group": None})
    assert fine == []
    _, [error] = text_errors({"title": "T", "statement": "word\n" * 121, "affected_group": None})
    assert (error.field, error.code, error.message) == ("statement", "too_long", "Keep this to 120 words or fewer.")


@pytest.mark.parametrize(
    ("status", "deadline", "expected"),
    [
        (BriefStatus.PUBLISHED, None, True),
        (BriefStatus.PUBLISHED, date(2026, 10, 2), True),  # the deadline day itself is still open
        (BriefStatus.PUBLISHED, date(2026, 10, 1), False),
        (BriefStatus.CLOSED, None, False),
        (BriefStatus.DRAFT, None, False),
    ],
)
def test_a_brief_is_open_while_published_and_before_its_deadline(
    status: BriefStatus, deadline: date | None, expected: bool
) -> None:
    assert is_open(status, deadline, date(2026, 10, 2)) is expected
