"""AC-REPO-5 and the explicit half of AC-REPO-3 (REQ-REPO-02; docs/spec/06 6.1 Browse repo): an organisation member
keyword-searches Tier-1 teasers with the niche, county, maturity, ask and linked-Problem filters; results include every
matching published teaser and no drafts, held or hidden teasers, and no Tier-2 field, embedding or tag data.

Every teaser here carries a random token, so the queries match only this test's proposals.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.seed.reference import seed_all
from tests.integration.api import make_client, sign_in_as
from tests.integration.proposals.helpers import (
    TIER2_MARKERS,
    Developers,
    ProposalWorld,
    create,
    draft_body,
    publish,
    published,
)

ITEM_KEYS = {"id", "owner_handle", "cert_id", "version_no", "published_at", "teaser"}
TEASER_KEYS = {
    "title",
    "niche",
    "country",
    "county_code",
    "maturity",
    "ask",
    "problem_statement",
    "impact_claims",
    "summary",
}


@dataclass(frozen=True, slots=True)
class Catalogue:
    token: str
    in_title: str  # Solar niche, Nairobi City, prototype, pilot, linked to the world's problem
    in_summary: str  # Solar niche, Mombasa, MVP, sale, linked to the world's problem
    other_niche: str  # Health niche, no county, idea, licence, linked to a new problem only
    draft: str
    held: str
    hidden: str
    health_slug: str


async def _health_niche(owner_engine: AsyncEngine, token: str) -> tuple[UUID, str]:
    niche_id, slug = uuid7(), f"health-{token}"
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())  # the counties
        await conn.execute(
            text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, :name)"),
            {"id": niche_id, "slug": slug, "name": f"Health {token}"},
        )
    return niche_id, slug


@pytest.fixture
async def catalogue(developers: Developers, proposal_world: ProposalWorld, owner_engine: AsyncEngine) -> Catalogue:
    token = "zq" + uuid4().hex[:10]
    health_id, health_slug = await _health_niche(owner_engine, token)
    first, second, third = await developers(), await developers(), await developers()
    in_title = await published(
        first, proposal_world, title=f"Cold-chain alerts {token}", county_code="KE-30", maturity="prototype"
    )
    in_summary = await published(
        first,
        proposal_world,
        title="Solar kiosks",
        summary=f"Kiosks keep phones charged ({token}).",
        county_code="KE-28",
        maturity="mvp",
        ask="sale",
    )
    body = draft_body(proposal_world, link=False, title=f"Clinic queues {token}", niche_id=str(health_id))
    body["teaser"] |= {"maturity": "idea", "ask": "licence"}
    body["new_problem"] = {"title": f"Queues {token}", "statement": "Patients wait all day."}
    other = await create(second, body)
    assert (await publish(second, other["id"])).status_code == 200
    draft = await create(first, draft_body(proposal_world, title=f"Unpublished {token}"))
    held = await published(
        second,
        proposal_world,
        title=f"Outage map {token}",
        summary=f"Unlike the corrupt {proposal_world.org_brand}, we report outages.",
    )
    assert held["moderation"]["state"] == "held"
    hidden = await published(third, proposal_world, title=f"Retired {token}")
    assert (await third.delete(f"/api/me/proposals/{hidden['proposal_id']}")).status_code == 200
    return Catalogue(
        token=token,
        in_title=in_title["proposal_id"],
        in_summary=in_summary["proposal_id"],
        other_niche=other["id"],
        draft=draft["id"],
        held=held["proposal_id"],
        hidden=hidden["proposal_id"],
        health_slug=health_slug,
    )


@pytest.fixture
async def member(app_engine: AsyncEngine, owner_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """A reviewer of an E2 organisation (Browse repo is on every org plan)."""
    user_id, org_id = uuid7(), uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, email, display_name, email_verified_at) VALUES (:id, :email, 'Rev', now())"),
            {"id": user_id, "email": f"browse-{uuid4().hex[:10]}@example.test"},
        )
        await conn.execute(
            text(
                "INSERT INTO organizations (id, kind, legal_name, slug, source, verification)"
                " VALUES (:id, 'company', 'Browsing Ltd', :slug, 'admin', 'e2')"
            ),
            {"id": org_id, "slug": f"browsing-{org_id.hex}"},
        )
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, '{reviewer}')"),
            {"id": uuid7(), "org": org_id, "user": user_id},
        )
    async with make_client(app_engine) as client:
        await sign_in_as(client, app_engine, user_id, mfa_verified=True)
        yield client


async def walk(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        response = await client.get("/api/proposals", params={**params, **({"cursor": cursor} if cursor else {})})
        assert response.status_code == 200, response.text
        page = response.json()
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def ids(items: list[dict[str, Any]]) -> list[str]:
    return [item["id"] for item in items]


async def test_keyword_search_finds_every_published_teaser_and_nothing_else(
    member: httpx.AsyncClient, catalogue: Catalogue, proposal_world: ProposalWorld
) -> None:
    found = await walk(member, q=catalogue.token)
    assert set(ids(found)) == {catalogue.in_title, catalogue.in_summary, catalogue.other_niche}
    assert ids(found)[-1] == catalogue.in_summary  # a title match ranks above a summary match
    by_id = {item["id"]: item for item in found}
    teaser = by_id[catalogue.in_title]["teaser"]
    assert teaser["title"] == f"Cold-chain alerts {catalogue.token}"
    assert teaser["niche"]["label"] == proposal_world.niche_label
    assert by_id[catalogue.in_title]["cert_id"]
    assert by_id[catalogue.in_title]["owner_handle"].startswith("dev-")
    # Drafts, held and hidden teasers are never found, whatever the query.
    for hidden in (catalogue.draft, catalogue.held, catalogue.hidden):
        assert hidden not in ids(await walk(member, q=catalogue.token))
        assert hidden not in ids(await walk(member, limit=50))
    assert await walk(member, q=f"{catalogue.token} nothingmatches") == []


async def test_filters_niche_county_maturity_ask_and_problem(
    member: httpx.AsyncClient, catalogue: Catalogue, proposal_world: ProposalWorld
) -> None:
    q = catalogue.token
    solar = {catalogue.in_title, catalogue.in_summary}
    assert set(ids(await walk(member, q=q, niche=proposal_world.niche_slug))) == solar
    assert set(ids(await walk(member, q=q, niche=proposal_world.parent_slug))) == solar  # a parent includes children
    assert ids(await walk(member, q=q, niche=catalogue.health_slug)) == [catalogue.other_niche]
    assert ids(await walk(member, q=q, county="KE-30")) == [catalogue.in_title]
    assert set(ids(await walk(member, q=q, county=["KE-30", "KE-28"]))) == solar
    assert ids(await walk(member, q=q, maturity="mvp")) == [catalogue.in_summary]
    assert ids(await walk(member, q=q, ask="licence")) == [catalogue.other_niche]
    assert set(ids(await walk(member, q=q, ask=["pilot", "sale"]))) == solar
    assert set(ids(await walk(member, q=q, problem=str(proposal_world.problem_id)))) == solar
    assert ids(await walk(member, q=q, maturity="live")) == []
    # Filters without keywords: every published teaser of the niche, this test's among them.
    assert ids(await walk(member, niche=catalogue.health_slug)) == [catalogue.other_niche]


async def test_results_are_tier1_only(member: httpx.AsyncClient, catalogue: Catalogue) -> None:
    """AC-REPO-3 (explicit test): the Tier-1 allow-list is the whole item; no Tier-2 text, embedding or tag data."""
    response = await member.get("/api/proposals", params={"q": catalogue.token})
    assert response.status_code == 200
    for marker in TIER2_MARKERS:
        assert marker not in response.text
    for item in response.json()["items"]:
        assert set(item) == ITEM_KEYS
        assert set(item["teaser"]) == TEASER_KEYS
        assert item["teaser"]["niche"] is None or set(item["teaser"]["niche"]) == {"id", "slug", "label"}


async def test_paging_walks_every_result_once(member: httpx.AsyncClient, catalogue: Catalogue) -> None:
    whole = await walk(member, q=catalogue.token, limit=50)
    assert await walk(member, q=catalogue.token, limit=1) == whole
    assert await walk(member, niche=catalogue.health_slug, limit=1) == await walk(member, niche=catalogue.health_slug)


def forged(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-cursor",
        forged([True, "2026-09-29T10:00:00+00:00", str(uuid7())]),
        forged([0.5, "2026-09-29T10:00:00", str(uuid7())]),  # no time zone
        forged([0.5, 5, str(uuid7())]),
        forged([0.5, "2026-09-29T10:00:00+00:00", ["x"]]),
        forged([float("nan"), "2026-09-29T10:00:00+00:00", str(uuid7())]),
    ],
)
async def test_a_forged_cursor_answers_400(member: httpx.AsyncClient, cursor: str) -> None:
    response = await member.get("/api/proposals", params={"cursor": cursor})
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "invalid_cursor"


async def test_bad_parameters_answer_422_and_signed_out_callers_401(
    member: httpx.AsyncClient, app_engine: AsyncEngine
) -> None:
    assert (await member.get("/api/proposals", params={"q": "a\x00b"})).status_code == 422
    assert (await member.get("/api/proposals", params={"county": "030"})).status_code == 422
    assert (await member.get("/api/proposals", params={"maturity": "ancient"})).status_code == 422
    assert (await member.get("/api/proposals", params={"limit": 51})).status_code == 422
    too_many = await member.get("/api/proposals", params={"niche": [f"n-{i}" for i in range(51)]})
    assert too_many.status_code == 422
    assert too_many.json()["detail"]["code"] == "too_many_filter_values"
    async with make_client(app_engine) as anonymous:
        assert (await anonymous.get("/api/proposals")).status_code == 401
