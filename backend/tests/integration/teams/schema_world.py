"""Fixtures of the peers and team schema tests (revision 0011, REQ-DEV-03): developers with or without the peers switch,
in a county, with liked niches; organisation-only accounts and staff; a problem or a Brief; an invitation as its
sender writes it, a decision as a party takes it, a team (an accepted invitation and its thread) and a message. Every
helper runs inside one transaction of the owner engine (``tracker.as_app``) and switches the role as it acts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t

RLS = "row-level security"
DENIED = "permission denied"
INVITE = (
    "INSERT INTO team_invitations (id, from_user_id, to_user_id, problem_id, note)"
    " VALUES (:id, :sender, :to, :problem, :note)"
)
DECIDE = "SELECT app_decide_team_invitation(:invitation, :decision)"
CLOSE = "SELECT app_close_team_thread(:thread, :reason)"
BLOCK = "SELECT app_block_developer(:blocked)"
UNBLOCK = "SELECT app_unblock_developer(:blocked)"
POST = "INSERT INTO team_messages (id, thread_id, sender_user_id, body) VALUES (:id, :thread, :sender, :body)"
PEERS = "SELECT * FROM app_peers(:limit, :offset)"
CARD = "SELECT * FROM app_developer_card(:user)"
REPORT = "SELECT case_id, created FROM app_report_team_message(:message, CAST(:reasons AS text[]))"
REPORTED = "SELECT * FROM app_reported_team_message(:case)"
HANDLES = "SELECT app_contributor_handles(:proposal)"
CONTRIBUTE = "INSERT INTO proposal_contributors (proposal_id, user_id, thread_id) VALUES (:proposal, :user, :thread)"


async def refused(conn: AsyncConnection, sql: str, match: str, sqlstate: str | None = None, **params: object) -> None:
    """Run ``sql`` in a savepoint, assert it fails with ``match`` (and ``sqlstate``); the transaction stays usable."""
    savepoint = await conn.begin_nested()
    with pytest.raises(DBAPIError, match=match) as caught:
        await conn.execute(sa.text(sql), params)
    await savepoint.rollback()
    if sqlstate is not None:
        assert getattr(caught.value.orig, "sqlstate", None) == sqlstate, caught.value


async def niche(conn: AsyncConnection, name: str) -> UUID:
    """As the owner: a niche whose slug starts with ``name`` (slugs sort by it)."""
    niche_id = uuid7()
    await t.run(
        conn,
        "INSERT INTO niches (id, slug, name_en) VALUES (:id, :slug, :name)",
        id=niche_id,
        slug=f"{name}-{niche_id.hex}",
        name=name.title(),
    )
    return niche_id


async def slug(conn: AsyncConnection, niche_id: UUID) -> str:
    found: str = await t.run(conn, "SELECT slug FROM niches WHERE id = :id", id=niche_id)
    return found


async def county(conn: AsyncConnection, name: str = "Kisumu") -> str:
    """As the owner: a county (the test database has no seed regions); Kenya, the country, is ``KE``."""
    await t.run(conn, "INSERT INTO regions (code, kind, name) VALUES ('KE', 'country', 'Kenya') ON CONFLICT DO NOTHING")
    code = f"XE-{uuid7().hex[-5:]}"
    await t.run(
        conn, "INSERT INTO regions (code, parent_code, kind, name) VALUES (:c, 'KE', 'county', :n)", c=code, n=name
    )
    return code


async def developer(
    conn: AsyncConnection,
    label: str,
    *,
    peers: bool = True,
    county_code: str | None = None,
    liked: tuple[UUID, ...] = (),
    followed: tuple[UUID, ...] = (),
    demo: bool = False,
    staff: str | None = None,
) -> UUID:
    """As the owner: a user with a developer profile (handle ``<label>-<hex>``), the peers switch as given, a county
    and liked (and followed) niches; a demo account or a staff member (with TOTP) when asked."""
    await t.as_owner(conn)
    user = await w.add_user(conn, f"{label}-{uuid7().hex}@example.test", label.title(), staff_role=staff)
    if demo:
        await t.run(conn, "UPDATE users SET demo_account = true WHERE id = :u", u=user)
    await t.run(
        conn,
        "INSERT INTO developer_profiles (user_id, handle, county_code, peers_visible) VALUES (:u, :h, :c, :p)",
        u=user,
        h=f"{label}-{user.hex[-12:]}",
        c=county_code,
        p=peers,
    )
    for niche_id, kind in [(n, "liked") for n in liked] + [(n, "followed") for n in followed]:
        await t.run(
            conn,
            "INSERT INTO developer_niches (user_id, niche_id, kind) VALUES (:u, :n, CAST(:k AS niche_interest))",
            u=user,
            n=niche_id,
            k=kind,
        )
    return user


async def common_niche(conn: AsyncConnection) -> UUID:
    """As the owner: the niche every ``peer`` likes (one per database, so the team tests' developers are peers)."""
    await t.as_owner(conn)
    await t.run(
        conn,
        "INSERT INTO niches (id, slug, name_en) VALUES (:id, 'teams-common', 'Teams') ON CONFLICT (slug) DO NOTHING",
        id=uuid7(),
    )
    found: UUID = await t.run(conn, "SELECT id FROM niches WHERE slug = 'teams-common'")
    return found


async def peer(conn: AsyncConnection, label: str, **options: Any) -> UUID:
    """As the owner: a developer (``developer``'s options) who also likes the common niche, so any two who opted in are
    peers and may invite each other."""
    liked = (await common_niche(conn), *options.pop("liked", ()))
    return await developer(conn, label, liked=liked, **options)


async def handle(conn: AsyncConnection, user: UUID) -> str:
    await t.as_owner(conn)
    found: str = await t.run(conn, "SELECT handle::text FROM developer_profiles WHERE user_id = :u", u=user)
    return found


async def organisation(conn: AsyncConnection, label: str) -> UUID:
    """As the owner: an E2 organisation (its Briefs may be published)."""
    await t.as_owner(conn)
    org = uuid7()
    await t.run(
        conn,
        "INSERT INTO organizations (id, kind, legal_name, slug, source, verification) VALUES (:id, 'company', :name,"
        " :slug, 'self_signup', 'e2')",
        id=org,
        name=f"{label.title()} Ltd",
        slug=f"{label}-{org.hex}",
    )
    return org


async def org_only(conn: AsyncConnection, org: UUID | None = None) -> UUID:
    """As the owner: a signed-in account without a developer profile, an owner and admin of an organisation."""
    org = org or await organisation(conn, "orgonly")
    user = await w.add_user(conn, f"member-{uuid7().hex}@example.test", "Member")
    await t.member(conn, org, user, "{owner,admin}")
    return user


async def problem(
    conn: AsyncConnection, by: UUID, *, status: str = "published", moderation_state: str = "clear"
) -> UUID:
    """As the owner: a developer's problem (published and clear unless told otherwise)."""
    await t.as_owner(conn)
    return await w.add_problem(conn, by, await niche(conn, "problem"), status=status, moderation_state=moderation_state)


async def brief(conn: AsyncConnection, org: UUID, by: UUID, *, visibility: str, status: str = "published") -> UUID:
    """As the owner: a published, clear problem of an E2 organisation with its Brief (``closed`` after publishing)."""
    await t.as_owner(conn)
    problem_id = await w.add_problem(conn, by, await niche(conn, "brief"), org_id=org)
    await t.run(
        conn,
        "INSERT INTO problem_briefs (problem_id, org_id, visibility, status) VALUES (:p, :o,"
        " CAST(:v AS brief_visibility), 'published')",
        p=problem_id,
        o=org,
        v=visibility,
    )
    if status != "published":
        await t.run(
            conn,
            "UPDATE problem_briefs SET status = CAST(:s AS brief_status) WHERE problem_id = :p",
            s=status,
            p=problem_id,
        )
    return problem_id


async def invite(conn: AsyncConnection, sender: UUID, to: UUID, problem_id: UUID, note: str | None = None) -> UUID:
    """As ``sender`` (bridge_app): an invitation to ``to`` on ``problem_id``."""
    invitation = uuid7()
    await t.act(conn, sender)
    await t.run(conn, INVITE, id=invitation, sender=sender, to=to, problem=problem_id, note=note)
    return invitation


def invitation_params(sender: UUID, to: UUID, problem_id: UUID, note: str | None = None) -> dict[str, Any]:
    return {"id": uuid7(), "sender": sender, "to": to, "problem": problem_id, "note": note}


async def decide(conn: AsyncConnection, by: UUID, invitation: UUID, decision: str) -> UUID | None:
    """As ``by``: the invitation's decision; the new thread's id for ``accept``."""
    await t.act(conn, by)
    thread: UUID | None = await t.run(conn, DECIDE, invitation=invitation, decision=decision)
    return thread


async def team(conn: AsyncConnection, sender: UUID, to: UUID, problem_id: UUID) -> tuple[UUID, UUID]:
    """An invitation from ``sender`` accepted by ``to``: (invitation, thread)."""
    invitation = await invite(conn, sender, to, problem_id)
    thread = await decide(conn, to, invitation, "accept")
    assert thread is not None
    return invitation, thread


async def post(conn: AsyncConnection, sender: UUID, thread: UUID, body: str = "Shall we split the work?") -> UUID:
    """As ``sender``: a message of the thread."""
    message = uuid7()
    await t.act(conn, sender)
    await t.run(conn, POST, id=message, thread=thread, sender=sender, body=body)
    return message


async def peers(conn: AsyncConnection, user: UUID, limit: int = 50, offset: int = 0) -> list[sa.Row[Any]]:
    """As ``user``: a page of their peers."""
    await t.act(conn, user)
    return list((await conn.execute(sa.text(PEERS), {"limit": limit, "offset": offset})).all())


async def peer_ids(conn: AsyncConnection, user: UUID) -> list[UUID]:
    return [row.user_id for row in await peers(conn, user)]


async def card(conn: AsyncConnection, caller: UUID | None, user: UUID) -> list[sa.Row[Any]]:
    await t.act(conn, caller)
    return list((await conn.execute(sa.text(CARD), {"user": user})).all())


async def count(conn: AsyncConnection, caller: UUID | None, sql: str, **params: object) -> int:
    """As ``caller`` (bridge_app): the first column of ``sql`` (a count)."""
    await t.act(conn, caller)
    found: int = await t.run(conn, sql, **params)
    return found
