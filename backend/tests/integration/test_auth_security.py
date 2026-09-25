"""Regression tests for the Phase 1 review findings on REQ-AUTH-01, REQ-TEN-01 (API), REQ-BIL-01 and REQ-CON-01.

Each test names the finding it pins: pre-hijacking, signup abuse, proxy-aware throttling, TOTP races and formats,
role and step-up 403s, generated cross-tenant 404s, time-based rules, consent history and subscription rows.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import bridge.clock
from bridge.auth import totp
from bridge.config import get_settings
from bridge.seed.reference import seed_all
from tests.integration.api import make_client, outbox, refresh_csrf

PASSWORD = "correct horse battery staple"


@pytest.fixture(scope="module", autouse=True)
async def seeded(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())


@pytest.fixture
async def client(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app_engine) as c:
        yield c


@pytest.fixture
async def other(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """A second browser (its own cookies)."""
    async with make_client(app_engine) as c:
        yield c


def email() -> str:
    return f"user-{uuid4().hex[:10]}@example.com"


def last_link(client: httpx.AsyncClient, to: str) -> str:
    message = [m for m in outbox(client).outbox if m.to == to][-1]
    match = re.search(r"/auth/link#token=([A-Za-z0-9_\-]+)", message.text)
    assert match, message.text
    return match.group(1)


async def signup(
    client: httpx.AsyncClient,
    address: str,
    *,
    side: str = "developer",
    password: str = PASSWORD,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    body: dict[str, Any] = {
        "email": address,
        "password": password,
        "display_name": "Test User",
        "side": side,
        "accept_terms": True,
        "consents": {"marketing": True},
    }
    if side == "org":
        body["org"] = {"legal_name": "Org (fixture)", "kind": "company"}
    return await client.post("/api/auth/signup", json=body, headers=headers or {})


async def verified(client: httpx.AsyncClient, address: str, *, side: str = "developer") -> None:
    assert (await signup(client, address, side=side)).status_code == 202
    assert (
        await client.post("/api/auth/magic-link/consume", json={"token": last_link(client, address)})
    ).status_code == 200
    await refresh_csrf(client)


def now_counter() -> int:
    return int(time.time() // 30)


async def enrol(client: httpx.AsyncClient) -> str:
    secret = str((await client.post("/api/auth/totp/enrol", json={"password": PASSWORD})).json()["secret"])
    assert (
        await client.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, now_counter())})
    ).status_code == 200
    return secret


# ------------------------------------------------------------------ BLOCKER: account pre-hijacking


async def test_a_password_set_by_someone_else_before_verification_does_not_survive(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    victim = email()
    assert (await signup(other, victim, password="attacker chose this")).status_code == 202  # attacker's browser
    link = last_link(other, victim)  # delivered to the victim's inbox; opened in the victim's browser
    assert (await client.post("/api/auth/magic-link/consume", json={"token": link})).status_code == 200
    await refresh_csrf(other)
    stolen = await other.post("/api/auth/login", json={"email": victim, "password": "attacker chose this"})
    assert stolen.status_code == 401
    await refresh_csrf(client)
    assert (await client.post("/api/auth/password", json={"new_password": "victim's own password"})).status_code == 204


async def test_the_signup_browser_keeps_its_password(client: httpx.AsyncClient) -> None:
    address = email()
    await verified(client, address)
    assert (await client.post("/api/auth/login", json={"email": address, "password": PASSWORD})).status_code == 200


async def test_a_repeat_signup_of_an_unverified_address_replaces_the_password(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    address = email()
    await signup(other, address, password="first password here")
    await signup(client, address, password="second password here")
    await client.post("/api/auth/magic-link/consume", json={"token": last_link(client, address)})
    await refresh_csrf(client)
    assert (
        await client.post("/api/auth/login", json={"email": address, "password": "first password here"})
    ).status_code == 401
    assert (
        await client.post("/api/auth/login", json={"email": address, "password": "second password here"})
    ).status_code == 200


# ------------------------------------------------------------------ MAJOR: signup abuse and proxy-aware throttling


async def test_signup_is_throttled_and_account_exists_mail_is_daily(client: httpx.AsyncClient) -> None:
    address = email()
    await verified(client, address)
    codes = [(await signup(client, address)).status_code for _ in range(5)]
    assert codes == [202] * 5  # same answer every time
    notices = [m for m in outbox(client).outbox if m.to == address and "already have" in m.subject]
    assert len(notices) == 1  # throttled at 3 and deduplicated per day


async def test_forwarded_client_ips_from_a_trusted_proxy_get_separate_buckets(client: httpx.AsyncClient) -> None:
    address = email()
    first = {"X-Forwarded-For": "203.0.113.10"}
    for _ in range(5):
        await client.post("/api/auth/login", json={"email": address, "password": "wrong password here"}, headers=first)
    blocked = await client.post("/api/auth/login", json={"email": address, "password": "wrong"}, headers=first)
    assert blocked.status_code == 429
    elsewhere = await client.post(
        "/api/auth/login", json={"email": address, "password": "wrong"}, headers={"X-Forwarded-For": "203.0.113.99"}
    )
    assert elsewhere.status_code == 401


async def test_an_untrusted_source_cannot_spoof_its_address(app_engine: AsyncEngine) -> None:
    settings = get_settings().model_copy(update={"trusted_proxies": "10.99.99.99"})
    async with make_client(app_engine, settings=settings) as c:
        address = email()
        for n in range(5):
            spoof = {"X-Forwarded-For": f"198.51.100.{n}"}
            await c.post("/api/auth/login", json={"email": address, "password": "wrong password"}, headers=spoof)
        again = await c.post(
            "/api/auth/login", json={"email": address, "password": "x"}, headers={"X-Forwarded-For": "198.51.100.77"}
        )
        assert again.status_code == 429


# ------------------------------------------------------------------ TOTP: formats, races, re-auth, rotation


async def test_totp_accepts_spaces_and_refuses_a_concurrent_replay(
    client: httpx.AsyncClient, app_engine: AsyncEngine
) -> None:
    address = email()
    await verified(client, address)
    secret = await enrol(client)
    code = totp.code_at(secret, now_counter() + 1)
    spaced = f"{code[:3]} {code[3:]}"
    async with make_client(app_engine) as twin:
        twin.cookies.update(client.cookies)
        await refresh_csrf(twin)
        results = await asyncio.gather(
            client.post("/api/auth/step-up", json={"code": spaced}),
            twin.post("/api/auth/step-up", json={"code": spaced}),
        )
    assert sorted(r.status_code for r in results) == [200, 401]


async def test_totp_enrolment_needs_the_current_password(client: httpx.AsyncClient) -> None:
    await verified(client, email())
    refused = await client.post("/api/auth/totp/enrol", json={"password": "not my password at all"})
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "current_password_required"


async def test_the_second_step_rotates_the_session_and_hides_orgs_until_then(client: httpx.AsyncClient) -> None:
    address = email()
    await verified(client, address, side="org")
    secret = await enrol(client)
    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    await client.post("/api/auth/login", json={"email": address, "password": PASSWORD})
    pending_cookie = client.cookies.get("bridge_session")
    await refresh_csrf(client)
    me = (await client.get("/api/auth/me")).json()
    assert me["side"] == "pending"
    assert me["memberships"] == []
    await client.post("/api/auth/mfa/verify", json={"code": totp.code_at(secret, now_counter() + 1)})
    assert client.cookies.get("bridge_session") != pending_cookie


# ------------------------------------------------------------------ roles, step-up and generated 404s


async def _org_owner(client: httpx.AsyncClient) -> tuple[str, str]:
    await verified(client, email(), side="org")
    await enrol(client)
    me = (await client.get("/api/auth/me")).json()
    return str(me["memberships"][0]["org_id"]), str(me["user"]["id"])


async def _add_member(owner_engine: AsyncEngine, org_id: str, user_id: str, roles: str) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO memberships (id, org_id, user_id, roles) VALUES (:id, :org, :user, CAST(:roles AS "
                "org_role[]))"
            ),
            {"id": uuid4(), "org": UUID(org_id), "user": UUID(user_id), "roles": roles},
        )


async def test_members_lacking_a_role_get_403(
    client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    org_id, _ = await _org_owner(client)
    await verified(other, email())
    other_id = str((await other.get("/api/auth/me")).json()["user"]["id"])
    await _add_member(owner_engine, org_id, other_id, "{viewer}")
    patch = await other.patch(f"/api/orgs/{org_id}", json={"website": "https://example.com"})
    assert patch.status_code == 403
    assert patch.json()["detail"]["code"] == "forbidden"
    roles = await other.put(f"/api/orgs/{org_id}/members/{other_id}/roles", json={"roles": ["owner"]})
    assert roles.status_code == 403


async def test_role_changes_need_a_fresh_second_factor(client: httpx.AsyncClient, app_engine: AsyncEngine) -> None:
    org_id, user_id = await _org_owner(client)
    async with app_engine.begin() as conn:
        await conn.execute(
            text("UPDATE sessions SET mfa_verified_at = now() - interval '13 hours' WHERE user_id = :u"),
            {"u": UUID(user_id)},
        )
    stale = await client.put(f"/api/orgs/{org_id}/members/{user_id}/roles", json={"roles": ["owner", "signatory"]})
    assert stale.status_code == 403
    assert stale.json()["detail"]["code"] == "step_up_required"


async def test_every_org_route_answers_404_to_a_non_member(client: httpx.AsyncClient, other: httpx.AsyncClient) -> None:
    """Generated from the app's routes: any path with {org_id}, any method, with and without a fresh step-up."""
    org_id, _ = await _org_owner(client)
    await verified(other, email(), side="org")
    await enrol(other)  # a fresh second factor, so step-up cannot mask the membership check
    app = other.app  # type: ignore[attr-defined]
    for route in app.routes:
        path = getattr(route, "path", "")
        if "{org_id}" not in path:
            continue
        url = path.replace("{org_id}", org_id).replace("{user_id}", str(uuid4()))
        for method in sorted(getattr(route, "methods", set()) - {"HEAD"}):
            body = {"roles": ["viewer"]} if method == "PUT" else {}
            response = await other.request(method, url, json=body if method in {"PUT", "PATCH", "POST"} else None)
            assert response.status_code == 404, (method, path, response.text)


async def test_invalid_org_updates_are_422_not_500(client: httpx.AsyncClient) -> None:
    org_id, _ = await _org_owner(client)
    assert (await client.patch(f"/api/orgs/{org_id}", json={"legal_name": None})).status_code == 422
    assert (await client.patch(f"/api/orgs/{org_id}", json={"website": "javascript:alert(1)"})).status_code == 422


async def test_unknown_county_is_422(client: httpx.AsyncClient) -> None:
    await verified(client, email())
    response = await client.patch("/api/me/profile", json={"county_code": "KE-99"})
    assert response.status_code == 422
    assert (await client.patch("/api/me/profile", json={"county_code": "KE-30"})).status_code == 200


# ------------------------------------------------------------------ time-based rules (injectable clock)


async def test_links_expire_after_15_minutes(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    address = email()
    await signup(client, address)
    later = datetime.now(UTC) + timedelta(minutes=16)
    monkeypatch.setattr(bridge.clock, "utcnow", lambda: later)
    expired = await client.post("/api/auth/magic-link/consume", json={"token": last_link(client, address)})
    assert expired.status_code == 400


async def test_expired_sessions_are_signed_out(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    await verified(client, email())
    later = datetime.now(UTC) + timedelta(days=31)
    monkeypatch.setattr(bridge.clock, "utcnow", lambda: later)
    assert (await client.get("/api/auth/me")).status_code == 401


# ------------------------------------------------------------------ consents and subscriptions


async def test_consent_history_latest_decision_wins(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    await verified(client, email())
    version = (await client.get("/api/consents")).json()["version"]
    for granted in (False, True, False):
        response = await client.put("/api/me/consents", json={"marketing": {"granted": granted, "version": version}})
        state = {c["purpose"]: c["granted"] for c in response.json()}
        assert state["marketing"] is granted
    stale = await client.put("/api/me/consents", json={"marketing": {"granted": True, "version": "old"}})
    assert stale.status_code == 409
    user_id = UUID(str((await client.get("/api/auth/me")).json()["user"]["id"]))
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT text_version, length(text_sha256) FROM consents WHERE user_id = :u AND purpose = "
                    "'marketing'"
                ),
                {"u": user_id},
            )
        ).all()
    assert len(rows) == 4  # signup + three changes
    assert all(v == version and n == 32 for v, n in rows)


async def test_signup_creates_one_live_free_subscription(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    await verified(client, email())
    user_id = UUID(str((await client.get("/api/auth/me")).json()["user"]["id"]))
    async with owner_engine.connect() as conn:
        plans = (
            (
                await conn.execute(
                    text(
                        "SELECT p.code FROM subscriptions s JOIN plans p ON p.id = s.plan_id WHERE s.user_id = :u AND "
                        "s.status = 'active'"
                    ),
                    {"u": user_id},
                )
            )
            .scalars()
            .all()
        )
    assert plans == ["dev_free"]
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE subscriptions SET plan_id = (SELECT id FROM plans WHERE code = 'dev_pro_monthly') WHERE "
                "user_id = :u"
            ),
            {"u": user_id},
        )
    ent = (await client.get("/api/me/entitlements")).json()
    assert ent["plan"] == "dev_pro_monthly"
    assert ent["limits"]["active_proposals"] is None


async def test_org_members_see_org_entitlements_not_developer_ones(client: httpx.AsyncClient) -> None:
    org_id, _ = await _org_owner(client)
    assert (await client.get("/api/me/entitlements")).status_code == 404
    org = (await client.get(f"/api/orgs/{org_id}/entitlements")).json()
    assert org["plan"] == "org_claimed"
