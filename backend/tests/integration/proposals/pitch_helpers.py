"""Fixtures for the Pitch tests (REQ-PROP-03, REQ-REPO-03, REQ-NOT-02, REQ-BIL-02, REQ-DIR-04; docs/spec/06 6.2, 6.3).

``pitch_orgs`` is the AC-PROP-1 cast, written as the owner role with a random tag in every name: two E2 organisations
("Safaricom <tag>", "Airtel <tag>") with a TOTP-enrolled reviewer each, an E0 one ("Telkom <tag>", no members), an E1
one ("Claimed <tag>", its owner a member) and an untagged E2 bystander ("Bystander <tag>") with a reviewer, all under
the proposal world's niche. ``member_client`` signs a member in with the second factor done (org routes need it).
``RecordingHooks`` wraps the default ``TagHooks`` and records every call.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.proposals.tag_hooks import TagHooks, default_hooks
from bridge.seed.reference import seed_all
from tests.integration.api import make_client, outbox, sign_in_as
from tests.integration.proposals.helpers import Developers, ProposalWorld, published, rows


@dataclass(frozen=True, slots=True)
class Org:
    id: UUID
    name: str
    slug: str
    member: UUID | None  # a reviewer (E2), the owner (E1), or None (E0)


@dataclass(frozen=True, slots=True)
class PitchOrgs:
    tag: str
    safaricom: Org
    airtel: Org
    telkom: Org
    claimed: Org
    bystander: Org

    def cast(self) -> tuple[Org, Org, Org, Org]:
        return self.safaricom, self.airtel, self.telkom, self.claimed


async def add_org(
    owner_engine: AsyncEngine,
    name: str,
    *,
    verification: str,
    niche_id: UUID | None,
    roles: str | None = "{reviewer}",
    suspended: bool = False,
) -> Org:
    org_id = uuid7()
    slug = f"{name.lower().replace(' ', '-')}-{org_id.hex[-6:]}"
    member = None
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, county_code,"
                " e2_verified_at, suspended_at) VALUES (:id, 'company', :name, :slug, 'admin',"
                " CAST(:verification AS org_verification), 'KE-30',"
                " CASE WHEN :verification = 'e2' THEN now() END, CASE WHEN :suspended THEN now() END)"
            ),
            {"id": org_id, "name": name, "slug": slug, "verification": verification, "suspended": suspended},
        )
        if niche_id is not None:
            await conn.execute(
                text("INSERT INTO org_niches (org_id, niche_id) VALUES (:org, :niche)"),
                {"org": org_id, "niche": niche_id},
            )
        if roles is not None:
            member = await add_member(conn, org_id, roles)
    return Org(org_id, name, slug, member)


async def add_member(conn: Any, org_id: UUID, roles: str) -> UUID:
    user_id = uuid7()
    await conn.execute(
        text(
            "INSERT INTO users (id, email, display_name, email_verified_at, totp_enabled_at)"
            " VALUES (:id, :email, 'Member', now(), now())"
        ),
        {"id": user_id, "email": f"member-{uuid4().hex[:10]}@example.test"},
    )
    await conn.execute(
        text(
            "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, CAST(:roles AS org_role[]))"
        ),
        {"id": uuid7(), "org": org_id, "user": user_id, "roles": roles},
    )
    return user_id


@pytest.fixture
async def pitch_orgs(owner_engine: AsyncEngine, proposal_world: ProposalWorld) -> PitchOrgs:
    tag = uuid4().hex[:8]
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())  # the counties
    niche = proposal_world.niche_id
    return PitchOrgs(
        tag=tag,
        safaricom=await add_org(owner_engine, f"Safaricom {tag}", verification="e2", niche_id=niche),
        airtel=await add_org(owner_engine, f"Airtel {tag}", verification="e2", niche_id=niche),
        telkom=await add_org(owner_engine, f"Telkom {tag}", verification="unclaimed", niche_id=niche, roles=None),
        claimed=await add_org(owner_engine, f"Claimed {tag}", verification="e1", niche_id=niche, roles="{owner}"),
        bystander=await add_org(owner_engine, f"Bystander {tag}", verification="e2", niche_id=niche),
    )


Members = Callable[[UUID], Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def member_client(app_engine: AsyncEngine) -> AsyncIterator[Members]:
    """``await member_client(user_id)``: a client signed in as that member, second factor done."""
    async with AsyncExitStack() as stack:

        async def make(user_id: UUID) -> httpx.AsyncClient:
            client = await stack.enter_async_context(make_client(app_engine))
            await sign_in_as(client, app_engine, user_id, mfa_verified=True)
            client.user_id = user_id  # type: ignore[attr-defined]
            return client

        yield make


@dataclass
class RecordingHooks:
    """The default hooks, recording each call's keyword arguments (``fail`` makes ``grant_on_tag`` raise)."""

    engagements: list[dict[str, UUID]] = field(default_factory=list)
    grants: list[dict[str, UUID]] = field(default_factory=list)
    fail: bool = False

    def hooks(self) -> TagHooks:
        inner = default_hooks()

        async def open_engagement(db: AsyncSession, **kwargs: UUID) -> UUID:
            self.engagements.append(kwargs)
            return await inner.open_engagement(db, **kwargs)

        async def grant_on_tag(db: AsyncSession, **kwargs: UUID) -> UUID | None:
            self.grants.append(kwargs)
            if self.fail:
                raise RuntimeError("grant failed")
            return await inner.grant_on_tag(db, **kwargs)

        return TagHooks(open_engagement=open_engagement, grant_on_tag=grant_on_tag)


def install(client: httpx.AsyncClient, hooks: RecordingHooks) -> RecordingHooks:
    client.app.state.tag_hooks = hooks.hooks()  # type: ignore[attr-defined]
    return hooks


async def pitch(client: httpx.AsyncClient, proposal_id: str, *orgs: Org | UUID) -> httpx.Response:
    ids = [str(org.id if isinstance(org, Org) else org) for org in orgs]
    return await client.post(f"/api/me/proposals/{proposal_id}/tags", json={"org_ids": ids})


async def pitchable(developers: Developers, world: ProposalWorld, **teaser: Any) -> tuple[httpx.AsyncClient, str]:
    """A D1 developer's client and one published, clear proposal of theirs."""
    client = await developers()
    return client, (await published(client, world, **teaser))["proposal_id"]


async def counts(owner_engine: AsyncEngine, developer_id: UUID) -> dict[str, int]:
    """What a Pitch may create, for one developer: tags, engagements, EM1 deliveries, in-app rows, audit events."""
    queries = {
        "tags": "SELECT count(*) FROM tags WHERE developer_id = :u",
        "engagements": "SELECT count(*) FROM engagements WHERE developer_id = :u",
        "deliveries": "SELECT count(*) FROM notification_deliveries WHERE user_id = :u",
        "in_app": "SELECT count(*) FROM in_app_notifications WHERE user_id = :u",
        "pitched": "SELECT count(*) FROM audit_events WHERE actor_user_id = :u AND action = 'proposal.pitched'",
    }
    return {name: int((await rows(owner_engine, sql, u=developer_id))[0][0]) for name, sql in queries.items()}


async def org_mail(owner_engine: AsyncEngine, orgs: list[Org]) -> int:
    """Deliveries and in-app rows for any member or scope of ``orgs`` (held tags and privacy: always 0 here)."""
    ids = [org.id for org in orgs]
    members = [org.member for org in orgs if org.member is not None]
    sql = (
        "SELECT (SELECT count(*) FROM notification_deliveries WHERE org_id = ANY(:ids) OR user_id = ANY(:members))"
        " + (SELECT count(*) FROM in_app_notifications WHERE org_id = ANY(:ids) OR user_id = ANY(:members))"
    )
    return int((await rows(owner_engine, sql, ids=ids, members=members))[0][0])


def sent(client: httpx.AsyncClient) -> list[Any]:
    return list(outbox(client).outbox)
