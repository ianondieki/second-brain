"""Shared parts of the demo seed (``bridge.seed.demo``): where it may run, the in-process API it drives, its report and
its owner-role queries."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Iterable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bridge.auth import totp
from bridge.config import DEMO_ENVS, Settings
from bridge.crypto.envelope import KeyWrapper, key_wrapper_from_settings
from bridge.db import create_session_factory
from bridge.integrations.sms import SmsProvider, sms_provider_from_settings
from bridge.llm.embeddings import Embedder
from bridge.main import create_app
from bridge.notifications.email import EmailProvider, provider_from_settings
from bridge.seed.demo.data import DEMO_PASSWORD, totp_secret
from bridge.storage.objects import ObjectStore, object_store_from_settings
from bridge.storage.scanner import Scanner, scanner_from_settings

SEED_METHOD: Final = "demo_seed"  # the signup method recorded in the auth.signup audit event
SEED_USER_AGENT: Final = "bridge-demo-seed"
BASE_URL: Final = "https://demo-seed.localhost"  # in process only (ASGI transport): nothing listens here


class DemoSeedRefused(RuntimeError):
    """The environment does not allow demo accounts (staging, production, or APP_ENV not set)."""


class DemoSeedError(RuntimeError):
    """A step of the demo seed was refused or answered unexpectedly; nothing after it ran."""


class DemoKeysChanged(DemoSeedError):
    """The demo database was seeded under other keys (its TOTP secrets do not open): always fatal; make demo-reset."""


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
    embedder: Embedder | None = None  # the embedding step's; None: built from settings (EMBEDDER) like the job's

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
    # P23-1: vectors the embedding job wrote in the last step, per table (derived data, not demo content: never in
    # ``created``, so a demo people used tops up its vectors without reporting a change)
    embedded: dict[str, int] = field(default_factory=dict)

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
    """One demo user signed in to the in-process API through the login routes (password, then TOTP when enrolled)."""

    def __init__(self, client: httpx.AsyncClient, user_id: UUID, email: str) -> None:
        self.client = client
        self.user_id = user_id
        self.email = email

    async def call(self, method: str, path: str, *, expect: Iterable[int] = (200,), **kwargs: Any) -> httpx.Response:
        response = await self.client.request(method, path, **kwargs)
        if response.status_code not in set(expect):
            raise DemoSeedError(f"{method} {path} as {self.email}: {response.status_code} {response.text[:300]}")
        return response

    async def refresh_csrf(self) -> None:
        """The CSRF token is bound to the session: fetch it again whenever the session cookie changes."""
        response = await self.client.get("/api/auth/csrf")
        self.client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


async def next_totp_code(owner: AsyncEngine, email: str) -> str:
    """A code of the account's demo secret that the server will accept now: codes are single use (the counter must
    pass ``totp_last_counter``) and one step of drift is allowed, so wait for the next window when both are spent."""
    row = await _one(owner, "SELECT totp_last_counter FROM users WHERE email = :email", email=email)
    last = -1 if row is None or row.totp_last_counter is None else int(row.totp_last_counter)
    while True:
        now = int(time.time() // totp.PERIOD)
        counter = max(now, last + 1)
        if counter <= now + totp.DRIFT_STEPS:
            return totp.code_at(totp_secret(email), counter)
        await asyncio.sleep((now + 1) * totp.PERIOD - time.time() + 0.5)


@asynccontextmanager
async def signed_in(app: FastAPI, owner: AsyncEngine, email: str) -> AsyncIterator[Actor]:
    """Sign ``email`` in as a browser does: ``POST /api/auth/login`` with the demo password, then, for an account with
    TOTP, ``POST /api/auth/mfa/verify`` with its current code (so the session's second factor is fresh: the ADR-002
    step-up for signing and endorsing). Logs out at the end."""
    user_id = await _user_id_of(owner, email)
    if user_id is None:
        raise DemoSeedError(f"no account for {email}")
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 0))
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL, headers={"User-Agent": SEED_USER_AGENT}) as c:
        actor = Actor(c, user_id, email)
        await actor.refresh_csrf()
        login = await actor.call("POST", "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD})
        await actor.refresh_csrf()
        if login.json()["mfa_required"]:
            code = await next_totp_code(owner, email)
            await actor.call("POST", "/api/auth/mfa/verify", json={"code": code})
            await actor.refresh_csrf()
        try:
            yield actor
        finally:
            await c.post("/api/auth/logout")


class Actors:
    """The demo users signed in so far, each signed in on first use only (a run with nothing to do signs nobody in).
    A sign-in that failed (a password or second factor changed in the app) is not tried again in the same run."""

    def __init__(self, stack: AsyncExitStack, app: FastAPI, owner: AsyncEngine) -> None:
        self._stack, self._app, self._owner = stack, app, owner
        self._signed_in: dict[str, Actor] = {}
        self._failed: dict[str, DemoSeedError] = {}

    async def get(self, email: str) -> Actor:
        if email in self._failed:
            raise self._failed[email]
        if email not in self._signed_in:
            try:
                self._signed_in[email] = await self._stack.enter_async_context(signed_in(self._app, self._owner, email))
            except DemoSeedError as exc:
                self._failed[email] = DemoSeedError(f"{email} could not sign in (password or TOTP changed?): {exc}")
                raise self._failed[email] from exc
        return self._signed_in[email]


async def guarded(report: DemoReport, *, strict: bool, what: str, step: Awaitable[None]) -> None:
    """Run one step of the seed. On a database the demo was seeded into before (``strict`` false), a step the app
    refuses because someone used the demo (a password changed, an engagement moved on, a proposal deleted) is left as
    it is with one line in the report, so ``make demo`` still comes up; on a new database every refusal is an error."""
    try:
        await step
    except DemoSeedError as exc:
        if strict or isinstance(exc, DemoKeysChanged):
            raise
        report.notes.append(f"{what}: left as it is ({exc})")


# ---------------------------------------------------------------------------------------------------------- queries
# Seed only: raw SQL on the engine it is given, which in the seed is the owner role (bridge_owner, no RLS). Never for
# application code, which reads and writes as bridge_app under Row-Level Security.


async def _one(engine: AsyncEngine, sql: str, **params: object) -> Any:
    """Seed only: the one row (or None) of an owner-role query."""
    async with engine.connect() as conn:
        return (await conn.execute(text(sql), params)).one_or_none()


async def _execute(engine: AsyncEngine, sql: str, **params: object) -> int:
    """Seed only: run an owner-role statement in its own transaction; the number of rows it changed."""
    async with engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return int(getattr(result, "rowcount", 0) or 0)


async def _niche_ids(owner: AsyncEngine) -> dict[str, UUID]:
    """Seed only: niche slug -> id."""
    async with owner.connect() as conn:
        rows = (await conn.execute(text("SELECT slug::text, id FROM niches"))).all()
    return {str(slug): UUID(str(niche_id)) for slug, niche_id in rows}


async def _user_id_of(owner: AsyncEngine, email: str) -> UUID | None:
    """Seed only: the id of the account with this address, or None."""
    row = await _one(owner, "SELECT id FROM users WHERE email = :email", email=email)
    return None if row is None else UUID(str(row.id))
