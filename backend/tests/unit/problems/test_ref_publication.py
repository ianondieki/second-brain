"""A problem reference shows its publication day and seed marker only while the problem is PUBLISHED (P16-C1 fix round
1, reviewer MAJOR 1): the same rule as its label, so no client can build a label the API withholds."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from bridge.models.enums import ProblemSource, ProblemStatus
from bridge.problems.service import _ref, published_facts

PUBLISHED = datetime(2026, 9, 29, 22, 30, tzinfo=UTC)


def row(
    status: ProblemStatus, *, source: ProblemSource = ProblemSource.RESEARCH_AGENT, seeded: bool = True
) -> tuple[object, ...]:
    return (uuid4(), "Clinic queues", source, None, None, None, None, status, PUBLISHED, seeded)


def test_an_archived_research_card_linked_to_an_idea_carries_no_label_day_or_seed_marker() -> None:
    ref = _ref(row(ProblemStatus.ARCHIVED))
    assert ref.label is None
    assert ref.published_at is None
    assert ref.seeded_example is False


def test_a_published_research_card_carries_all_three() -> None:
    ref = _ref(row(ProblemStatus.PUBLISHED))
    assert ref.label is not None
    assert "30 September 2026" in ref.label
    assert (ref.published_at, ref.seeded_example) == (PUBLISHED, True)


def test_the_rule_for_every_status() -> None:
    for status in ProblemStatus:
        shown = published_facts(status, PUBLISHED, True)
        assert shown == ((PUBLISHED, True) if status is ProblemStatus.PUBLISHED else (None, False)), status


def test_a_developer_problem_keeps_its_label_without_publication_facts_when_not_published() -> None:
    ref = _ref(row(ProblemStatus.ARCHIVED, source=ProblemSource.DEVELOPER, seeded=False))
    assert (ref.label, ref.published_at, ref.seeded_example) == ("Developer-reported", None, False)
