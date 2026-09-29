"""Shared fixtures and helpers for the proposal API tests (REQ-PROP-01/02, REQ-MOD-01, REQ-PROV-01/05, REQ-BIL-02).

``proposal_world`` is a two-level niche (``Energy <tag> › Solar <tag>``), a published problem by another developer, a
held problem and a listed directory organisation ("Pwani Telecom Limited <tag>"), written as the owner role.
``developers()`` gives a client signed in as a new developer (D1 by default) with its own in-memory object store and
throwaway Tier-2 key; pass the provenance fixtures' ``wrapper`` to register what it publishes. Import the fixtures
into a test module to use them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.crypto.envelope import KeyWrapper
from bridge.ids import uuid7
from bridge.proposals import attestations
from bridge.storage.objects import InMemoryObjectStore
from tests.integration import world as w
from tests.integration.api import make_client, sign_in_as

# Distinctive Tier-2 text: tests assert it never reaches a Tier-1 response, a log line or an audit payload.
SECRET_APPROACH = "TIER2-SECRET-approach LoRa mesh relays every 90 s"
SECRET_PRICING = "TIER2-SECRET-pricing KES 25,000 setup"
SECRET_LINK = "https://tier2-secret-demo.example.test/walkthrough"
TIER2_MARKERS = ("TIER2-SECRET", "tier2-secret-demo")


@dataclass(frozen=True, slots=True)
class ProposalWorld:
    tag: str
    parent_id: UUID
    niche_id: UUID
    niche_slug: str
    parent_slug: str
    niche_label: str
    problem_id: UUID
    held_problem_id: UUID
    org_name: str
    org_brand: str


async def _exec(engine: AsyncEngine, sql: str, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


@pytest.fixture(scope="session")
async def proposal_world(owner_engine: AsyncEngine) -> ProposalWorld:
    tag = uuid4().hex[:8]
    parent_id, niche_id, org_id = uuid7(), uuid7(), uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, :name)"),
            {"id": parent_id, "slug": f"energy-{tag}", "name": f"Energy {tag}"},
        )
        await conn.execute(
            text("INSERT INTO niches (id, parent_id, slug, name_en) VALUES (:id, :parent, :slug, :name)"),
            {"id": niche_id, "parent": parent_id, "slug": f"solar-{tag}", "name": f"Solar {tag}"},
        )
        author = await w.add_user(conn, f"author-{tag}@example.test", "Author")
        problem_id = await w.add_problem(conn, author, niche_id)
        held_problem_id = await w.add_problem(conn, author, niche_id, moderation_state="held")
        brand = "Pwani" + "".join(chr(ord("a") + int(ch, 16)) for ch in tag)  # letters only, as brand aliases are
        await conn.execute(
            text(
                "INSERT INTO organizations (id, kind, legal_name, slug, source, verification)"
                " VALUES (:id, 'company', :name, :slug, 'seed', 'unclaimed')"
            ),
            {"id": org_id, "name": f"{brand} Telecom Limited", "slug": f"pwani-telecom-{tag}"},
        )
    return ProposalWorld(
        tag=tag,
        parent_id=parent_id,
        niche_id=niche_id,
        niche_slug=f"solar-{tag}",
        parent_slug=f"energy-{tag}",
        niche_label=f"Energy {tag} › Solar {tag}",
        problem_id=problem_id,
        held_problem_id=held_problem_id,
        org_name=f"{brand} Telecom Limited",
        org_brand=brand,
    )


async def add_developer(owner_engine: AsyncEngine, *, level: str = "d1") -> UUID:
    user_id = uuid7()
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (id, email, display_name, email_verified_at) VALUES (:id, :email, 'Dev', now())"),
            {"id": user_id, "email": f"prop-{uuid4().hex[:10]}@example.test"},
        )
        await conn.execute(
            text(
                "INSERT INTO developer_profiles (user_id, handle, verification_level)"
                " VALUES (:id, :handle, CAST(:level AS dev_verification))"
            ),
            {"id": user_id, "handle": f"dev-{user_id.hex[-12:]}", "level": level},
        )
    return user_id


Developers = Callable[..., Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def developers(app_engine: AsyncEngine, owner_engine: AsyncEngine) -> AsyncIterator[Developers]:
    """``await developers(level="d1", wrapper=None, user_id=None)``: a signed-in developer's client."""
    async with AsyncExitStack() as stack:

        async def make(
            *, level: str = "d1", wrapper: KeyWrapper | None = None, user_id: UUID | None = None
        ) -> httpx.AsyncClient:
            uid = user_id or await add_developer(owner_engine, level=level)
            client = await stack.enter_async_context(make_client(app_engine))
            if wrapper is not None:
                client.app.state.key_wrapper = wrapper  # type: ignore[attr-defined]
            await sign_in_as(client, app_engine, uid, mfa_verified=False)
            client.user_id = uid  # type: ignore[attr-defined]
            return client

        yield make


def user_of(client: httpx.AsyncClient) -> UUID:
    user_id: UUID = client.user_id  # type: ignore[attr-defined]
    return user_id


def store_of(client: httpx.AsyncClient) -> InMemoryObjectStore:
    store: InMemoryObjectStore = client.app.state.object_store  # type: ignore[attr-defined]
    return store


def teaser(world: ProposalWorld, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "title": "Cold-chain alerts",
        "niche_id": str(world.niche_id),
        "county_code": None,
        "maturity": "prototype",
        "ask": "pilot",
        "problem_statement": "Milk spoils before it reaches a cooler.",
        "impact_claims": "Cuts spoilage for 40 farms.",
        "summary": "An SMS goes out when a cooler warms up.",
    }
    return values | overrides


def draft_body(world: ProposalWorld, *, link: bool = True, **teaser_overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "teaser": teaser(world, **teaser_overrides),
        "confidential": {
            "approach": SECRET_APPROACH,
            "architecture": "TIER2-SECRET-architecture gateway",
            "pricing": SECRET_PRICING,
            "links": [SECRET_LINK],
        },
    }
    if link:
        body["problem_ids"] = [str(world.problem_id)]
    return body


def attest(**overrides: Any) -> dict[str, Any]:
    confirmed = {"created_it": True, "not_owned_by_employer_or_client": True, "no_third_party_confidential": True}
    return {"attestations": confirmed | overrides, "attestation_text_version": attestations.VERSION}


async def create(client: httpx.AsyncClient, body: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/api/me/proposals", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def publish(client: httpx.AsyncClient, proposal_id: str, **overrides: Any) -> httpx.Response:
    return await client.post(f"/api/me/proposals/{proposal_id}/publish", json=attest(**overrides))


async def published(client: httpx.AsyncClient, world: ProposalWorld, **teaser_overrides: Any) -> dict[str, Any]:
    """Create and publish a complete proposal; the publish response."""
    created = await create(client, draft_body(world, **teaser_overrides))
    response = await publish(client, created["id"])
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def staff_client(
    stack: AsyncExitStack, app_engine: AsyncEngine, owner_engine: AsyncEngine, role: str = "moderator"
) -> httpx.AsyncClient:
    async with owner_engine.begin() as conn:
        staff_id = await w.add_user(conn, f"staff-{uuid4().hex[:10]}@example.test", "Staff", staff_role=role)
    client = await stack.enter_async_context(make_client(app_engine))
    await sign_in_as(client, app_engine, staff_id, mfa_verified=True)
    client.user_id = staff_id  # type: ignore[attr-defined]
    return client


Staff = Callable[..., Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def moderators(app_engine: AsyncEngine, owner_engine: AsyncEngine) -> AsyncIterator[Staff]:
    """``await moderators(role="moderator")``: a staff member's client (TOTP enrolled, second factor fresh)."""
    async with AsyncExitStack() as stack:

        async def make(role: str = "moderator") -> httpx.AsyncClient:
            return await staff_client(stack, app_engine, owner_engine, role)

        yield make


async def cases_about(staff: httpx.AsyncClient, subject_id: str, *, decided: bool = False) -> list[dict[str, Any]]:
    response = await staff.get("/api/admin/moderation/cases", params={"decided": str(decided).lower()})
    assert response.status_code == 200, response.text
    return [c for c in response.json()["items"] if c["subject_id"] == subject_id]
