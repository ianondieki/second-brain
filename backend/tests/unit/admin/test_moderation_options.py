"""REQ-MOD-01 queue (REQ-ADM-01; PLAN §8 P15): what the moderation queue tells a moderator, in plain code.

``decision_options`` gives the decisions the decision route accepts for a case and, when one is refused, the code the
route answers (the database still decides: ``app_moderate_*`` refuses own content and non-staff). ``flagged_fields``
reads the Tier-1 field names out of the pre-screen's classifier output, whatever shape ``merge`` gave it, and ignores
anything that is not a field name."""

from __future__ import annotations

from typing import Any

import pytest

from bridge.admin.moderation import _CURRENT_TEXT, TIER1_FIELDS, decision_options, flagged_fields


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ({}, (["approve", "reject"], None)),
        ({"subject_type": "problem"}, (["approve", "reject"], None)),
        ({"vulnerable": True}, (["reject"], "cannot_approve_vulnerability")),
        ({"own": True}, ([], "own_content")),
        ({"own": True, "vulnerable": True}, ([], "own_content")),
        ({"found": False}, ([], "subject_gone")),
        ({"subject_type": "org_claim", "found": False}, ([], "unsupported_subject")),
        ({"subject_type": "message"}, ([], "unsupported_subject")),
        ({"unresolved": False}, ([], "already_decided")),
        ({"unresolved": False, "subject_type": "org_claim"}, ([], "already_decided")),
    ],
)
def test_decision_options(case: dict[str, Any], expected: tuple[list[str], str | None]) -> None:
    given: dict[str, Any] = {
        "unresolved": True,
        "subject_type": "proposal",
        "found": True,
        "own": False,
        "vulnerable": False,
    } | case
    assert decision_options(**given) == expected


@pytest.mark.parametrize(
    ("classifier", "expected"),
    [
        (None, []),
        ({"engine": "rules", "labels": ["x"], "fields": ["summary", "title"]}, ["summary", "title"]),
        ({"screens": [{"fields": ["summary"]}, {"fields": ["title", "summary"]}]}, ["summary", "title"]),
        ({"fields": "summary"}, []),
        ({"fields": ["summary", 3, None, ""]}, ["summary"]),
        ({"screens": "rules"}, []),
        ({"screens": [None, {"fields": ["impact_claims"]}]}, ["impact_claims"]),
        (["summary"], []),
    ],
)
def test_flagged_fields(classifier: Any, expected: list[str]) -> None:
    assert flagged_fields(classifier) == expected


def test_a_decision_screens_the_same_tier1_fields_the_queue_shows() -> None:
    for subject, fields in TIER1_FIELDS.items():
        statement = str(_CURRENT_TEXT[subject])
        assert statement.startswith(f"SELECT {', '.join(fields)} FROM "), subject
    assert set(_CURRENT_TEXT) == set(TIER1_FIELDS)
