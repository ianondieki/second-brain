"""Fixtures of the event and trend schema tests (revision 0010, REQ-DEV-02): the people (developers, an E2
organisation with a member of every role, a second organisation, staff), an event as its poster writes it, the decided
and cancelled states through the definers, a county, and a trend candidate as the job sends it. Every helper runs
inside one transaction of the owner engine (``tracker.as_app``) and switches the role as it acts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.ids import uuid7
from tests.integration import world as w
from tests.integration.engagements import tracker as t

RLS = "row-level security"
DENIED = "permission denied"
POST = (
    "INSERT INTO events (id, org_id, created_by, title, description, starts_at, ends_at, online, venue, county_code,"
    " join_url, link) VALUES (:id, :org, :by, :title, :description, :starts, :ends, :online, :venue, :county,"
    " :join_url, :link)"
)
DECIDE = "SELECT app_decide_event(:event, :decision, :seen)"
CANCEL = "SELECT app_cancel_event(:event)"
REMIND = "INSERT INTO event_reminders (user_id, event_id) VALUES (:user, :event)"
DUE = "SELECT user_id, event_id FROM app_event_reminders_due(:now)"
CREATE_TREND = "SELECT app_create_trend_candidate(CAST(:card AS jsonb), CAST(:sources AS jsonb))"
DECIDE_TREND = "SELECT app_decide_trend_card(:card, :decision)"


@dataclass(frozen=True, slots=True)
class People:
    developer: UUID
    other: UUID  # a second developer
    org: UUID  # E2
    owner: UUID  # owner and admin of org
    signatory: UUID
    reviewer: UUID
    finance: UUID
    viewer: UUID  # also an organisation-only account: no developer profile
    other_org: UUID  # E2
    other_editor: UUID  # owner and admin of other_org
    admin: UUID  # staff admin with TOTP
    moderator: UUID  # staff moderator with TOTP


async def developer(conn: AsyncConnection, label: str) -> UUID:
    """As the owner: an active user with a developer profile."""
    user = await w.add_user(conn, f"{label}-{uuid7().hex}@example.test", label.title())
    await t.run(
        conn, "INSERT INTO developer_profiles (user_id, handle) VALUES (:u, :h)", u=user, h=f"{label}-{user.hex}"
    )
    return user


async def organisation(conn: AsyncConnection, label: str) -> UUID:
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


async def member(conn: AsyncConnection, org: UUID, label: str, roles: str) -> UUID:
    user = await w.add_user(conn, f"{label}-{uuid7().hex}@example.test", label.title())
    await t.member(conn, org, user, roles)
    return user


async def people(conn: AsyncConnection) -> People:
    devs = [await developer(conn, label) for label in ("dev", "other")]
    org, other_org = await organisation(conn, "events"), await organisation(conn, "rival")
    staff = [
        await w.add_user(conn, f"{role}-{uuid7().hex}@example.test", role.title(), staff_role=role)
        for role in ("admin", "moderator")
    ]
    return People(
        devs[0],
        devs[1],
        org=org,
        owner=await member(conn, org, "owner", "{owner,admin}"),
        signatory=await member(conn, org, "signatory", "{signatory}"),
        reviewer=await member(conn, org, "reviewer", "{reviewer}"),
        finance=await member(conn, org, "finance", "{finance}"),
        viewer=await member(conn, org, "viewer", "{viewer}"),
        other_org=other_org,
        other_editor=await member(conn, other_org, "rival", "{owner,admin}"),
        admin=staff[0],
        moderator=staff[1],
    )


async def county(conn: AsyncConnection) -> str:
    """As the owner: a county (the test database has no seed regions)."""
    await t.run(conn, "INSERT INTO regions (code, kind, name) VALUES ('KE', 'country', 'Kenya') ON CONFLICT DO NOTHING")
    code = f"XE-{uuid7().hex[-4:]}"
    await t.run(
        conn, "INSERT INTO regions (code, parent_code, kind, name) VALUES (:c, 'KE', 'county', 'Kisumu')", c=code
    )
    return code


async def clock(conn: AsyncConnection) -> datetime:
    now: datetime = await t.run(conn, "SELECT app_clock_now()")
    return now


def event(org: UUID | None, by: UUID, now: datetime, **overrides: Any) -> dict[str, Any]:
    """An online event two days after ``now``, two hours long."""
    starts = now + timedelta(days=2)
    params: dict[str, Any] = {
        "id": uuid7(),
        "org": org,
        "by": by,
        "title": "Nairobi Python meetup",
        "description": "Talks and a workshop.\nBring a laptop.",
        "starts": starts,
        "ends": starts + timedelta(hours=2),
        "online": True,
        "venue": None,
        "county": None,
        "join_url": "https://meet.example.test/python",
        "link": None,
    }
    return params | overrides


async def post(conn: AsyncConnection, org: UUID | None, by: UUID, now: datetime, **overrides: Any) -> UUID:
    """As ``by`` (bridge_app, the organisation's context when it has one): a draft event."""
    await t.act(conn, by, org)
    params = event(org, by, now, **overrides)
    await t.run(conn, POST, **params)
    return UUID(str(params["id"]))


async def seen_of(conn: AsyncConnection, event_id: UUID) -> datetime:
    """As the owner: the event's updated_at, the version a reviewer reads."""
    await t.as_owner(conn)
    seen: datetime = await t.run(conn, "SELECT updated_at FROM events WHERE id = :id", id=event_id)
    return seen


async def decide(conn: AsyncConnection, staff: UUID, event_id: UUID, decision: str = "publish") -> None:
    """As ``staff``: decide the event as it is now (the version they reviewed)."""
    seen = await seen_of(conn, event_id)
    await t.act(conn, staff)
    await t.run(conn, DECIDE, event=event_id, decision=decision, seen=seen)


async def published(conn: AsyncConnection, p: People, now: datetime, **overrides: Any) -> UUID:
    """An event of ``p.org`` posted by its reviewer and published by the moderator."""
    event_id = await post(conn, p.org, p.reviewer, now, **overrides)
    await decide(conn, p.moderator, event_id)
    return event_id


async def status_of(conn: AsyncConnection, event_id: UUID) -> sa.Row[Any]:
    """As the owner: the event's status and decision columns."""
    await t.as_owner(conn)
    found = await conn.execute(
        sa.text("SELECT status, decided_by, decided_at, cancelled_at, title FROM events WHERE id = :id"),
        {"id": event_id},
    )
    return found.one()


async def visible(conn: AsyncConnection, user: UUID | None, ids: list[UUID], org: UUID | None = None) -> set[UUID]:
    """As ``user``: which of ``ids`` the events' SELECT policy shows."""
    await t.act(conn, user, org)
    found = await conn.execute(sa.text("SELECT id FROM events WHERE id = ANY(:ids)"), {"ids": ids})
    return set(found.scalars())


def source(**overrides: Any) -> dict[str, Any]:
    """One trend source as the job sends it."""
    found = {
        "url": "https://blog.example.test/2026/09/edge-ai",
        "publisher": "Example Tech Blog",
        "published_date": "2026-09-01",
        "retrieved_at": "2026-09-02",
        "quote": "On-device inference grew threefold this year.",
        "excerpt_ref": "tech:edge-ai.1",
        "support": "Edge AI adoption is growing.",
    }
    return found | overrides


def card(**overrides: Any) -> dict[str, Any]:
    found: dict[str, Any] = {
        "title": "Edge AI moves onto phones",
        "summary": "Phone makers ship on-device models for translation and photos.",
        "topic_slug": "edge-ai",
        "confidence": 0.8125,
        "llm_trace_id": "trend-0001",
    }
    return found | overrides
