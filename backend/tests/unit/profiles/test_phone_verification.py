"""REQ-PROV-04 (D1): Kenyan mobile numbers to E.164, the code digest and the fixed SMS wording."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from bridge.integrations.sms import MAX_SMS_CHARS, SmsMessage
from bridge.profiles.verification import (
    OTP_DIGITS,
    InvalidPhoneError,
    _CodeState,
    _refusal,
    advisory_key,
    mask_phone,
    new_code,
    normalise_kenyan_mobile,
    otp_digest,
    sms_text,
)

SECRET = "test-secret-key-0123456789abcdef0123456789"
VERIFICATION = UUID("01920000-0000-7000-8000-000000000001")
# 0712345678 in other scripts' digits: str.isdigit() accepts them, the normaliser must not.
ARABIC_INDIC = "".join(chr(0x0660 + int(d)) for d in "0712345678")
FULLWIDTH = "".join(chr(0xFF10 + int(d)) for d in "0712345678")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0712345678", "+254712345678"),
        ("0112345678", "+254112345678"),
        ("0722 000 111", "+254722000111"),
        ("0110-123-456", "+254110123456"),
        ("(0712) 345.678", "+254712345678"),
        ("254712345678", "+254712345678"),
        ("254 112 345 678", "+254112345678"),
        ("+254712345678", "+254712345678"),
        ("+254 712 345 678", "+254712345678"),
        ("  +254-110-000-000 ", "+254110000000"),
    ],
)
def test_kenyan_mobile_numbers_become_e164(raw: str, expected: str) -> None:
    assert normalise_kenyan_mobile(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("", id="empty"),
        pytest.param("0712 34567", id="nine-digits-national"),
        pytest.param("07123456789", id="eleven-digits-national"),
        pytest.param("0201234567", id="nairobi-landline"),
        pytest.param("0412345678", id="mombasa-landline"),
        pytest.param("712345678", id="no-trunk-prefix"),
        pytest.param("+255712345678", id="tanzania"),
        pytest.param("+14155550123", id="united-states"),
        pytest.param("00254712345678", id="international-00-prefix"),
        pytest.param("+2540712345678", id="trunk-zero-after-country-code"),
        pytest.param("+254 712 345 67a", id="letter"),
        pytest.param("+254712345678 ext 1", id="extension"),
        pytest.param(ARABIC_INDIC, id="arabic-indic-digits"),
        pytest.param(FULLWIDTH, id="fullwidth-digits"),
        pytest.param("07 12 34 56 78 +", id="stray-plus"),
        pytest.param("++254712345678", id="double-plus"),
    ],
)
def test_anything_else_is_refused(raw: str) -> None:
    with pytest.raises(InvalidPhoneError):
        normalise_kenyan_mobile(raw)


def test_codes_are_six_random_digits() -> None:
    codes = {new_code() for _ in range(200)}
    assert all(len(c) == OTP_DIGITS and c.isascii() and c.isdigit() for c in codes)
    assert len(codes) > 150  # not a constant, not a short cycle


def test_the_digest_is_a_keyed_hmac_bound_to_the_code_row() -> None:
    digest = otp_digest(SECRET, VERIFICATION, "123456")
    assert len(digest) == 32
    assert digest == otp_digest(SECRET, VERIFICATION, "123456")
    assert digest != otp_digest(SECRET, VERIFICATION, "123457")
    assert digest != otp_digest(SECRET, UUID("01920000-0000-7000-8000-000000000002"), "123456")
    assert digest != otp_digest("another-secret-key-0123456789abcdef0123", VERIFICATION, "123456")
    assert digest != hashlib.sha256(b"123456").digest()  # never an unkeyed hash: six digits are guessable offline


def test_the_mask_keeps_only_the_country_code_and_last_three_digits() -> None:
    assert mask_phone("+254712345678") == "+254******678"


def test_the_sms_is_one_short_segment_with_the_code_and_the_expiry() -> None:
    text = sms_text("004213")
    assert "004213" in text
    assert "10 minutes" in text
    assert len(text) <= MAX_SMS_CHARS
    SmsMessage(to="+254712345678", text=text)  # passes the seam's own checks


def test_refusals_report_what_the_database_decided() -> None:
    before = _CodeState("+254712345678", 1, datetime.now(UTC), None)
    assert _refusal(before, replace(before, verified_at=datetime.now(UTC))).code == "already_verified"  # a race won
    assert _refusal(before, replace(before, attempts=5)).code == "code_locked"
    assert _refusal(before, before).code == "code_expired"  # refused without counting: the database clock said so
    wrong = _refusal(before, replace(before, attempts=2))
    assert (wrong.status, wrong.code, wrong.extra) == (400, "invalid_code", {"attempts_left": 3})


def test_advisory_keys_are_stable_signed_64_bit_integers() -> None:
    digest = otp_digest(SECRET, VERIFICATION, "123456")
    assert advisory_key(digest) == advisory_key(digest) == int.from_bytes(digest[:8], "big", signed=True)
    assert advisory_key(b"\xff" * 32) == -1  # pg_advisory_xact_lock takes a signed bigint
    assert advisory_key(b"\x7f" + b"\xff" * 31) == 2**63 - 1


def test_the_code_state_repr_leaves_the_number_out() -> None:
    state = _CodeState("+254712345678", 2, datetime(2026, 9, 28, 12, 0, tzinfo=UTC), None)
    for shown in (repr(state), str(state), f"{state!r}"):
        assert "712345678" not in shown
        assert "attempts=2" in shown
    assert state.phone_e164 == "+254712345678"
    assert state == _CodeState("+254712345678", 2, state.expires_at, None)
    assert state != replace(state, phone_e164="+254712345679")  # still compared, only hidden
