"""Account flows (REQ-AUTH-01): signup, email verification, password and magic-link login, TOTP, step-up.

Plain code decides every outcome (docs/spec/04 principle 1). Responses never reveal whether an email address has an
account: signup, magic-link and resend requests always answer "check your email".
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.auth import emails, passwords, sessions, throttle, totp
from bridge.auth.crypto import decode_key, decrypt, encrypt, new_token, token_hash
from bridge.auth.models import LoginToken, User
from bridge.auth.schemas import SignupRequest
from bridge.billing.service import start_free_subscription
from bridge.clock import utcnow
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.ids import uuid7
from bridge.models.enums import MFA_REQUIRED_ORG_ROLES, LoginTokenPurpose, MembershipStatus, PlanSide
from bridge.notifications.deliveries import send_email
from bridge.notifications.email import EmailMessage, EmailProvider, is_mailbox
from bridge.profiles.consents import record_decisions
from bridge.profiles.models import DeveloperProfile
from bridge.tenancy.models import Membership
from bridge.tenancy.service import create_organization


class AuthError(Exception):
    """A refused auth action; ``code`` is the stable API error code."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(slots=True)
class LoginOutcome:
    session: sessions.LiveSession
    mfa_required: bool


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def _user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == normalise_email(email)))).scalar_one_or_none()


def _link(settings: Settings, token: str) -> str:
    # The token travels in the fragment, which browsers never send to servers or in Referer headers.
    return f"{settings.public_base_url.rstrip('/')}/auth/link#token={token}"


async def _issue_link(db: AsyncSession, settings: Settings, user: User, purpose: LoginTokenPurpose) -> str:
    token = new_token()
    db.add(
        LoginToken(
            user_id=user.id,
            token_hash=token_hash(token),
            purpose=purpose,
            expires_at=utcnow() + timedelta(minutes=settings.magic_link_ttl_minutes),
        )
    )
    await db.flush()
    return _link(settings, token)


async def _mail(db: AsyncSession, provider: EmailProvider, user: User, wording: emails.Wording, kind: str) -> None:
    await bind_tenant(db, user_id=user.id)
    message = EmailMessage(to=user.email, subject=wording.subject, text=wording.text, html=None, tag=kind, headers={})
    await send_email(db, provider, message=message, kind=kind, user_id=user.id)


def _handle_from(display_name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")[:24] or "dev"
    return f"{base}-{secrets.token_hex(3)}"


def _slug_from(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "org"
    return f"{base}-{secrets.token_hex(3)}"


async def signup(db: AsyncSession, settings: Settings, provider: EmailProvider, req: SignupRequest) -> None:
    """Create an unverified account (developer, or organisation owner) and email a verification link."""
    email = normalise_email(req.email)
    if not is_mailbox(email):
        # Only plain ASCII mailboxes can be emailed safely (no encoded words, quoted or Unicode local parts).
        raise AuthError("invalid_email", 422)
    if not req.accept_terms:
        raise AuthError("terms_not_accepted", 422)
    if req.side == "org" and req.org is None:
        raise AuthError("org_details_required", 422)
    try:
        passwords.check_policy(req.password, email=email)
    except passwords.PasswordPolicyError as exc:
        raise AuthError("weak_password", 422) from exc

    existing = await _user_by_email(db, email)
    if existing is not None:
        # Same answer as a new signup; the owner of the address learns someone tried.
        login_url = f"{settings.public_base_url.rstrip('/')}/login"
        await _mail(
            db, provider, existing, emails.account_exists(settings.product_name, login_url), "auth.account_exists"
        )
        return

    user = User(
        id=uuid7(),
        email=email,
        password_hash=passwords.hash_password(req.password),
        display_name=req.display_name.strip(),
        locale=req.locale,
    )
    db.add(user)
    await db.flush()
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
        payload={"side": req.side},
    )
    link = await _issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
    await _mail(
        db,
        provider,
        user,
        emails.verify_email(settings.product_name, link, settings.magic_link_ttl_minutes),
        "auth.verify_email",
    )


async def request_magic_link(
    db: AsyncSession, settings: Settings, provider: EmailProvider, email: str, ip: str
) -> None:
    """Email a sign-in link (or a verification link for an unverified account). Silent when throttled or unknown."""
    keys = throttle.keys(settings.secret_key.get_secret_value(), "magic", email, ip)
    if await throttle.blocked(db, keys, pair_limit=3, window=timedelta(minutes=15)):
        return
    throttle.record(db, keys, succeeded=True)
    user = await _user_by_email(db, email)
    if user is None:
        return
    if user.email_verified_at is None:
        link = await _issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
        wording = emails.verify_email(settings.product_name, link, settings.magic_link_ttl_minutes)
        await _mail(db, provider, user, wording, "auth.verify_email")
        return
    link = await _issue_link(db, settings, user, LoginTokenPurpose.LOGIN)
    await _mail(
        db,
        provider,
        user,
        emails.login_link(settings.product_name, link, settings.magic_link_ttl_minutes),
        "auth.login_link",
    )


async def _start_session(db: AsyncSession, settings: Settings, user: User, user_agent: str | None) -> LoginOutcome:
    mfa = user.totp_enabled_at is not None
    live = await sessions.create(
        db, user, ttl=timedelta(days=settings.session_ttl_days), mfa_pending=mfa, user_agent=user_agent
    )
    await bind_tenant(db, user_id=user.id)
    return LoginOutcome(live, mfa_required=mfa)


async def consume_link(db: AsyncSession, settings: Settings, token: str, user_agent: str | None) -> LoginOutcome:
    """Spend a magic-link token once: verify the email if needed and sign in."""
    row = (
        await db.execute(select(LoginToken).where(LoginToken.token_hash == token_hash(token)).with_for_update())
    ).scalar_one_or_none()
    now = utcnow()
    if row is None or row.used_at is not None or row.expires_at <= now:
        raise AuthError("invalid_or_expired_link", 400)
    row.used_at = now
    user = await db.get(User, row.user_id)
    if user is None or user.status != "active":
        raise AuthError("invalid_or_expired_link", 400)
    if user.email_verified_at is None:
        user.email_verified_at = now
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
    db: AsyncSession,
    settings: Settings,
    provider: EmailProvider,
    email: str,
    password: str,
    ip: str,
    user_agent: str | None,
) -> LoginOutcome:
    keys = throttle.keys(settings.secret_key.get_secret_value(), "login", email, ip)
    if await throttle.blocked(db, keys, pair_limit=settings.login_attempts_per_minute):
        raise AuthError("too_many_attempts", 429)
    user = await _user_by_email(db, email)
    ok = passwords.verify_password(user.password_hash if user else None, password)
    throttle.record(db, keys, succeeded=ok)
    if user is None or not ok or user.status != "active":
        raise AuthError("invalid_credentials", 401)
    if user.email_verified_at is None:
        await request_magic_link(db, settings, provider, email, ip)
        raise AuthError("email_unverified", 403)
    if user.password_hash and passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(password)
    outcome = await _start_session(db, settings, user, user_agent)
    await audit(
        db, "auth.login", actor_user_id=user.id, subject_type="user", subject_id=user.id, payload={"method": "password"}
    )
    return outcome


def _key(settings: Settings) -> bytes:
    return decode_key(settings.data_encryption_key.get_secret_value())


def _secret(settings: Settings, user: User, blob: bytes) -> str:
    return decrypt(_key(settings), blob, user.id.bytes).decode("ascii")


def check_second_factor(settings: Settings, user: User, code: str) -> bool:
    """Verify a TOTP code (with replay protection) or spend a recovery code. Mutates the user row on success."""
    if user.totp_secret_enc is None:
        return False
    if "-" in code or not code.strip().isdigit():
        remaining = totp.use_recovery_code(list(user.totp_recovery_hashes), code)
        if remaining is None:
            return False
        user.totp_recovery_hashes = remaining
        return True
    check = totp.verify(_secret(settings, user, user.totp_secret_enc), code, last_counter=user.totp_last_counter)
    if check.ok:
        user.totp_last_counter = check.counter
    return check.ok


async def complete_mfa(db: AsyncSession, settings: Settings, live: sessions.LiveSession, code: str, ip: str) -> None:
    """Second step of sign-in, and the step-up check: refresh ``mfa_verified_at`` on a valid code."""
    keys = throttle.keys(settings.secret_key.get_secret_value(), "mfa", str(live.user.id), ip)
    if await throttle.blocked(db, keys, pair_limit=settings.login_attempts_per_minute):
        raise AuthError("too_many_attempts", 429)
    ok = check_second_factor(settings, live.user, code)
    throttle.record(db, keys, succeeded=ok)
    if not ok:
        raise AuthError("invalid_code", 401)
    live.row.mfa_pending = False
    live.row.mfa_verified_at = utcnow()
    await audit(db, "auth.mfa_verified", actor_user_id=live.user.id, subject_type="user", subject_id=live.user.id)


def begin_totp_enrolment(settings: Settings, user: User) -> tuple[str, str]:
    if user.totp_enabled_at is not None:
        raise AuthError("totp_already_enabled", 409)
    secret = totp.new_secret()
    user.totp_pending_enc = encrypt(_key(settings), secret.encode("ascii"), user.id.bytes)
    return secret, totp.provisioning_uri(secret, user.email, settings.product_name)


async def confirm_totp_enrolment(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, code: str
) -> list[str]:
    user = live.user
    if user.totp_pending_enc is None:
        raise AuthError("no_pending_enrolment", 409)
    secret = _secret(settings, user, user.totp_pending_enc)
    check = totp.verify(secret, code, last_counter=None)
    if not check.ok:
        raise AuthError("invalid_code", 401)
    codes = totp.new_recovery_codes()
    user.totp_secret_enc, user.totp_pending_enc = user.totp_pending_enc, None
    user.totp_enabled_at = utcnow()
    user.totp_last_counter = check.counter
    user.totp_recovery_hashes = [totp.recovery_hash(c) for c in codes]
    live.row.mfa_pending = False
    live.row.mfa_verified_at = utcnow()
    # Other sessions were created without the second factor: end them.
    await sessions.revoke_all(db, user.id, except_id=live.row.id)
    await audit(db, "auth.totp_enabled", actor_user_id=user.id, subject_type="user", subject_id=user.id)
    return codes


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


async def disable_totp(db: AsyncSession, live: sessions.LiveSession) -> None:
    if await mfa_required_for(db, live.user):
        raise AuthError("mfa_mandatory_for_role", 403)
    user = live.user
    user.totp_secret_enc = user.totp_pending_enc = None
    user.totp_enabled_at = None
    user.totp_last_counter = None
    user.totp_recovery_hashes = []
    await audit(db, "auth.totp_disabled", actor_user_id=user.id, subject_type="user", subject_id=user.id)


async def logout(db: AsyncSession, live: sessions.LiveSession) -> None:
    await sessions.revoke(db, live.row)
    await audit(db, "auth.logout", actor_user_id=live.user.id, subject_type="user", subject_id=live.user.id)


Side = Literal["developer", "org", "staff"]
