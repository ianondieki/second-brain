"""REQ-PROP-01, REQ-UX-03 (P24-B follow-up): "Describe a new problem" files the problem where the teaser is.

The publish flow's new problem takes the teaser's county (``proposal_versions.county_code``), so Explore can count it
under that county; a teaser with no county files a nationwide problem (NULL). Published at once, held when the
pre-screen holds it.
"""

from __future__ import annotations

import inspect
from typing import Any
from uuid import UUID, uuid4

import pytest

from bridge.problems import service


class Db:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.calls.append((" ".join(str(statement).split()), params))


@pytest.mark.parametrize(("county", "held"), [("KE-30", False), (None, False), ("KE-17", True)])
async def test_the_new_problem_is_filed_in_the_teasers_county(county: str | None, held: bool) -> None:
    db, user, niche = Db(), uuid4(), uuid4()
    problem_id = await service.create_developer_problem(
        db,  # type: ignore[arg-type]
        user_id=user,
        niche_id=niche,
        county_code=county,
        title="Milk spoils on the way",
        statement="Farmers lose a third of the milk before the cooler.",
        held=held,
    )
    [(sql, params)] = db.calls
    assert "county_code" in sql
    assert sql.startswith("INSERT INTO problems (id, source, niche_id, county_code, title")
    assert params == {
        "id": problem_id,
        "niche": niche,
        "county": county,
        "title": "Milk spoils on the way",
        "statement": "Farmers lose a third of the milk before the cooler.",
        "user": user,
        "moderation": "held" if held else "clear",
    }
    assert isinstance(problem_id, UUID)


def test_the_county_is_a_required_argument() -> None:
    """No caller can forget the county: it is keyword-only and has no default."""
    parameter = inspect.signature(service.create_developer_problem).parameters["county_code"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
