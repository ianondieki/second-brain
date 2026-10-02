"""Fixtures for the tracker API tests (P5): a committed world of two parties, clients signed in as each person, the
engagement opened the way P4 will open it (``open_engagement_for_tag``), and a runner for the queued notification
jobs.

Rows are written as the owner role and committed (the API runs in its own transactions as ``bridge_app``); every world
has its own developer, organisation and proposal, so tests never share an engagement.
"""

from __future__ import annotations

import base64
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.auth import totp
from bridge.auth.crypto import encrypt
from bridge.config import Settings, get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.engagements import notify
from bridge.engagements.calendar import add_business_days
from bridge.engagements.commands import open_engagement_for_tag
from bridge.ids import uuid7
from bridge.notifications.email import FakeEmailProvider
from tests.integration import world as w
from tests.integration.api import make_client, sign_in_as

MUTUAL_NDA_VERSION = "p5-test"
PROPOSAL_TITLE = "RLS proposal"  # tests/integration/world.add_proposal


def deals_on(settings: Settings | None = None) -> Settings:
    """The test settings with FEATURE_DEALS_ENABLED on (AC-SEC-7 keeps deal steps off by default)."""
    return (settings or get_settings()).model_copy(update={"feature_deals_enabled": True})


@dataclass(frozen=True, slots=True)
class World:
    developer: UUID  # D2 unless built otherwise, TOTP enrolled, verified email
    developer_email: str
    totp_secret: str  # the developer's TOTP secret (for a real /api/auth/step-up)
    org: UUID  # E2, verified domain
    org_name: str
    owner: UUID  # owner + admin, TOTP
    signatory: UUID  # TOTP
    reviewer: UUID  # TOTP
    finance: UUID
    viewer: UUID
    proposal: UUID
    version: UUID
    tag: UUID
    outsider: UUID  # another developer, TOTP
    staff: UUID  # staff admin, TOTP


async def run(conn: AsyncConnection, sql: str, **params: object) -> Any:
    result = await conn.execute(text(sql), params)
    return result.scalar() if result.returns_rows else None


async def _user(conn: AsyncConnection, prefix: str, domain: str, *, totp_on: bool) -> UUID:
    user_id = uuid7()
    now = datetime.now(UTC)
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


async def ensure_mutual_nda(conn: AsyncConnection) -> None:
    """A mutual NDA template (a placeholder body), as the seed installs one."""
    body = "DRAFT - TEST PLACEHOLDER\n\n[[LEGAL-PLACEHOLDER:mutual-nda-p5-test]]\n"
    legal = await run(
        conn,
        "INSERT INTO legal_templates (id, kind, version, body, sha256) VALUES (:id, 'mutual_nda', :v, :body,"
        " sha256(convert_to(:body, 'UTF8'))) ON CONFLICT (kind, version) DO NOTHING RETURNING id",
        id=uuid7(),
        v=MUTUAL_NDA_VERSION,
        body=body,
    )
    if legal is not None:
        await run(
            conn,
            "INSERT INTO nda_templates (id, kind, version, legal_template_id, sha256)"
            " SELECT :id, 'mutual', :v, id, sha256 FROM legal_templates WHERE id = :legal",
            id=uuid7(),
            v=MUTUAL_NDA_VERSION,
            legal=legal,
        )


async def build(owner_engine: AsyncEngine, *, d2: bool = True, public_entity: bool = False) -> World:
    """As the owner, committed: the developer's published proposal delivered by tag to an E2 organisation."""
    domain = f"org-{uuid4().hex[:10]}.example.test"
    secret = totp.new_secret()
    async with owner_engine.begin() as conn:
        developer = await _user(conn, "developer", "dev.example.test", totp_on=True)
        key = base64.b64decode(get_settings().data_encryption_key.get_secret_value())
        await run(
            conn,
            "UPDATE users SET totp_secret_enc = :secret WHERE id = :id",
            secret=encrypt(key, secret.encode("ascii"), developer.bytes),
            id=developer,
        )
        org = uuid7()
        org_name = f"Telco {uuid4().hex[:6]} (fixture)"
        await run(
            conn,
            "INSERT INTO organizations (id, kind, legal_name, slug, source, verification, verified_domain,"
            " public_entity) VALUES (:id, 'company', :name, :slug, 'seed', 'e2', :domain, :public)",
            id=org,
            name=org_name,
            slug=f"p5-{org.hex}",
            domain=domain,
            public=public_entity,
        )
        people: dict[str, UUID] = {}
        for name, roles, totp_on in (
            ("owner", "{owner,admin}", True),
            ("signatory", "{signatory}", True),
            ("reviewer", "{reviewer}", True),
            ("finance", "{finance}", True),
            ("viewer", "{viewer}", False),
        ):
            people[name] = await _user(conn, name, domain, totp_on=totp_on)
            await run(
                conn,
                "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :u, CAST(:r AS org_role[]))",
                id=uuid7(),
                org=org,
                u=people[name],
                r=roles,
            )
        niche = uuid7()
        await run(conn, "INSERT INTO niches (id, slug, name_en) VALUES (:id, :s, 'P5')", id=niche, s=f"p5-{niche.hex}")
        problem = await w.add_problem(conn, developer, niche)
        proposal, version = await w.add_proposal(conn, developer, niche, problem)
        if d2:
            await run(conn, "UPDATE developer_profiles SET verification_level = 'd2' WHERE user_id = :u", u=developer)
        tag = uuid7()
        await run(
            conn,
            "INSERT INTO tags (id, proposal_id, org_id, developer_id, status) VALUES (:id, :p, :o, :d, 'delivered')",
            id=tag,
            p=proposal,
            o=org,
            d=developer,
        )
        outsider = await _user(conn, "outsider", "elsewhere.example.test", totp_on=True)
        staff = await w.add_user(conn, f"staff-{uuid4().hex[:8]}@example.test", "Staff", staff_role="admin")
        await ensure_mutual_nda(conn)
        developer_email = str(await run(conn, "SELECT email FROM users WHERE id = :id", id=developer))
    return World(
        developer=developer,
        developer_email=developer_email,
        totp_secret=secret,
        org=org,
        org_name=org_name,
        owner=people["owner"],
        signatory=people["signatory"],
        reviewer=people["reviewer"],
        finance=people["finance"],
        viewer=people["viewer"],
        proposal=proposal,
        version=version,
        tag=tag,
        outsider=outsider,
        staff=staff,
    )


async def open_engagement(app_engine: AsyncEngine, world: World) -> UUID:
    """The developer opens the SUBMITTED engagement of their delivered tag, as P4 will (``open_engagement_for_tag``)."""
    factory = create_session_factory(app_engine)
    async with factory() as db:
        await bind_tenant(db, user_id=world.developer)
        engagement = await open_engagement_for_tag(db, world.tag)
        await db.commit()
        return engagement.id


@asynccontextmanager
async def clients(
    app_engine: AsyncEngine, settings: Settings, *users: UUID, mfa_verified: bool = True
) -> AsyncIterator[list[httpx.AsyncClient]]:
    """One signed-in client per user (each with its own app instance and cookies)."""
    async with AsyncExitStack() as stack:
        signed_in = []
        for index, user in enumerate(users):
            client = await stack.enter_async_context(make_client(app_engine, settings, ip=f"127.0.1.{index + 1}"))
            await sign_in_as(client, app_engine, user, mfa_verified=mfa_verified)
            signed_in.append(client)
        yield signed_in


class Tracker:
    """Drives one engagement through the API as a given client, keeping its ``lock_version`` fresh."""

    def __init__(self, engagement: UUID) -> None:
        self.engagement = engagement

    def path(self, suffix: str = "") -> str:
        return f"/api/engagements/{self.engagement}{suffix}"

    async def detail(self, client: httpx.AsyncClient) -> dict[str, Any]:
        response = await client.get(self.path())
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def post(
        self, client: httpx.AsyncClient, command: str, body: dict[str, Any] | None = None, *, lock: int | None = None
    ) -> httpx.Response:
        if lock is None:
            lock = int((await client.get(self.path())).json().get("lock_version", 0))
        return await client.post(self.path(f"/{command}"), json={"lock_version": lock, **(body or {})})

    async def ok(self, client: httpx.AsyncClient, command: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.post(client, command, body)
        assert response.status_code == 200, (command, response.status_code, response.text)
        detail: dict[str, Any] = response.json()
        return detail


async def notification_jobs(owner_engine: AsyncEngine, engagement: UUID) -> list[tuple[int, dict[str, Any]]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, args FROM procrastinate_jobs WHERE queue_name = :q AND task_name = :t"
                " AND args->>'engagement_id' = :e ORDER BY id"
            ),
            {"q": notify.QUEUE, "t": notify.TASK, "e": str(engagement)},
        )
        return [(int(job_id), dict(args)) for job_id, args in rows.all()]


async def run_notifications(
    owner_engine: AsyncEngine,
    app_engine: AsyncEngine,
    engagement: UUID,
    provider: FakeEmailProvider,
    settings: Settings | None = None,
    *,
    keep: bool = False,
) -> int:
    """Run the engagement's queued notification jobs as the worker would, then delete them (unless ``keep``)."""
    jobs = await notification_jobs(owner_engine, engagement)
    factory = create_session_factory(app_engine)
    for _, args in jobs:
        done = await notify.deliver(
            factory,
            provider,
            settings or get_settings(),
            engagement_id=UUID(args["engagement_id"]),
            event_id=UUID(args["event_id"]),
            developer_id=UUID(args["developer_id"]),
            reason_text=args.get("reason_text"),
        )
        assert done
    if jobs and not keep:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM procrastinate_jobs WHERE id = ANY(:ids)"), {"ids": [job_id for job_id, _ in jobs]}
            )
    return len(jobs)


MAIN_PATH = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "INTEREST_CONFIRMED",
    "CONTACT_MADE",
    "NDA_PENDING",
    "NDA_SIGNED",
    "NEGOTIATION",
    "AGREEMENT_SIGNING",
    "IN_IMPLEMENTATION",
    "DELIVERED",
    "SIGN_OFF",
    "PAYMENT_FINAL",
    "CLOSED",
)
FINAL_AMOUNT = 25_000_000  # KES 250,000.00


async def db_today(engine: AsyncEngine) -> date:
    """Today in Nairobi on the shared clock (the test clock may run ahead of the wall clock)."""
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT (app_clock_now() AT TIME ZONE 'Africa/Nairobi')::date"))
        today: date = result.scalar_one()
        return today


async def holidays_of(owner_engine: AsyncEngine) -> frozenset[date]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(text("SELECT observed_on FROM holidays WHERE country = 'KE'"))
        return frozenset(rows.scalars().all())


@asynccontextmanager
async def moved_clock(owner_engine: AsyncEngine) -> AsyncIterator[Callable[[int], Awaitable[None]]]:
    """The shared dev/test clock, moved forward by whole days on demand, and put back as it was at the end."""
    async with owner_engine.connect() as conn:
        enabled, offset = (await conn.execute(text("SELECT enabled, clock_offset FROM test_clock"))).one()
    moved = [offset]

    async def advance(days: int) -> None:
        moved[0] += timedelta(days=days)
        async with owner_engine.begin() as conn:
            await conn.execute(text("UPDATE test_clock SET enabled = true, clock_offset = :o"), {"o": moved[0]})

    try:
        yield advance
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("UPDATE test_clock SET enabled = :e, clock_offset = :o"), {"e": enabled, "o": offset}
            )


async def business_days_later(owner_engine: AsyncEngine, advance: Callable[[int], Awaitable[None]], n: int) -> date:
    """Move the clock to the ``n``-th Kenyan business day after today (Nairobi); returns that date."""
    today = await db_today(owner_engine)
    later = add_business_days(today, n, await holidays_of(owner_engine))
    await advance((later - today).days)
    assert await db_today(owner_engine) == later
    return later


def simple_terms(today: date, ip_terms: str = "non_exclusive_licence") -> dict[str, Any]:
    return {
        "ip_terms": ip_terms,
        "deemed_acceptance_days": 0,
        "milestones": [
            {"deliverable": "Pilot", "amount_kes_minor": FINAL_AMOUNT, "due_date": str(today + timedelta(days=30))}
        ],
    }


@dataclass(frozen=True, slots=True)
class Seats:
    """Signed-in clients for the people of a world."""

    dev: httpx.AsyncClient
    owner: httpx.AsyncClient
    signatory: httpx.AsyncClient
    reviewer: httpx.AsyncClient
    finance: httpx.AsyncClient


@asynccontextmanager
async def seats(app_engine: AsyncEngine, settings: Settings, world: World) -> AsyncIterator[Seats]:
    async with clients(
        app_engine, settings, world.developer, world.owner, world.signatory, world.reviewer, world.finance
    ) as signed_in:
        yield Seats(*signed_in)


async def walk_to(t: Tracker, s: Seats, world: World, today: date, until: str) -> dict[str, Any]:
    """Take the engagement along the main path (one milestone, the organisation drafting the terms) to ``until``,
    each step by its party through the API; returns the last detail read."""
    detail = await t.detail(s.dev)
    while detail["state"] != until:
        here = detail["state"]
        if here == "SUBMITTED":
            detail = await t.ok(s.reviewer, "start-review")
        elif here == "UNDER_REVIEW":
            contact = {"contact_user_id": str(world.owner), "contact_channel": "phone", "contact_by": str(today)}
            detail = await t.ok(s.signatory, "approve", contact)
        elif here == "INTEREST_CONFIRMED":
            detail = await t.ok(s.owner, "mark-contacted")
        elif here == "CONTACT_MADE":
            if "confirm_contact" in (await t.detail(s.dev))["actions"]:
                await t.ok(s.dev, "confirm-contact")
            detail = await t.ok(s.dev, "send-nda")
        elif here == "NDA_PENDING":
            await t.ok(s.dev, "sign-nda")
            detail = await t.ok(s.signatory, "sign-nda")
        elif here == "NDA_SIGNED":
            detail = await t.ok(s.owner, "propose-terms", simple_terms(today))
        elif here == "NEGOTIATION":
            detail = await t.ok(s.dev, "mark-final")
        elif here == "AGREEMENT_SIGNING":
            await t.ok(s.signatory, "sign-agreement")
            detail = await t.ok(s.dev, "sign-agreement")
        elif here == "IN_IMPLEMENTATION":
            milestone = detail["agreements"][0]["milestones"][0]["id"]
            for step, client in (("start", s.dev), ("submit", s.dev), ("accept", s.reviewer)):
                await t.ok(client, f"milestones/{milestone}/{step}")
            detail = await t.ok(s.dev, "deliver")
        elif here == "DELIVERED":
            detail = await t.ok(s.reviewer, "accept-delivery")
        elif here == "SIGN_OFF":
            await t.ok(s.signatory, "sign-certificate")
            detail = await t.ok(s.dev, "sign-certificate")
        elif here == "PAYMENT_FINAL":
            payment = {"amount_kes_minor": FINAL_AMOUNT, "method": "bank", "paid_on": str(today)}
            await t.ok(s.finance, "record-payment", payment)
            detail = await t.ok(s.dev, "confirm-payment", {"amount_received_kes_minor": FINAL_AMOUNT})
        else:  # pragma: no cover - a test asked for a state off the main path
            raise AssertionError(f"cannot walk from {here} to {until}")
        assert MAIN_PATH.index(detail["state"]) > MAIN_PATH.index(here), (here, detail["state"])
    return detail
