"""REQ-FND-04 (P28 track PD): the public demo against a database seeded as the demo image seeds it, with
``PUBLIC_DEMO=true`` (reference data, the provisional directory step, then ``python -m bridge.seed --demo``).

- AT-PD-1: ``POST /api/auth/demo/sign-in {"persona": "amina"}`` is 200 with the session cookie; ``/api/auth/me`` is
  Amina's with the second factor satisfied, and the sign-in is audited ``auth.login`` (``method: demo_persona``).
  Peter (Telco A's signatory) expresses interest in Amina's proposal and Amina accepts it, both step-up actions, and
  the moderator opens the staff queue (staff routes need a fresh second factor), none with a code.
- AT-PD-2: with the mode off the route is 404 and ``/api/public/demo`` says ``enabled: false``.
- AT-PD-5: ``fictional`` leaves out every ``ke_provisional`` organisation and every research card citing a news
  excerpt.

The database is the module's own: the demo seed's rows would disturb other tests' counts in the shared one.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import Settings, get_settings
from bridge.crypto.envelope import LocalKeyWrapper
from bridge.integrations.sms import FakeSmsProvider
from bridge.notifications.email import FakeEmailProvider
from bridge.seed.demo import DemoReport, DemoRuntime, seed_demo
from bridge.seed.demo.data import AMINA, ORGS, P1, TELCO_A
from bridge.seed.demo.research import SEEDED_ANSWERS
from bridge.seed.directory import directory_loadable, load_directory, seed_directory
from bridge.seed.reference import seed_all
from bridge.storage.objects import InMemoryObjectStore
from bridge.storage.scanner import FakeScanner
from tests.integration.api import make_client, refresh_csrf
from tests.integration.conftest import create_database, drop_database, role_engine, run_alembic
from tests.integration.engagements.api_world import Tracker, db_today

SIGN_IN = "/api/auth/demo/sign-in"
LOCKED = {"code": "public_demo_locked", "message": "This is switched off in the public demo."}
Seeded = tuple[dict[str, int] | None, DemoReport]  # the directory step's counts (None: skipped) and the demo report
PROVISIONAL = sorted(str(row["slug"]) for row in load_directory()["orgs"])


def public(**update: Any) -> Settings:
    """The demo image's settings: the public demo (fictional unless updated), with the local demo's feature flags."""
    flags = {"feature_tier2_enabled": True, "feature_deals_enabled": True}
    return get_settings().model_copy(update={"public_demo": True, **flags, **update})


@pytest.fixture(scope="module")
def demo_url(admin_url: URL) -> Iterator[URL]:
    name = f"bridge_public_{uuid4().hex[:12]}"
    url = create_database(admin_url, name)
    try:
        run_alembic(url, lambda config: command.upgrade(config, "head"))
        yield url
    finally:
        drop_database(admin_url, name)


@pytest.fixture(scope="module")
async def owner(demo_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(demo_url, "bridge_owner")
    yield engine
    await engine.dispose()


@pytest.fixture(scope="module")
async def app(demo_url: URL) -> AsyncIterator[AsyncEngine]:
    engine = role_engine(demo_url, "bridge_app")
    yield engine
    await engine.dispose()


def runtime() -> DemoRuntime:
    return DemoRuntime(
        email_provider=FakeEmailProvider(),
        sms_provider=FakeSmsProvider(),
        key_wrapper=LocalKeyWrapper(os.urandom(32)),
        object_store=InMemoryObjectStore(),
        scanner=FakeScanner(),
    )


async def seed(owner: AsyncEngine, app: AsyncEngine, settings: Settings) -> Seeded:
    """What the image runs: ``python -m bridge.seed`` (its ``run``: reference data, then the directory when loadable)
    and ``--demo``."""
    async with owner.begin() as conn:
        await seed_all(conn, settings)
        directory = await seed_directory(conn, settings) if directory_loadable(settings) else None
    return directory, await seed_demo(settings, owner_engine=owner, app_engine=app, runtime=runtime())


@pytest.fixture(scope="module")
async def fictional(owner: AsyncEngine, app: AsyncEngine) -> Seeded:
    return await seed(owner, app, public())


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def scalar(engine: AsyncEngine, sql: str, **params: object) -> Any:
    return (await rows(engine, sql, **params))[0][0]


@asynccontextmanager
async def visitor(app: AsyncEngine, settings: Settings | None = None, ip: str = "127.0.2.1") -> AsyncIterator[Any]:
    async with make_client(app, settings or public(), ip=ip) as client:
        yield client


async def sign_in(client: httpx.AsyncClient, persona: str) -> httpx.Response:
    response = await client.post(SIGN_IN, json={"persona": persona})
    await refresh_csrf(client)  # the CSRF token is bound to the new session
    return response


# ------------------------------------------------------------------------------------------------- AT-PD-5 (fictional)


async def test_the_fictional_public_seed_has_no_real_organisation_and_no_news_excerpt(
    fictional: Seeded, owner: AsyncEngine
) -> None:
    directory, report = fictional
    assert directory is None  # the provisional directory step was skipped
    assert await scalar(owner, "SELECT count(*) FROM organizations WHERE slug = ANY(:s)", s=PROVISIONAL) == 0
    names = {row.legal_name for row in await rows(owner, "SELECT legal_name FROM organizations")}
    assert names == {org.legal_name for org in ORGS}  # the four fixtures, nothing else
    assert await scalar(owner, "SELECT count(*) FROM research_runs") == 0
    unofficial = "SELECT count(*) FROM problem_sources WHERE source_type IS DISTINCT FROM 'official'"
    assert await scalar(owner, unofficial) == 0
    assert (
        f"research cards: {len(SEEDED_ANSWERS)} left out of the public demo (they cite news excerpts;"
        " PUBLIC_DEMO_CONTENT=full restores them)"
    ) in report.notes
    personas = await rows(
        owner,
        "SELECT email, demo_account, status::text AS status, totp_enabled_at IS NOT NULL AS totp FROM users"
        " WHERE email = ANY(:e)",
        e=[
            "amina@developers.example",
            "brian@developers.example",
            "owner@telco-a.example",
            "signatory@telco-a.example",
            "reviewer@telco-a.example",
            "owner@county-c.example",
            "moderator@staff.example",
        ],
    )
    assert len(personas) == 7
    assert all((p.demo_account, p.status, p.totp) == (True, "active", True) for p in personas)


# ------------------------------------------------------------------------------------------------------------ AT-PD-1


async def test_a_persona_signs_in_with_one_press_and_its_second_factor_counts(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine
) -> None:
    _, report = fictional
    amina = report.users[AMINA.email]
    async with visitor(app) as client:
        response = await sign_in(client, "amina")
        assert response.status_code == 200, response.text
        assert response.json()["mfa_required"] is False
        assert response.json()["user"]["email"] == AMINA.email
        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"{get_settings().session_cookie_name}=")
        assert "HttpOnly" in cookie
        assert "Secure" in cookie
        me = (await client.get("/api/auth/me")).json()
    assert me["user"]["id"] == str(amina)
    assert me["side"] == "developer"
    assert me["mfa"]["verified"] is True
    assert me["mfa"]["enrolled"] is True
    [session] = await rows(
        owner,
        "SELECT mfa_pending, mfa_verified_at > now() - interval '1 minute' AS fresh FROM sessions WHERE user_id = :u"
        " ORDER BY created_at DESC LIMIT 1",
        u=amina,
    )
    assert (session.mfa_pending, session.fresh) == (False, True)
    audits = await rows(
        owner,
        "SELECT payload FROM audit_events WHERE action = 'auth.login' AND actor_user_id = :u"
        " AND payload->>'method' = 'demo_persona'",
        u=amina,
    )
    assert [a.payload for a in audits] == [{"method": "demo_persona", "persona": "amina"}]


async def test_step_up_actions_work_for_personas_without_a_code(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine
) -> None:
    """Peter expresses interest in Amina's P1 (signatory, step-up) and Amina accepts it (step-up, an endorsement); the
    moderator reads the moderation queue (staff routes need a fresh second factor)."""
    _, report = fictional
    today = await db_today(owner)
    interest = {
        "proposal_id": str(report.proposals[P1.key]),
        "origin": "org_browse",
        "match_id": None,
        "contact_user_id": str(report.users["owner@telco-a.example"]),  # Grace, Telco A's owner
        "channel": "video_call",
        "contact_by": str(today + timedelta(days=1)),
    }
    async with visitor(app, ip="127.0.2.2") as peter, visitor(app, ip="127.0.2.3") as amina:
        assert (await sign_in(peter, "peter")).status_code == 200
        created = await peter.post(f"/api/orgs/{report.orgs[TELCO_A.legal_name]}/interest", json=interest)
        assert created.status_code == 201, created.text
        assert (await sign_in(amina, "amina")).status_code == 200
        accepted = await Tracker(UUID(created.json()["id"])).ok(amina, "accept-interest")
        assert accepted["state"] == "INTEREST_CONFIRMED"
    async with visitor(app, ip="127.0.2.4") as moderator:
        assert (await sign_in(moderator, "moderator")).status_code == 200
        queue = await moderator.get("/api/admin/moderation/cases")
        assert queue.status_code == 200, queue.text


async def test_the_status_route_lists_the_personas(app: AsyncEngine) -> None:
    async with visitor(app) as client:
        body = (await client.get("/api/public/demo")).json()
    assert body["enabled"] is True
    assert [p["key"] for p in body["personas"]] == ["amina", "brian", "grace", "peter", "rita", "hassan", "moderator"]


# ------------------------------------------------------------------------------------------------------------ AT-PD-2


async def test_with_the_mode_off_there_is_no_persona_sign_in(fictional: Seeded, app: AsyncEngine) -> None:
    async with visitor(app, get_settings()) as client:
        response = await client.post(SIGN_IN, json={"persona": "amina"})
        assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")
        assert (await client.get("/api/public/demo")).json() == {
            "enabled": False,
            "personas": [],
            "reset_hour_eat": None,
        }
        assert get_settings().session_cookie_name not in client.cookies
