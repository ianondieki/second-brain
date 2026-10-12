"""Fixtures of the deadlines and pipeline tests (REQ-ENG-13, REQ-ENG-14; docs/platform/tasks/P27.md tracks A and B),
on top of the tracker's ``api_world``: a second E2 organisation with a reviewer, a signatory and an owner; an open
Brief with a deadline (and a statement the feed must never carry); a published event; the world's developer's second
proposal linked to a Brief and pitched to its organisation; another developer's engagement with the world's
organisation. Rows are written as the owner role and committed, as ``api_world`` does."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements.commands import open_engagement_for_tag
from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements.api_world import World, run

BRIEF_STATEMENT = "Depots lose a fifth of their milk before it reaches Nairobi (a Brief statement)."
EVENT_DESCRIPTION = "A long description of the meetup that no calendar feed should carry."


@dataclass(frozen=True, slots=True)
class Org:
    id: UUID
    name: str
    owner: UUID  # owner + admin, TOTP
    reviewer: UUID  # TOTP
    signatory: UUID  # TOTP


async def person(conn: AsyncConnection, prefix: str, domain: str) -> UUID:
    """A user with a verified email and TOTP enrolled."""
    user_id = uuid7()
    now = datetime.now(UTC)
    await run(
        conn,
        "INSERT INTO users (id, email, display_name, email_verified_at, totp_enabled_at)"
        " VALUES (:id, :email, :name, :now, :now)",
        id=user_id,
        email=f"{prefix}-{uuid4().hex[:8]}@{domain}",
        name=f"{prefix.title()} {uuid4().hex[:4]}",
        now=now,
    )
    return user_id


async def add_org(owner_engine: AsyncEngine) -> Org:
    """An E2 organisation with an owner (and admin), a reviewer and a signatory."""
    domain = f"org-{uuid4().hex[:10]}.example.test"
    async with owner_engine.begin() as conn:
        org_id = uuid7()
        name = f"Sacco {uuid4().hex[:6]} (fixture)"
        await run(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, verified_domain)"
            " VALUES (:id, 'company', :name, :slug, 'seed', 'e2', :domain)",
            id=org_id,
            name=name,
            slug=f"p27-{org_id.hex}",
            domain=domain,
        )
        people: dict[str, UUID] = {}
        for role, roles in (("owner", "{owner,admin}"), ("reviewer", "{reviewer}"), ("signatory", "{signatory}")):
            people[role] = await person(conn, role, domain)
            await run(
                conn,
                "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, CAST(:r AS org_role[]))",
                id=uuid7(),
                org=org_id,
                u=people[role],
                r=roles,
            )
    return Org(org_id, name, people["owner"], people["reviewer"], people["signatory"])


async def niche(conn: AsyncConnection) -> UUID:
    niche_id = uuid7()
    sql = "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'P27')"
    await run(conn, sql, id=niche_id, s=f"p27-{niche_id.hex}")
    return niche_id


async def add_brief(owner_engine: AsyncEngine, org_id: UUID, author: UUID, deadline: date, *, title: str) -> UUID:
    """A published, clear Brief of ``org_id`` closing at the end of ``deadline`` (Nairobi)."""
    async with owner_engine.begin() as conn:
        niche_id = await niche(conn)
        problem_id = uuid7()
        await run(
            conn,
            "INSERT INTO problems (id, source, niche_id, title, statement, status, created_by, org_id,"
            " moderation_state) VALUES (:id, 'org_brief', :niche, :title, :statement, 'published', :user, :org,"
            " 'clear')",
            id=problem_id,
            niche=niche_id,
            title=title,
            statement=BRIEF_STATEMENT,
            user=author,
            org=org_id,
        )
        await run(
            conn,
            "INSERT INTO problem_briefs (problem_id, org_id, visibility, status, deadline)"
            " VALUES (:p, :o, 'public', 'published', :d)",
            p=problem_id,
            o=org_id,
            d=deadline,
        )
    return problem_id


async def add_event(
    owner_engine: AsyncEngine, org_id: UUID | None, poster: UUID, starts_at: datetime, *, title: str, staff: UUID
) -> UUID:
    """A published online event of ``org_id`` (the platform's with None), two hours long."""
    event_id = uuid7()
    async with owner_engine.begin() as conn:
        await run(
            conn,
            "INSERT INTO events (id, org_id, created_by, title, description, starts_at, ends_at, online, join_url,"
            " status, decided_by, decided_at) VALUES (:id, :org, :user, :title, :description, :starts, :ends, true,"
            " 'https://meet.example.test/p27', 'published', :staff, now())",
            id=event_id,
            org=org_id,
            user=poster,
            title=title,
            description=EVENT_DESCRIPTION,
            starts=starts_at,
            ends=starts_at + timedelta(hours=2),
            staff=staff,
        )
    return event_id


async def remind(owner_engine: AsyncEngine, user_id: UUID, event_id: UUID) -> None:
    async with owner_engine.begin() as conn:
        await run(conn, "INSERT INTO event_reminders (user_id, event_id) VALUES (:u, :e)", u=user_id, e=event_id)


async def open_tag(app_engine: AsyncEngine, developer: UUID, tag: UUID) -> UUID:
    """The developer opens the SUBMITTED engagement of their delivered tag."""
    factory = create_session_factory(app_engine)
    async with factory() as db:
        await bind_tenant(db, user_id=developer)
        engagement = await open_engagement_for_tag(db, tag)
        await db.commit()
        return engagement.id


async def _tagged_proposal(conn: AsyncConnection, developer: UUID, org_id: UUID, problem_id: UUID | None) -> UUID:
    """A published proposal of ``developer`` (linked to ``problem_id``, or a problem of its own) and its delivered tag
    to ``org_id``; returns the tag."""
    niche_id = await niche(conn)
    if problem_id is None:
        problem_id = await w.add_problem(conn, developer, niche_id)
    proposal, _ = await w.add_proposal(conn, developer, niche_id, problem_id)
    tag = uuid7()
    await run(
        conn,
        "INSERT INTO tags (id, proposal_id, org_id, developer_id, status) VALUES (:id, :p, :o, :d, 'delivered')",
        id=tag,
        p=proposal,
        o=org_id,
        d=developer,
    )
    return tag


async def pitch_to_brief(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, world: World, org: Org, brief: UUID
) -> UUID:
    """The world's developer's second proposal, linked to ``brief``, pitched to its organisation: the engagement."""
    async with owner_engine.begin() as conn:
        tag = await _tagged_proposal(conn, world.developer, org.id, brief)
    return await open_tag(app_engine, world.developer, tag)


async def another_developer(owner_engine: AsyncEngine, app_engine: AsyncEngine, org_id: UUID) -> tuple[UUID, UUID]:
    """A new D2 developer (TOTP) whose proposal is delivered to ``org_id``: (developer, engagement)."""
    async with owner_engine.begin() as conn:
        developer = await person(conn, "developer", "dev.example.test")
        tag = await _tagged_proposal(conn, developer, org_id, None)
        await run(conn, "UPDATE developer_profiles SET verification_level = 'd2' WHERE user_id = :u", u=developer)
    return developer, await open_tag(app_engine, developer, tag)


async def one(owner_engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with owner_engine.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one()
