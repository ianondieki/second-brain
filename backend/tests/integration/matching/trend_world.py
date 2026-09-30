"""A committed world for the P12 trending and ranker tests (REQ-TREND-01/02, REQ-PERS-01/03): a niche tree of its own
(so no other test's rows share its baselines), research cards, Briefs, developers' problems and proposals published a
given number of days ago, and cross-organisation signals written as ``bridge_owner`` at chosen times, as P10's code
writes them (``tenancy.signals``: salted actor digests and organisation pseudonyms, never an id or a name).

Times are relative to ``app_clock_now()`` (the test clock another test may have moved), so ages are what a test says.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.ids import uuid7
from bridge.matching.ranking_config import get_ranking
from bridge.matching.trend_facts import Board, board, load
from bridge.seed.reference import load_reference, seed_regions
from tests.integration.matching.scout_world import Teaser, add_org, add_person, add_teaser, run

NOW = "app_clock_now()"


@dataclass(frozen=True, slots=True)
class TrendWorld:
    tag: str
    parent: UUID  # "Farming <tag>"
    niche: UUID  # "Grain <tag>", a child of parent
    sibling: UUID  # "Dairy <tag>", another child of parent
    elsewhere: UUID  # "Transport <tag>"
    author: UUID  # a developer who reported problems

    def slug(self, key: str) -> str:
        return f"p12-{key}-{self.tag}"

    def label(self, key: str) -> str:
        names = {"parent": "Farming", "niche": "Grain", "sibling": "Dairy", "elsewhere": "Transport"}
        own = f"{names[key]} {self.tag}"
        return f"Farming {self.tag} › {own}" if key in ("niche", "sibling") else own


async def build(owner_engine: AsyncEngine) -> TrendWorld:
    tag = uuid4().hex[:8]
    ids = {key: uuid7() for key in ("parent", "niche", "sibling", "elsewhere")}
    async with owner_engine.begin() as conn:
        await seed_regions(conn, load_reference()["regions"])
        for key, name, parent in (
            ("parent", "Farming", None),
            ("niche", "Grain", "parent"),
            ("sibling", "Dairy", "parent"),
            ("elsewhere", "Transport", None),
        ):
            await run(
                conn,
                "INSERT INTO niches (id, parent_id, slug, name_en) VALUES (:id, :parent, :slug, :name)",
                id=ids[key],
                parent=ids[parent] if parent else None,
                slug=f"p12-{key}-{tag}",
                name=f"{name} {tag}",
            )
        author = await add_person(conn, "author", "dev.example.test")
    return TrendWorld(tag, ids["parent"], ids["niche"], ids["sibling"], ids["elsewhere"], author)


async def research_card(
    owner_engine: AsyncEngine,
    niche: UUID,
    *,
    title: str = "Grain farmers lose harvests to drought",
    statement: str = "Grain farmers cannot plan planting after dry spells, so harvests fail.",
    county: str | None = None,
    confidence: str = "0.800",
    age_days: float = 1,
    source_days: tuple[float, ...] = (400,),
    status: str = "published",
) -> UUID:
    """An approved research card (a ``candidate`` when ``status`` says so) with one official source per entry of
    ``source_days`` (each a distinct publisher, dated that many days ago)."""
    card = uuid7()
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO problems (id, source, niche_id, title, statement, status, ai_generated, confidence,"
            " county_code) VALUES (:id, 'research_agent', :niche, :title, :statement, 'candidate', true, :confidence,"
            " :county)",
            id=card,
            niche=niche,
            title=title,
            statement=statement,
            confidence=Decimal(confidence),
            county=county,
        )
        for n, days in enumerate(source_days):
            await run(
                conn,
                "INSERT INTO problem_sources (id, problem_id, url, publisher, source_type, published_date,"
                " retrieved_at, quote) VALUES (:id, :p, :url, :publisher, 'official',"
                f" CAST({NOW} - make_interval(secs => :secs) AS date), {NOW}, 'A quoted line')",
                id=uuid7(),
                p=card,
                url=f"https://agency{n}.go.ke/report",
                publisher=f"Agency {n}",
                secs=days * 86400,
            )
        if status != "candidate":
            await run(
                conn,
                f"UPDATE problems SET status = CAST(:status AS problem_status),"
                f" published_at = {NOW} - make_interval(secs => :secs) WHERE id = :id",
                id=card,
                status=status,
                secs=age_days * 86400,
            )
    return card


async def brief(owner_engine: AsyncEngine, niche: UUID, *, age_days: float = 1, title: str = "Brief") -> UUID:
    """A verified (E2) organisation's published, public Brief."""
    problem = uuid7()
    async with owner_engine.begin() as conn:
        org = await add_org(conn, "brief")
        await run(
            conn,
            "INSERT INTO problems (id, source, niche_id, title, statement, status, created_by, org_id, published_at)"
            f" VALUES (:id, 'org_brief', :niche, :title, 'We need to track grain stocks across depots.', 'published',"
            f" :by, :org, {NOW} - make_interval(secs => :secs))",
            id=problem,
            niche=niche,
            title=title,
            by=org.owner,
            org=org.id,
            secs=age_days * 86400,
        )
        await run(
            conn,
            "INSERT INTO problem_briefs (problem_id, org_id, visibility, status)"
            " VALUES (:p, :org, 'public', 'published')",
            p=problem,
            org=org.id,
        )
    return problem


async def developer_problem(owner_engine: AsyncEngine, author: UUID, niche: UUID, *, age_days: float = 30) -> UUID:
    problem = uuid7()
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO problems (id, source, niche_id, title, statement, status, created_by, published_at)"
            " VALUES (:id, 'developer', :niche, 'Maize stores lose grain to pests', 'Stored maize spoils.',"
            f" 'published', :by, {NOW} - make_interval(secs => :secs))",
            id=problem,
            niche=niche,
            by=author,
            secs=age_days * 86400,
        )
    return problem


async def proposal(
    owner_engine: AsyncEngine,
    niche: UUID,
    problem: UUID,
    *,
    owner: UUID | None = None,
    age_days: float = 30,
    **teaser: Any,
) -> UUID:
    """A published, clear proposal linking ``problem`` (a new developer's unless ``owner``), published that long ago."""
    async with owner_engine.begin() as conn:
        developer = owner or await add_person(conn, "developer", "dev.example.test")
        proposal_id, _ = await add_teaser(conn, developer, niche, problem, Teaser(**teaser))
        await run(
            conn,
            f"UPDATE proposals SET published_at = {NOW} - make_interval(secs => :secs) WHERE id = :id",
            id=proposal_id,
            secs=age_days * 86400,
        )
    return proposal_id


async def signals(
    owner_engine: AsyncEngine,
    item: UUID,
    kind: str,
    *,
    days_ago: list[float],
    actors: int,
    orgs: int | None = None,
    label: str = "",
) -> None:
    """``actors`` distinct actors (spread over ``orgs`` organisations, one each by default) signal ``item`` once on
    each of the given days. ``label`` keeps two groups of actors apart."""
    orgs = orgs or actors
    tag = label or uuid4().hex[:8]
    async with owner_engine.begin() as conn:
        for days in days_ago:
            for n in range(actors):
                await run(
                    conn,
                    "INSERT INTO signal_events (id, item_id, kind, actor_hash, org_hash, ts) VALUES (:id, :item, :kind,"
                    f" :actor, :org, {NOW} - make_interval(secs => :secs))",
                    id=uuid7(),
                    item=item,
                    kind=kind,
                    actor=f"{tag}-actor-{n}".encode().ljust(32, b"\0"),
                    org=f"{tag}-org-{n % orgs}".encode().ljust(32, b"\0"),
                    secs=days * 86400,
                )


async def board_as(app_engine: AsyncEngine, user: UUID) -> Board:
    """The trend board as ``user`` reads it (under their Row-Level Security): every trend, shown or not."""
    async with create_session_factory(app_engine)() as db:
        await bind_tenant(db, user_id=user)
        cfg = get_ranking()
        return board(await load(db, cfg), cfg)


async def quiet_niche(owner_engine: AsyncEngine, world: TrendWorld, niche: UUID, count: int = 10) -> None:
    """Problems of long ago with no activity: the niche's baseline is near zero, so any fresh event has a high z."""
    for _ in range(count):
        await developer_problem(owner_engine, world.author, niche, age_days=200)
