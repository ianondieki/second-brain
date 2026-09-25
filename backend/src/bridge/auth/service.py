"""Account flows (REQ-AUTH-01): signup, email verification, password and magic-link login, TOTP, step-up.

Plain code decides every outcome (docs/spec/04 principle 1). Responses never reveal whether an email address has an
account: signup, magic-link and resend requests always answer "check your email", do the same argon2 work on every
path, and hand their emails to ``bridge.auth.mailer`` to send after the response.

Pre-hijacking defence (security review of T1.5): a password chosen before the address is verified only survives if the
verification link is opened in the browser that signed up (``bridge_signup`` cookie binding); otherwise verification
clears it and the owner sets their own. A repeat signup of an unverified address replaces the stored password.
"""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.audit.service import record as audit
from bridge.auth import emails, passwords, sessions, throttle, totp
from bridge.auth.cookies import signup_binding
from bridge.auth.crypto import decode_key, decrypt, encrypt, new_token, token_hash
from bridge.auth.mailer import PendingEmail
from bridge.auth.models import LoginToken, User
from bridge.auth.schemas import SignupRequest
from bridge.billing.service import start_free_subscription
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements.calendar import local_date
from bridge.ids import uuid7
from bridge.models.enums import MFA_REQUIRED_ORG_ROLES, LoginTokenPurpose, MembershipStatus, PlanSide, UserStatus
from bridge.notifications.email import is_mailbox
from bridge.profiles.consents import consents_version, record_decisions, terms_version
from bridge.profiles.models import DeveloperProfile
from bridge.tenancy.models import Membership
from bridge.tenancy.service import create_organization

SIGNUP_LIMIT = 3  # per (address, IP) in SIGNUP_WINDOW; also bounds "you already have an account" emails
SIGNUP_WINDOW = timedelta(minutes=15)
MAGIC_LIMIT = 3
MAGIC_WINDOW = timedelta(minutes=15)
REAUTH_WINDOW = timedelta(minutes=15)  # a session this new may change credentials without the current password


class AuthError(Exception):
    """A refused auth action; ``code`` is the stable API error code. ``pending`` emails still go out."""

    def __init__(
        self, code: str, status: int = 400, pending: list[PendingEmail] | None = None, verify_token: str | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.pending = pending or []
        self.verify_token = verify_token  # bind to this browser: it just proved the password


@dataclass(slots=True)
class LoginOutcome:
    session: sessions.LiveSession
    mfa_required: bool


@dataclass(slots=True)
class SignupOutcome:
    pending: list[PendingEmail] = field(default_factory=list)
    verify_token: str | None = None  # bound to the signing-up browser by the router's bridge_signup cookie


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def _user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == normalise_email(email)))).scalar_one_or_none()


def _link(settings: Settings, token: str) -> str:
    # The token travels in the fragment, which browsers never send to servers or in Referer headers.
    return f"{settings.public_base_url.rstrip('/')}/auth/link#token={token}"


async def _issue_link(db: AsyncSession, settings: Settings, user: User, purpose: LoginTokenPurpose) -> str:
    """A fresh single-use token; earlier unused tokens of the same purpose stop working."""
    now = clock.utcnow()
    await db.execute(
        update(LoginToken)
        .where(LoginToken.user_id == user.id, LoginToken.purpose == purpose, LoginToken.used_at.is_(None))
        .values(used_at=now)
    )
    token = new_token()
    db.add(
        LoginToken(
            user_id=user.id,
            token_hash=token_hash(token),
            purpose=purpose,
            expires_at=now + timedelta(minutes=settings.magic_link_ttl_minutes),
        )
    )
    await db.flush()
    return token


def _handle_from(display_name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")[:24] or "dev"
    return f"{base}-{secrets.token_hex(3)}"


def _slug_from(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "org"
    return f"{base}-{secrets.token_hex(3)}"


def _validate_signup(settings: Settings, req: SignupRequest, email: str) -> None:
    if not is_mailbox(email):
        # Only plain ASCII mailboxes can be emailed safely (no encoded words, quoted or Unicode local parts).
        raise AuthError("invalid_email", 422)
    if not req.accept_terms:
        raise AuthError("terms_not_accepted", 422)
    if req.side == "org" and req.org is None:
        raise AuthError("org_details_required", 422)
    if req.consents_version is not None and req.consents_version != consents_version(settings):
        raise AuthError("consent_text_changed", 409)
    try:
        passwords.check_policy(req.password, email=email)
    except passwords.PasswordPolicyError as exc:
        raise AuthError("weak_password", 422) from exc


def _verify_email(settings: Settings, user: User, token: str) -> PendingEmail:
    wording = emails.verify_email(settings.product_name, _link(settings, token), settings.magic_link_ttl_minutes)
    return PendingEmail(user.id, user.email, wording, "auth.verify_email")


async def _existing_account(db: AsyncSession, settings: Settings, user: User, password_hash: str) -> SignupOutcome:
    await bind_tenant(db, user_id=user.id)
    if user.email_verified_at is None:
        # Unverified: this signup's password replaces the stored one and earlier links stop working.
        user.password_hash = password_hash
        token = await _issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
        return SignupOutcome([_verify_email(settings, user, token)], token)
    login_url = f"{settings.public_base_url.rstrip('/')}/login"
    wording = emails.account_exists(settings.product_name, login_url)
    dedupe = f"auth.account_exists:{user.id}:{local_date(clock.utcnow()).isoformat()}"  # at most one a day
    return SignupOutcome([PendingEmail(user.id, user.email, wording, "auth.account_exists", dedupe)])


async def signup(db: AsyncSession, settings: Settings, req: SignupRequest, ip: str) -> SignupOutcome:
    """Create an unverified account (developer, or organisation owner) and return the verification email to send."""
    email = normalise_email(req.email)
    _validate_signup(settings, req, email)
    keys = throttle.keys(settings.secret_key.get_secret_value(), "signup", email, ip)
    if await throttle.blocked(db, keys, pair_limit=SIGNUP_LIMIT, window=SIGNUP_WINDOW):
        return SignupOutcome()  # silent: same answer, no email (stops email bombing through signup)
    throttle.record(db, keys, succeeded=True)
    password_hash = await passwords.hash_password_async(req.password)  # on every path: timing reveals nothing

    existing = await _user_by_email(db, email)
    if existing is not None:
        return await _existing_account(db, settings, existing, password_hash)

    user = User(
        id=uuid7(), email=email, password_hash=password_hash, display_name=req.display_name.strip(), locale=req.locale
    )
    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError:
        # A concurrent signup created the address first: answer exactly as for an existing account.
        existing = await _user_by_email(db, email)
        if existing is None:
            raise
        return await _existing_account(db, settings, existing, password_hash)
    await bind_tenant(db, user_id=user.id)

    org_id: UUID | None = None
    if req.side == "developer":
        db.add(DeveloperProfile(user_id=user.id, handle=_handle_from(user.display_name)))
        await db.flush()
        await start_free_subscription(db, settings, side=PlanSide.DEVELOPER, user_id=user.id)
    else:
        assert req.org is not None
        org_id = await create_organization(
            db, kind=req.org.kind, legal_name=req.org.legal_name, slug=_slug_from(req.org.legal_name)
        )
        await start_free_subscription(db, settings, side=PlanSide.ORG, org_id=org_id)

    await record_decisions(db, settings, user_id=user.id, decisions=req.consents, source="signup")
    await audit(
        db,
        "auth.signup",
        actor_user_id=user.id,
        org_id=org_id,
        subject_type="user",
        subject_id=user.id,
        payload={
            "side": req.side,
            "terms_version": terms_version(settings),
            "consents_version": consents_version(settings),
        },
    )
    token = await _issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
    return SignupOutcome([_verify_email(settings, user, token)], token)


async def request_magic_link(db: AsyncSession, settings: Settings, email: str, ip: str) -> list[PendingEmail]:
    """A sign-in link (or a verification link for an unverified account). Silent when throttled or unknown."""
    email = normalise_email(email)
    keys = throttle.keys(settings.secret_key.get_secret_value(), "magic", email, ip)
    if await throttle.blocked(db, keys, pair_limit=MAGIC_LIMIT, window=MAGIC_WINDOW):
        return []
    throttle.record(db, keys, succeeded=True)
    user = await _user_by_email(db, email)
    if user is None or user.status != UserStatus.ACTIVE:
        return []
    await bind_tenant(db, user_id=user.id)
    if user.email_verified_at is None:
        return [_verify_email(settings, user, await _issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL))]
    token = await _issue_link(db, settings, user, LoginTokenPurpose.LOGIN)
    wording = emails.login_link(settings.product_name, _link(settings, token), settings.magic_link_ttl_minutes)
    return [PendingEmail(user.id, user.email, wording, "auth.login_link")]


async def _start_session(db: AsyncSession, settings: Settings, user: User, user_agent: str | None) -> LoginOutcome:
    mfa = user.totp_enabled_at is not None
    live = await sessions.create(
        db, user, ttl=timedelta(days=settings.session_ttl_days), mfa_pending=mfa, user_agent=user_agent
    )
    await bind_tenant(db, user_id=user.id)
    return LoginOutcome(live, mfa_required=mfa)


async def consume_link(
    db: AsyncSession, settings: Settings, token: str, user_agent: str | None, signup_cookie: str | None
) -> LoginOutcome:
    """Spend a magic-link token once (row locked): verify the email if needed and sign in."""
    row = (
        await db.execute(select(LoginToken).where(LoginToken.token_hash == token_hash(token)).with_for_update())
    ).scalar_one_or_none()
    now = clock.utcnow()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise AuthError("invalid_or_expired_link", 400)
    row.used_at = now
    user = await db.get(User, row.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise AuthError("invalid_or_expired_link", 400)
    await bind_tenant(db, user_id=user.id)
    if user.email_verified_at is None:
        bound = row.purpose == LoginTokenPurpose.VERIFY_EMAIL and hmac.compare_digest(
            signup_cookie or "", signup_binding(settings, token)
        )
        if not bound:
            user.password_hash = None  # a password set before verification from another browser is not trusted
        user.email_verified_at = now
        await sessions.revoke_all(db, user.id)
    outcome = await _start_session(db, settings, user, user_agent)
    await audit(
        db,
        "auth.login",
        actor_user_id=user.id,
        subject_type="user",
        subject_id=user.id,
        payload={"method": row.purpose.value},
    )
    return outcome


async def login(
    db: AsyncSession, settings: Settings, email: str, password: str, ip: str, user_agent: str | None
) -> LoginOutcome:
    keys = throttle.keys(settings.secret_key.get_secret_value(), "login", email, ip)
    if await throttle.blocked(db, keys, pair_limit=settings.login_attempts_per_minute):
        raise AuthError("too_many_attempts", 429)
    user = await _user_by_email(db, email)
    ok = await passwords.verify_password_async(user.password_hash if user else None, password)
    throttle.record(db, keys, succeeded=ok)
    if user is None or not ok or user.status != UserStatus.ACTIVE:
        raise AuthError("invalid_credentials", 401)
    if user.email_verified_at is None:
        await bind_tenant(db, user_id=user.id)
        token = await _issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
        raise AuthError("email_unverified", 403, pending=[_verify_email(settings, user, token)], verify_token=token)
    if user.password_hash and passwords.needs_rehash(user.password_hash):
        user.password_hash = await passwords.hash_password_async(password)
    outcome = await _start_session(db, settings, user, user_agent)
    await audit(
        db, "auth.login", actor_user_id=user.id, subject_type="user", subject_id=user.id, payload={"method": "password"}
    )
    return outcome


def _key(settings: Settings) -> bytes:
    return decode_key(settings.data_encryption_key.get_secret_value())


def _secret(settings: Settings, user: User, blob: bytes) -> str:
    return decrypt(_key(settings), blob, user.id.bytes).decode("ascii")


def is_recovery_code(code: str) -> bool:
    """Recovery codes contain letters or a hyphen; a TOTP code is six digits, possibly typed with spaces."""
    compact = "".join(code.split())
    return "-" in compact or any(ch.isalpha() for ch in compact)


def check_second_factor(settings: Settings, user: User, code: str) -> bool:
    """Verify a TOTP code (with replay protection) or spend a recovery code. Mutates the user row on success.
    The caller must hold the user row locked (``lock_user``) so two requests cannot spend one code."""
    if user.totp_secret_enc is None:
        return False
    if is_recovery_code(code):
        remaining = totp.use_recovery_code(
            list(user.totp_recovery_hashes), code, settings.secret_key.get_secret_value()
        )
        if remaining is None:
            return False
        user.totp_recovery_hashes = remaining
        return True
    check = totp.verify(_secret(settings, user, user.totp_secret_enc), code, last_counter=user.totp_last_counter)
    if check.ok:
        user.totp_last_counter = check.counter
    return check.ok


async def lock_user(db: AsyncSession, user_id: UUID) -> User:
    """Reload the user row FOR UPDATE (serialises TOTP counters, recovery codes and credential changes)."""
    stmt = select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def complete_mfa(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, code: str, ip: str, *, rotate: bool
) -> sessions.LiveSession:
    """Second step of sign-in (``rotate``: a new session replaces the pending one) or a step-up (same session)."""
    keys = throttle.keys(settings.secret_key.get_secret_value(), "mfa", str(live.user.id), ip)
    if await throttle.blocked(db, keys, pair_limit=settings.login_attempts_per_minute):
        raise AuthError("too_many_attempts", 429)
    user = await lock_user(db, live.user.id)
    ok = check_second_factor(settings, user, code)
    throttle.record(db, keys, succeeded=ok)
    if not ok:
        raise AuthError("invalid_code", 401)
    now = clock.utcnow()
    if rotate:
        await sessions.revoke(db, live.row)
        fresh = await sessions.create(
            db, user, ttl=timedelta(days=settings.session_ttl_days), mfa_pending=False, user_agent=live.row.user_agent
        )
        fresh.row.mfa_verified_at = now
        live = fresh
    else:
        live.row.mfa_pending = False
        live.row.mfa_verified_at = now
    await audit(db, "auth.mfa_verified", actor_user_id=user.id, subject_type="user", subject_id=user.id)
    return live


async def _require_reauth(settings: Settings, user: User, live: sessions.LiveSession, password: str | None) -> None:
    """Credential changes need the current password, or (for a password-less account) a sign-in within 15 minutes."""
    if user.password_hash:
        if not password or not await passwords.verify_password_async(user.password_hash, password):
            raise AuthError("current_password_required", 403)
    elif clock.utcnow() - live.row.created_at > REAUTH_WINDOW:
        raise AuthError("recent_sign_in_required", 403)


def _notice(settings: Settings, user: User, what: str) -> PendingEmail:
    return PendingEmail(
        user.id, user.email, emails.security_notice(settings.product_name, what), "auth.security_notice"
    )


async def set_password(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, current: str | None, new: str
) -> list[PendingEmail]:
    user = await lock_user(db, live.user.id)
    await _require_reauth(settings, user, live, current)
    try:
        passwords.check_policy(new, email=user.email)
    except passwords.PasswordPolicyError as exc:
        raise AuthError("weak_password", 422) from exc
    user.password_hash = await passwords.hash_password_async(new)
    await sessions.revoke_all(db, user.id, except_id=live.row.id)
    await audit(db, "auth.password_set", actor_user_id=user.id, subject_type="user", subject_id=user.id)
    return [_notice(settings, user, "Your password was changed.")]


async def begin_totp_enrolment(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, password: str | None
) -> tuple[str, str]:
    user = await lock_user(db, live.user.id)
    if user.totp_enabled_at is not None:
        raise AuthError("totp_already_enabled", 409)
    await _require_reauth(settings, user, live, password)
    secret = totp.new_secret()
    user.totp_pending_enc = encrypt(_key(settings), secret.encode("ascii"), user.id.bytes)
    return secret, totp.provisioning_uri(secret, user.email, settings.product_name)


async def confirm_totp_enrolment(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, code: str
) -> tuple[list[str], list[PendingEmail]]:
    user = await lock_user(db, live.user.id)
    if user.totp_pending_enc is None:
        raise AuthError("no_pending_enrolment", 409)
    check = totp.verify(_secret(settings, user, user.totp_pending_enc), code, last_counter=None)
    if not check.ok:
        raise AuthError("invalid_code", 401)
    codes = totp.new_recovery_codes()
    key = settings.secret_key.get_secret_value()
    now = clock.utcnow()
    user.totp_secret_enc, user.totp_pending_enc = user.totp_pending_enc, None
    user.totp_enabled_at = now
    user.totp_last_counter = check.counter
    user.totp_recovery_hashes = [totp.recovery_hash(c, key) for c in codes]
    live.row.mfa_pending = False
    live.row.mfa_verified_at = now
    # Other sessions were created without the second factor: end them.
    await sessions.revoke_all(db, user.id, except_id=live.row.id)
    await audit(db, "auth.totp_enabled", actor_user_id=user.id, subject_type="user", subject_id=user.id)
    return codes, [_notice(settings, user, "Two-step sign-in was turned on.")]


async def mfa_required_for(db: AsyncSession, user: User) -> bool:
    """TOTP is mandatory for staff and for org owner/admin/signatory/reviewer (docs/spec/08 Auth).
    D2 developers join this rule when D2 exists (Phase 2)."""
    if user.staff_role is not None:
        return True
    stmt = (
        select(func.count())
        .select_from(Membership)
        .where(
            Membership.user_id == user.id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.roles.overlap(sorted(MFA_REQUIRED_ORG_ROLES)),
        )
    )
    return int((await db.execute(stmt)).scalar_one()) > 0


async def disable_totp(db: AsyncSession, settings: Settings, live: sessions.LiveSession) -> list[PendingEmail]:
    if await mfa_required_for(db, live.user):
        raise AuthError("mfa_mandatory_for_role", 403)
    user = await lock_user(db, live.user.id)
    user.totp_secret_enc = user.totp_pending_enc = None
    user.totp_enabled_at = None
    user.totp_last_counter = None
    user.totp_recovery_hashes = []
    await audit(db, "auth.totp_disabled", actor_user_id=user.id, subject_type="user", subject_id=user.id)
    return [_notice(settings, user, "Two-step sign-in was turned off.")]


async def has_developer_profile(db: AsyncSession, user_id: UUID) -> bool:
    return (await db.get(DeveloperProfile, user_id)) is not None


async def logout(db: AsyncSession, live: sessions.LiveSession) -> None:
    await sessions.revoke(db, live.row)
    await audit(db, "auth.logout", actor_user_id=live.user.id, subject_type="user", subject_id=live.user.id)
