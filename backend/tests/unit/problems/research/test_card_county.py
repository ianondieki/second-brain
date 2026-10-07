"""REQ-RES-01, REQ-UX-03 (P24-B follow-up): a research card may name its county.

- ``ProblemDraft.county_code`` is optional (null by default): the output schema still requires
  ``injection_suspected`` and nothing else new, so an answer without a county stays valid.
- At save time (``pipeline.county_of``) the code is the model's answer, so it is data: a malformed one never reaches
  the database, one that is not a county of the run's country in the regions table is dropped (the card stays,
  nationwide) and a county run's cards keep the run's county.
- The demo seed's four answers name a plausible county each.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from bridge.llm.prepare import check_schema
from bridge.problems.research import pipeline, synthesis
from bridge.seed.demo.research import seeded_answer


def draft(**overrides: Any) -> synthesis.ProblemDraft:
    values: dict[str, Any] = {
        "title": "Clinics must move claims onto the national digital health system",
        "statement": "Clinics must file claims on the new system.",
        "affected_group": "Clinics",
        "named_orgs": [],
        "citations": [],
    }
    return synthesis.ProblemDraft(**(values | overrides))


def test_a_draft_may_name_a_county_and_need_not() -> None:
    assert draft().county_code is None
    assert draft(county_code="KE-17").county_code == "KE-17"
    schema = check_schema(synthesis.ResearchSynthesis)
    card = schema["$defs"]["ProblemDraft"]
    assert "county_code" in card["properties"]
    assert "county_code" not in card.get("required", [])
    assert schema["required"] == ["injection_suspected", "problems"]
    with pytest.raises(ValueError, match="extra"):
        draft(county="KE-17")  # the schema still forbids anything else


class Db:
    def __init__(self, known: set[tuple[str, str]]) -> None:
        self.known = known
        self.asked: list[dict[str, Any]] = []

    async def scalar(self, statement: Any, params: dict[str, Any]) -> str | None:
        self.asked.append(params)
        assert "FROM regions WHERE code = :code AND kind = 'county' AND parent_code = :country" in str(statement)
        return params["code"] if (params["code"], params["country"]) in self.known else None


def run(county_code: str | None = None) -> Any:
    return SimpleNamespace(id=uuid4(), country="KE", county_code=county_code)


async def test_a_known_county_of_the_runs_country_is_kept() -> None:
    db = Db({("KE-17", "KE")})
    assert await pipeline.county_of(db, run(), "KE-17") == "KE-17"  # type: ignore[arg-type]
    assert db.asked == [{"code": "KE-17", "country": "KE"}]


@pytest.mark.parametrize("code", ["KE-99", "UG-102"], ids=["unknown", "another-country"])
async def test_an_unknown_county_is_dropped(code: str) -> None:
    db = Db({("UG-102", "UG"), ("KE-17", "KE")})
    assert await pipeline.county_of(db, run(), code) is None  # type: ignore[arg-type]
    assert len(db.asked) == 1


@pytest.mark.parametrize(
    "code",
    [None, "", "Kisumu", "ke-17", "KE-17 ", "KE-17'; DROP TABLE problems; --", "KE-123456", "KE_17"],
    ids=["none", "empty", "a-name", "lower-case", "trailing-space", "injection", "too-long", "underscore"],
)
async def test_a_malformed_county_never_reaches_the_database(code: str | None) -> None:
    db = Db({("KE-17", "KE")})
    assert await pipeline.county_of(db, run(), code) is None  # type: ignore[arg-type]
    assert db.asked == []


async def test_a_county_runs_cards_keep_the_runs_county() -> None:
    db = Db({("KE-17", "KE"), ("KE-30", "KE")})
    assert await pipeline.county_of(db, run("KE-30"), "KE-17") is None  # type: ignore[arg-type]
    assert db.asked == []


@pytest.mark.parametrize(
    ("niche", "county"),
    [
        ("networks-telecommunications", "KE-30"),
        ("agriculture", "KE-44"),
        ("health", "KE-17"),
        ("microfinance-saccos", "KE-30"),
    ],
)
def test_each_seeded_answer_names_its_county(niche: str, county: str) -> None:
    [card] = seeded_answer(niche).problems
    assert card.county_code == county
