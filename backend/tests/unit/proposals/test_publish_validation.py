"""AC-REPO-4/a (REQ-PROP-01): a proposal without at least one linked Problem or without a ``niche_id`` fails the publish
validation, as does any missing Tier-1 field or Tier-1 text the sanitiser refuses (including a new Problem's). Plain
code decides; the API test is ``integration/proposals/test_publish.py::test_publishing_validates_the_draft_first``."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from bridge.proposals import attestations, tier2
from bridge.proposals.editor import PROBLEM_REQUIRED, REQUIRED, attachment_problem, object_key, publish_errors
from bridge.proposals.router import _file_name
from bridge.storage.scanner import EICAR

# SHA-256 of "2026-09-29.1" and the three statements, one per line (bridge.proposals.attestations).
PINNED_DIGEST = "5d40383c0e5543556bbc9221e1df539e66153a74dbd699ce8320101c85e5a9d5"
COMPLETE: dict[str, Any] = {
    "title": "Cold-chain alerts",
    "niche_id": uuid4(),
    "maturity": "prototype",
    "ask": "pilot",
    "problem_statement": "Milk spoils before chilling.",
    "impact_claims": None,
    "summary": "An SMS when a cooler warms.",
}


def codes(values: dict[str, Any], **kwargs: Any) -> list[tuple[str, str]]:
    return [(e.field, e.code) for e in publish_errors(values, **kwargs)]


def test_a_complete_draft_with_a_linked_problem_passes() -> None:
    assert publish_errors(COMPLETE, has_problem=True) == []


def test_without_a_linked_or_new_problem_it_fails() -> None:
    [error] = publish_errors(COMPLETE, has_problem=False)
    assert (error.field, error.code, error.message) == ("problems", "problem_required", PROBLEM_REQUIRED)


def test_without_a_niche_it_fails() -> None:
    assert codes(COMPLETE | {"niche_id": None}, has_problem=True) == [("niche_id", "required")]


@pytest.mark.parametrize("field", list(REQUIRED))
def test_every_required_tier1_field(field: str) -> None:
    assert codes(COMPLETE | {field: None}, has_problem=True) == [(field, "required")]
    assert codes(COMPLETE | {field: ""}, has_problem=True) == [(field, "required")]


def test_the_sanitiser_runs_again_at_publishing() -> None:
    values = COMPLETE | {"summary": "See coldchain.io. " + " ".join(["w"] * 150), "impact_claims": "call 0712345678"}
    assert codes(values, has_problem=True) == [
        ("impact_claims", "contains_phone"),
        ("summary", "contains_domain"),
        ("summary", "too_many_words"),
    ]


def test_a_new_problem_counts_and_is_sanitised() -> None:
    new_problem = {"title": "Spoilage", "statement": "Mail me at a@b.co"}
    assert codes(COMPLETE, has_problem=True, new_problem=new_problem) == [("new_problem.statement", "contains_email")]


@pytest.mark.parametrize(
    ("content_type", "data", "ok"),
    [
        ("application/pdf", b"%PDF-1.7 ...", True),
        ("image/png", b"\x89PNG\r\n\x1a\n...", True),
        ("image/jpeg", b"\xff\xd8\xff\xe0...", True),
        ("text/markdown", "# Notes ✓".encode(), True),
        ("text/plain", b"plain", True),
        ("image/png", b"%PDF-1.7", False),
        ("text/plain", b"\xff\xfe", False),
        ("application/zip", b"PK\x03\x04", False),
        ("text/html", b"<html>", False),
    ],
)
def test_attachment_types(content_type: str, data: bytes, ok: bool) -> None:
    assert (attachment_problem(content_type, data) is None) is ok


def test_object_keys_carry_ids_only() -> None:
    proposal_id, attachment_id = uuid4(), uuid4()
    assert object_key(proposal_id, attachment_id) == f"attachments/{proposal_id}/{attachment_id}"


@pytest.mark.parametrize(
    ("header", "name"),
    [
        (None, "attachment"),
        ("", "attachment"),
        ("deck.pdf", "deck.pdf"),
        ("Pitch%20deck%20%E2%80%94%20v1.pdf", "Pitch deck — v1.pdf"),
        ("..%2F..%2Fetc%2Fpasswd", "passwd"),
        ("C:%5Cdocs%5Cplan.md", "plan.md"),
        ("bad%00name%0A.txt", "badname.txt"),
        ("x" * 300, "x" * 200),
    ],
)
def test_file_names_are_base_names_without_controls(header: str | None, name: str) -> None:
    assert _file_name(header) == name


def test_a_tier2_document_round_trips_and_refuses_anything_else() -> None:
    document = tier2.empty_document() | {"approach": "ünïcode ✓", "links": ["https://example.test"]}
    assert tier2.decode(tier2.encode(document)) == document
    for bad in (b"\xff", b"[1, 2]", b"not json", EICAR):
        with pytest.raises(tier2.Tier2Error) as caught:
            tier2.decode(bad)
        assert caught.value.__cause__ is None  # never chains the decoder's error, which holds the plaintext


def test_the_attestation_text_digest_is_pinned_to_its_version() -> None:
    """Changing the wording without a new VERSION fails here: stored attestations name (version, SHA-256)."""
    assert attestations.VERSION == "2026-09-29.1"
    assert attestations.text_digest().hex() == PINNED_DIGEST
