"""Helpers of This week's API, reminder and trend tests (REQ-DEV-02; P22 card B): a database of the module's own
(``conftest.week``) with Kenya's counties, a fresh future week per test, the shared clock moved to a Nairobi day and
time (committed, as the dev and test clock is), the people (developers with a county, an E2 organisation with a seat of
every role, an E1 one, a second E2 one, staff), events posted as their poster and decided by staff through the
definers, and signed-in clients of the in-process API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.db import bind_tenant, create_session_factory
from bridge.engagements.calendar import NAIROBI
from bridge.ids import uuid7
from tests.integration.api import make_client, sign_in_as
from tests.integration.matching.scout_world import Org, add_org, add_person, run

NAIROBI_CITY, MOMBASA, MACHAKOS = "KE-30", "KE-28", "KE-22"
_CLOCK_TO: Final = text(
    "UPDATE test_clock SET enabled = true,"
    " clock_offset = (CAST(:day AS date) + CAST(:at AS time)) AT TIME ZONE 'Africa/Nairobi' - clock_timestamp()"
)
_POST: Final = text(
    "INSERT INTO events (id, org_id, created_by, title, description, starts_at, ends_at, online, venue, county_code,"
    " join_url) VALUES (:id, :org, :by, :title, :description, :starts, :ends, :online, :venue, :county, :join_url)"
)


@dataclass
class WeekDb:
    """The module's database: the owner and bridge_app engines, and the weeks its tests took."""

    owner: AsyncEngine
    app: AsyncEngine
    weeks: list[date] = field(default_factory=list)

    def monday(self) -> date:
        """A Monday of the module's own, two weeks after the last one handed out (the first is three weeks ahead of the
        real date in Nairobi), so no two tests share "this week and next"."""
        today = datetime.now(NAIROBI).date()
        first = today + timedelta(days=21 - today.weekday())
        monday = first + timedelta(days=14 * len(self.weeks))
        self.weeks.append(monday)
        return monday

    def shared_monday(self) -> date:
        """The module's first Monday, for tests that store nothing a developer would list (the form's refusals)."""
        return self.weeks[0] if self.weeks else self.monday()


def nairobi(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=NAIROBI)


async def at(db: WeekDb, day: date, clock: time = time(12, 0)) -> None:
    """Move the shared clock to ``clock`` in Nairobi on ``day`` (committed: the API and the jobs read it)."""
    async with db.owner.begin() as conn:
        await conn.execute(_CLOCK_TO, {"day": day, "at": clock})


async def owner_rows(db: WeekDb, sql: str, **params: object) -> list[Any]:
    async with db.owner.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def owner_run(db: WeekDb, sql: str, **params: object) -> None:
    async with db.owner.begin() as conn:
        await conn.execute(text(sql), params)


@dataclass(frozen=True, slots=True)
class People:
    developer: UUID  # Nairobi City
    other: UUID  # Mombasa
    nowhere: UUID  # no county
    org: Org  # E2: owner (owner+admin), signatory, reviewer, finance, viewer (no developer profile)
    e1: Org  # E1
    rival: Org  # E2, another organisation
    admin: UUID  # staff admin with TOTP
    moderator: UUID  # staff moderator with TOTP


async def developer(conn: AsyncConnection, label: str, county: str | None) -> UUID:
    """As the owner: an active developer with a verified address, a county (or none) and the reminders consent."""
    user = await add_person(conn, label, "developers.example.test", totp_on=False)
    await run(
        conn,
        "INSERT INTO developer_profiles (user_id, handle, county_code) VALUES (:u, :h, :c)",
        u=user,
        h=f"{label}-{user.hex[-12:]}",
        c=county,
    )
    await consent(conn, user, granted=True)
    return user


async def consent(conn: AsyncConnection, user: UUID, *, granted: bool) -> None:
    """A ``reminders`` consent decision of ``user`` (as the owner)."""
    await run(
        conn,
        "INSERT INTO consents (id, user_id, purpose, granted, text_version, text_sha256, source)"
        " VALUES (:id, :user, 'reminders', :granted, 'v1', :sha, 'test')",
        id=uuid7(),
        user=user,
        granted=granted,
        sha=bytes(32),
    )


async def staff(conn: AsyncConnection, role: str) -> UUID:
    user = await add_person(conn, role, "staff.example.test", totp_on=True)
    await run(conn, "UPDATE users SET staff_role = CAST(:r AS staff_role) WHERE id = :u", r=role, u=user)
    return user


async def cast(db: WeekDb) -> People:
    """The people of one test (committed)."""
    async with db.owner.begin() as conn:
        return People(
            developer=await developer(conn, "dev", NAIROBI_CITY),
            other=await developer(conn, "other", MOMBASA),
            nowhere=await developer(conn, "nowhere", None),
            org=await add_org(conn, "events"),
            e1=await add_org(conn, "pending", verification="e1"),
            rival=await add_org(conn, "rival"),
            admin=await staff(conn, "admin"),
            moderator=await staff(conn, "moderator"),
        )


async def post(
    db: WeekDb,
    poster: UUID,
    org: UUID | None,
    starts: datetime,
    *,
    hours: float = 2,
    county: str | None = None,
    title: str = "Nairobi Python meetup",
) -> UUID:
    """A draft as its poster writes it (bridge_app, bound to the poster and the organisation): online, or at a venue
    in ``county``."""
    event_id = uuid7()
    params = {
        "id": event_id,
        "org": org,
        "by": poster,
        "title": title,
        "description": "Talks and a workshop.\nBring a laptop.",
        "starts": starts,
        "ends": starts + timedelta(hours=hours),
        "online": county is None,
        "venue": None if county is None else "iHub, Senteu Plaza",
        "county": county,
        "join_url": "https://meet.example.test/python" if county is None else None,
    }
    async with create_session_factory(db.app)() as session:
        await bind_tenant(session, user_id=poster, org_id=org)
        await session.execute(_POST, params)
        await session.commit()
    return event_id


async def decide(db: WeekDb, event_id: UUID, moderator: UUID, decision: str = "publish") -> None:
    """As staff, through ``app_decide_event`` on the version as it is now (the queue's path)."""
    [row] = await owner_rows(db, "SELECT updated_at FROM events WHERE id = :e", e=event_id)
    async with create_session_factory(db.app)() as session:
        await bind_tenant(session, user_id=moderator)
        await session.execute(
            text("SELECT app_decide_event(:e, :d, :s)"), {"e": event_id, "d": decision, "s": row.updated_at}
        )
        await session.commit()


async def published(db: WeekDb, people: People, starts: datetime, *, platform: bool = False, **kwargs: Any) -> UUID:
    """An event of ``people.org`` posted by its reviewer (or a platform event by the staff admin), published."""
    poster, org = (people.admin, None) if platform else (people.org.reviewer, people.org.id)
    event_id = await post(db, poster, org, starts, **kwargs)
    await decide(db, event_id, people.moderator)
    return event_id


async def cancel(db: WeekDb, event_id: UUID, by: UUID) -> None:
    async with create_session_factory(db.app)() as session:
        await bind_tenant(session, user_id=by)
        await session.execute(text("SELECT app_cancel_event(:e)"), {"e": event_id})
        await session.commit()


class Clients:
    """Signed-in in-process API clients of the module's database (the second factor fresh unless asked)."""

    def __init__(self, db: WeekDb, stack: AsyncExitStack) -> None:
        self._db, self._stack = db, stack

    async def __call__(self, user_id: UUID, *, fresh: bool = True) -> httpx.AsyncClient:
        client = await self._stack.enter_async_context(make_client(self._db.app))
        await sign_in_as(client, self._db.app, user_id, mfa_verified=fresh)
        return client


@asynccontextmanager
async def clients(db: WeekDb) -> AsyncIterator[Clients]:
    async with AsyncExitStack() as stack:
        yield Clients(db, stack)


def body(starts: datetime, *, hours: float = 2, county: str | None = None, **overrides: Any) -> dict[str, Any]:
    """The JSON of an event form: online, or at a venue in ``county``."""
    found: dict[str, Any] = {
        "title": "Nairobi Python meetup",
        "description": "Talks and a workshop.\nBring a laptop.",
        "starts_at": starts.isoformat(),
        "ends_at": (starts + timedelta(hours=hours)).isoformat(),
        "online": county is None,
        "venue": None if county is None else "iHub, Senteu Plaza",
        "county_code": county,
        "join_url": "https://meet.example.test/python" if county is None else None,
        "link": None,
    }
    return found | overrides


def code(response: httpx.Response) -> tuple[int, str | None]:
    """(status, error code) of a response."""
    detail = response.json().get("detail") if response.headers.get("content-type") == "application/json" else None
    return response.status_code, detail.get("code") if isinstance(detail, dict) else None


def org_path(org: UUID, suffix: str = "") -> str:
    return f"/api/orgs/{org}/events{suffix}"


ADMIN: Final = "/api/admin/events"
WEEK: Final = "/api/me/week"
WEEK_EVENTS: Final = "/api/me/week/events"


def utc(moment: datetime) -> datetime:
    return moment.astimezone(UTC)


async def audit_actions(db: WeekDb, subject: UUID) -> list[Any]:
    return await owner_rows(
        db,
        "SELECT action, actor_kind::text AS actor_kind, actor_user_id, org_id, payload FROM audit_events"
        " WHERE subject_id = :s ORDER BY occurred_at, seq",
        s=subject,
    )
