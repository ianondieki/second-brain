"""REQ-AUTH-02: the OAuth protocol half (``bridge.auth.oauth``) against respx fakes only; no test reaches a provider.

PKCE (RFC 7636 S256), the sealed flow cookie (state, nonce, verifier; expiry and tampering), exact redirect URIs,
provider parsing (GitHub user + emails, Google ID-token claims), the verified-email rules and the redirect allow-list.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx
from pydantic import SecretStr, ValidationError

from bridge.auth import oauth
from bridge.auth.schemas import OAuthSignup, OAuthStartRequest
from bridge.config import Settings
from bridge.models.enums import AuthProvider

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
GOOGLE_CLIENT = "bridge-test.apps.googleusercontent.com"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("s" * 40),
        "data_encryption_key": SecretStr("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="),
        "recovery_code_pepper": SecretStr("p" * 40),
        "public_base_url": "https://bridge.test",
        "github_client_id": SecretStr("gh-client-id"),
        "github_client_secret": SecretStr("gh-client-secret"),
        "google_client_id": SecretStr(GOOGLE_CLIENT),
        "google_client_secret": SecretStr("google-client-secret"),
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


SETTINGS = make_settings()


def client(name: str = "github") -> oauth.Client:
    configured = oauth.configured(SETTINGS, name)
    assert configured is not None
    return configured


def flow(provider: AuthProvider = AuthProvider.GITHUB, **overrides: Any) -> oauth.Flow:
    made = oauth.new_flow(provider, "login", "/dev", now=NOW)
    return made.model_copy(update=overrides) if overrides else made


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(url).query, strict_parsing=True).items()}


# ------------------------------------------------------------------ PKCE


def test_pkce_s256_matches_the_rfc_7636_example() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"  # RFC 7636 appendix B
    assert oauth.challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_verifiers_are_long_random_and_unreserved() -> None:
    first, second = oauth.new_verifier(), oauth.new_verifier()
    assert first != second
    assert 43 <= len(first) <= 128
    assert set(first) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


def test_every_flow_gets_fresh_state_nonce_and_verifier() -> None:
    one, two = flow(), flow()
    assert len({one.state, two.state, one.nonce, two.nonce, one.verifier, two.verifier}) == 6
    assert len(one.state) >= 43
    assert one.expires == int((NOW + timedelta(minutes=10)).timestamp())


# ------------------------------------------------------------------ providers and redirect URIs


def test_providers_are_enabled_only_when_both_values_are_set() -> None:
    assert oauth.enabled(SETTINGS) == [AuthProvider.GITHUB, AuthProvider.GOOGLE]
    github_only = make_settings(google_client_id=None, google_client_secret=None)
    assert oauth.enabled(github_only) == [AuthProvider.GITHUB]
    blank = make_settings(github_client_id=SecretStr(" "), github_client_secret=SecretStr(""))
    assert oauth.enabled(blank) == [AuthProvider.GOOGLE]
    assert oauth.configured(blank, "github") is None
    assert oauth.enabled(make_settings(**dict.fromkeys(_ALL_OAUTH_FIELDS))) == []


_ALL_OAUTH_FIELDS = ("github_client_id", "github_client_secret", "google_client_id", "google_client_secret")


@pytest.mark.parametrize("name", ["gitlab", "GitHub", "", "github/../google"])
def test_unknown_providers_are_not_configured(name: str) -> None:
    assert oauth.configured(SETTINGS, name) is None


def test_the_client_secret_never_appears_in_repr() -> None:
    assert "gh-client-secret" not in repr(client("github"))


@pytest.mark.parametrize("base", ["https://bridge.test", "https://bridge.test/"])
def test_redirect_uris_are_exact(base: str) -> None:
    settings = make_settings(public_base_url=base)
    assert oauth.redirect_uri(settings, AuthProvider.GITHUB) == "https://bridge.test/api/auth/oauth/github/callback"
    assert oauth.redirect_uri(settings, AuthProvider.GOOGLE) == "https://bridge.test/api/auth/oauth/google/callback"


def test_github_authorize_url() -> None:
    started = flow()
    url = oauth.authorize_url(client("github"), started)
    parts = urlsplit(url)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "github.com", "/login/oauth/authorize")
    assert query(url) == {
        "client_id": "gh-client-id",
        "redirect_uri": "https://bridge.test/api/auth/oauth/github/callback",
        "scope": "read:user user:email",
        "state": started.state,
        "code_challenge": oauth.challenge(started.verifier),
        "code_challenge_method": "S256",
    }
    assert started.verifier not in url


def test_google_authorize_url_adds_the_oidc_nonce() -> None:
    started = flow(AuthProvider.GOOGLE)
    url = oauth.authorize_url(client("google"), started)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    params = query(url)
    assert params["scope"] == "openid email profile"
    assert params["response_type"] == "code"
    assert params["nonce"] == started.nonce
    assert params["code_challenge_method"] == "S256"
    assert params["redirect_uri"] == "https://bridge.test/api/auth/oauth/google/callback"


# ------------------------------------------------------------------ the sealed flow cookie


def test_the_flow_cookie_round_trips_and_hides_its_secrets() -> None:
    signup = OAuthSignup(side="developer", accept_terms=True, consents={"marketing": True}, consents_version="v1")
    started = oauth.new_flow(AuthProvider.GOOGLE, "signup", "/org", now=NOW, signup=signup)
    sealed = oauth.seal(SETTINGS, started)
    for secret in (started.state, started.nonce, started.verifier):
        assert secret not in sealed
    assert len(sealed) < oauth.MAX_COOKIE_CHARS
    assert oauth.unseal(SETTINGS, sealed, now=NOW) == started


def test_the_flow_cookie_expires_after_ten_minutes() -> None:
    sealed = oauth.seal(SETTINGS, flow())
    assert oauth.unseal(SETTINGS, sealed, now=NOW + timedelta(minutes=9, seconds=59)) is not None
    assert oauth.unseal(SETTINGS, sealed, now=NOW + timedelta(minutes=10)) is None


def test_a_tampered_flow_cookie_is_refused() -> None:
    sealed = oauth.seal(SETTINGS, flow())
    for index in (3, 10, len(sealed) // 2, len(sealed) - 1):
        swapped = "A" if sealed[index] != "A" else "B"
        assert oauth.unseal(SETTINGS, sealed[:index] + swapped + sealed[index + 1 :], now=NOW) is None


def test_a_flow_cookie_sealed_under_another_key_is_refused() -> None:
    other = make_settings(secret_key=SecretStr("o" * 40))
    assert oauth.unseal(SETTINGS, oauth.seal(other, flow()), now=NOW) is None


@pytest.mark.parametrize("value", [None, "", "v1.", "v2.AAAA", "v1.!!!!", "v1.AAAA", "v1." + "A" * 5000, "garbage"])
def test_malformed_flow_cookies_are_refused(value: str | None) -> None:
    assert oauth.unseal(SETTINGS, value, now=NOW) is None


# ------------------------------------------------------------------ redirect allow-list


@pytest.mark.parametrize("path", ["/dev", "/org", "/settings/security"])
def test_allowed_return_paths(path: str) -> None:
    assert OAuthStartRequest(return_to=path).return_to == path


@pytest.mark.parametrize(
    "path",
    [
        "//evil.example",
        "https://evil.example/dev",
        "/dev/../admin",
        "/dev?next=//evil",
        "javascript:alert(1)",
        "/login",
    ],
)
def test_other_return_paths_are_refused(path: str) -> None:
    with pytest.raises(ValidationError):
        OAuthStartRequest(return_to=path)


def test_web_urls_are_built_only_for_known_pages() -> None:
    url = oauth.web_url(SETTINGS, "/login", {"oauth_error": "oauth_state", "provider": "github"})
    assert url == "https://bridge.test/login?oauth_error=oauth_state&provider=github"
    assert oauth.web_url(SETTINGS, "/auth/mfa") == "https://bridge.test/auth/mfa"
    for path in ("https://evil.example", "//evil.example", "/admin", "/dev/"):
        with pytest.raises(ValueError, match="not a web path"):
            oauth.web_url(SETTINGS, path)


# ------------------------------------------------------------------ GitHub identity


def github_user(**overrides: Any) -> dict[str, Any]:
    return {"id": 583231, "login": "octocat", "name": "The Octocat", **overrides}


def github_emails(email: str = "Octo@Example.com", *, verified: bool = True, primary: bool = True) -> list[Any]:
    return [
        {"email": "other@example.org", "primary": False, "verified": True, "visibility": None},
        {"email": email, "primary": primary, "verified": verified, "visibility": "private"},
    ]


def test_github_primary_verified_email() -> None:
    identity = oauth.parse_github(github_user(), github_emails())
    assert identity.provider is AuthProvider.GITHUB
    assert identity.subject == "583231"
    assert identity.email == "octo@example.com"
    assert identity.email_verified is True
    assert identity.display_name == "The Octocat"
    assert "octo@example.com" not in repr(identity)


def test_github_unverified_primary_email_is_not_verified() -> None:
    identity = oauth.parse_github(github_user(), github_emails(verified=False))
    assert identity.email == "octo@example.com"
    assert identity.email_verified is False


def test_github_without_a_primary_email_has_no_email() -> None:
    """Only the primary address counts; a verified secondary one is never used to find an account."""
    identity = oauth.parse_github(github_user(), github_emails(primary=False))
    assert identity.email is None
    assert identity.email_verified is False


@pytest.mark.parametrize("address", ["not an address", "=?utf-8?q?x?=@example.com", 42, None])
def test_github_unusable_email_counts_as_none(address: object) -> None:
    emails = [{"email": address, "primary": True, "verified": True}]
    identity = oauth.parse_github(github_user(), emails)
    assert (identity.email, identity.email_verified) == (None, False)


def test_github_display_name_falls_back_to_login_and_is_cleaned() -> None:
    assert oauth.parse_github(github_user(name=None), []).display_name == "octocat"
    assert oauth.parse_github(github_user(name="  Ada‮\x00 Lovelace\n "), []).display_name == "Ada Lovelace"
    assert oauth.parse_github(github_user(name="x" * 500), []).display_name == "x" * 120
    assert oauth.parse_github(github_user(name="\x00", login=None), []).display_name is None


@pytest.mark.parametrize("user_id", [None, "583231", True, 0, -1, 1.5])
def test_github_user_ids_must_be_positive_integers(user_id: object) -> None:
    with pytest.raises(oauth.ProviderError, match="user"):
        oauth.parse_github(github_user(id=user_id), github_emails())


def test_github_unexpected_shapes_are_provider_errors() -> None:
    with pytest.raises(oauth.ProviderError, match="user"):
        oauth.parse_github(["not", "a", "dict"], github_emails())
    with pytest.raises(oauth.ProviderError, match="emails"):
        oauth.parse_github(github_user(), {"email": "x@example.com"})


# ------------------------------------------------------------------ Google ID token


def id_token(**claims: Any) -> str:
    def part(value: Any) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'RS256', 'kid': 'k1'})}.{part(claims)}.c2lnbmF0dXJl"


def google_claims(flow_nonce: str, /, **overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "iss": "https://accounts.google.com",
        "aud": GOOGLE_CLIENT,
        "azp": GOOGLE_CLIENT,
        "sub": "110169484474386276334",
        "email": "Person@Gmail.com",
        "email_verified": True,
        "name": "A Person",
        "nonce": flow_nonce,
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(hours=1)).timestamp()),
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not _DROP}


_DROP = object()


def parse_google(**overrides: Any) -> oauth.ProviderIdentity:
    token = id_token(**google_claims("n-123", **overrides))
    return oauth.parse_google_id_token(token, client_id=GOOGLE_CLIENT, nonce="n-123", now=NOW)


def test_google_id_token_claims() -> None:
    identity = parse_google()
    assert identity.provider is AuthProvider.GOOGLE
    assert identity.subject == "110169484474386276334"
    assert (identity.email, identity.email_verified, identity.display_name) == ("person@gmail.com", True, "A Person")
    assert parse_google(iss="accounts.google.com").subject  # both documented issuer spellings
    assert parse_google(aud=[GOOGLE_CLIENT, "other"]).subject  # several audiences: azp must be us


@pytest.mark.parametrize("flag", [False, "false", None, _DROP, 1])
def test_google_email_is_verified_only_when_google_says_so(flag: object) -> None:
    assert parse_google(email_verified=flag).email_verified is False


def test_google_string_true_counts_as_verified() -> None:
    assert parse_google(email_verified="true").email_verified is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.example"},
        {"iss": ["https://accounts.google.com"]},
        {"iss": _DROP},
        {"aud": "someone-else"},
        {"aud": [GOOGLE_CLIENT, "other"], "azp": _DROP},
        {"aud": [GOOGLE_CLIENT], "azp": "someone-else"},
        {"azp": "someone-else"},
        {"exp": int(NOW.timestamp())},
        {"exp": str(int((NOW + timedelta(hours=1)).timestamp()))},
        {"exp": True},
        {"nonce": "another-nonce"},
        {"nonce": _DROP},
        {"nonce": "n-123é"},
        {"sub": ""},
        {"sub": 12345},
        {"sub": "x" * 256},
    ],
)
def test_google_id_tokens_failing_a_check_are_refused(overrides: dict[str, Any]) -> None:
    with pytest.raises(oauth.ProviderError, match="id_token"):
        parse_google(**overrides)


LIST_PAYLOAD = base64.urlsafe_b64encode(b"[1]").decode()


@pytest.mark.parametrize(
    "token",
    [None, 42, "", "a.b", "a.b.c.d", "a.!!!.c", f"a.{LIST_PAYLOAD}.c", "a.bm90IGpzb24.c", "a." + "e30" * 3000 + ".c"],
)
def test_malformed_id_tokens_are_refused(token: object) -> None:
    with pytest.raises(oauth.ProviderError, match="id_token"):
        oauth.parse_google_id_token(token, client_id=GOOGLE_CLIENT, nonce="n-123", now=NOW)


# ------------------------------------------------------------------ token exchange and user info (respx fakes)


async def test_github_exchange_sends_the_verifier_and_reads_the_identity() -> None:
    started = flow()
    with respx.mock(assert_all_called=True) as router:
        token = router.post(GITHUB_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "gho_fake", "token_type": "bearer", "scope": "x"})
        )
        user = router.get("https://api.github.com/user").mock(return_value=httpx.Response(200, json=github_user()))
        emails = router.get("https://api.github.com/user/emails").mock(
            return_value=httpx.Response(200, json=github_emails())
        )
        identity = await oauth.fetch_identity(client("github"), started, "the-code", now=NOW)
    form = parse_qs(token.calls.last.request.content.decode(), strict_parsing=True)
    assert form == {
        "grant_type": ["authorization_code"],
        "code": ["the-code"],
        "redirect_uri": ["https://bridge.test/api/auth/oauth/github/callback"],
        "client_id": ["gh-client-id"],
        "client_secret": ["gh-client-secret"],
        "code_verifier": [started.verifier],
    }
    assert token.calls.last.request.headers["accept"] == "application/json"
    for route in (user, emails):
        assert route.calls.last.request.headers["authorization"] == "Bearer gho_fake"
    assert (identity.subject, identity.email, identity.email_verified) == ("583231", "octo@example.com", True)


async def test_google_exchange_reads_the_id_token() -> None:
    started = flow(AuthProvider.GOOGLE)
    with respx.mock(assert_all_called=True) as router:
        token = router.post(GOOGLE_TOKEN_URL).mock(
            return_value=httpx.Response(
                200, json={"access_token": "ya29.fake", "id_token": id_token(**google_claims(started.nonce))}
            )
        )
        identity = await oauth.fetch_identity(client("google"), started, "the-code", now=NOW)
    form = parse_qs(token.calls.last.request.content.decode(), strict_parsing=True)
    assert form["code_verifier"] == [started.verifier]
    assert form["redirect_uri"] == ["https://bridge.test/api/auth/oauth/google/callback"]
    assert identity.subject == "110169484474386276334"


async def test_google_nonce_from_another_flow_is_refused() -> None:
    started = flow(AuthProvider.GOOGLE)
    with respx.mock(assert_all_called=True) as router:
        router.post(GOOGLE_TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"id_token": id_token(**google_claims("a-different-nonce"))})
        )
        with pytest.raises(oauth.ProviderError, match="id_token"):
            await oauth.fetch_identity(client("google"), started, "the-code", now=NOW)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"error": "bad_verification_code", "error_description": "<script>x</script>"}),
        httpx.Response(200, json={"token_type": "bearer"}),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(400, json={"error": "invalid_grant"}),
        httpx.Response(503),
        httpx.ConnectError("offline"),
        httpx.ReadTimeout("slow"),
    ],
)
async def test_token_exchange_failures_are_provider_errors(response: httpx.Response | Exception) -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(GITHUB_TOKEN_URL)
        if isinstance(response, Exception):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)
        with pytest.raises(oauth.ProviderError) as info:
            await oauth.fetch_identity(client("github"), flow(), "the-code", now=NOW)
    assert str(info.value) == "token"  # provider text never travels further


async def test_google_token_without_an_id_token_is_refused() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(GOOGLE_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "ya29.fake"}))
        with pytest.raises(oauth.ProviderError, match="id_token"):
            await oauth.fetch_identity(client("google"), flow(AuthProvider.GOOGLE), "the-code", now=NOW)


@pytest.mark.parametrize(("path", "stage"), [("/user", "user"), ("/user/emails", "emails")])
async def test_github_api_failures_are_provider_errors(path: str, stage: str) -> None:
    answers = {
        "/user": httpx.Response(200, json=github_user()),
        "/user/emails": httpx.Response(200, json=github_emails()),
        path: httpx.Response(401, json={"message": "Bad credentials"}),
    }
    with respx.mock(assert_all_called=False) as router:
        router.post(GITHUB_TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "gho_fake"}))
        for api_path, answer in answers.items():
            router.get(f"https://api.github.com{api_path}").mock(return_value=answer)
        with pytest.raises(oauth.ProviderError, match=stage):
            await oauth.fetch_identity(client("github"), flow(), "the-code", now=NOW)
