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
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

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
    assert trail["auth.oauth_login"] == {"provider": "github"}
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


async def test_login_without_an_account_goes_to_signup(client: httpx.AsyncClient, owner_engine: AsyncEngine) -> None:
    who = person()
    response = await round_trip(client, who, intent="login")
    assert landing(response) == ("/signup", {"oauth_error": "oauth_no_account", "provider": "github"})
    assert not signed_in(response)
    async with owner_engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM users WHERE email = :e"), {"e": who.email})
    assert count == 0  # terms and consents are chosen on the signup page first


async def test_a_verified_provider_address_links_a_verified_account(
    client: httpx.AsyncClient, other: httpx.AsyncClient
) -> None:
    address = email()
    await email_account(client, address)
    user_id = (await me(client))["user"]["id"]
    response = await round_trip(other, person(address), provider="google", intent="login")
    assert landing(response) == ("/dev", {})
    assert (await me(other))["user"]["id"] == user_id
    assert await linked(other) == ["google"]
    notices = [m for m in outbox(other).outbox if m.to == address and "Google sign-in was added" in m.text]
    assert len(notices) == 1


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
    assert landing(again) == ("/dev", {})  # both sides verified now: linked and signed in


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
