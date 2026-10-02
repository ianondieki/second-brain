"""REQ-DIR-05 (docs/spec/06 6.2, 6.5): the plain-code rules of a Problem Brief.

- Its label is "Posted by <organisation>" (the organisation the reader may see; none when it is hidden).
- Its state for the organisation's list is decided from the Brief's and its problem's states.
- Its text is public: cleaned to plain text, no contact details (the sanitiser's rule, in a Brief's words), within
  the ProblemCard's lengths, title and statement not blank.
- Its budget band is a code from ``weights_v1.yaml``; an unknown stored code shows no band.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bridge.matching.config import get_weights
from bridge.models.enums import BriefStatus, ModerationState, ProblemSource, ProblemStatus
from bridge.problems.brief_rules import MAX_LENGTHS, MESSAGES, band_out, brief_state, text_errors
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
