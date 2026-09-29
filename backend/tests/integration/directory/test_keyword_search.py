"""Directory keyword search (P4, REQ-PROP-03 picker; docs/spec/06 6.2 and 6.3): ``GET /api/directory/orgs?q=`` matches
each word of the query against the organisation's name, its niches (the niche or its parent) or its county, every word
somewhere (AND). Grouping under niche headings and cursor paging stay as T2.6a built them.

Fixture organisations carry a random tag in their names and niches, so each query here matches only this module's
rows whatever else the directory holds.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.seed.reference import seed_all
from tests.integration import world as w
from tests.integration.api import make_client, sign_in_as


@dataclass(frozen=True, slots=True)
class Orgs:
    tag: str
    alpha: str  # slug: Solar niche (parent Energy) and Water niche, Mombasa
    beta: str  # slug: no niche, Nairobi City
    gamma: str  # slug: Water niche, Kisumu
    solar_label: str
    water_label: str


async def _org(conn: AsyncConnection, name: str, slug: str, county: str, niches: list[UUID]) -> None:
    org_id = uuid7()
    await conn.execute(
        text(
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, county_code)"
            " VALUES (:id, 'company', :name, :slug, 'admin', 'unclaimed', :county)"
        ),
        {"id": org_id, "name": name, "slug": slug, "county": county},
    )
    for niche in niches:
        await conn.execute(
            text("INSERT INTO org_niches (org_id, niche_id) VALUES (:org, :niche)"), {"org": org_id, "niche": niche}
        )


@pytest.fixture(scope="module")
async def orgs(owner_engine: AsyncEngine) -> AsyncIterator[Orgs]:
    tag = "kw" + uuid4().hex[:8]
    energy, solar, water = uuid7(), uuid7(), uuid7()
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())
        await conn.execute(
            text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, :name)"),
            {"id": energy, "slug": f"energy-{tag}", "name": f"Energy {tag}"},
        )
        for niche_id, slug, name in ((solar, f"solar-{tag}", "Solar power"), (water, f"water-{tag}", "Water")):
            await conn.execute(
                text("INSERT INTO niches (id, parent_id, slug, name_en) VALUES (:id, :parent, :slug, :name)"),
                {"id": niche_id, "parent": energy, "slug": slug, "name": f"{name} {tag}"},
            )
        await _org(conn, f"Alpha Grid {tag}", f"alpha-{tag}", "KE-28", [solar, water])
        await _org(conn, f"Beta Works {tag}", f"beta-{tag}", "KE-30", [])
        await _org(conn, f"Gamma Pumps {tag}", f"gamma-{tag}", "KE-17", [water])
    try:
        yield Orgs(
            tag=tag,
            alpha=f"alpha-{tag}",
            beta=f"beta-{tag}",
            gamma=f"gamma-{tag}",
            solar_label=f"Energy {tag} › Solar power {tag}",
            water_label=f"Energy {tag} › Water {tag}",
        )
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("DELETE FROM organizations WHERE slug LIKE :mine"), {"mine": f"%-{tag}"})
            await conn.execute(
                text("DELETE FROM niches WHERE slug LIKE :mine AND parent_id IS NOT NULL"), {"mine": f"%-{tag}"}
            )
            await conn.execute(text("DELETE FROM niches WHERE slug LIKE :mine"), {"mine": f"%-{tag}"})


@pytest.fixture
async def client(app_engine: AsyncEngine, owner_engine: AsyncEngine, orgs: Orgs) -> AsyncIterator[httpx.AsyncClient]:
    async with owner_engine.begin() as conn:
        user_id = await w.add_user(conn, f"kw-{uuid4().hex[:10]}@example.test", "Searcher")
    async with make_client(app_engine) as c:
        await sign_in_as(c, app_engine, user_id, mfa_verified=False)
        yield c


async def search(client: httpx.AsyncClient, q: str, **params: Any) -> list[tuple[str | None, str]]:
    """Every (heading, slug) pair for ``q``, walking the cursor."""
    found: list[tuple[str | None, str]] = []
    cursor: str | None = None
    while True:
        query = {"q": q, **params, **({"cursor": cursor} if cursor else {})}
        response = await client.get("/api/directory/orgs", params=query)
        assert response.status_code == 200, response.text
        page = response.json()
        for group in page["groups"]:
            heading = group["niche"]["label"] if group["niche"] else None
            found.extend((heading, card["slug"]) for card in group["orgs"])
        cursor = page["next_cursor"]
        if cursor is None:
            return found


def slugs(pairs: list[tuple[str | None, str]]) -> set[str]:
    return {slug for _, slug in pairs}


async def test_a_word_matches_the_name(client: httpx.AsyncClient, orgs: Orgs) -> None:
    assert slugs(await search(client, orgs.tag)) == {orgs.alpha, orgs.beta, orgs.gamma}
    assert slugs(await search(client, f"pumps {orgs.tag}")) == {orgs.gamma}
    assert slugs(await search(client, f"PUMPS {orgs.tag.upper()}")) == {orgs.gamma}  # case-insensitive


async def test_a_word_matches_a_niche_or_its_parent(client: httpx.AsyncClient, orgs: Orgs) -> None:
    solar = await search(client, f"solar {orgs.tag}")
    assert slugs(solar) == {orgs.alpha}
    # A matching organisation is listed under each of its headings (the page is still a list of pairs).
    assert sorted(solar, key=str) == sorted([(orgs.solar_label, orgs.alpha), (orgs.water_label, orgs.alpha)], key=str)
    assert slugs(await search(client, f"water {orgs.tag}")) == {orgs.alpha, orgs.gamma}
    assert slugs(await search(client, f"energy {orgs.tag}")) == {orgs.alpha, orgs.gamma}  # the parent niche


async def test_a_word_matches_the_county(client: httpx.AsyncClient, orgs: Orgs) -> None:
    assert slugs(await search(client, f"mombasa {orgs.tag}")) == {orgs.alpha}
    assert slugs(await search(client, f"Nairobi {orgs.tag}")) == {orgs.beta}
    assert slugs(await search(client, f"kisumu water {orgs.tag}")) == {orgs.gamma}


async def test_every_word_must_match_somewhere(client: httpx.AsyncClient, orgs: Orgs) -> None:
    assert await search(client, f"mombasa pumps {orgs.tag}") == []  # Mombasa is Alpha's, pumps Gamma's
    assert await search(client, f"{orgs.tag} nowhere") == []
    assert slugs(await search(client, f"  {orgs.tag}   grid  ")) == {orgs.alpha}  # extra spaces are ignored


async def test_filters_and_paging_still_apply(client: httpx.AsyncClient, orgs: Orgs) -> None:
    assert slugs(await search(client, orgs.tag, county="KE-17")) == {orgs.gamma}
    assert slugs(await search(client, orgs.tag, niche=f"solar-{orgs.tag}")) == {orgs.alpha}
    whole = await search(client, orgs.tag, limit=100)
    assert await search(client, orgs.tag, limit=1) == whole
    assert len(whole) == 4  # Alpha twice (two headings), Beta under the null heading last, Gamma once
    assert whole[-1] == (None, orgs.beta)
