"""REQ-AUTH-01: token storage, AES-GCM secrets, argon2id parameters and the password rules."""

from __future__ import annotations

import base64

import pytest
from cryptography.exceptions import InvalidTag

from bridge.auth import passwords
from bridge.auth.crypto import decode_key, decrypt, encrypt, keyed_digest, new_token, token_hash

KEY = base64.b64encode(bytes(range(32))).decode()


def test_tokens_are_long_random_and_stored_hashed() -> None:
    a, b = new_token(), new_token()
    assert a != b
    assert len(a) >= 43
    assert token_hash(a) != token_hash(b)
    assert len(token_hash(a)) == 32


def test_keyed_digest_depends_on_key_and_purpose() -> None:
    assert keyed_digest("k1", "login", "a@b.c") != keyed_digest("k2", "login", "a@b.c")
    assert keyed_digest("k1", "login", "a@b.c") != keyed_digest("k1", "magic", "a@b.c")


def test_encryption_round_trip_and_context_binding() -> None:
    key = decode_key(KEY)
    blob = encrypt(key, b"JBSWY3DPEHPK3PXP", b"user-1")
    assert decrypt(key, blob, b"user-1") == b"JBSWY3DPEHPK3PXP"
    with pytest.raises(InvalidTag):
        decrypt(key, blob, b"user-2")  # a secret copied to another account does not decrypt


@pytest.mark.parametrize("bad", ["not base64!", base64.b64encode(b"short").decode()])
def test_bad_encryption_keys_are_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="DATA_ENCRYPTION_KEY"):
        decode_key(bad)


def test_argon2id_parameters_match_the_spec() -> None:
    encoded = passwords.hash_password("correct horse battery staple")
    assert encoded.startswith("$argon2id$")
    assert "m=65536,t=3" in encoded


def test_verify_password() -> None:
    encoded = passwords.hash_password("correct horse battery staple")
    assert passwords.verify_password(encoded, "correct horse battery staple")
    assert not passwords.verify_password(encoded, "wrong horse battery staple")
    assert not passwords.verify_password(None, "anything at all here")
    assert not passwords.verify_password("not-a-hash", "anything at all here")


@pytest.mark.parametrize(
    ("password", "ok"),
    [("short", False), ("x" * 11, False), ("x" * 12, True), ("x" * 129, False), ("me@example.com12", True)],
)
def test_password_policy(password: str, ok: bool) -> None:
    if ok:
        passwords.check_policy(password, email="me@example.com")
    else:
        with pytest.raises(passwords.PasswordPolicyError):
            passwords.check_policy(password, email="me@example.com")


def test_password_may_not_be_the_email() -> None:
    with pytest.raises(passwords.PasswordPolicyError):
        passwords.check_policy("Longer.Email@Example.com", email="longer.email@example.com")
