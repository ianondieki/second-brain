"""Per-proposal envelope encryption (REQ-REPO-01 storage, REQ-PROV-01 manifests; ADR-007): data keys are wrapped and
bound to their proposal, sealed messages are bound to proposal, version and purpose, and tampering never opens."""

from __future__ import annotations

import base64
import os
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from bridge.config import ConfigurationError, Settings
from bridge.crypto.envelope import (
    DataKey,
    EnvelopeError,
    KmsKeyWrapper,
    LocalKeyWrapper,
    Purpose,
    Sealed,
    key_wrapper_from_settings,
    new_data_key,
    open_data_key,
    open_sealed,
    seal,
)

KEK = bytes(range(32))
MANIFEST = Purpose.MANIFEST


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(base64.b64encode(bytes(32)).decode()),
        "recovery_code_pepper": SecretStr("p" * 32),
        "tier2_local_kek": None,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


async def test_a_data_key_round_trips_and_is_bound_to_its_proposal() -> None:
    wrapper = LocalKeyWrapper(KEK)
    proposal = uuid4()
    key = await new_data_key(wrapper, proposal)
    assert len(key.key) == 32
    assert key.key not in key.wrapped
    assert "key=" not in repr(key)
    reopened = await open_data_key(wrapper, wrapped=key.wrapped, key_id=key.key_id, proposal_id=proposal)
    assert reopened.key == key.key
    with pytest.raises(EnvelopeError, match="does not open for this proposal"):
        await open_data_key(wrapper, wrapped=key.wrapped, key_id=key.key_id, proposal_id=uuid4())


async def test_a_wrapped_key_from_another_kek_is_refused_by_id_and_by_tag() -> None:
    proposal = uuid4()
    key = await new_data_key(LocalKeyWrapper(KEK), proposal)
    other = LocalKeyWrapper(os.urandom(32))
    with pytest.raises(EnvelopeError, match="wrapped under"):
        await other.unwrap(key.wrapped, key_id=key.key_id, proposal_id=proposal)
    with pytest.raises(EnvelopeError):
        await other.unwrap(key.wrapped, key_id=other.key_id, proposal_id=proposal)
    with pytest.raises(EnvelopeError):
        await LocalKeyWrapper(KEK).unwrap(b"short", key_id=key.key_id, proposal_id=proposal)


def test_key_ids_are_stable_fingerprints_that_hide_the_key() -> None:
    assert LocalKeyWrapper(KEK).key_id == LocalKeyWrapper(KEK).key_id
    assert LocalKeyWrapper(KEK).key_id.startswith("local:")
    assert KEK.hex() not in LocalKeyWrapper(KEK).key_id
    assert LocalKeyWrapper(KEK).key_id != LocalKeyWrapper(os.urandom(32)).key_id


async def test_wrong_lengths_are_refused() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        LocalKeyWrapper(b"short")
    with pytest.raises(ValueError, match="32 bytes"):
        await LocalKeyWrapper(KEK).wrap(b"short", proposal_id=uuid4())


def test_sealed_messages_are_bound_to_proposal_version_and_purpose() -> None:
    key = DataKey(os.urandom(32), b"wrapped", "local:test")
    proposal, version = uuid4(), uuid4()
    sealed = seal(key, b'{"how": "secret"}', proposal_id=proposal, version_id=version, purpose=Purpose.TIER2)
    assert b"secret" not in sealed.ciphertext
    assert open_sealed(key, sealed, proposal_id=proposal, version_id=version, purpose=Purpose.TIER2) == (
        b'{"how": "secret"}'
    )
    for p, v, purpose in (
        (uuid4(), version, Purpose.TIER2),
        (proposal, uuid4(), Purpose.TIER2),
        (proposal, version, Purpose.MANIFEST),
    ):
        with pytest.raises(EnvelopeError):
            open_sealed(key, sealed, proposal_id=p, version_id=v, purpose=purpose)


def test_one_flipped_byte_never_opens() -> None:
    key = DataKey(os.urandom(32), b"wrapped", "local:test")
    proposal, version = uuid4(), uuid4()
    sealed = seal(key, b"manifest bytes", proposal_id=proposal, version_id=version, purpose=Purpose.MANIFEST)
    for index in range(len(sealed.ciphertext)):
        edited = bytearray(sealed.ciphertext)
        edited[index] ^= 0x01
        with pytest.raises(EnvelopeError):
            open_sealed(
                key, Sealed(sealed.nonce, bytes(edited)), proposal_id=proposal, version_id=version, purpose=MANIFEST
            )
    with pytest.raises(EnvelopeError):
        open_sealed(key, Sealed(b"", sealed.ciphertext), proposal_id=proposal, version_id=version, purpose=MANIFEST)


def test_nonces_are_fresh_per_message() -> None:
    key = DataKey(os.urandom(32), b"wrapped", "local:test")
    proposal, version = uuid4(), uuid4()
    nonces = {seal(key, b"x", proposal_id=proposal, version_id=version, purpose=Purpose.TIER2).nonce for _ in range(50)}
    assert len(nonces) == 50


def test_the_wrapper_comes_from_settings_and_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="TIER2_LOCAL_KEK"):
        key_wrapper_from_settings(settings())
    local = key_wrapper_from_settings(settings(tier2_local_kek=SecretStr(base64.b64encode(KEK).decode())))
    assert isinstance(local, LocalKeyWrapper)
    assert local.key_id == LocalKeyWrapper(KEK).key_id
    kms = key_wrapper_from_settings(settings(tier2_kms_key_id="arn:aws:kms:af-south-1:000000000000:key/test"))
    assert isinstance(kms, KmsKeyWrapper)
    assert kms.key_id.startswith("arn:aws:kms")


async def test_the_kms_wrapper_is_a_stub_that_refuses_until_phase_8() -> None:
    """Production fails closed: the stub raises locally and never reaches a KMS endpoint."""
    kms = KmsKeyWrapper("arn:aws:kms:af-south-1:000000000000:key/test")
    with pytest.raises(NotImplementedError, match="Phase 8"):
        await kms.wrap(bytes(32), proposal_id=uuid4())
    with pytest.raises(NotImplementedError, match="Phase 8"):
        await kms.unwrap(b"x", key_id=kms.key_id, proposal_id=uuid4())
