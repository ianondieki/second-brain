"""Fixtures for the engagement thread's API tests (P21 track A; REQ-ENG-11, AC-TRACK-9, N18).

A committed world (``api_world.build``), its engagement walked through the API to the stage a test needs, helpers that
post, upload and read as a signed-in client, a runner for the queued N18 jobs (as the worker would run them), and an
ending appended as the party (or the system) that ends it, for the terminal states the API cannot reach after stage 3.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import Settings, get_settings
from bridge.db import create_session_factory
from bridge.engagements import message_notify
from bridge.ids import uuid7
from bridge.notifications.email import FakeEmailProvider
from bridge.storage.objects import InMemoryObjectStore
from tests.integration.engagements.api_world import (
    Seats,
    Tracker,
    World,
    build,
    clients,
    db_today,
    deals_on,
    open_engagement,
    seats,
    walk_to,
)

PDF = b"%PDF-1.7\n% a pilot plan\n"


def thread_path(engagement: UUID, suffix: str = "") -> str:
    return f"/api/engagements/{engagement}/messages{suffix}"


@dataclass(frozen=True, slots=True)
class Thread:
    world: World
    engagement: UUID
    tracker: Tracker
    seats: Seats
    viewer: httpx.AsyncClient
    settings: Settings
    store: InMemoryObjectStore  # shared by every client's app, as one object store is in production

    @property
    def clients(self) -> tuple[httpx.AsyncClient, ...]:
        s = self.seats
        return (s.dev, s.owner, s.signatory, s.reviewer, s.finance, self.viewer)


def share_store(store: InMemoryObjectStore, *signed_in: httpx.AsyncClient) -> None:
    for client in signed_in:
        client.app.state.object_store = store  # type: ignore[attr-defined]


@asynccontextmanager
async def thread_at(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, until: str = "INTEREST_CONFIRMED", *, deals: bool = False
) -> AsyncIterator[Thread]:
    """A fresh world whose engagement the parties walked through the API to ``until`` (the owner named as contact)."""
    world = await build(owner_engine)
    engagement = await open_engagement(app_engine, world)
    settings = deals_on() if deals else get_settings()
    tracker = Tracker(engagement)
    async with seats(app_engine, settings, world) as s, clients(app_engine, settings, world.viewer) as [viewer]:
        if until != "SUBMITTED":
            await walk_to(tracker, s, world, await db_today(owner_engine), until)
        thread = Thread(world, engagement, tracker, s, viewer, settings, InMemoryObjectStore())
        share_store(thread.store, *thread.clients)
        yield thread


async def post(
    client: httpx.AsyncClient, engagement: UUID, body: str = "Hello.", attachments: Sequence[UUID | str] = ()
) -> httpx.Response:
    return await client.post(
        thread_path(engagement), json={"body": body, "attachment_ids": [str(a) for a in attachments]}
    )


async def posted(client: httpx.AsyncClient, engagement: UUID, body: str = "Hello.", **kwargs: Any) -> dict[str, Any]:
    response = await post(client, engagement, body, **kwargs)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


async def read(client: httpx.AsyncClient, engagement: UUID, **params: Any) -> dict[str, Any]:
    response = await client.get(thread_path(engagement), params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def upload(
    client: httpx.AsyncClient,
    engagement: UUID,
    data: bytes = PDF,
    *,
    content_type: str = "application/pdf",
    name: str = "pilot plan.pdf",
) -> httpx.Response:
    return await client.post(
        thread_path(engagement, "/attachments"),
        content=data,
        headers={"Content-Type": content_type, "X-File-Name": quote(name)},
    )


async def uploaded(client: httpx.AsyncClient, engagement: UUID, data: bytes = PDF, **kwargs: Any) -> UUID:
    response = await upload(client, engagement, data, **kwargs)
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def code(response: httpx.Response) -> tuple[int, str]:
    detail = response.json()["detail"]
    return response.status_code, str(detail["code"] if isinstance(detail, dict) else "validation")


async def message_jobs(owner_engine: AsyncEngine, engagement: UUID) -> list[tuple[int, dict[str, Any]]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, args FROM procrastinate_jobs WHERE queue_name = :q AND task_name = :t"
                " AND args->>'engagement_id' = :e ORDER BY id"
            ),
            {"q": message_notify.QUEUE, "t": message_notify.TASK, "e": str(engagement)},
        )
        return [(int(job_id), dict(args)) for job_id, args in rows.all()]


async def run_message_jobs(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, engagement: UUID, provider: FakeEmailProvider
) -> int:
    """Run the engagement's queued N18 jobs as the worker would, then delete them."""
    jobs = await message_jobs(owner_engine, engagement)
    factory = create_session_factory(app_engine)
    for _, args in jobs:
        done = await message_notify.deliver(
            factory,
            provider,
            get_settings(),
            engagement_id=UUID(args["engagement_id"]),
            message_id=UUID(args["message_id"]),
            developer_id=UUID(args["developer_id"]),
        )
        assert done
    if jobs:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM procrastinate_jobs WHERE id = ANY(:ids)"), {"ids": [job_id for job_id, _ in jobs]}
            )
    return len(jobs)


async def in_app(owner_engine: AsyncEngine, user: UUID, kind: str = message_notify.KIND) -> list[dict[str, Any]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT kind, title, body, link, org_id FROM in_app_notifications WHERE user_id = :u AND kind = :k"
                " ORDER BY created_at, id"
            ),
            {"u": user, "k": kind},
        )
        return [dict(row._mapping) for row in rows]


async def email_of(owner_engine: AsyncEngine, user: UUID) -> str:
    async with owner_engine.connect() as conn:
        return str((await conn.execute(text("SELECT email FROM users WHERE id = :u"), {"u": user})).scalar_one())


async def append(
    owner_engine: AsyncEngine,
    engagement: UUID,
    *,
    actor: UUID | None,
    role: str,
    org: UUID | None,
    to_state: str,
    command: str,
    reason: str | None = None,
    bound: UUID | None = None,
) -> None:
    """Append one event from wherever the engagement is to ``to_state``, written as bridge_app by ``actor`` (bound
    as ``bound`` for a system event), as the tracker's schema tests do, for the paths the API has no command for."""
    async with owner_engine.begin() as conn:
        here = (
            await conn.execute(text("SELECT state::text FROM engagements WHERE id = :e"), {"e": engagement})
        ).scalar()
        await conn.execute(text("SET LOCAL ROLE bridge_app"))
        await conn.execute(
            text("SELECT set_config('app.user_id', :u, true), set_config('app.org_id', :o, true)"),
            {"u": str(actor or bound), "o": str(org) if org else ""},
        )
        await conn.execute(
            text(
                "INSERT INTO engagement_events (id, engagement_id, actor_user_id, actor_role, command, from_state,"
                " to_state, end_reason, payload) VALUES (:id, :e, :actor, CAST(:role AS engagement_actor_role),"
                " :command, CAST(:here AS engagement_state), CAST(:there AS engagement_state),"
                " CAST(:reason AS engagement_end_reason), CAST(:payload AS jsonb))"
            ),
            {
                "id": uuid7(),
                "e": engagement,
                "actor": actor,
                "role": role,
                "command": command,
                "here": here,
                "there": to_state,
                "reason": reason,
                "payload": json.dumps({}),
            },
        )


async def end(owner_engine: AsyncEngine, world: World, engagement: UUID, state: str) -> None:
    """End the engagement in ``state`` as the party that ends it (the system for an expiry, bound to the developer):
    DECLINED and TERMINATED have no API path after stage 3 yet, and an expiry needs the job and the clock."""
    actor, role, org, reason = {
        "DECLINED": (world.signatory, "signatory", world.org, "NOT_PRIORITY"),
        "WITHDRAWN": (world.developer, "developer", None, None),
        "EXPIRED": (None, "system", None, "CONTACT_NOT_MADE"),
        "TERMINATED": (world.owner, "owner", world.org, None),
    }[state]
    await append(
        owner_engine,
        engagement,
        actor=actor,
        role=role,
        org=org,
        to_state=state,
        command=state.lower(),
        reason=reason,
        bound=world.developer,
    )
