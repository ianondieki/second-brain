"""CSRF protection: signed double-submit cookie bound to the session (docs/spec/08 Auth; OWASP CSRF cheat sheet).

The token is ``<nonce>.<hmac>`` where the HMAC covers the nonce and a binding derived from the session cookie
(``anon`` before login). The cookie is readable by the page (not httpOnly); every state-changing request must echo it
in ``X-CSRF-Token``. A token minted for one session is useless with another, and a planted cookie cannot be forged
without the server key.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ANONYMOUS = "anon"


def binding_for(session_cookie: str | None) -> str:
    """A short, non-reversible label for the session the token belongs to."""
    if not session_cookie:
        return ANONYMOUS
    return hashlib.sha256(session_cookie.encode("utf-8")).hexdigest()[:32]


def _mac(key: str, nonce: str, binding: str) -> str:
    return hmac.new(key.encode("utf-8"), f"csrf|{binding}|{nonce}".encode(), hashlib.sha256).hexdigest()


def issue(key: str, binding: str) -> str:
    nonce = secrets.token_urlsafe(18)
    return f"{nonce}.{_mac(key, nonce, binding)}"


def is_valid(key: str, token: str | None, binding: str) -> bool:
    if not token or "." not in token:
        return False
    nonce, _, mac = token.partition(".")
    return hmac.compare_digest(mac, _mac(key, nonce, binding))


def request_passes(key: str, *, method: str, cookie: str | None, header: str | None, binding: str) -> bool:
    """Safe methods pass; unsafe ones need header == cookie and a token valid for this session."""
    if method.upper() in SAFE_METHODS:
        return True
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        return False
    return is_valid(key, cookie, binding)
