"""Small cryptographic helpers for auth (REQ-AUTH-01): opaque tokens, keyed digests, AES-GCM for secrets at rest."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

TOKEN_BYTES = 32
NONCE_BYTES = 12


def new_token() -> str:
    """A 256-bit URL-safe random token (sessions, magic links, invitations)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> bytes:
    """SHA-256 of a high-entropy token: what the database stores instead of the token."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def keyed_digest(key: str, purpose: str, value: str) -> bytes:
    """HMAC-SHA256 of ``value`` under ``key`` and a purpose label (throttle keys for emails and IPs)."""
    return hmac.new(key.encode("utf-8"), f"{purpose}:{value}".encode(), hashlib.sha256).digest()


def decode_key(value: str) -> bytes:
    """Decode the base64 ``DATA_ENCRYPTION_KEY`` into 32 bytes; anything else is a configuration error."""
    try:
        key = base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError("DATA_ENCRYPTION_KEY must be base64") from exc
    if len(key) != 32:
        raise ValueError("DATA_ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


def encrypt(key: bytes, plaintext: bytes, context: bytes) -> bytes:
    """AES-256-GCM; ``context`` (the user id) is bound as associated data. Output: nonce || ciphertext."""
    nonce = secrets.token_bytes(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, context)


def decrypt(key: bytes, blob: bytes, context: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], context)
