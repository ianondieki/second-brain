"""Discover and Home render the problem's label in the reader's language (REQ-TREND-02, P12-F MINOR 2).

The API's ``label`` is English; the web app builds its own from ``source``, ``seeded_example`` and ``published_at``,
so every problem Discover sends (a trending problem, a recommendation, a project's "Solves" problem) carries both.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from bridge.matching.discover import NicheInfo, Niches, problem_out, problem_ref
from bridge.matching.trend_facts import ProblemFact

PUBLISHED = datetime(2026, 9, 29, 22, 30, tzinfo=UTC)  # 30 September in Nairobi


def fact(
    *, source: str = "research_agent", seeded: bool = False, published: datetime | None = PUBLISHED
) -> ProblemFact:
    return ProblemFact(
        id=uuid4(),
        source=source,
        title="Clinic queues",
        statement="Patients wait all day.",
        niche_id=None,
        parent_id=None,
        country="KE",
        country_name="Kenya",
        county_code=None,
        county_name=None,
        created_by=None,
        published_at=published,
        confidence=None,
        status="published",
        seeded_example=seeded,
    )


TREE = Niches([NicheInfo(uuid4(), "ict", "ICT", None)])


def test_a_seeded_research_card_says_so_with_its_publication_moment() -> None:
    problem = problem_out(fact(seeded=True), TREE)
    assert problem.seeded_example is True
    assert problem.published_at == PUBLISHED
    ref = problem_ref(fact(seeded=True), TREE)
    assert (ref.seeded_example, ref.published_at) == (True, PUBLISHED)
    assert ref.label is not None
    assert "30 September 2026" in ref.label


def test_a_live_research_card_is_not_a_seeded_example() -> None:
    ref = problem_ref(fact(seeded=False), TREE)
    assert ref.seeded_example is False
    assert ref.published_at == PUBLISHED
    assert ref.model_dump()["seeded_example"] is False


def test_a_developer_problem_carries_the_fields_too() -> None:
    ref = problem_ref(fact(source="developer", published=None), TREE)
    assert (ref.seeded_example, ref.published_at, ref.label) == (False, None, "Developer-reported")
    assert {"seeded_example", "published_at"} <= set(ref.model_dump())
