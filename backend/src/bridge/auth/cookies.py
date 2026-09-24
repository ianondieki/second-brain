"""Session and CSRF cookies (docs/spec/08 Auth: httpOnly; Secure; SameSite=Lax + CSRF double-submit)."""

from __future__ import annotations

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
