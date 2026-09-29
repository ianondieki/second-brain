"""Fixtures for the LLM layer against PostgreSQL: two organisations with their owners, a viewer and staff admin.

Written as the owner role (RLS does not apply to the table owner); every test then acts as ``bridge_app`` through
``factory``, bound with ``bind_tenant`` exactly as a request is. Fresh people per test, so spend never leaks between
tests (the global daily total is the whole database's and is only ever compared as a difference).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import bridge.models.all  # noqa: F401  # registers every table (foreign keys resolve at flush)
from bridge.db import create_session_factory
from bridge.ids import uuid7
from tests.integration import world as w


@dataclass(frozen=True, slots=True)
class People:
    tag: str
    a: UUID  # owner and admin of org_a
    org_a: UUID
    b: UUID  # owner and admin of org_b
    org_b: UUID
    viewer: UUID  # a viewer of org_a
    admin: UUID  # staff admin with TOTP enrolled


@pytest.fixture(scope="module")
def factory(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(app_engine)


@pytest.fixture
async def people(owner_engine: AsyncEngine) -> People:
    tag = uuid7().hex[-12:]
    async with owner_engine.begin() as conn:
        a = await w.add_user(conn, f"llm-a-{tag}@example.test", "A")
        b = await w.add_user(conn, f"llm-b-{tag}@example.test", "B")
        viewer = await w.add_user(conn, f"llm-viewer-{tag}@example.test", "Viewer")
        admin = await w.add_user(conn, f"llm-admin-{tag}@example.test", "Admin", staff_role="admin")
        orgs = {}
        for label, owner in (("a", a), ("b", b)):
            orgs[label] = uuid7()
            await conn.execute(
                text(
                    "INSERT INTO organizations (id, kind, legal_name, slug, source)"
                    " VALUES (:id, 'company', :name, :slug, 'self_signup')"
                ),
                {"id": orgs[label], "name": f"LLM org {label}", "slug": f"llm-{label}-{tag}"},
            )
            await conn.execute(
                text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, '{owner,admin}')"),
                {"id": uuid7(), "org": orgs[label], "user": owner},
            )
        await conn.execute(
            text("INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, '{viewer}')"),
            {"id": uuid7(), "org": orgs["a"], "user": viewer},
        )
    return People(tag, a, orgs["a"], b, orgs["b"], viewer, admin)
