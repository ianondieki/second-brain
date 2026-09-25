"""REQ-AUTH-01 through the API (X1-1 backend half; the browser half is frontend/e2e/auth.spec.ts).

Signup never reveals whether an address exists; the emailed link verifies and signs in once; password login with
argon2id; throttling; TOTP enrolment, second step and replay; role-based MFA; CSRF on every unsafe request.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

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


def link_token(client: httpx.AsyncClient, to: str) -> str:
    message = [m for m in outbox(client).outbox if m.to == to][-1]
    match = re.search(r"/auth/link#token=([A-Za-z0-9_\-]+)", message.text)
    assert match, message.text
    return match.group(1)


def email() -> str:
    return f"user-{uuid4().hex[:10]}@example.com"


async def signup(client: httpx.AsyncClient, address: str, side: str = "developer") -> httpx.Response:
    body: dict[str, object] = {
        "email": address,
        "password": PASSWORD,
        "display_name": "Test User",
        "side": side,
        "accept_terms": True,
        "consents": {"marketing": False, "reminders": True},
    }
    if side == "org":
        body["org"] = {"legal_name": "Telco A (fixture)", "kind": "company"}
    return await client.post("/api/auth/signup", json=body)


async def test_developer_signup_verify_and_me(client: httpx.AsyncClient) -> None:
    address = email()
    response = await signup(client, address)
    assert response.status_code == 202
    assert response.json() == {"status": "check_email"}
    consumed = await client.post("/api/auth/magic-link/consume", json={"token": link_token(client, address)})
    assert consumed.status_code == 200, consumed.text
    assert consumed.json()["mfa_required"] is False
    await refresh_csrf(client)
    me = (await client.get("/api/auth/me")).json()
    assert me["user"]["email"] == address
    assert me["user"]["email_verified"] is True
    assert me["side"] == "developer"
    assert (await client.get("/api/me/entitlements")).json()["plan"] == "dev_free"
    consents = {c["purpose"]: c["granted"] for c in (await client.get("/api/me/consents")).json()}
    assert consents["reminders"] is True
    assert consents["marketing"] is False
    assert consents["tier2_llm_assistant"] is False


async def test_signup_does_not_reveal_existing_accounts(client: httpx.AsyncClient) -> None:
    address = email()
    first = await signup(client, address)
    await client.post("/api/auth/magic-link/consume", json={"token": link_token(client, address)})
    await refresh_csrf(client)
    second = await signup(client, address)  # the address is now a verified account
    assert (first.status_code, first.json()) == (second.status_code, second.json())
    subjects = [m.subject for m in outbox(client).outbox if m.to == address]
    assert any("already have" in s for s in subjects)


async def test_a_repeat_signup_of_an_unverified_address_replaces_its_link(client: httpx.AsyncClient) -> None:
    address = email()
    await signup(client, address)
    first_link = link_token(client, address)
    await signup(client, address)
    second_link = link_token(client, address)
    assert first_link != second_link
    stale = await client.post("/api/auth/magic-link/consume", json={"token": first_link})
    assert stale.status_code == 400
    assert (await client.post("/api/auth/magic-link/consume", json={"token": second_link})).status_code == 200


async def test_links_work_once(client: httpx.AsyncClient) -> None:
    address = email()
    await signup(client, address)
    token = link_token(client, address)
    assert (await client.post("/api/auth/magic-link/consume", json={"token": token})).status_code == 200
    await refresh_csrf(client)
    again = await client.post("/api/auth/magic-link/consume", json={"token": token})
    assert again.status_code == 400
    assert again.json()["detail"]["code"] == "invalid_or_expired_link"


async def test_password_login_and_unverified_accounts(client: httpx.AsyncClient) -> None:
    address = email()
    await signup(client, address)
    signup_link = link_token(client, address)
    unverified = await client.post("/api/auth/login", json={"email": address, "password": PASSWORD})
    assert unverified.status_code == 403
    assert unverified.json()["detail"]["code"] == "email_unverified"
    # The login attempt (right password) emailed a fresh link bound to this browser; the signup link is spent.
    assert link_token(client, address) != signup_link
    await client.post("/api/auth/magic-link/consume", json={"token": link_token(client, address)})
    await refresh_csrf(client)
    wrong = await client.post("/api/auth/login", json={"email": address, "password": "not the password at all"})
    assert wrong.status_code == 401
    ok = await client.post("/api/auth/login", json={"email": address, "password": PASSWORD})
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == address


async def test_unknown_account_and_wrong_password_look_the_same(client: httpx.AsyncClient) -> None:
    unknown = await client.post("/api/auth/login", json={"email": email(), "password": PASSWORD})
    assert unknown.status_code == 401
    assert unknown.json()["detail"]["code"] == "invalid_credentials"


async def test_login_is_throttled_after_five_attempts(client: httpx.AsyncClient) -> None:
    address = email()
    codes = [
        (await client.post("/api/auth/login", json={"email": address, "password": "wrong password here"})).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429


async def test_unsafe_requests_need_the_csrf_header(client: httpx.AsyncClient) -> None:
    del client.headers["X-CSRF-Token"]
    response = await client.post("/api/auth/login", json={"email": email(), "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_failed"


async def test_session_cookie_flags(client: httpx.AsyncClient) -> None:
    address = email()
    await signup(client, address)
    response = await client.post("/api/auth/magic-link/consume", json={"token": link_token(client, address)})
    cookie = next(h for h in response.headers.get_list("set-cookie") if h.startswith("bridge_session="))
    lowered = cookie.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered


async def enrol_totp(client: httpx.AsyncClient) -> str:
    enrol = await client.post("/api/auth/totp/enrol", json={"password": PASSWORD})
    assert enrol.status_code == 200, enrol.text
    secret = str(enrol.json()["secret"])
    confirm = await client.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, _now_counter())})
    assert confirm.status_code == 200, confirm.text
    assert len(confirm.json()["recovery_codes"]) == 10
    return secret


def _now_counter() -> int:
    import time

    return int(time.time() // 30)


async def test_org_owner_must_enrol_totp_and_then_sign_in_with_it(client: httpx.AsyncClient) -> None:
    address = email()
    assert (await signup(client, address, side="org")).status_code == 202
    await client.post("/api/auth/magic-link/consume", json={"token": link_token(client, address)})
    await refresh_csrf(client)
    me = (await client.get("/api/auth/me")).json()
    assert me["side"] == "org"
    assert me["mfa"] == {"required": True, "enrolled": False, "verified": False}
    org_id = me["memberships"][0]["org_id"]
    assert set(me["memberships"][0]["roles"]) == {"owner", "admin"}
    blocked = await client.get(f"/api/orgs/{org_id}")
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_enrolment_required"

    secret = await enrol_totp(client)
    assert (await client.get(f"/api/orgs/{org_id}")).status_code == 200
    assert (await client.get(f"/api/orgs/{org_id}/entitlements")).status_code == 200

    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    login = await client.post("/api/auth/login", json={"email": address, "password": PASSWORD})
    assert login.json()["mfa_required"] is True
    await refresh_csrf(client)
    pending = await client.get(f"/api/orgs/{org_id}")
    assert pending.status_code == 401
    assert pending.json()["detail"]["code"] == "mfa_required"
    counter = _now_counter() + 1  # the enrolment used the current window; replay of it would be refused
    verified = await client.post("/api/auth/mfa/verify", json={"code": totp.code_at(secret, counter)})
    assert verified.status_code == 200, verified.text
    await refresh_csrf(client)  # the second step rotates the session, and with it the CSRF binding
    assert (await client.get(f"/api/orgs/{org_id}")).status_code == 200
    replay = await client.post("/api/auth/step-up", json={"code": totp.code_at(secret, counter)})
    assert replay.status_code == 401
    disable = await client.post("/api/auth/totp/disable")
    assert disable.status_code == 403
    assert disable.json()["detail"]["code"] == "mfa_mandatory_for_role"


async def test_role_changes_need_owner_and_step_up(client: httpx.AsyncClient) -> None:
    address = email()
    await signup(client, address, side="org")
    await client.post("/api/auth/magic-link/consume", json={"token": link_token(client, address)})
    await refresh_csrf(client)
    await enrol_totp(client)
    me = (await client.get("/api/auth/me")).json()
    org_id, user_id = me["memberships"][0]["org_id"], me["user"]["id"]
    demote = await client.put(f"/api/orgs/{org_id}/members/{user_id}/roles", json={"roles": ["viewer"]})
    assert demote.status_code == 409
    add_signatory = await client.put(
        f"/api/orgs/{org_id}/members/{user_id}/roles", json={"roles": ["owner", "signatory"]}
    )
    assert add_signatory.status_code == 200, add_signatory.text
    assert set(add_signatory.json()["roles"]) == {"owner", "signatory"}
