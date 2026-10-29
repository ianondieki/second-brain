"""Ed25519 server signatures for manifests and transparency roots (REQ-PROV-01, REQ-AUD-01; ADR-003).

What is signed is an ASCII message with a context label, so a signature over one kind of value can never be replayed
as another (the same key signs manifests and nightly Merkle roots):

- manifests: ``bridge-manifest-v1:<content_hash hex>``;
- transparency roots: ``bridge-transparency-root-v1:<YYYY-MM-DD>:<merkle_root hex>``.

Anyone can check a signature offline with the public key from ``/.well-known/provenance-keys.json``
(``docs/runbooks/verify-offline.md``). ``key_id`` is ``ed25519:`` plus the first 16 hex digits of SHA-256 of the raw
public key, so every record names the key that signed it and keys can rotate.

``LocalSigner`` reads ``PROVENANCE_SIGNING_KEY`` (dev and test; tests set a throwaway key). ``KmsSigner`` is the
production signer: a stub until Phase 8 that refuses, so production fails closed. Public keys are registered in
``provenance_keys`` by an owner-role command (``python -m bridge.provenance register-key``), never by the app role.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from bridge.config import ConfigurationError, Settings, decoded_key

MANIFEST_CONTEXT = "bridge-manifest-v1"
ROOT_CONTEXT = "bridge-transparency-root-v1"
ALGORITHM = "ed25519"


def manifest_message(content_hash: bytes) -> bytes:
    if len(content_hash) != 32:
        raise ValueError("content_hash is a 32-byte SHA-256 digest")
    return f"{MANIFEST_CONTEXT}:{content_hash.hex()}".encode("ascii")


def root_message(day: date, merkle_root: bytes) -> bytes:
    if len(merkle_root) != 32:
        raise ValueError("a Merkle root is a 32-byte SHA-256 digest")
    return f"{ROOT_CONTEXT}:{day.isoformat()}:{merkle_root.hex()}".encode("ascii")


def key_id_for(public_key: bytes) -> str:
    return f"{ALGORITHM}:{hashlib.sha256(public_key).hexdigest()[:16]}"


def verify_signature(public_key: bytes, message: bytes, signature: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError):
        return False
    return True


class Signer(Protocol):
    @property
    def key_id(self) -> str: ...

    @property
    def public_key(self) -> bytes:
        """The raw 32-byte Ed25519 public key."""
        ...

    async def sign(self, message: bytes) -> bytes: ...


class LocalSigner:
    """Ed25519 with a private key held in memory (dev and test)."""

    def __init__(self, private_key: bytes) -> None:
        self._key = Ed25519PrivateKey.from_private_bytes(private_key)
        self._public = self._key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self._key_id = key_id_for(self._public)

    @property
    def key_id(self) -> str:
        return self._key_id

    @property
    def public_key(self) -> bytes:
        return self._public

    async def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)


class KmsSigner:
    """Production signing with a non-exportable KMS key (``PROVENANCE_KMS_KEY_ID``). Not built until Phase 8 (the KMS
    must offer Ed25519, or ADR-003 needs an amendment): every call refuses, so production never signs with a weaker
    key in the meantime."""

    def __init__(self, kms_key_id: str) -> None:
        self.kms_key_id = kms_key_id

    @property
    def key_id(self) -> str:
        raise NotImplementedError("KMS signing arrives with the Phase 8 deployment (ADR-003, ADR-007)")

    @property
    def public_key(self) -> bytes:
        raise NotImplementedError("KMS signing arrives with the Phase 8 deployment (ADR-003, ADR-007)")

    async def sign(self, message: bytes) -> bytes:
        raise NotImplementedError("KMS signing arrives with the Phase 8 deployment (ADR-003, ADR-007)")


def signer_from_settings(settings: Settings) -> Signer:
    """KMS when ``PROVENANCE_KMS_KEY_ID`` is set, else the local key; neither set fails closed."""
    if settings.provenance_kms_key_id:
        return KmsSigner(settings.provenance_kms_key_id)
    if settings.provenance_signing_key is not None:
        raw = decoded_key(settings.provenance_signing_key)
        if raw is not None:  # Settings already refused a malformed key
            return LocalSigner(raw)
    raise ConfigurationError("provenance signing needs PROVENANCE_SIGNING_KEY (dev/test) or PROVENANCE_KMS_KEY_ID")


_REGISTER = text(
    "INSERT INTO provenance_keys (key_id, algorithm, public_key) VALUES (:key_id, 'ed25519', :public_key)"
    " ON CONFLICT (key_id) DO NOTHING"
)
_REGISTERED = text("SELECT public_key FROM provenance_keys WHERE key_id = :key_id")


async def register_public_key(connection: AsyncConnection, signer: Signer) -> bool:
    """Publish the signer's public key (owner role; idempotent). True when the key was added now."""
    inserted = (
        await connection.execute(_REGISTER, {"key_id": signer.key_id, "public_key": signer.public_key})
    ).rowcount
    stored = (await connection.execute(_REGISTERED, {"key_id": signer.key_id})).scalar_one()
    if bytes(stored) != signer.public_key:
        raise RuntimeError(f"provenance_keys already holds a different key under {signer.key_id}")
    return bool(inserted)
