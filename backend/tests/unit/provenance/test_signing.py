"""REQ-PROV-01 / ADR-003: Ed25519 signatures over context-labelled messages, key ids derived from public keys, the
KMS stub fails closed, and the key registration command refuses to run half-configured."""

from __future__ import annotations

import base64
from datetime import date
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from pydantic import SecretStr

from bridge.config import ConfigurationError, Settings
from bridge.provenance import __main__ as cli
from bridge.provenance.signing import (
    KmsSigner,
    LocalSigner,
    key_id_for,
    manifest_message,
    root_message,
    signer_from_settings,
    verify_signature,
)

SEED = bytes(range(32))


def settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": SecretStr("postgresql+psycopg://u:p@localhost/db"),
        "secret_key": SecretStr("x" * 32),
        "data_encryption_key": SecretStr(base64.b64encode(bytes(32)).decode()),
        "recovery_code_pepper": SecretStr("p" * 32),
        "provenance_signing_key": None,
        "database_owner_url": None,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def test_messages_are_context_labelled_ascii() -> None:
    digest = bytes(range(32))
    assert manifest_message(digest) == b"bridge-manifest-v1:" + digest.hex().encode()
    assert root_message(date(2026, 9, 28), digest) == b"bridge-transparency-root-v1:2026-09-28:" + digest.hex().encode()
    assert manifest_message(digest) != root_message(date(2026, 9, 28), digest)
    with pytest.raises(ValueError, match="32-byte"):
        manifest_message(b"short")
    with pytest.raises(ValueError, match="32-byte"):
        root_message(date(2026, 9, 28), b"short")


async def test_local_signer_signs_and_anyone_verifies_with_the_public_key() -> None:
    signer = LocalSigner(SEED)
    expected_public = Ed25519PrivateKey.from_private_bytes(SEED).public_key().public_bytes_raw()
    assert signer.public_key == expected_public
    assert signer.key_id == key_id_for(expected_public)
    assert signer.key_id.startswith("ed25519:")
    assert len(signer.key_id) == len("ed25519:") + 16
    message = manifest_message(bytes(32))
    signature = await signer.sign(message)
    assert len(signature) == 64
    assert verify_signature(signer.public_key, message, signature)
    assert not verify_signature(signer.public_key, manifest_message(bytes([1]) * 32), signature)
    assert not verify_signature(signer.public_key, message, bytes(64))
    assert not verify_signature(b"not a key", message, signature)


def test_the_private_key_is_never_exposed() -> None:
    signer = LocalSigner(SEED)
    raw_private = Ed25519PrivateKey.from_private_bytes(SEED).private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    assert raw_private.hex() not in repr(vars(signer))
    assert SEED.hex() not in signer.key_id


async def test_the_kms_signer_is_a_stub_that_refuses_until_phase_8() -> None:
    kms = KmsSigner("arn:aws:kms:af-south-1:000000000000:key/test")
    with pytest.raises(NotImplementedError, match="Phase 8"):
        await kms.sign(b"x")
    with pytest.raises(NotImplementedError):
        _ = kms.key_id
    with pytest.raises(NotImplementedError):
        _ = kms.public_key


def test_signer_from_settings_fails_closed() -> None:
    with pytest.raises(ConfigurationError, match="PROVENANCE_SIGNING_KEY"):
        signer_from_settings(settings())
    local = signer_from_settings(settings(provenance_signing_key=SecretStr(base64.b64encode(SEED).decode())))
    assert isinstance(local, LocalSigner)
    assert local.public_key == LocalSigner(SEED).public_key
    kms = signer_from_settings(settings(provenance_kms_key_id="arn:aws:kms:af-south-1:000000000000:key/test"))
    assert isinstance(kms, KmsSigner)


def test_register_key_command_without_a_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "get_settings", lambda: settings())
    assert cli.main(["register-key"]) == 2
    assert "PROVENANCE_SIGNING_KEY" in capsys.readouterr().err
    assert cli.main(["register-key", "--if-configured"]) == 0
    assert "no key registered" in capsys.readouterr().out


def test_register_key_command_needs_the_owner_url(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    configured = settings(provenance_signing_key=SecretStr(base64.b64encode(SEED).decode()))
    monkeypatch.setattr(cli, "get_settings", lambda: configured)
    assert cli.main(["register-key"]) == 2
    assert "DATABASE_OWNER_URL" in capsys.readouterr().err


def test_register_key_command_registers(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    configured = settings(
        provenance_signing_key=SecretStr(base64.b64encode(SEED).decode()),
        database_owner_url=SecretStr("postgresql+psycopg://owner@localhost/db"),
    )
    calls: list[str] = []

    async def fake_register(url: str, signer: Any) -> bool:
        calls.append(url)
        return len(calls) == 1

    monkeypatch.setattr(cli, "get_settings", lambda: configured)
    monkeypatch.setattr(cli, "register", fake_register)
    assert cli.main(["register-key"]) == 0
    assert cli.main(["register-key"]) == 0
    out = capsys.readouterr().out
    assert f"{LocalSigner(SEED).key_id} registered" in out
    assert "already registered" in out
    assert calls == ["postgresql+psycopg://owner@localhost/db"] * 2
