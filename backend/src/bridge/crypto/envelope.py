"""Per-proposal envelope encryption for Tier 2 (docs/spec/06 6.1; ADR-007 "per-proposal KMS envelope keys").

Each proposal has one random AES-256-GCM data key. The data key is stored only wrapped, in every
``proposal_confidential`` row of the proposal (``wrapped_dek`` and ``kms_key_id``), by a ``KeyWrapper``:

- ``LocalKeyWrapper``: AES-256-GCM under ``TIER2_LOCAL_KEK`` (dev and test only; tests set a throwaway key);
- ``KmsKeyWrapper``: the production wrapper. A stub until Phase 8 (ADR-007), so production fails closed: nothing can
  be sealed or opened there until KMS wrapping exists. Tests never reach KMS.

A wrap is bound to its proposal (AAD for the local wrapper, the encryption context for KMS), so a wrapped key copied
onto another proposal does not unwrap. Every message is sealed under a fresh 96-bit nonce with AAD that binds the
proposal id, the version id and the purpose, so a ciphertext moved to another version, proposal or column does not
open. Opening anything that was altered raises ``EnvelopeError``.

Contract for the publish flow (T2.3) and the registration job (T2.4): a version's Tier-2 document is a UTF-8 JSON
object sealed with ``Purpose.TIER2`` into ``proposal_confidential.ciphertext``/``nonce``; the registration manifest
is sealed with ``Purpose.MANIFEST`` into ``manifest_ciphertext``/``manifest_nonce``. Reuse the proposal's data key
for later versions (``open_data_key`` on an earlier row), create it with ``new_data_key`` for a new proposal.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from bridge.config import ConfigurationError, Settings, decoded_key

KEY_BYTES = 32
NONCE_BYTES = 12
_WRAP_LABEL = b"bridge.tier2.dek.v1|"
_SEAL_LABEL = "bridge.tier2.v1"


class EnvelopeError(Exception):
    """A wrapped key or sealed message does not open: wrong key, wrong binding, or altered bytes."""


class Purpose(StrEnum):
    TIER2 = "tier2"
    MANIFEST = "manifest"


class KeyWrapper(Protocol):
    """Wraps and unwraps data keys. Async because the production wrapper is a network call (KMS)."""

    @property
    def key_id(self) -> str: ...

    async def wrap(self, key: bytes, *, proposal_id: UUID) -> bytes: ...

    async def unwrap(self, wrapped: bytes, *, key_id: str, proposal_id: UUID) -> bytes: ...


class LocalKeyWrapper:
    """AES-256-GCM key wrapping under a local key encryption key (dev and test). Output: nonce || ciphertext."""

    def __init__(self, kek: bytes) -> None:
        if len(kek) != KEY_BYTES:
            raise ValueError("the key encryption key must be 32 bytes")
        self._aead = AESGCM(kek)
        # A fingerprint, not the key: 64 bits of SHA-256 of a random 256-bit key reveal nothing usable.
        self._key_id = "local:" + hashlib.sha256(b"bridge.kek.id|" + kek).hexdigest()[:16]

    @property
    def key_id(self) -> str:
        return self._key_id

    async def wrap(self, key: bytes, *, proposal_id: UUID) -> bytes:
        if len(key) != KEY_BYTES:
            raise ValueError("a data key is 32 bytes")
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, key, _WRAP_LABEL + proposal_id.bytes)

    async def unwrap(self, wrapped: bytes, *, key_id: str, proposal_id: UUID) -> bytes:
        if key_id != self._key_id:
            raise EnvelopeError(f"the data key was wrapped under {key_id}, not {self._key_id}")
        try:
            return self._aead.decrypt(wrapped[:NONCE_BYTES], wrapped[NONCE_BYTES:], _WRAP_LABEL + proposal_id.bytes)
        except (InvalidTag, ValueError) as exc:  # ValueError: truncated input
            raise EnvelopeError("the wrapped data key does not open for this proposal") from exc


class KmsKeyWrapper:
    """Production key wrapping through a KMS key (``TIER2_KMS_KEY_ID``). Not built until Phase 8 (ADR-007): every call
    refuses, so production cannot seal or open Tier 2 with anything weaker in the meantime."""

    def __init__(self, kms_key_id: str) -> None:
        self._key_id = kms_key_id

    @property
    def key_id(self) -> str:
        return self._key_id

    async def wrap(self, key: bytes, *, proposal_id: UUID) -> bytes:
        raise NotImplementedError("KMS key wrapping arrives with the Phase 8 deployment (ADR-007)")

    async def unwrap(self, wrapped: bytes, *, key_id: str, proposal_id: UUID) -> bytes:
        raise NotImplementedError("KMS key wrapping arrives with the Phase 8 deployment (ADR-007)")


def key_wrapper_from_settings(settings: Settings) -> KeyWrapper:
    """KMS when ``TIER2_KMS_KEY_ID`` is set, else the local key; neither set fails closed."""
    if settings.tier2_kms_key_id:
        return KmsKeyWrapper(settings.tier2_kms_key_id)
    if settings.tier2_local_kek is not None:
        kek = decoded_key(settings.tier2_local_kek)
        if kek is not None:  # Settings already refused a malformed key
            return LocalKeyWrapper(kek)
    raise ConfigurationError("Tier-2 encryption needs TIER2_LOCAL_KEK (dev/test) or TIER2_KMS_KEY_ID (production)")


@dataclass(frozen=True, slots=True)
class DataKey:
    """A proposal's data key: the plaintext key (memory only, never logged) and its stored wrapped form."""

    key: bytes = field(repr=False)
    wrapped: bytes
    key_id: str


@dataclass(frozen=True, slots=True)
class Sealed:
    nonce: bytes
    ciphertext: bytes


async def new_data_key(wrapper: KeyWrapper, proposal_id: UUID) -> DataKey:
    """A fresh random data key for a new proposal, wrapped for storage."""
    key = AESGCM.generate_key(bit_length=256)
    return DataKey(key, await wrapper.wrap(key, proposal_id=proposal_id), wrapper.key_id)


async def open_data_key(wrapper: KeyWrapper, *, wrapped: bytes, key_id: str, proposal_id: UUID) -> DataKey:
    """The data key of a stored row (``wrapped_dek``, ``kms_key_id``) of this proposal."""
    key = await wrapper.unwrap(wrapped, key_id=key_id, proposal_id=proposal_id)
    return DataKey(key, wrapped, key_id)


def associated_data(proposal_id: UUID, version_id: UUID, purpose: Purpose) -> bytes:
    return f"{_SEAL_LABEL}|{purpose.value}|{proposal_id}|{version_id}".encode("ascii")


def seal(key: DataKey, plaintext: bytes, *, proposal_id: UUID, version_id: UUID, purpose: Purpose) -> Sealed:
    nonce = os.urandom(NONCE_BYTES)
    aad = associated_data(proposal_id, version_id, purpose)
    return Sealed(nonce, AESGCM(key.key).encrypt(nonce, plaintext, aad))


def open_sealed(key: DataKey, sealed: Sealed, *, proposal_id: UUID, version_id: UUID, purpose: Purpose) -> bytes:
    aad = associated_data(proposal_id, version_id, purpose)
    try:
        return AESGCM(key.key).decrypt(sealed.nonce, sealed.ciphertext, aad)
    except (InvalidTag, ValueError) as exc:  # ValueError: a malformed nonce
        raise EnvelopeError("the ciphertext does not open for this proposal, version and purpose") from exc
