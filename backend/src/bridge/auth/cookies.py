"""Session and CSRF cookies (docs/spec/08 Auth: httpOnly; Secure; SameSite=Lax + CSRF double-submit)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Response

from bridge.auth import csrf
from bridge.config import Settings


def set_csrf(response: Response, settings: Settings, session_token: str | None) -> str:
    token = csrf.issue(settings.secret_key.get_secret_value(), csrf.binding_for(session_token))
    response.set_cookie(
        settings.csrf_cookie_name,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=False,  # the page reads it and echoes it in X-CSRF-Token
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return token


def set_session(response: Response, settings: Settings, session_token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    set_csrf(response, settings, session_token)


def clear_session(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/", secure=settings.cookie_secure, httponly=True)
    set_csrf(response, settings, None)


def signup_cookie_name(settings: Settings) -> str:
    return settings.signup_cookie_name


def signup_binding(settings: Settings, user_id: object, password_hash: str) -> str:
    """Ties verification to the browser that set the current password (pre-hijacking defence, security review of
    T1.5). Bound to the password hash, so any link for the account (signup, resend, login) opened in that browser
    keeps the password, and a later signup that replaces the password invalidates older bindings."""
    key = settings.secret_key.get_secret_value().encode("utf-8")
    return hmac.new(key, f"signup|{user_id}|{password_hash}".encode(), hashlib.sha256).hexdigest()


def identity_binding(settings: Settings, user_id: object, identity_id: object) -> str:
    """The same defence for an OAuth identity attached at signup with an address the provider had not verified
    (REQ-AUTH-02): only a verification link opened in the browser that signed up keeps the identity."""
    key = settings.secret_key.get_secret_value().encode("utf-8")
    return hmac.new(key, f"signup-identity|{user_id}|{identity_id}".encode(), hashlib.sha256).hexdigest()


def set_oauth_flow(response: Response, settings: Settings, sealed: str, max_age: int) -> None:
    """The sealed OAuth flow (bridge.auth.oauth). SameSite=Lax: the provider's redirect back is a top-level GET."""
    response.set_cookie(
        settings.oauth_cookie_name,
        sealed,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_oauth_flow(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.oauth_cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
    )


def set_signup_binding(response: Response, settings: Settings, binding: str | None) -> None:
    """Always set (a random value when there is no binding), so the cookie reveals nothing about the address."""
    value = binding or secrets.token_hex(32)
    response.set_cookie(
        signup_cookie_name(settings),
        value,
        max_age=settings.session_ttl_days * 86400,  # outlives any resend; the value reveals nothing
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
