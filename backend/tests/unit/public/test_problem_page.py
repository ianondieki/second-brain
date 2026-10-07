"""REQ-UX-03 (P24-B): the public problem page Explore links to, as data.

- The page: the published text, the source in the API's words, the county, the niche with its parent, and a Brief's
  organisation (name and level) only while the statement's join found it listed; null for every other problem.
- The statement: the public predicate on one id, the listed-organisation join, and no person, handle or address; the
  loader reads it as the public reader and has no page for an id it does not find.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine

from bridge.models.enums import OrgVerification, ProblemSource
from bridge.public import feed, queries

AT = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
TOP, CHILD = UUID(int=1), UUID(int=2)


def row(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": uuid4(),
        "title": "Rural towers lose power at night",
        "statement": "Base stations drop off the network when the diesel runs out after dark.",
        "affected_group": "Subscribers in rural counties",
        "source": ProblemSource.ORG_BRIEF,
        "published_at": AT,
        "county_code": "KE-30",
        "county_name": "Nairobi City",
        "niche_id": CHILD,
        "niche_name": "Networks & Telecommunications",
        "parent_id": TOP,
        "parent_name": "ICT",
        "org_verification": OrgVerification.E2,
        "example": False,
    }
    return SimpleNamespace(**(values | overrides))


def test_a_briefs_page_gives_its_listed_organisation_level_only() -> None:
    found = row()
    page = feed.problem_page(found, demo=False)
    assert page.model_dump() == {
        "id": found.id,
        "title": "Rural towers lose power at night",
        "statement": "Base stations drop off the network when the diesel runs out after dark.",
        "affected_group": "Subscribers in rural counties",
        "source": "brief",
        "posted_at": AT,
        "county": {"code": "KE-30", "name": "Nairobi City"},
        "niche": {"id": CHILD, "name": "Networks & Telecommunications", "parent": {"id": TOP, "name": "ICT"}},
        "organisation": {"verification": "e2"},
        "seeded": False,
    }


@pytest.mark.parametrize(
    ("overrides", "source"),
    [
        pytest.param(
            {"source": ProblemSource.ORG_BRIEF, "org_verification": None},
            "brief",
            id="brief-of-an-organisation-not-found-listed",
        ),
        pytest.param({"source": ProblemSource.DEVELOPER}, "developer", id="developer-with-org-columns"),
        pytest.param({"source": ProblemSource.RESEARCH_AGENT}, "research", id="research-card"),
    ],
)
def test_the_organisation_is_null_unless_a_brief_with_a_listed_organisation(
    overrides: dict[str, Any], source: str
) -> None:
    page = feed.problem_page(row(**overrides), demo=False)
    assert (page.source, page.organisation) == (source, None)


def test_a_page_without_county_or_niche_and_a_top_level_niche() -> None:
    bare = feed.problem_page(row(county_code=None, niche_id=None, source=ProblemSource.DEVELOPER), demo=False)
    assert (bare.county, bare.niche) == (None, None)
    top = feed.problem_page(row(niche_id=TOP, niche_name="Health", parent_id=None, parent_name=None), demo=False)
    assert top.niche is not None
    assert (top.niche.name, top.niche.parent) == ("Health", None)


SEEDED_CASES = [(False, False, False), (False, True, True), (True, False, True)]


@pytest.mark.parametrize(("demo", "example", "seeded"), SEEDED_CASES)
def test_a_page_is_seeded_as_its_problem_is(demo: bool, example: bool, seeded: bool) -> None:
    assert feed.problem_page(row(example=example), demo=demo).seeded is seeded


async def test_the_loader_reads_one_problem_as_the_public_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    found = row(source=ProblemSource.DEVELOPER, org_verification=None)
    asked: list[str] = []

    async def read(factory: Any, statement: Any) -> list[Any]:
        asked.append(str(statement).split()[1])
        return [found] if factory == "readable" else []

    monkeypatch.setattr(feed, "read", read)
    page = await feed.problem("readable", found.id, demo=False)  # type: ignore[arg-type]
    assert page is not None
    assert page.id == found.id
    assert await feed.problem("unreadable", found.id, demo=False) is None  # type: ignore[arg-type]
    assert asked == ["problems.id,", "problems.id,"]


def sql(problem_id: UUID) -> str:
    dialect = create_engine("postgresql+psycopg://").dialect  # nothing connects
    compiled = queries.problem_statement(problem_id).compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    return " ".join(str(compiled).split())


def test_the_statement_reads_one_readable_problem_and_a_listed_organisation_only() -> None:
    text = sql(UUID(int=7))
    for clause in (
        "problems.id = '00000000-0000-0000-0000-000000000007'",
        "problems.status = 'published' AND problems.moderation_state = 'clear'",
        "problems.source != 'org_brief' OR",
        "status = 'published' AND problem_briefs_1.visibility = 'public'",
        "LEFT OUTER JOIN organizations AS organizations_1 ON organizations_1.id = problems.org_id AND"
        " organizations_1.verification IN ('unclaimed', 'e1', 'e2') AND organizations_1.delisted_at IS NULL AND"
        " problems.source = 'org_brief'",
    ):
        assert clause in text, clause
    private = ("created_by", "display_name", "email", "handle", "owner", "slug", "verified_domain", "named_orgs")
    private += ("legal_name",)
    for column in private:
        assert column not in text, column
