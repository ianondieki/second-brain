"""Helpers of the peers and team-up API tests (REQ-DEV-03; P22 card C): a database of the module's own
(``conftest.teams``) with Kenya's counties; developers written as the owner role with a county, liked niches and the
peers switch; an organisation-only account and staff; problems and Briefs; signed-in clients of the in-process API;
and the calls a developer makes (invite, accept, post)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.api import make_client, sign_in_as
from tests.integration.matching.scout_world import Org, add_org, add_person, run

NAIROBI_CITY, MOMBASA, KISUMU = "KE-30", "KE-28", "KE-42"
PEERS: Final = "/api/me/peers"
TEAMS: Final = "/api/me/teams"
INVITATIONS: Final = "/api/me/teams/invitations"
BLOCKS: Final = "/api/me/blocks"


@dataclass
class TeamsDb:
    owner: AsyncEngine
    app: AsyncEngine


async def owner_rows(db: TeamsDb, sql: str, **params: object) -> list[Any]:
    async with db.owner.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def owner_run(db: TeamsDb, sql: str, **params: object) -> None:
    async with db.owner.begin() as conn:
        await conn.execute(text(sql), params)


async def forward(db: TeamsDb, by: timedelta) -> None:
    """Move the module database's shared clock forward by ``by`` (committed: the API reads it)."""
    await owner_run(db, "UPDATE test_clock SET enabled = true, clock_offset = clock_offset + :by", by=by)


async def niche(db: TeamsDb, name: str) -> tuple[UUID, str]:
    """A niche of the test's own: (id, slug); slugs sort by ``name``."""
    niche_id = uuid7()
    slug = f"{name}-{niche_id.hex}"
    await owner_run(db, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, :n)", id=niche_id, s=slug, n=name)
    return niche_id, slug


async def developer(
    db: TeamsDb,
    label: str,
    *,
    county: str | None = None,
    liked: tuple[UUID, ...] = (),
    peers: bool = True,
    demo: bool = False,
    headline: str | None = None,
) -> UUID:
    """As the owner: an active developer with a verified address, a handle ``<label>-<hex>``, a county, liked niches
    and the peers switch as given."""
    async with db.owner.begin() as conn:
        user = await add_person(conn, label, "developers.example.test", totp_on=False)
        if demo:
            await run(conn, "UPDATE users SET demo_account = true WHERE id = :u", u=user)
        await run(
            conn,
            "INSERT INTO developer_profiles (user_id, handle, county_code, peers_visible, headline, bio)"
            " VALUES (:u, :h, :c, :p, :hl, 'A private bio')",
            u=user,
            h=f"{label}-{user.hex[-12:]}",
            c=county,
            p=peers,
            hl=headline or f"{label.title()} builds things",
        )
        for niche_id in liked:
            await run(
                conn,
                "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, 'liked')",
                u=user,
                n=niche_id,
            )
    return user


async def handle_of(db: TeamsDb, user: UUID) -> str:
    [row] = await owner_rows(db, "SELECT handle::text FROM developer_profiles WHERE user_id = :u", u=user)
    return str(row[0])


async def org_only(db: TeamsDb) -> Org:
    async with db.owner.begin() as conn:
        return await add_org(conn, "teams")


async def staff(db: TeamsDb, role: str = "moderator") -> UUID:
    async with db.owner.begin() as conn:
        user = await add_person(conn, role, "staff.example.test", totp_on=True)
        await run(conn, "UPDATE users SET staff_role = CAST(:r AS staff_role) WHERE id = :u", r=role, u=user)
    return user


async def problem(db: TeamsDb, *, status: str = "published", moderation_state: str = "clear") -> UUID:
    """As the owner: a developer's problem by an author of no test (published and clear unless told otherwise)."""
    async with db.owner.begin() as conn:
        author = await w.add_user(conn, f"author-{uuid4().hex[:8]}@example.test", "Author")
        niche_id = uuid7()
        await run(
            conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Problem')", id=niche_id, s=niche_id.hex
        )
        return await w.add_problem(conn, author, niche_id, status=status, moderation_state=moderation_state)


async def problem_title(db: TeamsDb, problem_id: UUID) -> str:
    [row] = await owner_rows(db, "SELECT title FROM problems WHERE id = :p", p=problem_id)
    return str(row[0])


async def brief(db: TeamsDb, org: Org, *, visibility: str, status: str = "published") -> UUID:
    """As the owner: an E2 organisation's published, clear problem with its Brief."""
    async with db.owner.begin() as conn:
        niche_id = uuid7()
        await run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'Brief')", id=niche_id, s=niche_id.hex)
        problem_id = await w.add_problem(conn, org.owner, niche_id, org_id=org.id)
        await run(
            conn,
            "INSERT INTO problem_briefs (problem_id, org_id, visibility, status) VALUES (:p, :o,"
            " CAST(:v AS brief_visibility), 'published')",
            p=problem_id,
            o=org.id,
            v=visibility,
        )
        if status != "published":
            await run(
                conn,
                "UPDATE problem_briefs SET status = CAST(:s AS brief_status) WHERE problem_id = :p",
                s=status,
                p=problem_id,
            )
    return problem_id


class Clients:
    """Signed-in in-process API clients of the module's database."""

    def __init__(self, db: TeamsDb, stack: AsyncExitStack) -> None:
        self._db, self._stack = db, stack

    async def __call__(self, user_id: UUID, *, fresh: bool = False) -> httpx.AsyncClient:
        client = await self._stack.enter_async_context(make_client(self._db.app))
        await sign_in_as(client, self._db.app, user_id, mfa_verified=fresh)
        client.user_id = user_id  # type: ignore[attr-defined]
        return client


@asynccontextmanager
async def clients(db: TeamsDb) -> AsyncIterator[Clients]:
    async with AsyncExitStack() as stack:
        yield Clients(db, stack)


def code(response: httpx.Response) -> tuple[int, str | None]:
    """(status, error code) of a response."""
    detail = response.json().get("detail") if response.headers.get("content-type") == "application/json" else None
    return response.status_code, detail.get("code") if isinstance(detail, dict) else None


async def invite(
    client: httpx.AsyncClient, to: UUID, problem_id: UUID, note: str | None = None, *, expect: int = 201
) -> dict[str, Any]:
    response = await client.post(INVITATIONS, json={"to_user_id": str(to), "problem_id": str(problem_id), "note": note})
    assert response.status_code == expect, response.text
    found: dict[str, Any] = response.json()
    return found


async def accept(client: httpx.AsyncClient, invitation_id: str) -> str:
    response = await client.post(f"{INVITATIONS}/{invitation_id}/accept")
    assert response.status_code == 201, response.text
    thread: str = response.json()["thread_id"]
    return thread


async def team(sender: httpx.AsyncClient, to: httpx.AsyncClient, problem_id: UUID) -> str:
    """An invitation from ``sender`` accepted by ``to``: the thread's id."""
    invitation = await invite(sender, to.user_id, problem_id)  # type: ignore[attr-defined]
    return await accept(to, invitation["id"])


async def post(client: httpx.AsyncClient, thread: str, body: str = "Shall we split the work?") -> httpx.Response:
    return await client.post(f"{TEAMS}/{thread}/messages", json={"body": body})


async def notices(db: TeamsDb, user: UUID, kind: str) -> list[Any]:
    return await owner_rows(
        db,
        "SELECT kind, title, body, link FROM in_app_notifications WHERE user_id = :u AND kind = :k"
        " ORDER BY created_at, id",
        u=user,
        k=kind,
    )


async def audits(db: TeamsDb, action: str, actor: UUID) -> list[Any]:
    return await owner_rows(
        db,
        "SELECT action, subject_type, subject_id, payload FROM audit_events WHERE action = :a AND actor_user_id = :u"
        " ORDER BY occurred_at, seq",
        a=action,
        u=actor,
    )
