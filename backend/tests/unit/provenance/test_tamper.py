"""REQ-PROV-01 / AC-IP-2 (manifest half): editing one byte of a stored manifest is detected, whichever copy is edited.

The registered hash no longer matches, the Ed25519 signature over the original hash does not cover the edited bytes,
the RFC 3161 token timestamps the original hash only (openssl rejects the edited file), and an edited sealed copy does
not even decrypt. The database half (triggers refusing UPDATE/DELETE of registered rows) is in
``tests/integration/provenance/test_tamper_db.py`` and ``tests/integration/test_audit_chain.py``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from hypothesis import given, settings
from hypothesis import strategies as st

from bridge.crypto.envelope import DataKey, EnvelopeError, Purpose, Sealed, open_sealed, seal
from bridge.provenance.manifest import matches
from bridge.provenance.signing import manifest_message, verify_signature
from bridge.provenance.tsa import TsaClient
from tests.openssl_tsa import LocalTsa

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "provenance"
MANIFEST = (FIXTURES / "manifest_v1_basic.canonical.json").read_bytes()
CONTENT_HASH = bytes.fromhex((FIXTURES / "manifest_v1_basic.sha256").read_text(encoding="ascii").strip())
_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
PUBLIC_KEY = _KEY.public_key().public_bytes_raw()
SIGNATURE = _KEY.sign(manifest_message(CONTENT_HASH))  # what the pipeline stored for this manifest


def edit(data: bytes, index: int, mask: int) -> bytes:
    edited = bytearray(data)
    edited[index % len(data)] ^= mask
    return bytes(edited)


@settings(max_examples=200, deadline=None)
@given(index=st.integers(min_value=0), mask=st.integers(min_value=1, max_value=255))
def test_any_one_byte_edit_breaks_the_hash_and_the_signature(index: int, mask: int) -> None:
    assert matches(MANIFEST, CONTENT_HASH)
    edited = edit(MANIFEST, index, mask)
    assert not matches(edited, CONTENT_HASH)
    assert verify_signature(PUBLIC_KEY, manifest_message(CONTENT_HASH), SIGNATURE)
    assert not verify_signature(PUBLIC_KEY, manifest_message(hashlib.sha256(edited).digest()), SIGNATURE)


def test_every_byte_of_the_sealed_copy_is_authenticated() -> None:
    key = DataKey(bytes(range(32)), b"wrapped", "local:test")
    proposal, version = uuid4(), uuid4()
    sealed = seal(key, MANIFEST, proposal_id=proposal, version_id=version, purpose=Purpose.MANIFEST)
    for index in range(len(sealed.ciphertext)):
        with pytest.raises(EnvelopeError):
            open_sealed(
                key,
                Sealed(sealed.nonce, edit(sealed.ciphertext, index, 0x80)),
                proposal_id=proposal,
                version_id=version,
                purpose=Purpose.MANIFEST,
            )


async def test_openssl_rejects_an_edited_manifest_against_the_stored_token(local_tsa: LocalTsa, tmp_path: Path) -> None:
    token = await TsaClient(["http://tsa.test/tsr"], transport=local_tsa.transport()).timestamp(CONTENT_HASH)
    tsr = tmp_path / "token.tsr"
    tsr.write_bytes(token.response)
    original, edited = tmp_path / "manifest.json", tmp_path / "edited.json"
    original.write_bytes(MANIFEST)
    edited.write_bytes(edit(MANIFEST, 42, 0x01))
    ok = local_tsa.run("ts", "-verify", "-data", str(original), "-in", str(tsr), "-CAfile", str(local_tsa.ca_pem))
    bad = local_tsa.run("ts", "-verify", "-data", str(edited), "-in", str(tsr), "-CAfile", str(local_tsa.ca_pem))
    assert ok.returncode == 0, ok.stderr.decode(errors="replace")
    assert bad.returncode != 0
