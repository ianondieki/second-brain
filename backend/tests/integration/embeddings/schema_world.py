"""Fixtures of the embedding schema tests (revision 0012; REQ-PERS-02, REQ-EMB-01): developers with a profiling
decision, liked and followed niches and proposals; problems in each state; the worker (bridge_app with no user bound)
listing and writing vectors. Every helper runs inside one transaction of the owner engine (``tracker.as_app``) and
switches the role as it acts.

Within one transaction ``now()`` does not move, and the database stamps every vector with ``now()``. So a test that
needs "embedded a minute ago, changed since" first ages the fixtures (``age``: an hour back) and then moves the vector's
time a minute back (``embed_profile``/``embed_problem``); a change made afterwards is stamped ``now()``, later than the
vector, as a later transaction's would be."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t

MODEL, VERSION = "bge-m3-test", "1"
PROFILES = "SELECT user_id, text FROM app_profiles_to_embed(:model, :version, :limit)"
PROBLEMS = "SELECT problem_id, text FROM app_problems_to_embed(:model, :version, :limit)"
SET_PROFILE = "SELECT app_set_profile_embedding(:user, CAST(:vector AS vector), :model, :version)"
SET_PROBLEM = "SELECT app_set_problem_embedding(:problem, CAST(:vector AS vector), :model, :version)"
CLEAR = "SELECT app_clear_profile_embedding(:user)"
COUNTS = "SELECT profiles, problems FROM app_stale_embedding_counts(:model, :version)"
WORKER_ONLY = "the embedding worker only, with no user bound"
CONSENT = (
    "INSERT INTO consents (id, user_id, purpose, granted, text_version, text_sha256, source)"
    " VALUES (:id, :user, CAST(:purpose AS consent_purpose), :granted, 'v1', :sha, 'settings')"
)


def vector(first: float = 1.0, dims: int = 1024) -> str:
    """A vector literal: ``first`` then zeros."""
    return "[" + ",".join([repr(first)] + ["0"] * (dims - 1)) + "]"


async def decide(
    conn: AsyncConnection, user: UUID, granted: bool, purpose: str = "profiling", *, as_owner: bool = False
) -> None:
    """A consent decision, as the user (bridge_app, the settings page) unless ``as_owner``."""
    if as_owner:
        await t.as_owner(conn)
    else:
        await t.act(conn, user)
    await t.run(conn, CONSENT, id=uuid7(), user=user, purpose=purpose, granted=granted, sha=bytes(32))


async def named_niche(conn: AsyncConnection, name: str, sort_order: int = 0) -> UUID:
    """As the owner: a niche named ``name`` (English) at ``sort_order``."""
    await t.as_owner(conn)
    niche_id = uuid7()
    await t.run(
        conn,
        "INSERT INTO niches (id, slug, name_en, sort_order) VALUES (:id, :slug, :name, :order)",
        id=niche_id,
        slug=f"emb-{niche_id.hex}",
        name=name,
        order=sort_order,
    )
    return niche_id


async def proposal(
    conn: AsyncConnection,
    owner: UUID,
    niche_id: UUID,
    *,
    title: str,
    statement: str,
    status: str = "published",
    days_ago: int = 1,
) -> UUID:
    """As the owner: a proposal of ``owner`` with this Tier-1 title and problem statement, published ``days_ago`` days
    ago (a draft: never published; hidden: published, then hidden)."""
    await t.as_owner(conn)
    issue = await w.add_problem(conn, owner, niche_id)
    registered = status != "draft"
    proposal_id, _ = await w.add_proposal(
        conn, owner, niche_id, issue, status="published" if registered else "draft", registered=registered
    )
    await t.run(
        conn,
        "UPDATE proposals SET title = :title, problem_statement = :statement,"
        " published_at = CASE WHEN published_at IS NULL THEN NULL ELSE now() - make_interval(days => :days) END"
        " WHERE id = :id",
        id=proposal_id,
        title=title,
        statement=statement,
        days=days_ago,
    )
    if status == "hidden":
        await t.run(conn, "UPDATE proposals SET status = 'hidden', hidden_at = now() WHERE id = :id", id=proposal_id)
    return proposal_id


async def age(conn: AsyncConnection, *users: UUID) -> None:
    """As the owner: move the users' profile edits and proposal times an hour back."""
    await t.as_owner(conn)
    for user in users:
        await t.run(
            conn, "UPDATE developer_profiles SET updated_at = now() - interval '1 hour' WHERE user_id = :u", u=user
        )
        await t.run(
            conn,
            "UPDATE proposals SET updated_at = updated_at - interval '1 hour',"
            " published_at = published_at - interval '1 hour', hidden_at = hidden_at - interval '1 hour'"
            " WHERE owner_id = :u",
            u=user,
        )


async def profiles(
    conn: AsyncConnection, model: str = MODEL, version: str = VERSION, limit: int = 1000
) -> list[tuple[UUID, str]]:
    """As the worker: a page of ``app_profiles_to_embed``, in its order."""
    await t.act(conn, None)
    found = await conn.execute(sa.text(PROFILES), {"model": model, "version": version, "limit": limit})
    return [(row.user_id, row.text) for row in found]


async def listed(conn: AsyncConnection, *users: UUID, model: str = MODEL, version: str = VERSION) -> set[UUID]:
    """Which of ``users`` the profiles reader lists (other tests' committed rows may be listed too)."""
    return {user for user, _ in await profiles(conn, model, version)} & set(users)


async def problems(
    conn: AsyncConnection, model: str = MODEL, version: str = VERSION, limit: int = 1000
) -> list[tuple[UUID, str]]:
    await t.act(conn, None)
    found = await conn.execute(sa.text(PROBLEMS), {"model": model, "version": version, "limit": limit})
    return [(row.problem_id, row.text) for row in found]


async def set_profile(
    conn: AsyncConnection, user: UUID, *, model: str = MODEL, version: str = VERSION, first: float = 1.0
) -> bool:
    """As the worker: write ``user``'s profile vector; whether it wrote."""
    await t.act(conn, None)
    wrote: bool = await t.run(conn, SET_PROFILE, user=user, vector=vector(first), model=model, version=version)
    return wrote


async def set_problem(
    conn: AsyncConnection, problem_id: UUID, *, model: str = MODEL, version: str = VERSION, first: float = 1.0
) -> bool:
    await t.act(conn, None)
    wrote: bool = await t.run(conn, SET_PROBLEM, problem=problem_id, vector=vector(first), model=model, version=version)
    return wrote


async def embed_profile(conn: AsyncConnection, user: UUID, *, model: str = MODEL, version: str = VERSION) -> None:
    """Written by the worker, then dated a minute back (see the module's docstring)."""
    assert await set_profile(conn, user, model=model, version=version)
    await t.as_owner(conn)
    await t.run(
        conn,
        "UPDATE developer_profiles SET profile_embedded_at = now() - interval '1 minute' WHERE user_id = :u",
        u=user,
    )


async def embed_problem(conn: AsyncConnection, problem_id: UUID) -> None:
    assert await set_problem(conn, problem_id)
    await t.as_owner(conn)
    await t.run(
        conn,
        "UPDATE problems SET embedded_at = now() - interval '1 minute', updated_at = now() - interval '1 hour'"
        " WHERE id = :id",
        id=problem_id,
    )


async def stored_profile(conn: AsyncConnection, user: UUID) -> dict[str, Any]:
    """As the owner: the profile's vector (its first value), model, version and time."""
    await t.as_owner(conn)
    found = await conn.execute(
        sa.text(
            "SELECT (profile_embedding::real[])[1] AS first, embed_model, embed_version, profile_embedded_at"
            " FROM developer_profiles WHERE user_id = :u"
        ),
        {"u": user},
    )
    return dict(found.one()._mapping)


async def stored_problem(conn: AsyncConnection, problem_id: UUID) -> dict[str, Any]:
    await t.as_owner(conn)
    found = await conn.execute(
        sa.text(
            "SELECT (embedding::real[])[1] AS first, embed_model, embed_version, embedded_at FROM problems"
            " WHERE id = :id"
        ),
        {"id": problem_id},
    )
    return dict(found.one()._mapping)
