"""Helpers for the research agent's integration tests (REQ-RES-01, REQ-RES-02).

``research_world`` is a staff admin (TOTP enrolled, a demo account: the D-37 rule lets a free provider take the
call), a second staff admin, a moderator and a developer, and one niche per saved-excerpt niche under a fresh slug
(so the shared test database's reference niches and other tests' runs never meet these). ``catalogue`` is the saved
excerpts file with its niches renamed to those slugs: the real quotes, URLs, publishers and dates.

The model is a ``FakeAdapter`` behind a real ``LLMRuntime`` (``llm_runtime``): a free slot, the Anthropic route, or
the fake provider (the labelled demo fallback); calls go through ``routed_client``, so the ledger rows, the caps and
the demo-data rule are the application's. No network.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import FreeSlot, LLMProvider, Settings, get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.llm import registry as registry_module
from bridge.llm.deps import routed_client
from bridge.llm.fakes import FakeAdapter, Reply
from bridge.llm.routing import FreeRoute, LLMRuntime
from bridge.problems.research.pipeline import CardOrigin, RunOutcome, execute_run, start_run
from bridge.problems.research.policy import ResearchPolicy, get_research_policy
from bridge.problems.research.sources import Catalogue, load_catalogue
from tests.integration.world import add_user

NICHES = ("networks-telecommunications", "agriculture", "health", "microfinance-saccos")

TELECOM_DRAFT: dict[str, Any] = {
    "title": "Smaller operators struggle with call termination charges",
    "statement": (
        "Smaller mobile operators say the termination rate regime disadvantages them. The regulator's glide path"
        " takes the rate from Sh0.41 to Sh0.3 per minute by March 2029, while the market leader still held 89 percent"
        " of mobile money in December 2025."
    ),
    "affected_group": "Smaller mobile operators and their customers",
    "named_orgs": [],
    "citations": [
        {
            "excerpt_id": "ke-tel-001",
            "supporting_text": "share in the mobile money market had slimmed to 89 percent",
        },
        {"excerpt_id": "ke-tel-002", "supporting_text": "decline from the previous Sh0.41 to Sh0.37"},
        {
            "excerpt_id": "ke-tel-004",
            "supporting_text": "the current MTR regime disproportionately disadvantages smaller operators",
        },
    ],
}
SACCO_DRAFT: dict[str, Any] = {
    "title": "SACCOs need affordable cyber security and reporting tools",
    "statement": (
        "Regulated SACCOs held Sh1.21 trillion in assets after a 12.5 percent increase. Talks between SASRA and"
        " deposit-taking SACCOs focused on cybersecurity, quality of regulatory data and financial reporting."
    ),
    "affected_group": "Deposit-taking SACCOs and their members",
    "named_orgs": ["SACCO Societies Regulatory Authority"],
    "citations": [
        {"excerpt_id": "ke-sac-001", "supporting_text": "total assets held by regulated Saccos to Sh1.21 trillion"},
        {"excerpt_id": "ke-sac-004", "supporting_text": "cybersecurity, responsible use of technology"},
    ],
}


def answer(*drafts: Mapping[str, Any], injection_suspected: bool = False) -> dict[str, Any]:
    return {"injection_suspected": injection_suspected, "problems": [dict(d) for d in drafts]}


@dataclass(frozen=True)
class ResearchWorld:
    admin: UUID
    other_admin: UUID
    moderator: UUID
    developer: UUID
    niche_ids: dict[str, UUID]  # saved-excerpt niche -> this world's niche id
    slugs: dict[str, str]  # saved-excerpt niche -> this world's slug
    catalogue: Catalogue


async def make_research_world(owner_engine: AsyncEngine, *, demo_admin: bool = True) -> ResearchWorld:
    tag = uuid4().hex[:8]
    slugs = {niche: f"{niche}-{tag}" for niche in NICHES}
    niche_ids = {niche: uuid7() for niche in NICHES}
    async with owner_engine.begin() as conn:
        admin = await add_user(conn, f"research-admin-{tag}@example.test", "Research admin", staff_role="admin")
        other = await add_user(conn, f"research-admin2-{tag}@example.test", "Other admin", staff_role="admin")
        moderator = await add_user(conn, f"research-mod-{tag}@example.test", "Moderator", staff_role="moderator")
        developer = await add_user(conn, f"research-dev-{tag}@example.test", "Developer")
        await conn.execute(
            text("UPDATE users SET demo_account = :demo WHERE id = :id"), {"demo": demo_admin, "id": admin}
        )
        for niche in NICHES:
            await conn.execute(
                text("INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, :name)"),
                {"id": niche_ids[niche], "slug": slugs[niche], "name": f"{niche.title()} {tag}"},
            )
    saved = load_catalogue()
    renamed = tuple(dataclasses.replace(e, niche=slugs[e.niche]) for e in saved.excerpts)
    return ResearchWorld(admin, other, moderator, developer, niche_ids, slugs, Catalogue(renamed, saved.allowlists))


@pytest.fixture
async def research_world(owner_engine: AsyncEngine) -> ResearchWorld:
    return await make_research_world(owner_engine)


def llm_runtime(*replies: Reply, provider: LLMProvider = "free", adapter: FakeAdapter | None = None) -> LLMRuntime:
    """One ``FakeAdapter`` as a free slot (a fresh model name, so no other test's calls count against its cap), as
    the Anthropic route, or nothing at all (``fake``: every call is the labelled demo fallback)."""
    registry = registry_module.load(get_settings().llm_models_file)
    adapter = adapter or FakeAdapter(replies)
    slot = FreeSlot(1, "https://free-research.example/v1", SecretStr("sk-not-real"), f"r-{uuid4().hex[:8]}", 50, "none")
    return LLMRuntime(
        registry=registry,
        anthropic=adapter,
        anthropic_configured=provider == "anthropic",
        provider=provider,
        demo_fallback=provider != "anthropic",
        free=(FreeRoute(slot, registry.for_free_slot(slot), adapter),) if provider == "free" else (),
    )


def adapter_of(runtime: LLMRuntime) -> FakeAdapter:
    adapter = runtime.anthropic
    assert isinstance(adapter, FakeAdapter)
    return adapter


async def start(app_engine: AsyncEngine, world: ResearchWorld, niche: str, *, as_user: UUID | None = None) -> UUID:
    factory = create_session_factory(app_engine)
    async with factory() as db:
        await bind_tenant(db, user_id=as_user or world.admin)
        run = await start_run(
            db, user_id=as_user or world.admin, niche_slug=world.slugs[niche], country="KE", catalogue=world.catalogue
        )
        await db.commit()
        return run.id


async def execute(
    app_engine: AsyncEngine,
    world: ResearchWorld,
    run_id: UUID,
    runtime: LLMRuntime,
    *,
    policy: ResearchPolicy | None = None,
    settings: Settings | None = None,
    origin: CardOrigin = CardOrigin.LIVE,
    as_user: UUID | None = None,
) -> RunOutcome | None:
    """The job's body as the run's starter (or ``as_user``), through the application's routed client."""
    settings = settings or get_settings()
    factory = create_session_factory(app_engine)
    async with factory() as db:
        await bind_tenant(db, user_id=as_user or world.admin)
        client = routed_client(db, factory=factory, settings=settings, runtime=runtime)
        outcome = await execute_run(
            db,
            run_id,
            client=client,
            settings=settings,
            catalogue=world.catalogue,
            policy=policy or get_research_policy(),
            origin=origin,
        )
        await db.commit()
        return outcome


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def run_row(owner_engine: AsyncEngine, run_id: UUID) -> Any:
    [row] = await rows(owner_engine, "SELECT * FROM research_runs WHERE id = :id", id=run_id)
    return row
