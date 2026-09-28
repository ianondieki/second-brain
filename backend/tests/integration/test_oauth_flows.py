"""REQ-AUTH-02 through the API: GitHub and Google sign-in, signup, linking and unlinking.

Providers are respx fakes of their token and user-info endpoints (AC-SEC-5: the egress guard stays armed and no test
reaches github.com or google.com). Covers new signups, sign-in of linked accounts, the verified-email linking rule,
account pre-hijacking through unverified provider addresses, linking from settings with fresh proof, identities owned
by another account, state mismatch, replay and expiry, MFA-pending sign-in, unlinking rules and disabled providers.
"""

from __future__ import annotations

import base64
import json
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

import bridge.clock
from bridge.auth import identities, service, totp
from bridge.config import Settings, get_settings
from bridge.profiles.consents import consents_version
from bridge.seed.reference import seed_all
from tests.integration.api import make_client, outbox, refresh_csrf

WEB = "https://web.test"
GOOGLE_CLIENT = "bridge-test.apps.googleusercontent.com"
GITHUB_TOKEN = "https://github.com/login/oauth/access_token"
GITHUB_USER = "https://api.github.com/user"
GITHUB_EMAILS = "https://api.github.com/user/emails"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
PASSWORD = "correct horse battery staple"
OAUTH_FIELDS = ("github_client_id", "github_client_secret", "google_client_id", "google_client_secret")


def oauth_settings() -> Settings:
    return get_settings().model_copy(
        update={
            "public_base_url": WEB,
            "github_client_id": SecretStr("gh-test-client"),
            "github_client_secret": SecretStr("gh-test-secret"),
            "google_client_id": SecretStr(GOOGLE_CLIENT),
            "google_client_secret": SecretStr("google-test-secret"),
        }
    )


@pytest.fixture(scope="module", autouse=True)
async def seeded(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())


@pytest.fixture
async def client(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(app_engine, settings=oauth_settings()) as c:
        yield c


@pytest.fixture
async def other(app_engine: AsyncEngine) -> AsyncIterator[httpx.AsyncClient]:
    """A second browser (its own cookies)."""
    async with make_client(app_engine, settings=oauth_settings()) as c:
        yield c


def email() -> str:
    return f"user-{uuid4().hex[:10]}@example.com"


def signup_body(side: str = "developer") -> dict[str, Any]:
    choices: dict[str, Any] = {
        "side": side,
        "accept_terms": True,
        "consents": {"marketing": False, "reminders": True},
        "consents_version": consents_version(get_settings()),
    }
    if side == "org":
        choices["org"] = {"legal_name": "Telco A (fixture)", "kind": "company"}
    return {"signup": choices}


# ------------------------------------------------------------------ provider fakes and the round trip


@dataclass(frozen=True)
class Person:
    """Someone at the provider: a stable subject, a primary address and whether the provider verified it."""

    subject: str
    email: str
    verified: bool = True


def person(address: str | None = None, *, verified: bool = True) -> Person:
    return Person(str(uuid4().int % 10**9 + 1), address or email(), verified)


def id_token(**claims: Any) -> str:
    def part(value: Any) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256'})}.{part(claims)}.c2ln"


def fake_github(router: respx.MockRouter, who: Person, emails: list[Any] | None = None) -> respx.Route:
    token = router.post(GITHUB_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "gho_fake", "token_type": "bearer", "scope": "x"})
    )
    user = {"id": int(who.subject), "login": f"dev{who.subject}", "name": "Octo Dev"}
    router.get(GITHUB_USER).mock(return_value=httpx.Response(200, json=user))
    if emails is None:
        emails = [{"email": who.email, "primary": True, "verified": who.verified, "visibility": "private"}]
    router.get(GITHUB_EMAILS).mock(return_value=httpx.Response(200, json=emails))
    return token


def fake_google(router: respx.MockRouter, who: Person, nonce: str) -> respx.Route:
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": GOOGLE_CLIENT,
        "azp": GOOGLE_CLIENT,
        "sub": who.subject,
        "email": who.email,
        "email_verified": who.verified,
        "name": "Google Person",
        "nonce": nonce,
        "iat": now,
        "exp": now + 3600,
    }
    return router.post(GOOGLE_TOKEN).mock(return_value=httpx.Response(200, json={"id_token": id_token(**claims)}))


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}


async def start(
    client: httpx.AsyncClient, provider: str = "github", intent: str = "login", **body: Any
) -> dict[str, str]:
    response = await client.post(f"/api/auth/oauth/{provider}/start", json={"intent": intent, **body})
    assert response.status_code == 200, response.text
    return query(response.json()["authorize_url"])


async def round_trip(
    client: httpx.AsyncClient, who: Person, *, provider: str = "github", intent: str = "login", **body: Any
) -> httpx.Response:
    """Start a flow, let the fake provider answer and return the callback response (a redirect)."""
    params = await start(client, provider, intent, **body)
    with respx.mock(assert_all_called=False) as router:
        if provider == "github":
            fake_github(router, who)
        else:
            fake_google(router, who, params["nonce"])
        response = await client.get(
            f"/api/auth/oauth/{provider}/callback", params={"code": f"code-{uuid4().hex}", "state": params["state"]}
        )
    assert response.status_code == 302, response.text
    return response


def landing(response: httpx.Response) -> tuple[str, dict[str, str]]:
    location = response.headers["location"]
    assert location.startswith(WEB + "/"), location
    return urlsplit(location).path, query(location)


def cookie_names(response: httpx.Response) -> set[str]:
    return {header.split("=", 1)[0] for header in response.headers.get_list("set-cookie")}


def signed_in(response: httpx.Response) -> bool:
    return get_settings().session_cookie_name in {
        name for name in cookie_names(response) if not _deleted(response, name)
    }


def _deleted(response: httpx.Response, name: str) -> bool:
    header = next(h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}="))
    return "max-age=0" in header.lower() or header.startswith(f'{name}="";')


async def me(client: httpx.AsyncClient) -> dict[str, Any]:
    await refresh_csrf(client)
    response = await client.get("/api/auth/me")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def linked(client: httpx.AsyncClient) -> list[str]:
    response = await client.get("/api/me/identities")
    assert response.status_code == 200, response.text
    return [row["provider"] for row in response.json()]


def last_link(client: httpx.AsyncClient, to: str) -> str:
    message = [m for m in outbox(client).outbox if m.to == to][-1]
    match = re.search(r"/auth/link#token=([A-Za-z0-9_\-]+)", message.text)
    assert match, message.text
    return match.group(1)


async def email_account(client: httpx.AsyncClient, address: str) -> None:
    """A verified account made through the email form, signed in on ``client``."""
    body = {
        "email": address,
        "password": PASSWORD,
        "display_name": "Email User",
        "side": "developer",
        "accept_terms": True,
    }
    assert (await client.post("/api/auth/signup", json=body)).status_code == 202
    consumed = await client.post("/api/auth/magic-link/consume", json={"token": last_link(client, address)})
    assert consumed.status_code == 200, consumed.text
    await refresh_csrf(client)


async def identity_rows(owner_engine: AsyncEngine, address: str) -> list[str]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT i.provider::text FROM auth_identities i JOIN users u ON u.id = i.user_id WHERE u.email = :e"),
            {"e": address},
        )
        return [str(row[0]) for row in rows]


async def audit_trail(owner_engine: AsyncEngine, user_id: str) -> list[tuple[str, dict[str, Any]]]:
    async with owner_engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT action, payload FROM audit_events WHERE actor_user_id = :u ORDER BY seq"), {"u": UUID(user_id)}
        )
        return [(str(action), dict(payload)) for action, payload in rows]


# ------------------------------------------------------------------ configuration


async def test_only_configured_providers_are_offered(app_engine: AsyncEngine, client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/auth/oauth/providers")).json() == {"providers": ["github", "google"]}
    github_only = oauth_settings().model_copy(update={"google_client_id": None, "google_client_secret": None})
    async with make_client(app_engine, settings=github_only) as c:
        assert (await c.get("/api/auth/oauth/providers")).json() == {"providers": ["github"]}
        assert (await c.post("/api/auth/oauth/google/start", json={})).status_code == 404
        assert (await c.get("/api/auth/oauth/google/callback", params={"code": "x", "state": "y"})).status_code == 404
    nothing = oauth_settings().model_copy(update=dict.fromkeys(OAUTH_FIELDS))
    async with make_client(app_engine, settings=nothing) as unconfigured:
        assert (await unconfigured.get("/api/auth/oauth/providers")).json() == {"providers": []}
        assert (await unconfigured.post("/api/auth/oauth/github/start", json={})).status_code == 404
    assert (await client.post("/api/auth/oauth/gitlab/start", json={})).status_code == 404


async def test_the_flow_cookie_is_host_only_http_only_and_short_lived(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/auth/oauth/github/start", json={"intent": "login"})
    header = next(h for h in response.headers.get_list("set-cookie") if h.startswith("__Host-bridge_oauth="))
    lowered = header.lower()
    for flag in ("httponly", "secure", "samesite=lax", "path=/", "max-age=600"):
        assert flag in lowered, header
    assert "domain=" not in lowered


# ------------------------------------------------------------------ signup and sign-in


async def test_a_new_developer_signs_up_with_github(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    who = person()
    response = await round_trip(client, who, intent="signup", return_to="/dev", **signup_body())
    assert landing(response) == ("/dev", {})
    assert signed_in(response)
    assert _deleted(response, "__Host-bridge_oauth")  # the flow cookie is spent on every callback
    profile = await me(client)
    assert profile["user"]["email"] == who.email
    assert profile["user"]["email_verified"] is True
    assert profile["user"]["password_set"] is False
    assert profile["user"]["display_name"] == "Octo Dev"
    assert profile["side"] == "developer"
    assert await linked(client) == ["github"]
    consents = {c["purpose"]: c["granted"] for c in (await client.get("/api/me/consents")).json()}
    assert (consents["reminders"], consents["marketing"]) == (True, False)
    trail = dict(await audit_trail(owner_engine, profile["user"]["id"]))
    assert trail["auth.signup"]["method"] == "github"
    assert trail["auth.identity_linked"] == {"provider": "github"}
    assert trail["auth.oauth_login"] == {"provider": "github", "via": "signup"}
    assert who.email not in json.dumps(trail)


async def test_a_new_organisation_owner_signs_up_with_google(client: httpx.AsyncClient) -> None:
    who = person()
    response = await round_trip(client, who, provider="google", intent="signup", **signup_body("org"))
    assert landing(response) == ("/dev", {})
    profile = await me(client)
    assert profile["side"] == "org"
    assert profile["mfa"]["required"] is True  # org owners enrol TOTP next, as after an email signup
    assert await linked(client) == ["google"]


async def test_signup_needs_the_terms_and_current_consents(client: httpx.AsyncClient) -> None:
    async def refused(body: dict[str, Any]) -> tuple[int, str]:
        response = await client.post("/api/auth/oauth/github/start", json={"intent": "signup", **body})
        return response.status_code, response.json()["detail"]["code"]

    assert await refused({}) == (422, "terms_not_accepted")
    no_terms = signup_body()
    no_terms["signup"]["accept_terms"] = False
    assert await refused(no_terms) == (422, "terms_not_accepted")
    no_org = signup_body()
    no_org["signup"]["side"] = "org"
    assert await refused(no_org) == (422, "org_details_required")
    stale = signup_body()
    stale["signup"]["consents_version"] = "an-old-version"
    assert await refused(stale) == (409, "consent_text_changed")
    unversioned = signup_body()
    del unversioned["signup"]["consents_version"]
    assert await refused(unversioned) == (422, "consents_version_required")


async def test_a_linked_account_signs_in_again(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    who = person()
    await round_trip(client, who, intent="signup", **signup_body())
    user_id = (await me(client))["user"]["id"]
    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    response = await round_trip(client, who, intent="login", return_to="/settings/security")
    assert landing(response) == ("/settings/security", {})
    assert (await me(client))["user"]["id"] == user_id
    assert await identity_rows(owner_engine, who.email) == ["github"]
    assert ("auth.oauth_login", {"provider": "github", "via": "identity"}) in await audit_trail(owner_engine, user_id)


async def test_login_without_an_account_goes_to_signup(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    who = person()
    response = await round_trip(client, who, intent="login")
    assert landing(response) == ("/signup", {"oauth_error": "oauth_no_account", "provider": "github"})
    assert not signed_in(response)
    async with owner_engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM users WHERE email = :e"), {"e": who.email})
    assert count == 0  # terms and consents are chosen on the signup page first


def added_notices(client: httpx.AsyncClient, address: str, label: str = "Google") -> int:
    return len([m for m in outbox(client).outbox if m.to == address and f"{label} sign-in was added" in m.text])


async def enrol_totp(client: httpx.AsyncClient, password: str | None = PASSWORD) -> str:
    body = {"password": password} if password else {}
    secret = str((await client.post("/api/auth/totp/enrol", json=body)).json()["secret"])
    confirmed = await client.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, now_counter())})
    assert confirmed.status_code == 200, confirmed.text
    return secret


async def test_a_verified_provider_address_signs_in_without_linking(
    client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    """Orchestrator decision (fix round 1): a verified provider address signs in like an emailed link would and
    attaches nothing; the identity joins the account only through an explicit link from settings."""
    address = email()
    await email_account(client, address)
    user_id = (await me(client))["user"]["id"]
    who = person(address)
    for intent, body in (("login", {}), ("signup", signup_body())):
        response = await round_trip(other, who, provider="google", intent=intent, **body)
        assert landing(response) == ("/dev", {})
        assert (await me(other))["user"]["id"] == user_id
    assert await identity_rows(owner_engine, address) == []
    assert added_notices(other, address) == 0
    trail = await audit_trail(owner_engine, user_id)
    assert ("auth.oauth_login", {"provider": "google", "via": "email"}) in trail
    assert "auth.identity_linked" not in {action for action, _ in trail}
    # The owner can still add the same Google account explicitly, from settings.
    response = await round_trip(client, who, provider="google", intent="link")
    assert landing(response) == ("/settings/security", {"linked": "google"})
    assert await identity_rows(owner_engine, address) == ["google"]
    assert added_notices(client, address) == 1


async def test_a_totp_account_reached_by_its_address_gets_no_identity(
    client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    """The second factor comes before anything else: an abandoned MFA challenge leaves no identity behind, and a
    completed one does not attach the identity either."""
    address = email()
    await email_account(client, address)
    secret = await enrol_totp(client)
    who = person(address)
    abandoned = await round_trip(other, who, provider="google", intent="login")
    assert landing(abandoned) == ("/auth/mfa", {})
    assert signed_in(abandoned)
    assert await identity_rows(owner_engine, address) == []
    await refresh_csrf(other)
    link = await other.post("/api/auth/oauth/google/start", json={"intent": "link"})
    assert refusal(link) == (401, "mfa_required")
    verified = await other.post("/api/auth/mfa/verify", json={"code": totp.code_at(secret, now_counter() + 1)})
    assert verified.status_code == 200, verified.text
    assert await identity_rows(owner_engine, address) == []
    assert added_notices(other, address) == 0
    # An explicit link from settings, with the fresh second factor, still works.
    response = await round_trip(client, who, provider="google", intent="link")
    assert landing(response) == ("/settings/security", {"linked": "google"})
    assert await identity_rows(owner_engine, address) == ["google"]
    assert added_notices(client, address) == 1


# ------------------------------------------------------------------ account pre-hijacking


async def test_an_unverified_provider_address_never_reaches_an_existing_account(
    client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    victim = email()
    await email_account(client, victim)
    attacker = person(victim, verified=False)  # the attacker's GitHub claims the victim's address, unverified
    login = await round_trip(other, attacker, intent="login")
    assert landing(login) == ("/login", {"oauth_error": "oauth_email_unverified", "provider": "github"})
    assert not signed_in(login)
    signup = await round_trip(other, attacker, intent="signup", **signup_body())
    assert landing(signup) == ("/signup/check-email", {})
    assert not signed_in(signup)
    assert await identity_rows(owner_engine, victim) == []
    await refresh_csrf(other)
    assert (await other.get("/api/auth/me")).status_code == 401
    sent = [m for m in outbox(other).outbox if m.to == victim]
    assert len(sent) == 1
    assert "sign-in link" in sent[0].subject  # only the owner's inbox gets a way in


async def test_an_unverified_provider_address_gets_the_same_answer_with_or_without_an_account(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    taken = email()
    await email_account(client, taken)
    answers = []
    for address in (taken, email()):
        response = await round_trip(other, person(address, verified=False), intent="signup", **signup_body())
        answers.append((landing(response), sorted(cookie_names(response))))
    assert answers[0] == answers[1]


async def test_a_verified_provider_address_does_not_link_an_unverified_account(
    client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    victim = email()
    body = {"email": victim, "password": "attacker chose this", "display_name": "X", "side": "developer"}
    assert (await other.post("/api/auth/signup", json={**body, "accept_terms": True})).status_code == 202
    response = await round_trip(client, person(victim), provider="google", intent="login")
    assert landing(response) == ("/signup/check-email", {})
    assert not signed_in(response)
    assert await identity_rows(owner_engine, victim) == []
    # The owner opens the emailed link in their own browser: the attacker's password does not survive it.
    consumed = await client.post("/api/auth/magic-link/consume", json={"token": last_link(client, victim)})
    assert consumed.json()["user"]["password_set"] is False
    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    again = await round_trip(client, person(victim), provider="google", intent="login")
    assert landing(again) == ("/dev", {})  # both sides verified now: signed in, nothing attached
    assert await identity_rows(owner_engine, victim) == []


async def test_signup_with_an_unverified_provider_address_needs_email_verification(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    who = person(verified=False)
    response = await round_trip(client, who, intent="signup", **signup_body())
    assert landing(response) == ("/signup/check-email", {})
    assert not signed_in(response)
    assert "__Host-bridge_signup" in cookie_names(response)
    assert await identity_rows(owner_engine, who.email) == ["github"]
    early = await round_trip(client, who, intent="login")  # not before the address is confirmed
    assert landing(early) == ("/signup/check-email", {})
    assert not signed_in(early)
    consumed = await client.post("/api/auth/magic-link/consume", json={"token": last_link(client, who.email)})
    assert consumed.status_code == 200
    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    later = await round_trip(client, who, intent="login")  # confirmed in the signup browser: the identity stays
    assert landing(later) == ("/dev", {})
    assert (await me(client))["user"]["email_verified"] is True


async def test_an_identity_attached_before_verification_is_dropped_when_verified_elsewhere(
    client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    victim = email()
    attacker = person(victim, verified=False)
    await round_trip(other, attacker, intent="signup", **signup_body())  # the attacker's browser
    assert await identity_rows(owner_engine, victim) == ["github"]
    link = last_link(other, victim)  # delivered to the victim, opened in the victim's browser
    assert (await client.post("/api/auth/magic-link/consume", json={"token": link})).status_code == 200
    assert await identity_rows(owner_engine, victim) == []
    await refresh_csrf(other)
    retry = await round_trip(other, attacker, intent="login")
    assert landing(retry) == ("/login", {"oauth_error": "oauth_email_unverified", "provider": "github"})
    assert not signed_in(retry)


async def test_a_suspended_account_cannot_sign_in(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    who = person()
    await round_trip(client, who, intent="signup", **signup_body())
    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET status = 'suspended' WHERE email = :e"), {"e": who.email})
    response = await round_trip(client, who, intent="login")
    assert landing(response) == ("/login", {"oauth_error": "oauth_failed", "provider": "github"})
    assert not signed_in(response)


async def test_a_provider_without_a_primary_address_cannot_sign_up(client: httpx.AsyncClient) -> None:
    params = await start(client, "github", "signup", **signup_body())
    with respx.mock(assert_all_called=True) as router:
        fake_github(router, person(), emails=[{"email": email(), "primary": False, "verified": True}])
        response = await client.get("/api/auth/oauth/github/callback", params={"code": "c", "state": params["state"]})
    assert landing(response) == ("/signup", {"oauth_error": "oauth_no_email", "provider": "github"})
    assert not signed_in(response)


# ------------------------------------------------------------------ linking from settings


def now_counter() -> int:
    return int(time.time() // 30)


async def age_second_factor(owner_engine: AsyncEngine, address: str, hours: int) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE sessions SET mfa_verified_at = now() - make_interval(hours => :h) "
                "WHERE user_id = (SELECT id FROM users WHERE email = :e) AND revoked_at IS NULL"
            ),
            {"h": hours, "e": address},
        )


def refusal(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["detail"]["code"]


async def test_linking_from_settings(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    address = email()
    await email_account(client, address)
    user_id = (await me(client))["user"]["id"]
    who = person()  # a GitHub account with a different address: linking does not depend on the address
    response = await round_trip(client, who, intent="link")
    assert landing(response) == ("/settings/security", {"linked": "github"})
    assert not signed_in(response)  # the same session carries on
    assert await linked(client) == ["github"]
    assert [m for m in outbox(client).outbox if m.to == address and "GitHub sign-in was added" in m.text]
    assert ("auth.identity_linked", {"provider": "github"}) in await audit_trail(owner_engine, user_id)
    again = await round_trip(client, who, intent="link")  # linking the same identity again changes nothing
    assert landing(again) == ("/settings/security", {"linked": "github"})
    assert await linked(client) == ["github"]


async def test_linking_needs_a_signed_in_session(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/auth/oauth/github/start", json={"intent": "link"})
    assert refusal(response) == (401, "unauthenticated")


async def test_linking_needs_a_recent_sign_in_without_totp(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await email_account(client, email())
    later = datetime.now(UTC) + timedelta(minutes=16)
    monkeypatch.setattr(bridge.clock, "utcnow", lambda: later)
    response = await client.post("/api/auth/oauth/github/start", json={"intent": "link"})
    assert refusal(response) == (403, "recent_sign_in_required")


async def test_linking_and_unlinking_need_a_fresh_second_factor_with_totp(
    client: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    address = email()
    await email_account(client, address)
    secret = str((await client.post("/api/auth/totp/enrol", json={"password": PASSWORD})).json()["secret"])
    confirmed = await client.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, now_counter())})
    assert confirmed.status_code == 200
    await age_second_factor(owner_engine, address, 13)
    stale = await client.post("/api/auth/oauth/github/start", json={"intent": "link"})
    assert refusal(stale) == (403, "step_up_required")
    await age_second_factor(owner_engine, address, 0)
    response = await round_trip(client, person(), intent="link")
    assert landing(response) == ("/settings/security", {"linked": "github"})
    identity_id = (await client.get("/api/me/identities")).json()[0]["id"]
    await age_second_factor(owner_engine, address, 13)
    assert refusal(await client.delete(f"/api/auth/identities/{identity_id}")) == (403, "step_up_required")
    await age_second_factor(owner_engine, address, 0)
    assert (await client.delete(f"/api/auth/identities/{identity_id}")).status_code == 204


async def test_a_pending_second_factor_cannot_link(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    address = email()
    await email_account(client, address)
    async with owner_engine.begin() as conn:
        await conn.execute(
            text("UPDATE sessions SET mfa_pending = true WHERE user_id = (SELECT id FROM users WHERE email = :e)"),
            {"e": address},
        )
    response = await client.post("/api/auth/oauth/github/start", json={"intent": "link"})
    assert refusal(response) == (401, "mfa_required")


async def test_an_identity_owned_by_another_account_is_refused(
    client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    owner = person()
    await round_trip(client, owner, intent="signup", **signup_body())
    await email_account(other, email())
    response = await round_trip(other, owner, intent="link")
    assert landing(response) == ("/settings/security", {"oauth_error": "identity_in_use", "provider": "github"})
    assert await linked(other) == []
    assert await identity_rows(owner_engine, owner.email) == ["github"]


async def test_an_account_holds_one_identity_per_provider(client: httpx.AsyncClient, other: httpx.AsyncClient) -> None:
    address = email()
    await email_account(client, address)
    assert landing(await round_trip(client, person(), intent="link")) == ("/settings/security", {"linked": "github"})
    second = await round_trip(client, person(), intent="link")
    assert landing(second) == ("/settings/security", {"oauth_error": "provider_already_linked", "provider": "github"})
    # Another GitHub account with the same verified address cannot sign in by the address either.
    sign_in = await round_trip(other, person(address), intent="login")
    assert landing(sign_in) == ("/login", {"oauth_error": "provider_already_linked", "provider": "github"})
    assert not signed_in(sign_in)
    assert await linked(client) == ["github"]


async def test_a_link_finished_in_another_session_is_refused(client: httpx.AsyncClient) -> None:
    await email_account(client, email())
    params = await start(client, "github", "link")
    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    await email_account(client, email())  # someone else signs in on this browser before the provider answers
    with respx.mock(assert_all_called=False) as router:
        fake_github(router, person())
        response = await client.get("/api/auth/oauth/github/callback", params={"code": "c", "state": params["state"]})
    assert landing(response) == ("/login", {"oauth_error": "oauth_session", "provider": "github"})
    assert await linked(client) == []


# ------------------------------------------------------------------ state, replay, expiry and provider errors


async def test_a_state_mismatch_is_refused_before_any_provider_call(client: httpx.AsyncClient) -> None:
    await start(client, "github", "login")
    with respx.mock(assert_all_called=False) as router:
        token = fake_github(router, person())
        response = await client.get("/api/auth/oauth/github/callback", params={"code": "c", "state": "forged-state"})
    assert landing(response) == ("/login", {"oauth_error": "oauth_state", "provider": "github"})
    assert token.call_count == 0
    assert _deleted(response, "__Host-bridge_oauth")


async def test_a_code_from_another_browser_is_refused(client: httpx.AsyncClient, other: httpx.AsyncClient) -> None:
    """Login CSRF: an attacker's code and state, delivered to a victim's browser that holds no matching flow."""
    params = await start(client, "github", "login")
    with respx.mock(assert_all_called=False) as router:
        token = fake_github(router, person())
        response = await other.get("/api/auth/oauth/github/callback", params={"code": "c", "state": params["state"]})
    assert landing(response) == ("/login", {"oauth_error": "oauth_state", "provider": "github"})
    assert token.call_count == 0
    assert not signed_in(response)


async def test_a_replayed_callback_is_refused(client: httpx.AsyncClient, other: httpx.AsyncClient) -> None:
    who = person()
    await round_trip(client, who, intent="signup", **signup_body())
    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    params = await start(client, "github", "login")
    flow_cookie = client.cookies.get("__Host-bridge_oauth")
    assert flow_cookie
    callback = {"code": "code-used-once", "state": params["state"]}
    with respx.mock(assert_all_called=False) as router:
        fake_github(router, who)
        first = await client.get("/api/auth/oauth/github/callback", params=callback)
        assert landing(first) == ("/dev", {})
        replay = await client.get("/api/auth/oauth/github/callback", params=callback)  # the cookie is spent
    assert landing(replay) == ("/login", {"oauth_error": "oauth_state", "provider": "github"})
    # With a stolen copy of the cookie, the provider refuses the spent code (single use, PKCE-bound).
    other.cookies.set("__Host-bridge_oauth", flow_cookie)
    with respx.mock(assert_all_called=True) as router:
        router.post(GITHUB_TOKEN).mock(return_value=httpx.Response(200, json={"error": "bad_verification_code"}))
        stolen = await other.get("/api/auth/oauth/github/callback", params=callback)
    assert landing(stolen) == ("/login", {"oauth_error": "oauth_failed", "provider": "github"})
    assert not signed_in(stolen)


async def test_an_expired_flow_is_refused(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    params = await start(client, "github", "login")
    later = datetime.now(UTC) + timedelta(minutes=11)
    monkeypatch.setattr(bridge.clock, "utcnow", lambda: later)
    with respx.mock(assert_all_called=False) as router:
        token = fake_github(router, person())
        response = await client.get("/api/auth/oauth/github/callback", params={"code": "c", "state": params["state"]})
    assert landing(response) == ("/login", {"oauth_error": "oauth_state", "provider": "github"})
    assert token.call_count == 0


async def test_a_flow_for_one_provider_cannot_finish_at_another(client: httpx.AsyncClient) -> None:
    params = await start(client, "github", "login")
    with respx.mock(assert_all_called=False) as router:
        token = fake_google(router, person(), params.get("nonce", ""))
        response = await client.get("/api/auth/oauth/google/callback", params={"code": "c", "state": params["state"]})
    assert landing(response) == ("/login", {"oauth_error": "oauth_state", "provider": "google"})
    assert token.call_count == 0


async def test_provider_errors_are_never_shown(client: httpx.AsyncClient) -> None:
    params = await start(client, "google", "signup", **signup_body())
    denied = await client.get(
        "/api/auth/oauth/google/callback",
        params={"error": "access_denied", "error_description": "<script>alert(1)</script>", "state": params["state"]},
    )
    assert landing(denied) == ("/signup", {"oauth_error": "oauth_cancelled", "provider": "google"})
    assert "script" not in denied.headers["location"]
    assert "access_denied" not in denied.headers["location"]
    assert denied.headers["referrer-policy"] == "no-referrer"
    params = await start(client, "google", "login")
    with respx.mock(assert_all_called=True) as router:
        router.post(GOOGLE_TOKEN).mock(return_value=httpx.Response(500, text="internal detail from the provider"))
        failed = await client.get("/api/auth/oauth/google/callback", params={"code": "c", "state": params["state"]})
    assert landing(failed) == ("/login", {"oauth_error": "oauth_failed", "provider": "google"})
    params = await start(client, "google", "login")
    missing = await client.get("/api/auth/oauth/google/callback", params={"state": params["state"]})
    assert landing(missing) == ("/login", {"oauth_error": "oauth_failed", "provider": "google"})


# ------------------------------------------------------------------ second factor, unlinking, edge cases


async def test_accounts_with_totp_sign_in_pending_the_second_factor(client: httpx.AsyncClient) -> None:
    who = person()
    await round_trip(client, who, intent="signup", **signup_body())
    await refresh_csrf(client)
    secret = str((await client.post("/api/auth/totp/enrol", json={})).json()["secret"])  # password-less, recent
    assert (
        await client.post("/api/auth/totp/confirm", json={"code": totp.code_at(secret, now_counter())})
    ).status_code == 200
    await client.post("/api/auth/logout")
    await refresh_csrf(client)
    response = await round_trip(client, who, intent="login")
    assert landing(response) == ("/auth/mfa", {})
    assert signed_in(response)
    assert (await me(client))["side"] == "pending"
    verified = await client.post("/api/auth/mfa/verify", json={"code": totp.code_at(secret, now_counter() + 1)})
    assert verified.status_code == 200, verified.text


async def test_unlinking(client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    who = person()
    await round_trip(client, who, intent="signup", **signup_body())
    user_id = (await me(client))["user"]["id"]
    identity_id = (await client.get("/api/me/identities")).json()[0]["id"]
    url = f"/api/auth/identities/{identity_id}"
    await email_account(other, email())
    assert refusal(await other.delete(url)) == (404, "not_found")  # someone else's identity does not exist for them
    assert refusal(await client.delete(url, headers={"X-CSRF-Token": "forged"})) == (403, "csrf_failed")
    # A GitHub-only account can still sign in with an emailed link to its verified address.
    assert (await client.delete(url)).status_code == 204
    assert await linked(client) == []
    assert [m for m in outbox(client).outbox if m.to == who.email and "GitHub sign-in was removed" in m.text]
    assert ("auth.identity_unlinked", {"provider": "github"}) in await audit_trail(owner_engine, user_id)
    assert refusal(await client.delete(url)) == (404, "not_found")


async def test_the_last_way_to_sign_in_cannot_be_unlinked(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    who = person()
    await round_trip(client, who, intent="signup", **signup_body())
    await refresh_csrf(client)
    identity_id = (await client.get("/api/me/identities")).json()[0]["id"]
    async with owner_engine.begin() as conn:  # no password, no other identity and no verified address to email
        await conn.execute(text("UPDATE users SET email_verified_at = NULL WHERE email = :e"), {"e": who.email})
    response = await client.delete(f"/api/auth/identities/{identity_id}")
    assert refusal(response) == (409, "last_sign_in_method")


async def test_a_throttled_oauth_signup_creates_nothing(
    client: httpx.AsyncClient, owner_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def throttled(*_args: object) -> bool:
        return False

    monkeypatch.setattr(service, "allow_email", throttled)
    who = person(verified=False)
    response = await round_trip(client, who, intent="signup", **signup_body())
    assert landing(response) == ("/signup/check-email", {})
    async with owner_engine.connect() as conn:
        assert await conn.scalar(text("SELECT count(*) FROM users WHERE email = :e"), {"e": who.email}) == 0


@pytest.mark.parametrize("verified", [True, False])
async def test_consent_wording_changed_during_the_flow(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, verified: bool
) -> None:
    params = await start(client, "github", "signup", **signup_body())
    monkeypatch.setattr(identities, "consents_version", lambda _settings: "a-newer-version")
    with respx.mock(assert_all_called=False) as router:
        fake_github(router, person(verified=verified))
        response = await client.get("/api/auth/oauth/github/callback", params={"code": "c", "state": params["state"]})
    assert landing(response) == ("/signup", {"oauth_error": "consent_text_changed", "provider": "github"})


@pytest.mark.parametrize(("verified", "page"), [(True, "/signup"), (False, "/signup/check-email")])
async def test_an_address_taken_during_the_flow_creates_nothing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, verified: bool, page: str
) -> None:
    async def taken(*_args: object, **_kwargs: object) -> None:
        return None  # what create_account answers when a concurrent signup took the address

    monkeypatch.setattr(service, "create_account", taken)
    response = await round_trip(client, person(verified=verified), intent="signup", **signup_body())
    assert landing(response)[0] == page
    assert not signed_in(response)


async def test_a_callback_without_state_is_refused(client: httpx.AsyncClient) -> None:
    await start(client, "github", "login")
    response = await client.get("/api/auth/oauth/github/callback", params={"code": "c"})
    assert landing(response) == ("/login", {"oauth_error": "oauth_state", "provider": "github"})


async def test_a_suspended_account_is_not_reached_through_its_address(
    client: httpx.AsyncClient, other: httpx.AsyncClient, owner_engine: AsyncEngine
) -> None:
    address = email()
    await email_account(client, address)
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE users SET status = 'suspended' WHERE email = :e"), {"e": address})
    response = await round_trip(other, person(address), provider="google", intent="login")
    assert landing(response) == ("/login", {"oauth_error": "oauth_failed", "provider": "google"})
    assert await identity_rows(owner_engine, address) == []


async def test_a_throttled_resend_to_an_unverified_identity_sends_nothing(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    who = person(verified=False)
    await round_trip(client, who, intent="signup", **signup_body())
    sent = len([m for m in outbox(client).outbox if m.to == who.email])

    async def throttled(*_args: object) -> bool:
        return False

    monkeypatch.setattr(service, "allow_email", throttled)
    response = await round_trip(client, who, intent="login")
    assert landing(response) == ("/signup/check-email", {})
    assert len([m for m in outbox(client).outbox if m.to == who.email]) == sent


def hide_identities(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a concurrent request that attached the identity after this request looked it up."""

    async def not_found(*_args: object) -> None:
        return None

    monkeypatch.setattr(identities, "_identity", not_found)


@pytest.mark.parametrize("intent", ["link", "login", "signup"])
async def test_an_identity_attached_concurrently_is_not_attached_twice(
    client: httpx.AsyncClient,
    other: httpx.AsyncClient,
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    intent: str,
) -> None:
    taken = person()
    await round_trip(client, taken, intent="signup", **signup_body())  # the identity belongs to this account
    address = email()
    if intent != "signup":
        await email_account(other, address)
    hide_identities(monkeypatch)
    raced = Person(taken.subject, address)  # the same provider account, now with another verified address
    body = signup_body() if intent == "signup" else {}
    response = await round_trip(other, raced, intent=intent, **body)
    expected = {
        "link": ("/settings/security", {"oauth_error": "identity_in_use", "provider": "github"}),
        "login": ("/dev", {}),  # signed in by the verified address, which attaches nothing
        "signup": ("/signup", {"oauth_error": "oauth_failed", "provider": "github"}),
    }
    assert landing(response) == expected[intent]
    assert await identity_rows(owner_engine, taken.email) == ["github"]
    assert await identity_rows(owner_engine, address) == []
    async with owner_engine.connect() as conn:  # a signup that lost the race leaves no half-made account
        users = await conn.scalar(text("SELECT count(*) FROM users WHERE email = :e"), {"e": address})
    assert users == (0 if intent == "signup" else 1)
