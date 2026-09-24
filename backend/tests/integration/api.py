"""Helpers to drive the FastAPI app against the test database (in-process, no network)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.auth import sessions
from bridge.auth.models import User
from bridge.clock import utcnow
from bridge.config import get_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.main import create_app
from bridge.notifications.email import FakeEmailProvider


@asynccontextmanager
async def make_client(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """An https client (Secure cookies are sent) for an app wired to ``app_engine`` and a fake email outbox."""
    settings = get_settings()
    app = create_app(settings)
    app.state.engine = app_engine
    app.state.session_factory = create_session_factory(app_engine)
    app.state.email_provider = FakeEmailProvider()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        client.app = app  # type: ignore[attr-defined]
        csrf = await client.get("/api/auth/csrf")
        client.headers["X-CSRF-Token"] = csrf.json()["csrf_token"]
        yield client


def outbox(client: httpx.AsyncClient) -> FakeEmailProvider:
    provider: FakeEmailProvider = client.app.state.email_provider  # type: ignore[attr-defined]
    return provider


async def refresh_csrf(client: httpx.AsyncClient) -> None:
    client.headers["X-CSRF-Token"] = (await client.get("/api/auth/csrf")).json()["csrf_token"]


async def sign_in_as(client: httpx.AsyncClient, app_engine: AsyncEngine, user_id: UUID, *, mfa_verified: bool) -> None:
    """Create a session row directly and put its cookie on the client (for tests that are not about login)."""
    settings = get_settings()
    factory = create_session_factory(app_engine)
    async with factory() as db:
        user = await db.get(User, user_id)
        assert user is not None
        await bind_tenant(db, user_id=user_id)
        live = await sessions.create(db, user, ttl=timedelta(days=1), mfa_pending=False, user_agent="pytest")
        if mfa_verified:
            live.row.mfa_verified_at = utcnow()
        await db.commit()
    client.cookies.set(settings.session_cookie_name, live.token, domain="testserver")
    await refresh_csrf(client)
