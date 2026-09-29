"""Shared parts of the demo seed (``bridge.seed.demo``): where it may run, the in-process API it drives, its report and
its owner-role queries."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge import clock
from bridge.auth import sessions, totp
from bridge.auth.service import user_by_email
from bridge.config import Settings
from bridge.crypto.envelope import KeyWrapper, key_wrapper_from_settings
from bridge.db import bind_tenant, create_session_factory
from bridge.integrations.sms import SmsProvider, sms_provider_from_settings
from bridge.main import create_app
from bridge.notifications.email import EmailProvider, provider_from_settings
from bridge.seed.demo.data import totp_secret
from bridge.storage.objects import ObjectStore, object_store_from_settings
from bridge.storage.scanner import Scanner, scanner_from_settings

DEMO_ENVS: Final = frozenset({"dev", "test"})
SEED_METHOD: Final = "demo_seed"  # the signup method recorded in the auth.signup audit event
SEED_USER_AGENT: Final = "bridge-demo-seed"
BASE_URL: Final = "https://demo-seed.localhost"  # in process only (ASGI transport): nothing listens here


class DemoSeedRefused(RuntimeError):
    """The environment does not allow demo accounts (staging, production, or APP_ENV not set)."""


class DemoSeedError(RuntimeError):
    """A step of the demo seed was refused or answered unexpectedly; nothing after it ran."""


def demo_refusal(settings: Settings) -> str | None:
    """Why demo accounts and their fixed credentials are refused under ``settings``, or None when they are allowed.

    ``APP_ENV`` must be set explicitly (environment or ``backend/.env``) to dev or test: the settings default is dev,
    so a deployment that forgot to set it would otherwise get accounts with published passwords."""
    if "app_env" not in settings.model_fields_set:
        return (
            "APP_ENV is not set; the demo seed runs only when APP_ENV is set explicitly to dev or test (environment or"
            " backend/.env), never on the settings default"
        )
    if settings.app_env not in DEMO_ENVS:
        return (
            f"APP_ENV={settings.app_env}; the demo seed and its fixed demo credentials exist only in dev and test,"
            " never in staging or production"
        )
    return None


def ensure_demo_allowed(settings: Settings) -> None:
    reason = demo_refusal(settings)
    if reason is not None:
        raise DemoSeedRefused(reason)


def totp_code(email: str, *, at: float | None = None) -> str:
    """The current TOTP code of a demo account (its fixed secret), or the code at the Unix time ``at``."""
    moment = time.time() if at is None else at
    return totp.code_at(totp_secret(email), int(moment // totp.PERIOD))


# ---------------------------------------------------------------------------------------------------------- runtime


@dataclass(slots=True)
class DemoRuntime:
    """What the in-process API uses: built from settings for ``make demo``; tests pass in-memory stand-ins."""

    email_provider: EmailProvider
    sms_provider: SmsProvider
    key_wrapper: KeyWrapper
    object_store: ObjectStore
    scanner: Scanner

    @classmethod
    def from_settings(cls, settings: Settings) -> DemoRuntime:
        return cls(
            email_provider=provider_from_settings(settings),
            sms_provider=sms_provider_from_settings(settings),
            key_wrapper=key_wrapper_from_settings(settings),
            object_store=object_store_from_settings(settings),
            scanner=scanner_from_settings(settings),
        )


@dataclass(slots=True)
class DemoReport:
    users: dict[str, UUID] = field(default_factory=dict)
    orgs: dict[str, UUID] = field(default_factory=dict)
    proposals: dict[str, UUID] = field(default_factory=dict)
    cert_ids: dict[str, str] = field(default_factory=dict)
    created: list[str] = field(default_factory=list)  # what this run added, in order
    notes: list[str] = field(default_factory=list)  # steps skipped on purpose (a flag off)

    def did(self, what: str) -> None:
        self.created.append(what)


@asynccontextmanager
async def in_process_app(
    settings: Settings, engine: AsyncEngine, runtime: DemoRuntime
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker[AsyncSession]]]:
    app = create_app(settings)
    factory = create_session_factory(engine)
    app.state.engine = engine
    app.state.session_factory = factory
    app.state.email_provider = runtime.email_provider
    app.state.sms_provider = runtime.sms_provider
    app.state.key_wrapper = runtime.key_wrapper
    app.state.object_store = runtime.object_store
    app.state.scanner = runtime.scanner
    yield app, factory


class Actor:
    """One demo user signed in to the in-process API: a server-side session (second factor fresh) and its cookie."""

    def __init__(self, client: httpx.AsyncClient, user_id: UUID, email: str) -> None:
        self.client = client
        self.user_id = user_id
        self.email = email

    async def call(self, method: str, path: str, *, expect: Iterable[int] = (200,), **kwargs: Any) -> httpx.Response:
        response = await self.client.request(method, path, **kwargs)
        if response.status_code not in set(expect):
            raise DemoSeedError(f"{method} {path} as {self.email}: {response.status_code} {response.text[:300]}")
        return response


async def _refresh_csrf(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/auth/csrf")
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


@asynccontextmanager
async def signed_in(
    app: FastAPI, factory: async_sessionmaker[AsyncSession], settings: Settings, email: str
) -> AsyncIterator[Actor]:
    """Sign ``email`` in (a session created as login does, the second factor just confirmed); log out at the end."""
    async with factory() as db:
        user = await user_by_email(db, email)
        if user is None:
            raise DemoSeedError(f"no account for {email}")
        await bind_tenant(db, user_id=user.id)
        live = await sessions.create(db, user, ttl=timedelta(hours=1), mfa_pending=False, user_agent=SEED_USER_AGENT)
        live.row.mfa_verified_at = clock.utcnow()
        await db.commit()
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        client.cookies.set(settings.session_cookie_name, live.token)
        await _refresh_csrf(client)
        try:
            yield Actor(client, user.id, email)
        finally:
            await client.post("/api/auth/logout")


# ---------------------------------------------------------------------------------------------------------- queries


async def one(engine: AsyncEngine, sql: str, **params: object) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).one_or_none()


async def execute(engine: AsyncEngine, sql: str, **params: object) -> int:
    async with engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return int(getattr(result, "rowcount", 0) or 0)


async def niche_ids(owner: AsyncEngine) -> dict[str, UUID]:
    async with owner.connect() as conn:
        rows = (await conn.execute(text("SELECT slug::text, id FROM niches"))).all()
    return {str(slug): UUID(str(niche_id)) for slug, niche_id in rows}


async def user_id_of(owner: AsyncEngine, email: str) -> UUID | None:
    row = await one(owner, "SELECT id FROM users WHERE email = :email", email=email)
    return None if row is None else UUID(str(row.id))
