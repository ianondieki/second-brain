"""REQ-RES-02 / AC-RES-4 (prototype part): problem cards filter by niche, country and county, with a second country in
the fixtures (``tests/fixtures/sources/ug.yaml``'s country, UG) so the country filter is exercised; the card detail
shows its region and citations. AC-RES-2: a research ``candidate`` is on no public endpoint (the list, the detail,
a proposal's linked problems), whoever asks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from bridge.models.enums import ProblemSource, ProblemStatus
from bridge.problems.service import label_for
from tests.integration.api import make_client, sign_in_as
from tests.integration.problems.research_rig import TELECOM_DRAFT, ResearchWorld, answer, execute, llm_runtime, start

PUBLISHED = datetime(2026, 9, 29, 21, 30, tzinfo=UTC)  # 30 September in Nairobi


async def _problem(conn: Any, niche: UUID, author: UUID, *, country: str, county: str | None, title: str) -> UUID:
    problem_id = uuid7()
    await conn.execute(
        text(
            "INSERT INTO problems (id, source, niche_id, country, county_code, title, statement, status, created_by,"
            " moderation_state, published_at) VALUES (:id, 'developer', :niche, :country, :county, :title,"
            " 'A statement.', 'published', :author, 'clear', :at)"
        ),
        {
            "id": problem_id,
            "niche": niche,
            "country": country,
            "county": county,
            "title": title,
            "author": author,
            "at": PUBLISHED,
        },
    )
    return problem_id


@pytest.fixture
async def regions(owner_engine: AsyncEngine) -> None:
    """Kenya's two counties as the reference seed has them, and Uganda as a country only (no county row, so the
    shared database's county count stays the reference seed's 47)."""
    async with owner_engine.begin() as conn:
        for code, parent, kind, name in (
            ("KE", None, "country", "Kenya"),
            ("KE-30", "KE", "county", "Nairobi City"),
            ("KE-22", "KE", "county", "Kiambu"),
            ("UG", None, "country", "Uganda"),
        ):
            await conn.execute(
                text(
                    "INSERT INTO regions (code, parent_code, kind, name) VALUES (:c, :p, CAST(:k AS region_kind), :n)"
                    " ON CONFLICT DO NOTHING"
                ),
                {"c": code, "p": parent, "k": kind, "n": name},
            )


@pytest.fixture
async def reader(research_world: ResearchWorld, app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app_engine) as client:
        await sign_in_as(client, app_engine, research_world.developer, mfa_verified=True)
        yield client


async def test_ac_res_4_cards_filter_by_niche_country_and_county(
    research_world: ResearchWorld, owner_engine: AsyncEngine, reader: httpx.AsyncClient, regions: None
) -> None:
    niche = research_world.niche_ids["agriculture"]
    async with owner_engine.begin() as conn:
        kenya = await _problem(conn, niche, research_world.developer, country="KE", county=None, title="Kenya wide")
        nairobi = await _problem(conn, niche, research_world.developer, country="KE", county="KE-30", title="Nairobi")
        kiambu = await _problem(conn, niche, research_world.developer, country="KE", county="KE-22", title="Kiambu")
        kampala = await _problem(conn, niche, research_world.developer, country="UG", county=None, title="Kampala")
    slug = research_world.slugs["agriculture"]

    async def ids(**params: str) -> set[str]:
        response = await reader.get("/api/problems", params={"niche": slug, **params})
        assert response.status_code == 200, response.text
        return {item["id"] for item in response.json()["items"]}

    assert await ids() == {str(p) for p in (kenya, nairobi, kiambu, kampala)}
    assert await ids(country="KE") == {str(kenya), str(nairobi), str(kiambu)}
    assert await ids(country="UG") == {str(kampala)}
    assert await ids(county="KE-30") == {str(nairobi)}
    assert await ids(country="KE", county="KE-22") == {str(kiambu)}
    assert await ids(country="UG", county="KE-30") == set()
    assert await ids(country="TZ") == set()
    for bad in ({"country": "ke"}, {"country": "KEN"}, {"county": "Nairobi"}, {"county": "KE-"}):
        assert (await reader.get("/api/problems", params=bad)).status_code == 422, bad
    detail = (await reader.get(f"/api/problems/{kampala}")).json()
    assert (detail["country"], detail["county_code"], detail["label"], detail["citations"]) == (
        "UG",
        None,
        "Developer-reported",
        [],
    )


async def test_ac_res_2_a_candidate_is_on_no_public_endpoint(
    research_world: ResearchWorld,
    app_engine: AsyncEngine,
    owner_engine: AsyncEngine,
    reader: httpx.AsyncClient,
) -> None:
    run_id = await start(app_engine, research_world, "networks-telecommunications")
    outcome = await execute(app_engine, research_world, run_id, llm_runtime(answer(TELECOM_DRAFT)))
    assert outcome is not None
    [candidate] = outcome.candidates
    async with make_client(app_engine) as admin:
        await sign_in_as(admin, app_engine, research_world.admin, mfa_verified=True)
        for client in (reader, admin):
            assert (await client.get(f"/api/problems/{candidate}")).status_code == 404
            for params in ({}, {"niche": research_world.slugs["networks-telecommunications"]}, {"q": "termination"}):
                items = (await client.get("/api/problems", params=params | {"limit": "100"})).json()["items"]
                assert str(candidate) not in [i["id"] for i in items]
    async with make_client(app_engine) as anonymous:
        assert (await anonymous.get(f"/api/problems/{candidate}")).status_code == 401
    assert (await reader.get(f"/api/problems/{uuid7()}")).status_code == 404


def test_the_research_label_names_the_review_day_in_nairobi() -> None:
    assert label_for(ProblemSource.RESEARCH_AGENT, ProblemStatus.PUBLISHED, PUBLISHED, False) == (
        "AI-drafted, human-reviewed on 30 September 2026"
    )
    assert label_for(ProblemSource.RESEARCH_AGENT, ProblemStatus.PUBLISHED, PUBLISHED, True) == (
        "Seeded example for the demo (not a live AI result), human-reviewed on 30 September 2026"
    )
    assert label_for(ProblemSource.RESEARCH_AGENT, ProblemStatus.CANDIDATE, None, False) is None
    assert label_for(ProblemSource.DEVELOPER, ProblemStatus.PUBLISHED, PUBLISHED, False) == "Developer-reported"
    assert label_for(ProblemSource.ORG_BRIEF, ProblemStatus.PUBLISHED, PUBLISHED, False) is None
