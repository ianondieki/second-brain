"""Password hashing with argon2id (docs/spec/08 Auth: m=64 MiB, t=3) and the password rules (OWASP ASVS L2)."""

from __future__ import annotations

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

MIN_LENGTH = 12
MAX_LENGTH = 128

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4, hash_len=32, salt_len=16, type=Type.ID)
# Verified against when the account has no password, so a missing account costs the same time as a wrong password.
_DUMMY_HASH = _hasher.hash("dummy password for timing equalisation")


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str, *, email: str = "") -> None:
    """Length only (no composition rules, ASVS 2.1): 12-128 characters, not the email address itself."""
    if len(password) < MIN_LENGTH:
        raise PasswordPolicyError(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise PasswordPolicyError(f"Use at most {MAX_LENGTH} characters.")
    if email and password.strip().lower() == email.strip().lower():
        raise PasswordPolicyError("Do not use your email address as your password.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """Constant-effort check: a missing hash still runs one argon2 verification and then fails."""
    try:
        matched = _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return matched and password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


async def hash_password_async(password: str) -> str:
    """argon2id costs ~100 ms and 64 MiB: run it off the event loop so one signup cannot stall every request."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str | None, password: str) -> bool:
    return await asyncio.to_thread(verify_password, password_hash, password)
