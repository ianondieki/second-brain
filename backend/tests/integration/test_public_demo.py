"""REQ-FND-04 (P28 track PD): the public demo against a database seeded as the demo image seeds it, with
``PUBLIC_DEMO=true`` (reference data, the provisional directory step, then ``python -m bridge.seed --demo``).

- AT-PD-1: ``POST /api/auth/demo/sign-in {"persona": "amina"}`` is 200 with the session cookie; ``/api/auth/me`` is
  Amina's with the second factor satisfied, and the sign-in is audited ``auth.login`` (``method: demo_persona``).
  Peter (Telco A's signatory) expresses interest in Amina's proposal and Amina accepts it, both step-up actions, and
  the moderator opens the staff queue (staff routes need a fresh second factor), none with a code.
- AT-PD-2: with the mode off the route is 404 and ``/api/public/demo`` says ``enabled: false``.
- AT-PD-3: an unknown persona, an account that is no longer a demo account or no longer active, and a key outside the
  allowlist are 400 ``unknown_persona``; a body naming an email is refused (422) and signs nobody in; 30 attempts a
  minute per IP, then 429.
- AT-PD-4: a persona's password change, second-factor change, role change, uploads that keep a file (proposal and
  message attachments) and the clock's move are 403 ``public_demo_locked`` and change nothing; the certificate file
  check, which stores nothing, stays open. The persona allowlist is the only way in: the password sign-in with the
  published demo password, its second step and spending a link are locked too.
- AT-PD-5: ``fictional`` leaves out every ``ke_provisional`` organisation and every research card citing a news
  excerpt; ``full`` restores both.

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
from bridge.seed.demo.data import AMINA, DEMO_PASSWORD, ORGS, P1, STAFF_ADMIN, TELCO_A
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


# ------------------------------------------------------------------------------------------------------------ AT-PD-3


async def test_unknown_personas_and_other_fields_sign_nobody_in(fictional: Seeded, app: AsyncEngine) -> None:
    async with visitor(app, ip="127.0.2.5") as client:
        for persona in ("nobody", "admin", "AMINA", " amina", "admin@staff.example"):
            response = await client.post(SIGN_IN, json={"persona": persona})
            assert response.status_code == 400, persona
            assert response.json() == {
                "detail": {"code": "unknown_persona", "message": "Choose one of the demo personas."}
            }
        named = await client.post(SIGN_IN, json={"persona": "amina", "email": "admin@staff.example"})
        assert named.status_code == 422
        assert (await client.post(SIGN_IN, json={"email": "amina@developers.example"})).status_code == 422
        assert get_settings().session_cookie_name not in client.cookies
        assert (await client.get("/api/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE users SET demo_account = false WHERE email = :e",
        "UPDATE users SET status = 'suspended' WHERE email = :e",
    ],
)
async def test_an_allowlisted_address_that_is_not_an_active_demo_account_is_refused(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine, change: str
) -> None:
    hassan = "owner@county-c.example"
    async with owner.begin() as conn:
        await conn.execute(text(change), {"e": hassan})
    try:
        async with visitor(app, ip="127.0.2.6") as client:
            response = await client.post(SIGN_IN, json={"persona": "hassan"})
            assert (response.status_code, response.json()["detail"]["code"]) == (400, "unknown_persona")
            assert get_settings().session_cookie_name not in client.cookies
    finally:
        async with owner.begin() as conn:
            await conn.execute(
                text("UPDATE users SET demo_account = true, status = 'active' WHERE email = :e"), {"e": hassan}
            )
    async with visitor(app, ip="127.0.2.7") as client:
        assert (await client.post(SIGN_IN, json={"persona": "hassan"})).status_code == 200


async def test_sign_ins_are_throttled_per_ip(fictional: Seeded, app: AsyncEngine) -> None:
    async with visitor(app, ip="127.0.2.8") as client:
        for n in range(30):  # refused attempts count too
            assert (await client.post(SIGN_IN, json={"persona": "nobody"})).status_code == 400, n
        response = await client.post(SIGN_IN, json={"persona": "amina"})
        assert (response.status_code, response.json()["detail"]["code"]) == (429, "too_many_attempts")
    async with visitor(app, ip="127.0.2.9") as other:  # another address is not held back
        assert (await other.post(SIGN_IN, json={"persona": "amina"})).status_code == 200


# ------------------------------------------------------------------------------------------------------------ AT-PD-4


async def test_a_persona_cannot_change_credentials_roles_files_or_the_clock(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine
) -> None:
    _, report = fictional
    before = await rows(owner, "SELECT id, password_hash, totp_enabled_at FROM users ORDER BY id")
    roles_before = await rows(owner, "SELECT id, roles FROM memberships ORDER BY id")
    clock_before = await scalar(owner, "SELECT clock_offset FROM test_clock")
    engagement = await scalar(
        owner,
        "SELECT e.id FROM engagements e JOIN proposals p ON p.id = e.proposal_id WHERE p.owner_id = :u LIMIT 1",
        u=report.users[AMINA.email],
    )
    telco = report.orgs[TELCO_A.legal_name]
    peter = report.users["signatory@telco-a.example"]
    async with visitor(app, ip="127.0.3.1") as amina, visitor(app, ip="127.0.3.2") as grace:
        assert (await sign_in(amina, "amina")).status_code == 200
        assert (await sign_in(grace, "grace")).status_code == 200
        attempts = [
            await amina.post(
                "/api/auth/password", json={"current_password": "bridge-demo-2026", "new_password": "x" * 16}
            ),
            await amina.post("/api/auth/totp/disable"),
            await amina.post("/api/auth/totp/enrol", json={"password": "bridge-demo-2026"}),
            await amina.post("/api/auth/totp/recovery-codes", json={"current_password": "bridge-demo-2026"}),
            await amina.post("/api/auth/magic-link", json={"email": AMINA.email}),
            await amina.post(
                f"/api/me/proposals/{report.proposals[P1.key]}/attachments",
                content=b"%PDF-1.4 demo",
                headers={"Content-Type": "application/pdf", "X-File-Name": "a.pdf"},
            ),
            await amina.post(
                f"/api/engagements/{engagement}/messages/attachments",
                content=b"%PDF-1.4 demo",
                headers={"Content-Type": "application/pdf", "X-File-Name": "a.pdf"},
            ),
            await amina.post("/api/test-clock/advance", json={"days": 30}),
            await grace.put(f"/api/orgs/{telco}/members/{peter}/roles", json={"roles": ["viewer"]}),
        ]
        for response in attempts:
            assert response.status_code == 403, (response.request.url, response.text)
            assert response.json() == {"detail": LOCKED}
            assert response.headers["x-robots-tag"] == "noindex, nofollow"
        assert (await amina.get("/api/test-clock")).status_code == 200  # reading the clock stays open
        binary = {"Content-Type": "application/octet-stream"}
        checked = await amina.post("/api/verify", content=b"any file", headers=binary)
        assert checked.status_code == 200, checked.text  # the file check hashes the body and keeps nothing: open
        assert checked.json()["match"] is False
    assert await rows(owner, "SELECT id, password_hash, totp_enabled_at FROM users ORDER BY id") == before
    assert await rows(owner, "SELECT id, roles FROM memberships ORDER BY id") == roles_before
    assert await scalar(owner, "SELECT clock_offset FROM test_clock") == clock_before


async def test_signing_up_is_switched_off(fictional: Seeded, app: AsyncEngine) -> None:
    async with visitor(app, ip="127.0.3.3") as client:
        response = await client.post("/api/auth/signup", json={"email": "someone@example.com"})
    assert (response.status_code, response.json()) == (403, {"detail": LOCKED})


async def test_the_persona_allowlist_is_the_only_way_in(fictional: Seeded, app: AsyncEngine) -> None:
    """The published demo password opens nothing: the password sign-in (here as the demo staff admin, who is no
    persona), its second step and spending a link are locked, and no session cookie is set."""
    async with visitor(app, ip="127.0.3.4") as client:
        attempts = [
            await client.post("/api/auth/login", json={"email": STAFF_ADMIN.email, "password": DEMO_PASSWORD}),
            await client.post("/api/auth/login", json={"email": AMINA.email, "password": DEMO_PASSWORD}),
            await client.post("/api/auth/mfa/verify", json={"code": "123456"}),
            await client.post("/api/auth/magic-link/consume", json={"token": "x" * 43}),
        ]
        for response in attempts:
            assert (response.status_code, response.json()) == (403, {"detail": LOCKED}), response.request.url
        assert get_settings().session_cookie_name not in client.cookies
        assert (await client.get("/api/auth/me")).status_code == 401


# ------------------------------------------------------------------------------------------------- AT-PD-5 (full, last)


async def test_full_content_restores_the_directory_and_the_research_cards(
    fictional: Seeded, owner: AsyncEngine, app: AsyncEngine
) -> None:
    """Last in the module: the same database seeded again with PUBLIC_DEMO_CONTENT=full gains what fictional left out
    (the image wipes its data every night, so a real switch starts from an empty database)."""
    directory, report = await seed(owner, app, public(public_demo_content="full"))
    assert directory is not None
    assert await scalar(owner, "SELECT count(*) FROM organizations WHERE slug = ANY(:s)", s=PROVISIONAL) == len(
        PROVISIONAL
    )
    assert await scalar(owner, "SELECT count(*) FROM research_runs") == len(SEEDED_ANSWERS)
    assert await scalar(owner, "SELECT count(*) FROM problem_sources WHERE source_type = 'news'") > 0
    assert not [note for note in report.notes if note.startswith("research cards:")]
