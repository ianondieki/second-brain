"""A committed world for the P10 scout tests (REQ-SCOUT-01..03, REQ-ENG-04): two E2 organisations with every seat, a
niche tree of its own (so no other test's proposals match), a developer's proposals of every kind, and helpers to
add proposals, scouts and plans, run scans and read what they wrote.

Rows are written as the owner role and committed (the scan and the API run in their own transactions as
``bridge_app``). Nothing here is shared between tests: each ``build`` makes new organisations, niches and people.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.auth import totp
from bridge.auth.crypto import encrypt
from bridge.config import Settings, get_settings
from bridge.db import create_session_factory
from bridge.ids import uuid7
from bridge.llm.client import LLMClient
from bridge.matching.config import Weights, get_weights
from bridge.matching.scan import ScanDeps
from bridge.notifications.email import EmailMessage, FakeEmailProvider
from bridge.seed.reference import load_reference, seed_regions
from tests.integration import world as w

NAIROBI_CODE, MOMBASA_CODE = "KE-30", "KE-28"


async def run(conn: AsyncConnection, sql: str, **params: object) -> Any:
    result = await conn.execute(text(sql), params)
    return result.scalar() if result.returns_rows else None


async def add_person(conn: AsyncConnection, prefix: str, domain: str, *, totp_on: bool = True) -> UUID:
    user_id, now = uuid7(), datetime.now(UTC)
    await run(
        conn,
        "INSERT INTO users (id, email, display_name, email_verified_at, totp_enabled_at)"
        " VALUES (:id, :email, :name, :now, :totp)",
        id=user_id,
        email=f"{prefix}-{uuid4().hex[:8]}@{domain}",
        name=f"{prefix.title()} {uuid4().hex[:4]}",
        now=now,
        totp=now if totp_on else None,
    )
    return user_id


@dataclass(frozen=True, slots=True)
class Org:
    id: UUID
    name: str
    domain: str
    owner: UUID  # owner + admin
    signatory: UUID
    reviewer: UUID  # at the verified domain
    reviewer_elsewhere: UUID  # a reviewer whose address is not at the verified domain
    finance: UUID
    viewer: UUID


async def add_org(conn: AsyncConnection, label: str, verification: str = "e2") -> Org:
    domain = f"{label}-{uuid4().hex[:8]}.example.test"
    org_id = uuid7()
    name = f"{label.title()} {uuid4().hex[:4]} (fixture)"
    await run(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, verified_domain)"
        " VALUES (:id, 'company', :name, :slug, 'seed', CAST(:v AS org_verification), :domain)",
        id=org_id,
        name=name,
        slug=f"p10-{org_id.hex}",
        v=verification,
        domain=domain,
    )
    people: dict[str, UUID] = {}
    for role, roles, where in (
        ("owner", "{owner,admin}", domain),
        ("signatory", "{signatory}", domain),
        ("reviewer", "{reviewer}", domain),
        ("reviewer_elsewhere", "{reviewer}", "elsewhere.example.test"),
        ("finance", "{finance}", domain),
        ("viewer", "{viewer}", domain),
    ):
        people[role] = await add_person(conn, role.replace("_", "-"), where, totp_on=role != "viewer")
        await run(
            conn,
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, CAST(:r AS org_role[]))",
            id=uuid7(),
            org=org_id,
            u=people[role],
            r=roles,
        )
    return Org(org_id, name, domain, **people)


@dataclass(frozen=True, slots=True)
class Teaser:
    title: str = "Mobile money savings for SACCO members"
    problem_statement: str = "SACCO members cannot save small daily amounts"
    summary: str = "A USSD savings wallet linked to the SACCO ledger"
    impact_claims: str | None = "Pilot with 3 SACCOs in Nairobi"
    county: str | None = NAIROBI_CODE
    maturity: str = "mvp"


@dataclass(frozen=True, slots=True)
class ScoutWorld:
    org: Org
    other: Org
    parent: UUID  # "Finance <tag>"
    niche: UUID  # "Microfinance <tag>", a child of parent
    sibling: UUID  # "Insurance <tag>", another child of parent
    elsewhere: UUID  # "Agriculture <tag>"
    tag: str
    developer: UUID
    developer_email: str
    totp_secret: str
    problem: UUID
    proposals: dict[str, tuple[UUID, UUID]] = field(default_factory=dict)

    def proposal(self, key: str) -> UUID:
        return self.proposals[key][0]


async def add_teaser(
    conn: AsyncConnection,
    owner: UUID,
    niche: UUID,
    problem: UUID,
    teaser: Teaser,
    *,
    moderation_state: str = "clear",
    status: str = "published",
    registered: bool = True,
) -> tuple[UUID, UUID]:
    """A proposal with one version carrying ``teaser`` (registered and listed unless ``registered`` is false), as
    ``tests.integration.world.add_proposal`` writes one."""
    proposal, version = uuid7(), uuid7()
    values = {
        "title": teaser.title,
        "ps": teaser.problem_statement,
        "summary": teaser.summary,
        "impact": teaser.impact_claims,
        "county": teaser.county,
        "maturity": teaser.maturity,
        "niche": niche,
    }
    await run(
        conn,
        "INSERT INTO developer_profiles (user_id, handle) VALUES (:owner, :handle) ON CONFLICT (user_id) DO NOTHING",
        owner=owner,
        handle=f"dev-{owner.hex}",
    )
    await run(
        conn,
        "INSERT INTO proposals (id, owner_id, moderation_state, title, niche_id, problem_statement, summary,"
        " impact_claims, county_code, maturity) VALUES (:id, :owner, CAST(:moderation AS moderation_state), :title,"
        " :niche, :ps, :summary, :impact, :county, CAST(:maturity AS proposal_maturity))",
        id=proposal,
        owner=owner,
        moderation=moderation_state,
        **values,
    )
    await run(
        conn,
        "INSERT INTO proposal_versions (id, proposal_id, version_no, title, niche_id, maturity, ask, problem_statement,"
        " summary, impact_claims, county_code) VALUES (:id, :proposal, 1, :title, :niche,"
        " CAST(:maturity AS proposal_maturity), 'pilot', :ps, :summary, :impact, :county)",
        id=version,
        proposal=proposal,
        **values,
    )
    await run(
        conn,
        "INSERT INTO proposal_confidential (version_id, proposal_id, owner_id, ciphertext, nonce, wrapped_dek,"
        " kms_key_id) VALUES (:version, :proposal, :owner, '\\x01', '\\x02', '\\x03', 'local:test')",
        version=version,
        proposal=proposal,
        owner=owner,
    )
    await run(
        conn,
        "INSERT INTO proposal_problems (proposal_version_id, problem_id) VALUES (:version, :problem)",
        version=version,
        problem=problem,
    )
    if registered:
        await run(
            conn,
            "UPDATE proposal_versions SET status = 'registered', cert_id = :cert, registered_at = now() WHERE id = :id",
            id=version,
            cert=uuid7().hex[:16],
        )
        await run(
            conn,
            "UPDATE proposals SET status = CAST(:status AS proposal_status), current_version_id = :version,"
            " published_at = now() WHERE id = :id",
            id=proposal,
            status=status,
            version=version,
        )
    else:
        await run(conn, "UPDATE proposals SET draft_version_id = :version WHERE id = :id", id=proposal, version=version)
    return proposal, version


async def build(owner_engine: AsyncEngine, *, verification: str = "e2") -> ScoutWorld:
    """Two organisations, a niche tree and the developer's proposals (all committed)."""
    tag = uuid4().hex[:8]
    secret = totp.new_secret()
    async with owner_engine.begin() as conn:
        await seed_regions(conn, load_reference()["regions"])
        org = await add_org(conn, "telco", verification)
        other = await add_org(conn, "bank")
        niches: dict[str, UUID] = {}
        for key, name, parent in (
            ("parent", f"Finance {tag}", None),
            ("niche", f"Microfinance {tag}", "parent"),
            ("sibling", f"Insurance {tag}", "parent"),
            ("elsewhere", f"Agriculture {tag}", None),
        ):
            niches[key] = uuid7()
            await run(
                conn,
                "INSERT INTO niches (id, parent_id, slug, name_en) VALUES (:id, :parent, :slug, :name)",
                id=niches[key],
                parent=niches[parent] if parent else None,
                slug=f"p10-{key}-{tag}",
                name=name,
            )
        developer = await add_person(conn, "developer", "dev.example.test")
        dek = base64.b64decode(get_settings().data_encryption_key.get_secret_value())
        await run(
            conn,
            "UPDATE users SET totp_secret_enc = :secret WHERE id = :id",
            secret=encrypt(dek, secret.encode("ascii"), developer.bytes),
            id=developer,
        )
        problem = await w.add_problem(conn, developer, niches["niche"])
        email = str(await run(conn, "SELECT email FROM users WHERE id = :id", id=developer))
    return ScoutWorld(
        org=org,
        other=other,
        parent=niches["parent"],
        niche=niches["niche"],
        sibling=niches["sibling"],
        elsewhere=niches["elsewhere"],
        tag=tag,
        developer=developer,
        developer_email=email,
        totp_secret=secret,
        problem=problem,
    )


async def publish(
    owner_engine: AsyncEngine, world: ScoutWorld, key: str, teaser: Teaser | None = None, **options: Any
) -> tuple[UUID, UUID]:
    """A proposal of the developer's in the world's niche (or ``options['niche']``), committed now."""
    niche = options.pop("niche", world.niche)
    async with owner_engine.begin() as conn:
        found = await add_teaser(conn, world.developer, niche, world.problem, teaser or Teaser(), **options)
    world.proposals[key] = found
    return found


async def add_scout(owner_engine: AsyncEngine, org: Org, niches: list[UUID], **columns: Any) -> UUID:
    """A scout of ``org`` created by its owner (as the owner role; the recipients trigger still runs)."""
    scout_id = uuid7()
    values: dict[str, Any] = {
        "frequency": "weekly",
        "counties": [],
        "include_keywords": [],
        "exclude_keywords": [],
        "maturity": [],
        "recipients": [org.reviewer],
        "min_fit": 60,
    } | columns
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO scout_agents (id, org_id, niches, created_by, frequency, counties, include_keywords,"
            " exclude_keywords, maturity, recipients, min_fit) VALUES (:id, :org, CAST(:niches AS uuid[]), :by,"
            " CAST(:frequency AS scout_frequency), CAST(:counties AS text[]), CAST(:include_keywords AS text[]),"
            " CAST(:exclude_keywords AS text[]), CAST(:maturity AS proposal_maturity[]), CAST(:recipients AS uuid[]),"
            " :min_fit)",
            id=scout_id,
            org=org.id,
            niches=niches,
            by=org.owner,
            **values,
        )
    return scout_id


async def subscribe(owner_engine: AsyncEngine, org_id: UUID, code: str = "org_growth") -> None:
    """The organisation's live subscription to ``code`` (its plans row made when missing)."""
    async with owner_engine.begin() as conn:
        plan = await run(conn, "SELECT id FROM plans WHERE code = :code", code=code)
        if plan is None:
            plan = uuid7()
            await run(
                conn,
                "INSERT INTO plans (id, code, side, name, price_kes_minor, interval, limits)"
                " VALUES (:id, :code, 'org', :code, 4500000, 'month', '{}')",
                id=plan,
                code=code,
            )
        await run(
            conn,
            "INSERT INTO subscriptions (id, org_id, plan_id, status, current_period_start)"
            " VALUES (:id, :org, :plan, 'active', now())",
            id=uuid7(),
            org=org_id,
            plan=plan,
        )


def deps(
    app_engine: AsyncEngine,
    *,
    llm: LLMClient | None = None,
    settings: Settings | None = None,
    weights: Weights | None = None,
    **overrides: Any,
) -> tuple[ScanDeps, FakeEmailProvider]:
    email = FakeEmailProvider()
    return (
        ScanDeps(
            factory=create_session_factory(app_engine),
            settings=settings or get_settings(),
            email=email,
            weights=replace(weights or get_weights(), **overrides),
            llm=lambda _db: llm,
        ),
        email,
    )


def outbox_of(email: FakeEmailProvider, org: Org) -> list[EmailMessage]:
    """The messages to ``org``'s verified domain. ``run_periodic`` runs every due scout in the database, other tests'
    scouts included (a later week makes them due again), so a test reads only its own organisation's mail."""
    return [m for m in email.outbox if m.to.endswith(f"@{org.domain}")]


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def matches(owner_engine: AsyncEngine, scout: UUID) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT id, proposal_id, version_id, score, rationale, rationale_demo_fallback, injection_suspected,"
        " rule_breakdown, digest_sent_at, niche_id FROM agent_matches WHERE scout_id = :s ORDER BY score DESC, id",
        s=scout,
    )


async def runs(owner_engine: AsyncEngine, scout: UUID) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT id, trigger::text AS trigger, status::text AS status, scanned_count, matched_count, error_code,"
        " window_start, window_end FROM agent_runs WHERE scout_id = :s ORDER BY started_at, id",
        s=scout,
    )
