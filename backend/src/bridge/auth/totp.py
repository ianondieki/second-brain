"""TOTP (RFC 6238: SHA-1, 6 digits, 30 s) with replay protection and one-time recovery codes (REQ-AUTH-01)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

import pyotp

DIGITS = 6
PERIOD = 30
DRIFT_STEPS = 1  # accept the previous and the next 30-second window
RECOVERY_CODES = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i


def new_secret() -> str:
    return str(pyotp.random_base32(length=32))


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    return str(pyotp.TOTP(secret, digits=DIGITS, interval=PERIOD).provisioning_uri(name=account, issuer_name=issuer))


def code_at(secret: str, counter: int) -> str:
    return str(pyotp.TOTP(secret, digits=DIGITS, interval=PERIOD).generate_otp(counter))


@dataclass(frozen=True, slots=True)
class TotpCheck:
    ok: bool
    counter: int | None = None


def verify(secret: str, code: str, *, last_counter: int | None, now: float | None = None) -> TotpCheck:
    """Accept a code from the current window +/- one step, never one at or before ``last_counter`` (no replay)."""
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) != DIGITS:
        return TotpCheck(False)
    current = int((time.time() if now is None else now) // PERIOD)
    for counter in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(code_at(secret, counter), digits):
            return TotpCheck(True, counter)
    return TotpCheck(False)


def new_recovery_codes() -> list[str]:
    """Ten codes like ``k7mq-x2pd``; shown once, stored only as SHA-256 hex."""
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def recovery_hash(code: str) -> str:
    normalised = code.strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def use_recovery_code(stored: list[str], code: str) -> list[str] | None:
    """Return the remaining hashes after spending ``code``, or None when it is not a valid unused code."""
    wanted = recovery_hash(code)
    for index, candidate in enumerate(stored):
        if hmac.compare_digest(candidate, wanted):
            return stored[:index] + stored[index + 1 :]
    return None
