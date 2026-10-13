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
  published demo password, its second step and spending a link are locked too. The admin research API lists and runs
  official excerpts only.
- AT-PD-5: ``fictional`` leaves out every ``ke_provisional`` organisation and every research card citing a news
  excerpt, and has the public demo's own card cited to official excerpts only; ``full`` restores the directory and
  the news-citing cards.

The database is the module's own: the demo seed's rows would disturb other tests' counts in the shared one.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge import public_demo
from bridge.auth import throttle
from bridge.auth.crypto import token_hash
from bridge.config import Settings, get_settings
from bridge.crypto.envelope import LocalKeyWrapper
from bridge.demo import public_access
from bridge.integrations.sms import FakeSmsProvider
from bridge.notifications.email import FakeEmailProvider
from bridge.seed.demo import DemoReport, DemoRuntime, seed_demo
from bridge.seed.demo.data import AMINA, DEMO_PASSWORD, ORGS, P1, P2, STAFF_ADMIN, TELCO_A
from bridge.seed.demo.proposals import _draft
from bridge.seed.demo.research import OFFICIAL_ANSWERS, SEEDED_ANSWERS, SeededExampleClient
from bridge.seed.directory import directory_loadable, load_directory, seed_directory
from bridge.seed.reference import seed_all
from bridge.storage.objects import InMemoryObjectStore
from bridge.storage.scanner import FakeScanner
from tests.integration.api import make_client, refresh_csrf, sign_in_as
from tests.integration.conftest import own_database, role_engine
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
    with own_database(admin_url, "bridge_public") as url:
        yield url


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


KEYS = LocalKeyWrapper(os.urandom(32))  # the Tier-2 key wrapper of the seed and of every visitor's API


def runtime() -> DemoRuntime:
    return DemoRuntime(
        email_provider=FakeEmailProvider(),
        sms_provider=FakeSmsProvider(),
        key_wrapper=KEYS,
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
    """The fictional public seed, recording the excerpt ids each seeded research run sent (``SENT``)."""
    original = SeededExampleClient.complete

    async def recording(self: SeededExampleClient, task: str, messages: Any, schema: Any, **kwargs: Any) -> Any:
        texts = " ".join(getattr(part, "value", "") for message in messages for part in message.parts)
        SENT.append(set(re.findall(r"id: ([a-z][a-z0-9-]*)", texts)))
        return await original(self, task, messages, schema, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SeededExampleClient, "complete", recording)
        return await seed(owner, app, public())


SENT: list[set[str]] = []  # per seeded research run of the fictional seed: the excerpt ids its "model" was sent
# What a rerun must not add to (sessions, sign-in attempts and audit events grow with every sign-in, so not those).
SEEDED_TABLES = (
    "users",
    "organizations",
    "memberships",
    "proposals",
    "proposal_versions",
    "problems",
    "problem_sources",
    "research_runs",
    "engagements",
    "engagement_messages",
    "tags",
    "signal_events",
    "saved_searches",
    "quiz_sets",
    "quiz_attempts",
    "events",
    "trend_cards",
)


async def rows(engine: AsyncEngine, sql: str, **params: object) -> list[Any]:
    async with engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def scalar(engine: AsyncEngine, sql: str, **params: object) -> Any:
    return (await rows(engine, sql, **params))[0][0]


@asynccontextmanager
async def visitor(app: AsyncEngine, settings: Settings | None = None, ip: str = "41.90.2.1") -> AsyncIterator[Any]:
    async with make_client(app, settings or public(), ip=ip) as client:
        client.app.state.key_wrapper = KEYS  # type: ignore[attr-defined]
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
    unofficial = "SELECT count(*) FROM problem_sources WHERE source_type IS DISTINCT FROM 'official'"
    assert await scalar(owner, unofficial) == 0
    cards = await rows(
        owner,
        "SELECT n.slug::text AS niche, p.status::text AS status, p.title, p.county_code,"
        " (SELECT array_agg(s.excerpt_ref ORDER BY s.excerpt_ref) FROM problem_sources s WHERE s.problem_id = p.id)"
        " AS refs FROM problems p JOIN research_runs r ON r.id = p.research_run_id JOIN niches n ON n.id = r.niche_id",
    )
    official = OFFICIAL_ANSWERS["microfinance-saccos"]
    assert [tuple(card) for card in cards] == [  # the public demo's own card, cited to official excerpts only
        (
            "microfinance-saccos",
            "published",
            official["title"],
            None,
            [f"example:{i}" for i, _ in sorted(official["citations"])],
        )
    ]
    assert await scalar(owner, "SELECT count(*) FROM research_runs") == 1
    # The run was sent the official excerpts a fictional run may use, and nothing else (catalogue_for, not the full
    # catalogue, whose freshest SACCO excerpts are news).
    assert [{"ke-sac-003", "ke-sac-004", "ke-sac-005"}] == SENT
    assert (
        f"research cards: {len(SEEDED_ANSWERS)} citing news excerpts left out of the public demo, with"
        f" {len(OFFICIAL_ANSWERS)} citing official excerpts only in their place (PUBLIC_DEMO_CONTENT=full seeds the"
        " others)"
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


async def test_seeding_the_fictional_demo_again_changes_nothing(
    fictional: Seeded, owner: AsyncEngine, app: AsyncEngine
) -> None:
    """The image seeds on every boot of a wiped database, and a rerun on a seeded one tops nothing up."""

    async def counts() -> dict[str, int]:
        return {table: int(await scalar(owner, f"SELECT count(*) FROM {table}")) for table in SEEDED_TABLES}

    before = await counts()
    directory, report = await seed(owner, app, public())
    assert directory is None
    assert report.created == []
    assert await counts() == before
    assert len(SENT) == 1  # no second research run


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
    async with visitor(app, ip="41.90.2.2") as peter, visitor(app, ip="41.90.2.3") as amina:
        assert (await sign_in(peter, "peter")).status_code == 200
        created = await peter.post(f"/api/orgs/{report.orgs[TELCO_A.legal_name]}/interest", json=interest)
        assert created.status_code == 201, created.text
        assert (await sign_in(amina, "amina")).status_code == 200
        accepted = await Tracker(UUID(created.json()["id"])).ok(amina, "accept-interest")
        assert accepted["state"] == "INTEREST_CONFIRMED"
    async with visitor(app, ip="41.90.2.4") as moderator:
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
    async with visitor(app, ip="41.90.2.5") as client:
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
        async with visitor(app, ip="41.90.2.6") as client:
            response = await client.post(SIGN_IN, json={"persona": "hassan"})
            assert (response.status_code, response.json()["detail"]["code"]) == (400, "unknown_persona")
            assert get_settings().session_cookie_name not in client.cookies
    finally:
        async with owner.begin() as conn:
            await conn.execute(
                text("UPDATE users SET demo_account = true, status = 'active' WHERE email = :e"), {"e": hassan}
            )
    async with visitor(app, ip="41.90.2.7") as client:
        assert (await client.post(SIGN_IN, json={"persona": "hassan"})).status_code == 200


async def test_sign_ins_are_throttled_per_ip(fictional: Seeded, app: AsyncEngine) -> None:
    async with visitor(app, ip="41.90.2.8") as client:
        for n in range(30):  # refused attempts count too
            assert (await client.post(SIGN_IN, json={"persona": "nobody"})).status_code == 400, n
        response = await client.post(SIGN_IN, json={"persona": "amina"})
        assert (response.status_code, response.json()["detail"]["code"]) == (429, "too_many_attempts")
    async with visitor(app, ip="41.90.2.9") as other:  # another address is not held back
        assert (await other.post(SIGN_IN, json={"persona": "amina"})).status_code == 200


async def ledger(owner: AsyncEngine, purpose: str, ip: str) -> int:
    """Sign-in attempts of the last minute in the bucket of ``purpose`` and ``ip`` (the throttle's own digests)."""
    keys = throttle.ip_keys(get_settings().secret_key.get_secret_value(), purpose, ip)
    sql = "SELECT count(*) FROM login_attempts WHERE ip_digest = :d AND created_at > now() - interval '1 minute'"
    return int(await scalar(owner, sql, d=keys.ip))


async def test_addresses_that_tell_no_visitor_apart_share_one_high_bucket(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine
) -> None:
    """Loopback, private and link-local clients (Codespaces' forwarder, a bare docker run) share one bucket of 300 a
    minute, so 30 requests from one of them lock nobody out; past 300 every such client waits, a global address not."""
    shared = public_access.SHARED_PURPOSE, "shared"
    try:
        async with visitor(app, ip="127.0.0.1") as local:
            for n in range(30):
                assert (await local.post(SIGN_IN, json={"persona": "nobody"})).status_code == 400, n
            assert (await sign_in(local, "amina")).status_code == 200  # not locked at 30
            assert await ledger(owner, *shared) == 31
            assert await ledger(owner, public_access.THROTTLE_PURPOSE, "127.0.0.1") == 0  # no per-address bucket
            for n in range(31, public_access.SHARED_SIGN_INS_PER_MINUTE):
                assert (await local.post(SIGN_IN, json={"persona": "nobody"})).status_code == 400, n
            refused = await local.post(SIGN_IN, json={"persona": "amina"})
            assert (refused.status_code, refused.json()["detail"]["code"]) == (429, "too_many_attempts")
        for ip in ("10.1.2.3", "169.254.1.1", "::1"):
            async with visitor(app, ip=ip) as other:
                assert (await other.post(SIGN_IN, json={"persona": "amina"})).status_code == 429, ip
        async with visitor(app, ip="41.90.2.10") as global_visitor:
            assert (await global_visitor.post(SIGN_IN, json={"persona": "amina"})).status_code == 200
    finally:  # leave the shared bucket empty for the module's later sign-ins
        keys = throttle.ip_keys(get_settings().secret_key.get_secret_value(), *shared)
        async with owner.begin() as conn:
            await conn.execute(text("DELETE FROM login_attempts WHERE ip_digest = :d"), {"d": keys.ip})


async def test_a_trusted_proxys_own_address_uses_the_shared_bucket(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine
) -> None:
    proxy = "41.90.2.11"
    before = await ledger(owner, public_access.SHARED_PURPOSE, "shared")
    async with visitor(app, public(trusted_proxies=f"127.0.0.1,{proxy}"), ip=proxy) as client:
        assert (await client.post(SIGN_IN, json={"persona": "amina"})).status_code == 200
    assert await ledger(owner, public_access.SHARED_PURPOSE, "shared") == before + 1
    assert await ledger(owner, public_access.THROTTLE_PURPOSE, proxy) == 0


async def test_switching_persona_ends_the_session_the_browser_had(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine
) -> None:
    async with visitor(app, ip="41.90.2.12") as client:
        assert (await sign_in(client, "amina")).status_code == 200
        first = client.cookies[get_settings().session_cookie_name]
        assert (await sign_in(client, "brian")).status_code == 200
        second = client.cookies[get_settings().session_cookie_name]
        assert (await client.get("/api/auth/me")).json()["user"]["email"] == "brian@developers.example"
    revoked = "SELECT revoked_at IS NOT NULL FROM sessions WHERE token_hash = :h"
    assert await scalar(owner, revoked, h=token_hash(first)) is True
    assert await scalar(owner, revoked, h=token_hash(second)) is False


async def test_a_persona_keeps_only_its_newest_sessions(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap (500 live sessions a persona, lowered to 2 here): the oldest beyond it are revoked."""
    assert public_access.MAX_SESSIONS_PER_PERSONA == 500
    monkeypatch.setattr(public_access, "MAX_SESSIONS_PER_PERSONA", 2)
    tokens = []
    for n in range(4):
        async with visitor(app, ip=f"41.90.2.{20 + n}") as client:  # a fresh browser each time: no cookie to end
            assert (await sign_in(client, "rita")).status_code == 200
            tokens.append(client.cookies[get_settings().session_cookie_name])
    live = await rows(
        owner,
        "SELECT token_hash FROM sessions s JOIN users u ON u.id = s.user_id WHERE u.email = 'reviewer@telco-a.example'"
        " AND s.revoked_at IS NULL AND s.expires_at > now()",
    )
    assert {bytes(row.token_hash) for row in live} == {token_hash(t) for t in tokens[-2:]}


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
    async with visitor(app, ip="41.90.3.1") as amina, visitor(app, ip="41.90.3.2") as grace:
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
    async with visitor(app, ip="41.90.3.3") as client:
        response = await client.post("/api/auth/signup", json={"email": "someone@example.com"})
    assert (response.status_code, response.json()) == (403, {"detail": LOCKED})


async def test_the_persona_allowlist_is_the_only_way_in(fictional: Seeded, app: AsyncEngine) -> None:
    """The published demo password opens nothing: the password sign-in (here as the demo staff admin, who is no
    persona), its second step and spending a link are locked, and no session cookie is set."""
    async with visitor(app, ip="41.90.3.4") as client:
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


async def test_the_admin_api_lists_official_excerpts_only(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine
) -> None:
    """Even a staff admin (who cannot sign in to the public demo; signed in directly here) sees only the official
    excerpts there, and neither starts a run nor decides a card (staff writes are locked; ``test_public_demo_content``
    shows a niche without official excerpts is refused); with the mode off every saved excerpt is listed."""
    _, report = fictional
    admin = report.users[STAFF_ADMIN.email]
    async with visitor(app, ip="41.90.3.5") as client:
        await sign_in_as(client, app, admin, mfa_verified=True)
        sources = (await client.get("/api/admin/research/sources")).json()
        assert {excerpt["source_type"] for excerpt in sources["excerpts"]} == {"official"}
        assert len(sources["excerpts"]) == 6
        locked = await client.post("/api/admin/research/runs", json={"niche": "health", "country": "KE"})
        assert (locked.status_code, locked.json()) == (403, {"detail": LOCKED})  # staff start nothing here
        card = await scalar(owner, "SELECT p.id FROM problems p JOIN research_runs r ON r.id = p.research_run_id")
        decided = await client.post(f"/api/admin/research/candidates/{card}/decision", json={"decision": "reject"})
        assert (decided.status_code, decided.json()) == (403, {"detail": LOCKED})  # nor decide a card
        assert await scalar(owner, "SELECT status::text FROM problems WHERE id = :p", p=card) == "published"
    async with visitor(app, get_settings(), ip="41.90.3.6") as client:
        await sign_in_as(client, app, admin, mfa_verified=True)
        assert len((await client.get("/api/admin/research/sources")).json()["excerpts"]) == 19


# ------------------------------------------------------------------------------------- the public pages stay frozen


async def public_view(app: AsyncEngine, settings: Settings, ip: str) -> dict[str, Any]:
    """What a signed-out visitor sees on a fresh API (its own 60-second caches): the feed, Explore and the titles."""
    async with visitor(app, settings, ip=ip) as reader:
        feed = (await reader.get("/api/public/activity")).json()
        explore = (await reader.get("/api/public/explore")).json()
    teasers = [t for group in (*explore["counties"], *explore["niches"]) for t in group["newest"]]
    return {
        "feed_titles": {item["title"] for item in feed["items"]},
        "explore_ids": {t["id"] for t in teasers},
        "explore_titles": {t["title"] for t in teasers},
        "problems": explore["totals"]["problems"],
    }


async def test_a_visitors_text_never_reaches_the_signed_out_pages(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine
) -> None:
    """Security review MAJOR 2 (a). After the freeze Grace posts a Brief (approved here by the owner role, as staff
    would: no staff decision is open in the public demo) and Amina publishes a new version of P1 with a new problem.
    Neither reaches /api/public/* (lists omit them, their pages are 404, P1 leaves the feed, since its event would show
    the new teaser title), the seeded problems still do, a reader with the mode off would see them, and signed-in
    pages are unchanged."""
    _, report = fictional
    frozen = await scalar(owner, "SELECT now()")
    niches = {str(slug): niche for slug, niche in await rows(owner, "SELECT slug, id FROM niches")}
    brief_title, new_title = "Visitor brief after the freeze", "Visitor title after the freeze"
    async with visitor(app, ip="41.90.4.1") as grace, visitor(app, ip="41.90.4.2") as amina:
        assert (await sign_in(grace, "grace")).status_code == 200
        brief = await grace.post(
            f"/api/orgs/{report.orgs[TELCO_A.legal_name]}/briefs",
            json={
                "title": brief_title,
                "statement": "Tower sites need fuel deliveries planned a week ahead.",
                "niche_id": str(niches["networks-telecommunications"]),
            },
        )
        assert brief.status_code == 201, brief.text
        brief_id = brief.json()["id"]
        async with owner.begin() as conn:  # what a staff approval would do (decisions are locked here)
            await conn.execute(
                text(
                    "UPDATE problems SET status = 'published', moderation_state = 'clear', published_at = now()"
                    " WHERE id = :p"
                ),
                {"p": brief_id},
            )
            await conn.execute(
                text("UPDATE problem_briefs SET status = 'published' WHERE problem_id = :p"), {"p": brief_id}
            )
        assert (await sign_in(amina, "amina")).status_code == 200
        body = _draft(replace(P1, title=new_title), niches, [])
        body["new_problem"] = {
            "title": "Visitor problem after the freeze",
            "statement": "Members wait days for loan statements.",
        }
        saved = await amina.patch(f"/api/me/proposals/{report.proposals[P1.key]}", json=body)
        assert saved.status_code == 200, saved.text
        terms = (await amina.get("/api/proposals/attestations")).json()
        published = await amina.post(
            f"/api/me/proposals/{report.proposals[P1.key]}/publish",
            json={
                "attestations": dict.fromkeys(
                    ("created_it", "not_owned_by_employer_or_client", "no_third_party_confidential"), True
                ),
                "attestation_text_version": terms["version"],
            },
        )
        assert published.status_code == 200, published.text
        new_problem = published.json()["new_problem_id"]
        assert (await amina.get(f"/api/problems/{new_problem}")).status_code == 200  # signed-in pages unchanged
        assert (await amina.get(f"/api/problems/{brief_id}")).status_code == 200
    frozen_view = await public_view(app, public(public_demo_frozen_at=frozen), "41.90.4.3")
    open_view = await public_view(app, get_settings(), "41.90.4.4")  # the same rows without the freeze
    for leaked in (brief_id, new_problem):
        assert leaked in open_view["explore_ids"]  # they would be public without the freeze
        assert leaked not in frozen_view["explore_ids"]
    assert new_title in open_view["feed_titles"]
    assert not {new_title, P1.title, brief_title, "Visitor problem after the freeze"} & frozen_view["feed_titles"]
    assert P2.new_problem is not None
    assert P2.new_problem.title in frozen_view["explore_titles"]  # the seeded problems are still there
    assert frozen_view["problems"] == open_view["problems"] - 2
    async with visitor(app, public(public_demo_frozen_at=frozen), ip="41.90.4.5") as reader:
        for leaked in (brief_id, new_problem):
            response = await reader.get(f"/api/public/problems/{leaked}")
            assert (response.status_code, response.json()["detail"]["code"]) == (404, "not_found")
        seeded = next(iter(frozen_view["explore_ids"]))
        assert (await reader.get(f"/api/public/problems/{seeded}")).status_code == 200


async def test_publishing_is_capped_per_account_and_nairobi_day(
    fictional: Seeded, app: AsyncEngine, owner: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Security review MINOR (TSA egress): an account's next publish past the day's cap is 429 public_demo_limit
    (the cap, 20, lowered here to what Amina has registered today) and registers nothing."""
    _, report = fictional
    assert public_demo.PUBLISHES_PER_DAY == 20
    today = (
        "SELECT count(*) FROM proposal_versions v JOIN proposals p ON p.id = v.proposal_id WHERE p.owner_id = :u"
        " AND v.registered_at >= (date_trunc('day', now() AT TIME ZONE 'Africa/Nairobi') AT TIME ZONE 'Africa/Nairobi')"
    )
    registered = int(await scalar(owner, today, u=report.users[AMINA.email]))
    monkeypatch.setattr(public_demo, "PUBLISHES_PER_DAY", registered)
    async with visitor(app, ip="41.90.4.7") as amina:
        assert (await sign_in(amina, "amina")).status_code == 200
        terms = (await amina.get("/api/proposals/attestations")).json()
        statements = ("created_it", "not_owned_by_employer_or_client", "no_third_party_confidential")
        refused = await amina.post(
            f"/api/me/proposals/{report.proposals[P2.key]}/publish",
            json={"attestations": dict.fromkeys(statements, True), "attestation_text_version": terms["version"]},
        )
    assert refused.status_code == 429, refused.text
    assert refused.json() == {
        "detail": {
            "code": "public_demo_limit",
            "message": "The public demo publishes up to 20 versions a day for each account. Try again tomorrow.",
        }
    }
    assert int(await scalar(owner, today, u=report.users[AMINA.email])) == registered


async def test_the_moderator_persona_reads_but_decides_nothing(fictional: Seeded, app: AsyncEngine) -> None:
    """Security review MAJOR 2 (b): every staff decision answers 403 public_demo_locked; the queues stay readable."""
    async with visitor(app, ip="41.90.4.6") as moderator:
        assert (await sign_in(moderator, "moderator")).status_code == 200
        queue = await moderator.get("/api/admin/moderation/cases")
        assert queue.status_code == 200, queue.text
        case = queue.json()["items"][0]["id"]
        assert (await moderator.get(f"/api/admin/moderation/cases/{case}")).status_code == 200
        events = await moderator.get("/api/admin/events")
        assert events.status_code == 200, events.text
        decisions = [
            await moderator.post(f"/api/admin/moderation/cases/{case}/decision", json={"decision": "approve"}),
            await moderator.post(f"/api/admin/events/{UUID(int=7)}/decision", json={"decision": "publish"}),
            await moderator.post(f"/api/admin/events/{UUID(int=7)}/cancel"),
            await moderator.post(
                f"/api/admin/research/candidates/{UUID(int=7)}/decision", json={"decision": "approve"}
            ),
        ]
        for response in decisions:
            assert (response.status_code, response.json()) == (403, {"detail": LOCKED}), response.request.url


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
    niches = await rows(
        owner, "SELECT n.slug::text FROM research_runs r JOIN niches n ON n.id = r.niche_id ORDER BY n.slug"
    )
    # Every niche has its card; microfinance keeps the official one written first (the seed never adds a second card
    # to a niche, and the image wipes its data every night, so a real full start seeds SEEDED_ANSWERS' own).
    assert [row[0] for row in niches] == sorted(SEEDED_ANSWERS)
    assert await scalar(owner, "SELECT count(*) FROM problem_sources WHERE source_type = 'news'") > 0
    assert not [note for note in report.notes if note.startswith("research cards:")]
