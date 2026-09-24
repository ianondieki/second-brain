"""REQ-AUTH-01: TOTP windows and replay, recovery codes, signed double-submit CSRF tokens."""

from __future__ import annotations

from bridge.auth import csrf, totp

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
NOW = 1_790_000_000.0


def test_current_and_adjacent_windows_are_accepted() -> None:
    counter = int(NOW // 30)
    for step in (-1, 0, 1):
        assert totp.verify(SECRET, totp.code_at(SECRET, counter + step), last_counter=None, now=NOW).ok
    assert not totp.verify(SECRET, totp.code_at(SECRET, counter + 2), last_counter=None, now=NOW).ok


def test_a_code_cannot_be_replayed() -> None:
    counter = int(NOW // 30)
    code = totp.code_at(SECRET, counter)
    first = totp.verify(SECRET, code, last_counter=None, now=NOW)
    assert first.ok
    assert first.counter == counter
    assert not totp.verify(SECRET, code, last_counter=first.counter, now=NOW).ok


def test_malformed_codes_are_rejected() -> None:
    assert not totp.verify(SECRET, "12345", last_counter=None, now=NOW).ok
    assert not totp.verify(SECRET, "abcdef", last_counter=None, now=NOW).ok


def test_provisioning_uri_names_issuer_and_account() -> None:
    uri = totp.provisioning_uri(SECRET, "dev@example.com", "Bridge (working name)")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=Bridge" in uri


def test_recovery_codes_work_once() -> None:
    codes = totp.new_recovery_codes()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    stored = [totp.recovery_hash(c) for c in codes]
    remaining = totp.use_recovery_code(stored, codes[3].upper())
    assert remaining is not None
    assert len(remaining) == 9
    assert totp.use_recovery_code(remaining, codes[3]) is None


def test_csrf_token_is_bound_to_the_session() -> None:
    session_a, session_b = csrf.binding_for("token-a"), csrf.binding_for("token-b")
    token = csrf.issue("key", session_a)
    assert csrf.is_valid("key", token, session_a)
    assert not csrf.is_valid("key", token, session_b)
    assert not csrf.is_valid("other-key", token, session_a)
    assert not csrf.is_valid("key", "forged.value", session_a)


def test_csrf_request_rules() -> None:
    binding = csrf.binding_for(None)
    token = csrf.issue("key", binding)
    assert csrf.request_passes("key", method="GET", cookie=None, header=None, binding=binding)
    assert csrf.request_passes("key", method="POST", cookie=token, header=token, binding=binding)
    assert not csrf.request_passes("key", method="POST", cookie=token, header=None, binding=binding)
    assert not csrf.request_passes("key", method="DELETE", cookie=token, header=token + "x", binding=binding)
    assert not csrf.request_passes("key", method="POST", cookie=None, header=token, binding=binding)
