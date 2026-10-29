"""Fixtures for the revision 0005 schema tests (REQ-SCOUT-01, REQ-RES-01, REQ-TREND-01, REQ-BIL-08).

Every helper runs inside one rolled-back transaction of the owner engine (``as_app``): fixtures are written as the
owner, then the connection switches to ``bridge_app`` acting for a user (``act``), as the application does. The
generic helpers (``as_app``, ``run``, ``act``, ``as_owner``, ``expect``, ``rowcount``) are the tracker tests'.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements.tracker import act, as_app, as_owner, expect, rowcount, run

__all__ = [
    "Proposals",
    "Seats",
    "act",
    "add_niche",
    "add_org",
    "add_user",
    "as_app",
    "as_owner",
    "expect",
    "member",
    "proposals",
    "rowcount",
    "run",
    "seats",
]


async def add_user(
    conn: AsyncConnection, prefix: str, *, staff_role: str | None = None, status: str = "active", totp: bool = True
) -> UUID:
    """A user (TOTP enrolled by default: app_is_staff needs it for staff)."""
    user_id = uuid7()
    now = datetime.now(UTC)
    await run(
        conn,
        "INSERT INTO users (id, email, display_name, staff_role, status, email_verified_at, totp_enabled_at)"
        " VALUES (:id, :email, :name, CAST(:staff AS staff_role), CAST(:status AS user_status), :now, :totp)",
        id=user_id,
        email=f"{prefix}-{uuid4().hex[:10]}@example.test",
        name=prefix.title(),
        staff=staff_role,
        status=status,
        now=now,
        totp=now if totp else None,
    )
    return user_id


async def add_org(conn: AsyncConnection, verification: str = "e2", *, suspended: bool = False) -> UUID:
    org_id = uuid7()
    await run(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, suspended_at)"
        " VALUES (:id, 'company', 'Schema v4 Ltd', :slug, 'seed', CAST(:verification AS org_verification),"
        " CASE WHEN :suspended THEN now() END)",
        id=org_id,
        slug=f"v4-{org_id.hex}",
        verification=verification,
        suspended=suspended,
    )
    return org_id


async def member(conn: AsyncConnection, org: UUID, user: UUID, roles: str, status: str = "active") -> UUID:
    membership = uuid7()
    await run(
        conn,
        "INSERT INTO memberships (id, org_id, user_id, roles, status) VALUES (:id, :org, :user,"
        " CAST(:roles AS org_role[]), CAST(:status AS membership_status))",
        id=membership,
        org=org,
        user=user,
        roles=roles,
        status=status,
    )
    return membership


async def add_niche(conn: AsyncConnection) -> UUID:
    niche = uuid7()
    await run(
        conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Schema v4')", id=niche, s=f"v4-{niche.hex}"
    )
    return niche


@dataclass(frozen=True, slots=True)
class Seats:
    """An organisation and one member per role."""

    org: UUID
    owner: UUID  # owner and admin
    admin: UUID
    signatory: UUID
    reviewer: UUID
    finance: UUID
    viewer: UUID


async def seats(conn: AsyncConnection, verification: str = "e2", *, suspended: bool = False) -> Seats:
    org = await add_org(conn, verification, suspended=suspended)
    people: dict[str, UUID] = {}
    for role, roles in (
        ("owner", "{owner,admin}"),
        ("admin", "{admin}"),
        ("signatory", "{signatory}"),
        ("reviewer", "{reviewer}"),
        ("finance", "{finance}"),
        ("viewer", "{viewer}"),
    ):
        people[role] = await add_user(conn, role)
        await member(conn, org, people[role], roles)
    return Seats(org=org, **people)


@dataclass(frozen=True, slots=True)
class Proposals:
    """A developer's proposals by visibility: only ``published`` (clear) is readable by other signed-in users."""

    developer: UUID
    niche: UUID
    published: UUID
    published_version: UUID
    draft: UUID
    draft_version: UUID
    held: UUID
    held_version: UUID


async def proposals(conn: AsyncConnection, niche: UUID) -> Proposals:
    developer = await add_user(conn, "developer")
    problem = await w.add_problem(conn, developer, niche)
    published, published_version = await w.add_proposal(conn, developer, niche, problem)
    draft, draft_version = await w.add_proposal(conn, developer, niche, problem, registered=False)
    held, held_version = await w.add_proposal(conn, developer, niche, problem, moderation_state="held")
    return Proposals(developer, niche, published, published_version, draft, draft_version, held, held_version)
