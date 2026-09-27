"""OAuth 2.0 sign-in with GitHub and Google (REQ-AUTH-02, ADR-002): the protocol half.

Authorization code flow with PKCE (RFC 7636, S256). ``state``, the OpenID Connect ``nonce`` (Google) and the PKCE
verifier travel in the ``__Host-bridge_oauth`` cookie, sealed with AES-256-GCM under a key derived from SECRET_KEY,
valid for 10 minutes and bound to one flow: provider, intent, a return path from an allow-list and, for linking, the
session that started it. The callback accepts a code only with the matching ``state`` from that cookie, so a code
minted in another browser (login CSRF) or replayed after the cookie is spent is refused before any provider call.

Provider access tokens are used once, in memory, to read the identity; they are never stored or logged. Google's ID
token is read from the token endpoint's own TLS response, where OpenID Connect Core 1.0 section 3.1.3.7 lets the TLS
server check stand in for the signature check; issuer, audience, authorised party, expiry and nonce are checked.
Which account an identity may reach is decided in ``bridge.auth.identities``.

Endpoints and parameters follow the providers' public documentation (GitHub "Authorizing OAuth apps" and the REST
"users" and "emails" endpoints; Google Identity "OpenID Connect"). CI only talks to respx fakes of them; the D-26 test
apps are for a manual check against the real providers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import quote, urlencode

import httpx
from cryptography.exceptions import InvalidTag
from pydantic import BaseModel, ConfigDict, SecretStr

from bridge.auth.crypto import decrypt, encrypt
from bridge.auth.schemas import OAuthSignup, ReturnPath
from bridge.config import Settings
from bridge.logging import get_logger
from bridge.models.enums import AuthProvider
from bridge.notifications.email import is_mailbox

FLOW_TTL = timedelta(minutes=10)
HTTP_TIMEOUT_SECONDS = 10.0
MAX_COOKIE_CHARS = 3800  # a browser keeps about 4096 bytes for name and value together
MAX_ID_TOKEN_CHARS = 8192
MAX_NAME_CHARS = 120  # users.display_name
MAX_SUBJECT_CHARS = 255  # auth_identities.subject

Intent = Literal["login", "signup", "link"]

# The only pages a callback sends the browser to (on PUBLIC_BASE_URL). Nothing from the request becomes a target.
WEB_PATHS = frozenset({"/dev", "/org", "/settings/security", "/login", "/signup", "/signup/check-email", "/auth/mfa"})

log = get_logger("bridge.auth.oauth")


@dataclass(frozen=True, slots=True)
class Provider:
    name: AuthProvider
    label: str  # in security notices
    authorize_url: str
    token_url: str
    scopes: str
    oidc: bool  # Google: OpenID Connect (nonce, ID token); GitHub: OAuth 2.0 plus its REST API


GITHUB = Provider(
    AuthProvider.GITHUB,
    "GitHub",
    "https://github.com/login/oauth/authorize",
    "https://github.com/login/oauth/access_token",
    "read:user user:email",
    oidc=False,
)
GOOGLE = Provider(
    AuthProvider.GOOGLE,
    "Google",
    "https://accounts.google.com/o/oauth2/v2/auth",
    "https://oauth2.googleapis.com/token",
    "openid email profile",
    oidc=True,
)
PROVIDERS: dict[AuthProvider, Provider] = {p.name: p for p in (GITHUB, GOOGLE)}
GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GOOGLE_ISSUERS = frozenset({"https://accounts.google.com", "accounts.google.com"})


@dataclass(frozen=True, slots=True)
class Client:
    """A configured provider: our client credentials and the exact redirect URI registered with it."""

    provider: Provider
    client_id: str
    client_secret: SecretStr = field(repr=False)
    redirect_uri: str


def _value(secret: SecretStr | None) -> str | None:
    text = secret.get_secret_value().strip() if secret is not None else ""
    return text or None


def configured(settings: Settings, name: str) -> Client | None:
    """The provider's client when both its values are set, else None; unknown and disabled providers look alike."""
    try:
        provider = PROVIDERS[AuthProvider(name)]
    except ValueError:
        return None
    pairs = {
        AuthProvider.GITHUB: (settings.github_client_id, settings.github_client_secret),
        AuthProvider.GOOGLE: (settings.google_client_id, settings.google_client_secret),
    }
    client_id, secret = (_value(value) for value in pairs[provider.name])
    if client_id is None or secret is None:
        return None
    return Client(provider, client_id, SecretStr(secret), redirect_uri(settings, provider.name))


def enabled(settings: Settings) -> list[AuthProvider]:
    return [name for name in PROVIDERS if configured(settings, name.value) is not None]


def redirect_uri(settings: Settings, provider: AuthProvider) -> str:
    return f"{settings.public_base_url.rstrip('/')}/api/auth/oauth/{provider.value}/callback"


# ------------------------------------------------------------------------------------------------ PKCE and the flow


def new_verifier() -> str:
    """RFC 7636 section 4.1: 43 to 128 unreserved characters; 48 random bytes give 64."""
    return secrets.token_urlsafe(48)


def challenge(verifier: str) -> str:
    """RFC 7636 section 4.2, S256: BASE64URL(SHA256(ASCII(verifier))) without padding."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class Flow(BaseModel):
    """One sign-in attempt, sealed into the flow cookie. Nothing in it is trusted until ``unseal`` authenticates it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: AuthProvider
    intent: Intent
    state: str
    nonce: str
    verifier: str
    return_to: ReturnPath
    session: str | None = None  # link: csrf.binding_for(token) of the session that started the flow
    signup: OAuthSignup | None = None  # signup: the choices the form showed
    expires: int  # Unix seconds


def new_flow(
    provider: AuthProvider,
    intent: Intent,
    return_to: ReturnPath,
    *,
    now: datetime,
    session: str | None = None,
    signup: OAuthSignup | None = None,
) -> Flow:
    return Flow(
        provider=provider,
        intent=intent,
        state=secrets.token_urlsafe(32),
        nonce=secrets.token_urlsafe(32),
        verifier=new_verifier(),
        return_to=return_to,
        session=session,
        signup=signup,
        expires=int((now + FLOW_TTL).timestamp()),
    )


_SEAL_PREFIX = "v1."
_SEAL_CONTEXT = b"bridge/oauth-flow/v1"


def _seal_key(settings: Settings) -> bytes:
    """A key used for flow cookies only, derived from SECRET_KEY (HMAC-SHA256 as a PRF)."""
    return hmac.new(settings.secret_key.get_secret_value().encode("utf-8"), _SEAL_CONTEXT, hashlib.sha256).digest()


def seal(settings: Settings, flow: Flow) -> str:
    """Encrypt and authenticate the flow (AES-256-GCM): the verifier and nonce stay secret, any change is detected."""
    blob = encrypt(_seal_key(settings), flow.model_dump_json().encode("utf-8"), _SEAL_CONTEXT)
    return _SEAL_PREFIX + base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")


def unseal(settings: Settings, value: str | None, *, now: datetime) -> Flow | None:
    """The flow in a cookie, or None when it is missing, malformed, forged, tampered with or older than 10 minutes."""
    if not value or len(value) > MAX_COOKIE_CHARS or not value.startswith(_SEAL_PREFIX):
        return None
    body = value[len(_SEAL_PREFIX) :]
    try:
        blob = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        flow = Flow.model_validate_json(decrypt(_seal_key(settings), blob, _SEAL_CONTEXT))
    except (ValueError, InvalidTag):  # bad base64 or nonce, a forged or changed blob, or not a flow
        return None
    return flow if flow.expires > int(now.timestamp()) else None


def authorize_url(client: Client, flow: Flow) -> str:
    params = {
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "scope": client.provider.scopes,
        "state": flow.state,
        "code_challenge": challenge(flow.verifier),
        "code_challenge_method": "S256",
    }
    if client.provider.oidc:
        params |= {"response_type": "code", "nonce": flow.nonce}
    return f"{client.provider.authorize_url}?{urlencode(params, quote_via=quote)}"


def web_url(settings: Settings, path: str, params: Mapping[str, str] | None = None) -> str:
    """An absolute URL for one of ``WEB_PATHS`` on the web app; any other path is a programming error."""
    if path not in WEB_PATHS:
        raise ValueError(f"not a web path: {path!r}")
    query = f"?{urlencode(params)}" if params else ""
    return f"{settings.public_base_url.rstrip('/')}{path}{query}"


# ------------------------------------------------------------------------------------------------ provider identity


@dataclass(frozen=True, slots=True)
class ProviderIdentity:
    provider: AuthProvider
    subject: str  # the provider's stable account id: GitHub's numeric user id, Google's ``sub``
    email: str | None = field(repr=False)  # normalised; None when the provider gave no usable primary address
    email_verified: bool  # the provider says it verified ``email``
    display_name: str | None = field(repr=False)


class ProviderError(Exception):
    """The provider refused or answered something unusable. ``stage`` names the step; provider text is dropped."""

    def __init__(self, stage: str) -> None:
        super().__init__(stage)
        self.stage = stage


async def fetch_identity(client: Client, flow: Flow, code: str, *, now: datetime) -> ProviderIdentity:
    """Exchange the code (with the PKCE verifier) and read who signed in. Raises ``ProviderError``."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=False) as http:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": client.redirect_uri,
            "client_id": client.client_id,
            "client_secret": client.client_secret.get_secret_value(),
            "code_verifier": flow.verifier,
        }
        tokens = await _call(http, "POST", client.provider.token_url, "token", data=form)
        if not isinstance(tokens, dict) or "error" in tokens:  # GitHub reports a refused code with 200 OK
            raise ProviderError("token")
        if client.provider.oidc:
            return parse_google_id_token(tokens.get("id_token"), client_id=client.client_id, nonce=flow.nonce, now=now)
        access = tokens.get("access_token")
        if not isinstance(access, str) or not access:
            raise ProviderError("token")
        headers = {
            "Authorization": f"Bearer {access}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        user = await _call(http, "GET", f"{GITHUB_API}/user", "user", headers=headers)
        emails = await _call(http, "GET", f"{GITHUB_API}/user/emails", "emails", headers=headers)
        return parse_github(user, emails)


async def _call(http: httpx.AsyncClient, method: str, url: str, stage: str, **kwargs: Any) -> Any:
    headers = {"Accept": "application/json", "User-Agent": "bridge-oauth", **kwargs.pop("headers", {})}
    try:
        response = await http.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as exc:  # no network, DNS, TLS, timeouts: log the type only, never the message
        log.warning("auth.oauth_provider_unreachable", stage=stage, error_type=type(exc).__name__)
        raise ProviderError(stage) from None
    if not response.is_success:
        log.warning("auth.oauth_provider_refused", stage=stage, status=response.status_code)
        raise ProviderError(stage)
    try:
        return response.json()
    except ValueError:
        raise ProviderError(stage) from None


def _mailbox(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    return email if is_mailbox(email) else None


def _display_name(value: object) -> str | None:
    """Printable text only (no control or bidi-override characters), whitespace collapsed, at most 120 characters."""
    if not isinstance(value, str):
        return None
    printable = "".join(ch for ch in value if not unicodedata.category(ch).startswith("C"))
    return " ".join(printable.split())[:MAX_NAME_CHARS].rstrip() or None


def parse_github(user: Any, emails: Any) -> ProviderIdentity:
    """GitHub ``/user`` and ``/user/emails``. Only the primary address counts, and it is verified only when GitHub
    says so; secondary addresses are never used to find an account."""
    if not isinstance(user, dict):
        raise ProviderError("user")
    user_id = user.get("id")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ProviderError("user")
    if not isinstance(emails, list):
        raise ProviderError("emails")
    primary = next((e for e in emails if isinstance(e, dict) and e.get("primary") is True), None)
    email = _mailbox(primary.get("email")) if primary is not None else None
    verified = email is not None and primary is not None and primary.get("verified") is True
    name = _display_name(user.get("name")) or _display_name(user.get("login"))
    return ProviderIdentity(AuthProvider.GITHUB, str(user_id), email, verified, name)


def _jwt_claims(token: object) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 2 or len(token) > MAX_ID_TOKEN_CHARS:
        raise ProviderError("id_token")
    payload = token.split(".")[1]
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except ValueError:  # bad base64, bad UTF-8 or bad JSON
        raise ProviderError("id_token") from None
    if not isinstance(claims, dict):
        raise ProviderError("id_token")
    return claims


def parse_google_id_token(token: object, *, client_id: str, nonce: str, now: datetime) -> ProviderIdentity:
    """Google's ID token from the token endpoint (OpenID Connect Core 1.0 section 3.1.3.7): the issuer is Google, the
    audience is this client (the authorised party too when there are several), it has not expired and it carries
    this flow's nonce. ``email_verified`` is taken only when Google sets it."""
    claims = _jwt_claims(token)
    issuer, audience, party = claims.get("iss"), claims.get("aud"), claims.get("azp")
    expires, subject, got_nonce = claims.get("exp"), claims.get("sub"), claims.get("nonce")
    if isinstance(audience, list):
        audience_ok = client_id in audience and party == client_id
    else:
        audience_ok = audience == client_id and party in (None, client_id)
    if not (
        isinstance(issuer, str)
        and issuer in GOOGLE_ISSUERS
        and audience_ok
        and isinstance(expires, int)
        and not isinstance(expires, bool)
        and expires > now.timestamp()
        and isinstance(got_nonce, str)
        and hmac.compare_digest(got_nonce.encode("utf-8"), nonce.encode("utf-8"))
        and isinstance(subject, str)
        and 0 < len(subject) <= MAX_SUBJECT_CHARS
    ):
        raise ProviderError("id_token")
    email = _mailbox(claims.get("email"))
    flag = claims.get("email_verified")
    verified = email is not None and (flag is True or flag == "true")  # not 1, which equals True in Python
    return ProviderIdentity(AuthProvider.GOOGLE, subject, email, verified, _display_name(claims.get("name")))
