"""Helpers for the Team tests (REQ-TEN-02, P28 track C): people, links, rows and codes."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import Settings
from bridge.ids import uuid7
from bridge.notifications.email import EmailMessage
from tests.integration.api import outbox
from tests.integration.engagements.api_world import World, build, deals_on
from tests.integration.matching.scout_world import subscribe

SETTINGS: Settings = deals_on()
LINK = re.compile(r"https?://[^/\s]+/invitations/([A-Za-z0-9_-]{43})")


def code(response: httpx.Response) -> tuple[int, str | None]:
    body = response.json() if response.content else None
    detail = body.get("detail") if isinstance(body, dict) else None
    return response.status_code, detail.get("code") if isinstance(detail, dict) else None


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def person(owner_engine: AsyncEngine, email: str | None = None, *, verified: bool = True) -> tuple[UUID, str]:
    """A user (TOTP enrolled) with ``email`` (a fresh address if None), verified unless ``verified`` is False."""
    user_id = uuid7()
    address = email or f"invitee-{uuid4().hex[:10]}@example.com"  # EmailStr refuses .test
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (id, email, display_name, email_verified_at, totp_enabled_at)"
                " VALUES (:id, :email, :name, CASE WHEN :verified THEN now() END, now())"
            ),
            {"id": user_id, "email": address, "name": f"Invitee {uuid4().hex[:4]}", "verified": verified},
        )
    return user_id, address


def address() -> str:
    return f"newcomer-{uuid4().hex[:10]}@example.com"


def mail_to(client: httpx.AsyncClient, to: str) -> list[EmailMessage]:
    return [m for m in outbox(client).outbox if m.to == to]


def token_in(message: EmailMessage) -> str:
    found = LINK.search(message.text)
    assert found is not None, message.text
    return found.group(1)


async def invite(client: httpx.AsyncClient, org: UUID, email: str, roles: list[str] | None = None) -> httpx.Response:
    return await client.post(f"/api/orgs/{org}/invitations", json={"email": email, "roles": roles or ["reviewer"]})


async def audit_actions(owner_engine: AsyncEngine, org: UUID, prefix: str) -> list[Any]:
    return await rows(
        owner_engine,
        "SELECT action, actor_user_id, actor_kind::text AS actor_kind, subject_type, subject_id, payload"
        " FROM audit_events WHERE org_id = :org AND action LIKE :prefix ORDER BY occurred_at, seq",
        org=org,
        prefix=f"{prefix}%",
    )


async def team_world(owner_engine: AsyncEngine, plan: str | None = "org_enterprise") -> World:
    """The tracker's world (an E2 organisation, five members) on ``plan`` (Enterprise: seats unlimited, so the
    invitation tests are about invitations; None leaves it on the free plan, whose 2 seats it already exceeds)."""
    world = await build(owner_engine)
    if plan is not None:
        await subscribe(owner_engine, world.org, plan)
    return world
