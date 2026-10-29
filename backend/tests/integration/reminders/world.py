"""The reminders' world against PostgreSQL: the tracker's parties (``tests/integration/engagements/tracker.py``) with
an engagement walked to a stage, consents and a dispatcher whose sessions join one owner transaction that the test
rolls back (``tracker.as_app``), so nothing is left behind and the shared test clock can be moved safely.

Fixtures are written as the owner; every dispatcher run switches the connection back to ``bridge_app`` first, so the
reminders read and write under RLS and the app's grants exactly as the worker does.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from bridge.config import Settings, get_settings
from bridge.ids import uuid7
from bridge.llm.deps import build_runtime
from bridge.llm.routing import LLMRuntime
from bridge.notifications.email import FakeEmailProvider
from bridge.reminders.dispatch import Deps, Report, run_developer_nudges, run_org_digests
from tests.integration.engagements import tracker

BASE_URL = "https://bridge.example.test"
# walk() plans milestone 1 for 31 March 2027: 09:00 EAT on the 30th is the day before (a Tuesday).
DAY_BEFORE_DUE = datetime(2027, 3, 30, 6, 0, tzinfo=UTC)


def settings(**overrides: Any) -> Settings:
    return get_settings().model_copy(update={"public_base_url": BASE_URL, **overrides})


@dataclass
class World:
    conn: AsyncConnection
    p: tracker.Parties
    engagement: UUID
    email: FakeEmailProvider = field(default_factory=FakeEmailProvider)
    cfg: Settings = field(default_factory=settings)
    llm: LLMRuntime | None = None

    @property
    def factory(self) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(bind=self.conn, expire_on_commit=False)

    def deps(self) -> Deps:
        llm = self.llm if self.llm is not None else build_runtime(self.cfg)
        return Deps(self.factory, self.cfg, self.email, llm)

    async def nudges(self, users: Sequence[UUID] | None = None, **kwargs: Any) -> Report:
        await self.conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        return await run_developer_nudges(self.deps(), user_ids=users or [self.p.developer], **kwargs)

    async def digests(self, users: Sequence[UUID], **kwargs: Any) -> Report:
        await self.conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        return await run_org_digests(self.deps(), user_ids=users, **kwargs)

    async def owner_rows(self, sql: str, **params: object) -> list[sa.Row[Any]]:
        """Rows read as the owner (no RLS), then back to the app role."""
        await tracker.as_owner(self.conn)
        rows = list((await self.conn.execute(sa.text(sql), params)).all())
        await self.conn.execute(sa.text("SET LOCAL ROLE bridge_app"))
        return rows

    async def deliveries(self, user: UUID) -> list[tuple[str, str, str]]:
        rows = await self.owner_rows(
            "SELECT kind, channel::text, status::text FROM notification_deliveries WHERE user_id = :u"
            " ORDER BY channel, kind",
            u=user,
        )
        return [(row[0], row[1], row[2]) for row in rows]

    async def in_app(self, user: UUID) -> list[tuple[str, str]]:
        rows = await self.owner_rows(
            "SELECT kind, title FROM in_app_notifications WHERE user_id = :u ORDER BY created_at", u=user
        )
        return [(row[0], row[1]) for row in rows]

    async def in_app_links(self, user: UUID) -> list[str]:
        rows = await self.owner_rows(
            "SELECT link FROM in_app_notifications WHERE user_id = :u ORDER BY created_at", u=user
        )
        return [str(row[0]) for row in rows]


async def consent(conn: AsyncConnection, user: UUID, *, granted: bool = True) -> None:
    """A ``reminders`` consent decision of ``user`` (as the owner)."""
    await tracker.as_owner(conn)
    await tracker.run(
        conn,
        "INSERT INTO consents (id, user_id, purpose, granted, text_version, text_sha256, source)"
        " VALUES (:id, :user, 'reminders', :granted, 'v1', :sha, 'test')",
        id=uuid7(),
        user=user,
        granted=granted,
        sha=bytes(32),
    )


async def build(conn: AsyncConnection, *, until: str = "IN_IMPLEMENTATION", consents: bool = True) -> World:
    """The tracker's parties with one engagement walked to ``until``; the developer and the signatory opted in to
    reminders."""
    p = await tracker.parties(conn)
    await tracker.act(conn, p.developer)
    engagement = await tracker.engage(conn, p)
    await tracker.walk(conn, p, engagement, until)
    if consents:
        for user in (p.developer, p.signatory):
            await consent(conn, user)
    return World(conn, p, engagement)
