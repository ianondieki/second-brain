"""Developer verification D1: a Kenyan mobile number confirmed by a one-time code (REQ-PROV-04).

docs/spec/06 6.4 item 8 and ADR-002 item 3: D0 is a verified email; D1 adds a phone code sent through
``SmsProvider``; D1 is required to publish (register a proposal version) and to tag an organisation. Those routes
depend on ``require_d1`` (``D1Developer``), which answers 403 ``d1_required`` below D1 (AC-IP-5). D2 (KYC
``ManualReview``) follows in T2.10b.

Plain code and SQL decide (docs/spec/04 principle 1):

- Numbers normalise to E.164: ``+254`` and nine digits starting 7 or 1 (Kenyan mobiles), typed as ``07..``, ``01..``,
  ``254..`` or ``+254..`` with optional spaces, dots, hyphens or parentheses. Anything else is 422 ``invalid_phone``.
- A code is six random digits, valid 10 minutes, with 5 attempts. The row stores only HMAC-SHA-256 under
  ``SECRET_KEY`` (purpose ``phone_otp``, bound to the row id), inserted without RETURNING; Python never reads the
  digest back. ``app_confirm_phone_otp`` compares it in SQL with the database clock, counts the attempt and, on a
  match, raises the profile from D0 to D1 (``bridge_app`` has no UPDATE on ``verification_level``). The attempt counts
  even without a match, so the transaction is committed after every call.
- Sends are throttled on the ``login_attempts`` ledger (``bridge.auth.throttle``: HMAC keys, never raw values) per
  user, per number and per client IP: one per user a minute; 3 per user or number and 30 per IP in 15 minutes; 5 per
  user or number and 100 per IP a day. Concurrent requests count and record one after another: the profile row lock
  serialises one user's requests, and transaction-level advisory locks on the number's and the IP's digests serialise
  every account's requests for one number or from one IP. Locks are always taken in the same order (profile row, then
  the two advisory keys in ascending order), so two requests never wait on each other; COMMIT releases them.
- The code row, the throttle records and the audit event are committed before the SMS leaves, so a failed or slow send
  cannot be retried past the limits.
- Audit events carry the code's id and SHA-256(subject_salt || number); logs carry the code's id only. Neither ever
  holds the number, the code or the SMS text.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.audit.service import record as audit
from bridge.auth import throttle
from bridge.auth.crypto import keyed_digest
from bridge.auth.deps import CurrentSession, Db
from bridge.auth.models import User
from bridge.config import Settings
from bridge.errors import ApiError, forbidden
from bridge.ids import uuid7
from bridge.integrations.sms import SmsError, SmsMessage, SmsProvider
from bridge.logging import get_logger
from bridge.models.enums import DevVerification
from bridge.profiles.models import DeveloperProfile, PhoneVerification

OTP_DIGITS = 6
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5  # per code; enforced in SQL by app_confirm_phone_otp (revision 0002)
RESEND_AFTER = timedelta(minutes=1)
SEND_WINDOW = timedelta(minutes=15)
SENDS_PER_WINDOW = 3  # per user and per number
SENDS_PER_DAY = 5  # per user and per number
IP_SENDS_PER_WINDOW = 30  # generous for a shared campus NAT; bounds a script
IP_SENDS_PER_DAY = 100
DAY = timedelta(days=1)

_SEPARATORS = re.compile(r"[\s().\-]")
_KENYAN_MOBILE = re.compile(r"(?:\+254|254|0)([17][0-9]{8})")
_CODE = re.compile(r"[0-9]{6}")
_CONFIRM = text("SELECT app_confirm_phone_otp(:verification, :digest)")
_ADVISORY_LOCK = text("SELECT pg_advisory_xact_lock(:key)")


class InvalidPhoneError(ValueError):
    """Not a Kenyan mobile number in a form ``normalise_kenyan_mobile`` accepts."""


class VerificationError(Exception):
    """A refused verification step: ``status`` and the stable API ``code``, a message for people and extra keys."""

    def __init__(self, status: int, code: str, message: str, **extra: Any) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def api_error(self) -> ApiError:
        return ApiError(self.status, self.code, self.message, **self.extra)


@dataclass(frozen=True, slots=True)
class CodeSent:
    verification_id: UUID
    expires_at: datetime
    phone_masked: str


@dataclass(frozen=True, slots=True)
class _CodeState:
    phone_e164: str
    attempts: int
    expires_at: datetime
    verified_at: datetime | None


def normalise_kenyan_mobile(raw: str) -> str:
    """``+254`` followed by the nine-digit mobile number (7xx or 1xx). Raises ``InvalidPhoneError`` otherwise."""
    compact = _SEPARATORS.sub("", raw.strip())
    match = _KENYAN_MOBILE.fullmatch(compact) if compact.isascii() else None
    if match is None:
        raise InvalidPhoneError("not a Kenyan mobile number")
    return f"+254{match.group(1)}"


def new_code() -> str:
    return f"{secrets.randbelow(10**OTP_DIGITS):0{OTP_DIGITS}d}"


def otp_digest(secret: str, verification_id: UUID, code: str) -> bytes:
    """HMAC-SHA-256 under ``SECRET_KEY``: what the row stores and what ``app_confirm_phone_otp`` compares. Keyed, so a
    copy of the table does not give up a six-digit code to an offline search."""
    return keyed_digest(secret, "phone_otp", f"{verification_id}:{code}")


def phone_digest(subject_salt: bytes, phone_e164: str) -> str:
    """The number as audit payloads carry it (docs/spec/06 6.4 item 4): SHA-256(subject_salt || number), hex."""
    return hashlib.sha256(subject_salt + phone_e164.encode("ascii")).hexdigest()


def mask_phone(phone_e164: str) -> str:
    return phone_e164[:4] + "*" * (len(phone_e164) - 7) + phone_e164[-3:]


def sms_text(code: str) -> str:
    """The fixed SMS wording. [[COPY-REVIEW]] (English only until the Swahili catalogue; the product name is the
    working name): no link, no claim, one GSM-7 segment."""
    minutes = int(OTP_TTL.total_seconds() // 60)
    return f"{code} is your Bridge verification code. It expires in {minutes} minutes. Do not share it with anyone."


def _secret(settings: Settings) -> str:
    return settings.secret_key.get_secret_value()


async def _level(db: AsyncSession, user_id: UUID, *, lock: bool = False) -> DevVerification | None:
    stmt = select(DeveloperProfile.verification_level).where(DeveloperProfile.user_id == user_id)
    if lock:  # serialises one user's concurrent requests, so both cannot pass the throttle before either commits
        stmt = stmt.with_for_update()
    level: DevVerification | None = (await db.execute(stmt)).scalar_one_or_none()
    return level


def advisory_key(digest: bytes) -> int:
    """The signed 64-bit ``pg_advisory_xact_lock`` key for a keyed digest (its first eight bytes)."""
    return int.from_bytes(digest[:8], "big", signed=True)


async def _lock_number_and_ip(db: AsyncSession, number_keys: throttle.Keys) -> None:
    """Hold the number's and the client IP's advisory locks until COMMIT, so requests from several accounts for one
    number, or from one IP, cannot all pass the limits before any of them has recorded its send. Ascending key order
    is one total order for every request, so no two requests can each hold the lock the other waits for."""
    for key in sorted({advisory_key(number_keys.email), advisory_key(number_keys.ip)}):
        await db.execute(_ADVISORY_LOCK, {"key": key})


async def _code_state(db: AsyncSession, user_id: UUID, verification_id: UUID) -> _CodeState | None:
    """The caller's code row without its digest (RLS limits the read to the caller's rows as well)."""
    stmt = select(
        PhoneVerification.phone_e164,
        PhoneVerification.attempts,
        PhoneVerification.expires_at,
        PhoneVerification.verified_at,
    ).where(PhoneVerification.id == verification_id, PhoneVerification.user_id == user_id)
    row = (await db.execute(stmt)).one_or_none()
    return None if row is None else _CodeState(*row)


async def _audit_code(
    db: AsyncSession, action: str, user_id: UUID, verification_id: UUID, payload: dict[str, Any]
) -> None:
    await audit(
        db,
        action,
        actor_user_id=user_id,
        subject_type="phone_verification",
        subject_id=verification_id,
        payload=payload,
    )


async def _over_limits(db: AsyncSession, keys: throttle.Keys) -> bool:
    return await throttle.blocked(
        db,
        keys,
        pair_limit=SENDS_PER_WINDOW,
        window=SEND_WINDOW,
        account_limit=SENDS_PER_WINDOW,
        ip_limit=IP_SENDS_PER_WINDOW,
    ) or await throttle.blocked(
        db, keys, pair_limit=SENDS_PER_DAY, window=DAY, account_limit=SENDS_PER_DAY, ip_limit=IP_SENDS_PER_DAY
    )


async def request_code(
    db: AsyncSession, settings: Settings, sms: SmsProvider, *, user: User, phone: str, ip: str
) -> CodeSent:
    """Issue a D1 code for ``phone`` and send it by SMS. The code row, the throttle records and the audit event are
    committed before the send; a refusal raises ``VerificationError`` with nothing written."""
    log = get_logger("bridge.profiles.verification")
    try:
        number = normalise_kenyan_mobile(phone)
    except InvalidPhoneError as exc:
        raise VerificationError(422, "invalid_phone", "Enter a Kenyan mobile number, such as 0712 345 678.") from exc
    level = await _level(db, user.id, lock=True)
    if level is None:
        raise VerificationError(404, "not_found", "No developer profile.")
    if level != DevVerification.D0:
        raise VerificationError(409, "already_verified", "Your mobile number is already verified.")
    secret = _secret(settings)
    user_keys = throttle.keys(secret, "phone_otp_user", str(user.id), ip)
    number_keys = throttle.keys(secret, "phone_otp_number", number, ip)
    await _lock_number_and_ip(db, number_keys)  # after the profile row lock, before counting
    if await throttle.account_count(db, user_keys, window=RESEND_AFTER) > 0:
        log.info("verification.sms_throttled", reason="resend_too_soon")
        raise VerificationError(
            429,
            "resend_too_soon",
            "Wait a minute before asking for another code.",
            retry_after_seconds=int(RESEND_AFTER.total_seconds()),
        )
    if await _over_limits(db, user_keys) or await _over_limits(db, number_keys):
        log.info("verification.sms_throttled", reason="too_many_codes")
        raise VerificationError(429, "too_many_codes", "Too many codes were requested. Try again later.")

    throttle.record(db, user_keys, succeeded=True)
    throttle.record(db, number_keys, succeeded=True)
    verification_id, code = uuid7(), new_code()
    expires_at = clock.utcnow() + OTP_TTL
    # No RETURNING: bridge_app need not (and after the 0002 fix cannot) read otp_hash back.
    await db.execute(
        insert(PhoneVerification).values(
            id=verification_id,
            user_id=user.id,
            phone_e164=number,
            otp_hash=otp_digest(secret, verification_id, code),
            expires_at=expires_at,
        )
    )
    payload = {"phone_digest": phone_digest(user.subject_salt, number)}
    await _audit_code(db, "verification.phone_code_sent", user.id, verification_id, payload)
    await db.commit()

    try:
        await sms.send(SmsMessage(to=number, text=sms_text(code)))
    except SmsError as exc:
        log.warning(
            "verification.sms_failed",
            verification_id=str(verification_id),
            provider=sms.name,
            transient=exc.transient,
            provider_status=exc.code,
        )
        raise VerificationError(503, "sms_unavailable", "We could not send the SMS. Try again in a minute.") from exc
    log.info("verification.sms_sent", verification_id=str(verification_id), provider=sms.name)
    return CodeSent(verification_id, expires_at, mask_phone(number))


def _refuse_if_closed(state: _CodeState) -> None:
    if state.verified_at is not None:
        raise VerificationError(409, "already_verified", "Your mobile number is already verified.")
    if state.attempts >= OTP_MAX_ATTEMPTS:
        raise VerificationError(429, "code_locked", "Too many wrong codes. Ask for a new code.")
    if state.expires_at <= clock.utcnow():
        raise VerificationError(400, "code_expired", "This code has expired. Ask for a new code.")


def _refusal(before: _CodeState, after: _CodeState) -> VerificationError:
    """Why ``app_confirm_phone_otp`` said no. It refuses without counting only a code that is verified, locked or
    expired by the database clock."""
    if after.verified_at is not None:
        return VerificationError(409, "already_verified", "Your mobile number is already verified.")
    if after.attempts >= OTP_MAX_ATTEMPTS:
        return VerificationError(429, "code_locked", "Too many wrong codes. Ask for a new code.")
    if after.attempts == before.attempts:
        return VerificationError(400, "code_expired", "This code has expired. Ask for a new code.")
    return VerificationError(
        400,
        "invalid_code",
        "That code is not right. Check the SMS and try again.",
        attempts_left=OTP_MAX_ATTEMPTS - after.attempts,
    )


async def confirm_code(
    db: AsyncSession, settings: Settings, *, user: User, verification_id: UUID, code: str
) -> DevVerification:
    """Check ``code`` against one of the caller's codes in SQL and commit (the attempt counts even when the code is
    wrong). Returns the caller's new level; raises ``VerificationError`` otherwise."""
    compact = "".join(code.split())
    if not _CODE.fullmatch(compact):
        raise VerificationError(422, "invalid_code_format", "Enter the 6-digit code from the SMS.")
    before = await _code_state(db, user.id, verification_id)
    if before is None:
        raise VerificationError(404, "not_found", "Not found.")
    _refuse_if_closed(before)

    digest = otp_digest(_secret(settings), verification_id, compact)
    matched = bool((await db.execute(_CONFIRM, {"verification": verification_id, "digest": digest})).scalar_one())
    after = await _code_state(db, user.id, verification_id)
    assert after is not None  # the row was visible a moment ago and the app never deletes it
    if matched:
        verified = {"phone_digest": phone_digest(user.subject_salt, after.phone_e164), "level": "d1"}
        await _audit_code(db, "verification.phone_verified", user.id, verification_id, verified)
        await db.commit()
        return await _level(db, user.id) or DevVerification.D1
    if after.attempts > before.attempts:
        failed = {"attempts": after.attempts, "locked": after.attempts >= OTP_MAX_ATTEMPTS}
        await _audit_code(db, "verification.phone_code_failed", user.id, verification_id, failed)
    await db.commit()  # the counted attempt must survive the refusal
    raise _refusal(before, after)


async def require_d1(live: CurrentSession, db: Db) -> DeveloperProfile:
    """Guard for publishing (registering a proposal version) and tagging: 403 ``d1_required`` unless the signed-in
    user's developer profile is at D1 or above (AC-IP-5). Reads the level fresh from the database."""
    profile = await db.get(DeveloperProfile, live.user.id, populate_existing=True)
    if profile is None or profile.verification_level == DevVerification.D0:
        raise forbidden("d1_required", "Verify your mobile number to publish or tag.")
    return profile


D1Developer = Annotated[DeveloperProfile, Depends(require_d1)]


def get_sms_provider(request: Request) -> SmsProvider:
    provider: SmsProvider = request.app.state.sms_provider
    return provider


SmsDep = Annotated[SmsProvider, Depends(get_sms_provider)]
