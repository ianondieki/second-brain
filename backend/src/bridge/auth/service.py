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
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from cryptography.exceptions import InvalidTag
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.audit.service import record as audit
from bridge.auth import emails, handles, passwords, sessions, throttle, totp
from bridge.auth.cookies import identity_binding, signup_binding
from bridge.auth.crypto import decode_key, decrypt, encrypt, new_token, token_hash
from bridge.auth.mailer import PendingEmail
from bridge.auth.models import AuthIdentity, LoginToken, User
from bridge.auth.schemas import OrgSignup, SignupRequest
from bridge.billing.service import start_free_subscription
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.engagements.calendar import local_date
from bridge.ids import uuid7
from bridge.logging import get_logger
from bridge.models.enums import (
    MFA_REQUIRED_ORG_ROLES,
    ConsentPurpose,
    LoginTokenPurpose,
    MembershipStatus,
    PlanSide,
    UserStatus,
)
from bridge.notifications.email import is_mailbox
from bridge.profiles import consents as consent_rules
from bridge.profiles.consents import consents_version, record_decisions, terms_version
from bridge.profiles.models import DeveloperProfile
from bridge.tenancy.models import Membership
from bridge.tenancy.service import create_organization

SIGNUP_LIMIT = 3  # per (address, IP) in SIGNUP_WINDOW; also bounds "you already have an account" emails
SIGNUP_WINDOW = timedelta(minutes=15)
MAGIC_LIMIT = 3
MAGIC_WINDOW = timedelta(minutes=15)
EMAIL_ACCOUNT_LIMIT = 6  # emails to one address in a window from any IPs (bounds distributed mail bombing)
EMAIL_DAILY_LIMIT = 20  # emails to one address a day, whatever the source
EMAIL_IP_LIMIT = 300  # emails from one IP in a window: generous for shared NAT, bounds a mail-bombing script
REAUTH_WINDOW = timedelta(minutes=15)  # a session this new may change credentials without the current password
REAUTH_IP_LIMIT = throttle.PER_IP_ANY_ACCOUNT  # current-password checks a minute from one client IP, any account
PENDING_TOTP_TTL = timedelta(minutes=15)  # the magic-link lifetime: a setup left open longer must start again
# Associated data of the pending envelope: its kind, then the user id (the active envelope binds the user id only).
PENDING_LABEL = b"totp-pending|"
HANDLE_ATTEMPTS = 5  # a taken handle is drawn again; with ~40 random bits a second clash in a row is vanishingly rare
HANDLE_CONSTRAINT = "uq_developer_profiles_handle"


class AuthError(Exception):
    """A refused auth action; ``code`` is the stable API error code. ``pending`` emails still go out."""

    def __init__(
        self, code: str, status: int = 400, pending: list[PendingEmail] | None = None, binding: str | None = None
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.pending = pending or []
        self.binding = binding  # this browser just proved the password: bind verification to it


class HandleUnavailable(RuntimeError):
    """Every handle drawn for a new developer was taken (``HANDLE_ATTEMPTS`` in a row): the signup fails closed."""


@dataclass(slots=True)
class LoginOutcome:
    session: sessions.LiveSession
    mfa_required: bool


@dataclass(slots=True)
class SignupOutcome:
    pending: list[PendingEmail] = field(default_factory=list)
    binding: str | None = None  # the router sets it as the __Host-bridge_signup cookie


log = get_logger("bridge.auth.service")


async def allow_email(db: AsyncSession, settings: Settings, purpose: str, email: str, ip: str) -> bool:
    """Throttle an action that sends email; record it when allowed. A drop is silent to the caller but logged."""
    limit, window = (SIGNUP_LIMIT, SIGNUP_WINDOW) if purpose == "signup" else (MAGIC_LIMIT, MAGIC_WINDOW)
    keys = throttle.keys(settings.secret_key.get_secret_value(), purpose, email, ip)
    if (
        await throttle.blocked(
            db, keys, pair_limit=limit, window=window, account_limit=EMAIL_ACCOUNT_LIMIT, ip_limit=EMAIL_IP_LIMIT
        )
        or await throttle.account_count(db, keys, window=timedelta(days=1)) >= EMAIL_DAILY_LIMIT
    ):
        log.info("auth.email_throttled", purpose=purpose)
        return False
    throttle.record(db, keys, succeeded=True)
    return True


def normalise_email(email: str) -> str:
    return email.strip().lower()


async def user_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == normalise_email(email)))).scalar_one_or_none()


def _link(settings: Settings, token: str) -> str:
    # The token travels in the fragment, which browsers never send to servers or in Referer headers.
    return f"{settings.public_base_url.rstrip('/')}/auth/link#token={token}"


async def _spend_links(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        update(LoginToken)
        .where(LoginToken.user_id == user_id, LoginToken.used_at.is_(None))
        .values(used_at=clock.utcnow())
    )


def _binding(settings: Settings, user: User) -> str | None:
    return signup_binding(settings, user.id, user.password_hash) if user.password_hash else None


async def issue_link(db: AsyncSession, settings: Settings, user: User, purpose: LoginTokenPurpose) -> str:
    """A fresh single-use token. Earlier links stay valid until one is used or the password is replaced, so a
    stranger asking for a link cannot void the owner's."""
    now = clock.utcnow()
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


async def _add_developer_profile(db: AsyncSession, user_id: UUID) -> None:
    """The new developer's profile under a random handle (``handles.new_handle``: nothing of the display name or the
    email address goes into it). A taken handle is retried in a savepoint, at most ``HANDLE_ATTEMPTS`` times; any other
    integrity error is raised."""
    for _ in range(HANDLE_ATTEMPTS):
        try:
            async with db.begin_nested():
                db.add(DeveloperProfile(user_id=user_id, handle=handles.new_handle()))
                await db.flush()
        except IntegrityError as exc:
            if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != HANDLE_CONSTRAINT:
                raise
            log.info("auth.handle_taken")  # drawn again; the handle itself is not logged
            continue
        return
    raise HandleUnavailable(f"no free developer handle in {HANDLE_ATTEMPTS} draws")


def _slug_from(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "org"
    return f"{base}-{secrets.token_hex(3)}"


def refuse_session_only(decisions: Mapping[ConsentPurpose, bool]) -> None:
    """Signup records lasting decisions only. A purpose decided for one sign-in (``tier2_llm_assistant``,
    REQ-PROP-05) is refused whatever its value, as the settings API refuses it, so signup never writes a row of it.
    The email form and both steps of an OAuth signup (start and callback) call this."""
    if any(purpose in consent_rules.SESSION_ONLY for purpose in decisions):
        raise AuthError("consent_session_only", 422)


def _validate_signup(settings: Settings, req: SignupRequest, email: str) -> None:
    if not is_mailbox(email):
        # Only plain ASCII mailboxes can be emailed safely (no encoded words, quoted or Unicode local parts).
        raise AuthError("invalid_email", 422)
    if not req.accept_terms:
        raise AuthError("terms_not_accepted", 422)
    if req.side == "org" and req.org is None:
        raise AuthError("org_details_required", 422)
    refuse_session_only(req.consents)
    if req.consents and req.consents_version is None:
        raise AuthError("consents_version_required", 422)
    if req.consents_version is not None and req.consents_version != consents_version(settings):
        raise AuthError("consent_text_changed", 409)
    try:
        passwords.check_policy(req.password, email=email)
    except passwords.PasswordPolicyError as exc:
        raise AuthError("weak_password", 422) from exc


def verification_email(settings: Settings, user: User, token: str) -> PendingEmail:
    wording = emails.verify_email(settings.product_name, _link(settings, token), settings.magic_link_ttl_minutes)
    return PendingEmail(user.id, user.email, wording, "auth.verify_email")


async def _existing_account(
    db: AsyncSession, settings: Settings, user: User, password_hash: str, ip: str
) -> SignupOutcome:
    await bind_tenant(db, user_id=user.id)
    if user.email_verified_at is None:
        # Unverified: this signup's password replaces the stored one, unless throttled (then nothing changes).
        # Earlier links stay valid, so a stranger's signup cannot void the owner's link; any link keeps the
        # password only in the browser that set it (the binding covers the current password hash).
        if not await allow_email(db, settings, "magic", user.email, ip):
            return SignupOutcome()
        user.password_hash = password_hash
        token = await issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
        return SignupOutcome([verification_email(settings, user, token)], _binding(settings, user))
    login_url = f"{settings.public_base_url.rstrip('/')}/login"
    wording = emails.account_exists(settings.product_name, login_url)
    dedupe = f"auth.account_exists:{user.id}:{local_date(clock.utcnow()).isoformat()}"  # at most one a day
    return SignupOutcome([PendingEmail(user.id, user.email, wording, "auth.account_exists", dedupe)])


async def signup(db: AsyncSession, settings: Settings, req: SignupRequest, ip: str) -> SignupOutcome:
    """Create an unverified account (developer, or organisation owner) and return the verification email to send."""
    email = normalise_email(req.email)
    _validate_signup(settings, req, email)
    if not await allow_email(db, settings, "signup", email, ip):
        return SignupOutcome()  # silent: same answer, no email (stops email bombing through signup)
    password_hash = await passwords.hash_password_async(req.password)  # on every path: timing reveals nothing

    existing = await user_by_email(db, email)
    if existing is not None:
        return await _existing_account(db, settings, existing, password_hash, ip)

    account = NewAccount(
        email=email,
        display_name=req.display_name.strip(),
        locale=req.locale,
        side=req.side,
        org=req.org,
        consents=req.consents,
        method="password",
    )
    user = await create_account(db, settings, account, password_hash=password_hash)
    if user is None:
        # A concurrent signup created the address first: answer exactly as for an existing account.
        existing = await user_by_email(db, email)
        assert existing is not None  # create_account re-raises when the address is still free
        return await _existing_account(db, settings, existing, password_hash, ip)
    token = await issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
    return SignupOutcome([verification_email(settings, user, token)], _binding(settings, user))


@dataclass(frozen=True, slots=True)
class NewAccount:
    """What a signup collects apart from the credential: the email form (REQ-AUTH-01) or OAuth (REQ-AUTH-02)."""

    email: str  # normalised
    display_name: str
    locale: str
    side: Literal["developer", "org"]
    org: OrgSignup | None
    consents: Mapping[ConsentPurpose, bool]
    method: str  # "password" or the OAuth provider, for the audit event


async def create_account(
    db: AsyncSession,
    settings: Settings,
    account: NewAccount,
    *,
    password_hash: str | None,
    verified_at: datetime | None = None,
) -> User | None:
    """Insert the user with a developer profile, or a new organisation it owns, plus the free plan, the consent
    decisions and the ``auth.signup`` audit event. None when a concurrent signup took the address first."""
    user = User(
        id=uuid7(),
        email=account.email,
        password_hash=password_hash,
        display_name=account.display_name,
        locale=account.locale,
        email_verified_at=verified_at,
    )
    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError:
        if await user_by_email(db, account.email) is None:
            raise
        return None
    await bind_tenant(db, user_id=user.id)

    org_id: UUID | None = None
    if account.side == "developer":
        await _add_developer_profile(db, user.id)
        await start_free_subscription(db, settings, side=PlanSide.DEVELOPER, user_id=user.id)
    else:
        assert account.org is not None
        org_id = await create_organization(
            db, kind=account.org.kind, legal_name=account.org.legal_name, slug=_slug_from(account.org.legal_name)
        )
        await start_free_subscription(db, settings, side=PlanSide.ORG, org_id=org_id)

    await record_decisions(db, settings, user_id=user.id, decisions=account.consents, source="signup")
    await audit(
        db,
        "auth.signup",
        actor_user_id=user.id,
        org_id=org_id,
        subject_type="user",
        subject_id=user.id,
        payload={
            "side": account.side,
            "method": account.method,
            "terms_version": terms_version(settings),
            "consents_version": consents_version(settings),
        },
    )
    return user


async def request_magic_link(db: AsyncSession, settings: Settings, email: str, ip: str) -> list[PendingEmail]:
    """A sign-in link (or a verification link for an unverified account). Silent when throttled or unknown."""
    email = normalise_email(email)
    if not await allow_email(db, settings, "magic", email, ip):
        return []
    user = await user_by_email(db, email)
    if user is None or user.status != UserStatus.ACTIVE:
        return []
    await bind_tenant(db, user_id=user.id)
    if user.email_verified_at is None:
        return [
            verification_email(settings, user, await issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL))
        ]
    token = await issue_link(db, settings, user, LoginTokenPurpose.LOGIN)
    wording = emails.login_link(settings.product_name, _link(settings, token), settings.magic_link_ttl_minutes)
    return [PendingEmail(user.id, user.email, wording, "auth.login_link")]


async def start_session(db: AsyncSession, settings: Settings, user: User, user_agent: str | None) -> LoginOutcome:
    mfa = user.totp_enabled_at is not None
    live = await sessions.create(
        db, user, ttl=timedelta(days=settings.session_ttl_days), mfa_pending=mfa, user_agent=user_agent
    )
    await bind_tenant(db, user_id=user.id)
    return LoginOutcome(live, mfa_required=mfa)


def _same(presented: str, expected: str) -> bool:
    """Constant-time comparison that also accepts non-ASCII input (a planted cookie) without raising."""
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


async def _drop_unbound_identities(db: AsyncSession, settings: Settings, user_id: UUID, signup_cookie: str) -> None:
    """OAuth identities attached before the address was verified (an OAuth signup whose provider had not verified the
    address, REQ-AUTH-02) survive only when the link is opened in the browser that attached them; elsewhere they
    could be an attacker's account waiting for the owner to verify (pre-hijacking)."""
    identities = (await db.execute(select(AuthIdentity).where(AuthIdentity.user_id == user_id))).scalars().all()
    for identity in identities:
        if not _same(signup_cookie, identity_binding(settings, user_id, identity.id)):
            await db.delete(identity)


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
        expected = _binding(settings, user)
        bound = expected is not None and _same(signup_cookie or "", expected)
        if not bound:
            user.password_hash = None  # a password set before verification from another browser is not trusted
        await _drop_unbound_identities(db, settings, user.id, signup_cookie or "")
        user.email_verified_at = now
        await sessions.revoke_all(db, user.id)
    await _spend_links(db, user.id)  # one link used: the account's other outstanding links stop working
    outcome = await start_session(db, settings, user, user_agent)
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
    user = await user_by_email(db, email)
    ok = await passwords.verify_password_async(user.password_hash if user else None, password)
    throttle.record(db, keys, succeeded=ok)
    if user is None or not ok or user.status != UserStatus.ACTIVE:
        raise AuthError("invalid_credentials", 401)
    if user.email_verified_at is None:
        await bind_tenant(db, user_id=user.id)
        pending: list[PendingEmail] = []
        if await allow_email(db, settings, "magic", user.email, ip):  # a resend, under the magic-link limits
            token = await issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
            pending = [verification_email(settings, user, token)]
        raise AuthError("email_unverified", 403, pending=pending, binding=_binding(settings, user))
    if user.password_hash and passwords.needs_rehash(user.password_hash):
        user.password_hash = await passwords.hash_password_async(password)
    outcome = await start_session(db, settings, user, user_agent)
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
            list(user.totp_recovery_hashes), code, settings.recovery_code_pepper.get_secret_value()
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


async def require_reauth(
    db: AsyncSession, settings: Settings, user: User, live: sessions.LiveSession, password: str | None, *, ip: str
) -> None:
    """Credential changes (password, TOTP enrolment, OAuth linking and unlinking) need the current password, or, for
    a password-less account, a sign-in within 15 minutes. The check is throttled like a login, so a stolen session
    cannot guess the password: 5 attempts a minute for the account from any IP, and ``REAUTH_IP_LIMIT`` a minute from
    one client IP for any account (T2.12 follow-up: the IP key was a constant, so that limit was platform-wide)."""
    if user.password_hash:
        limit = settings.login_attempts_per_minute
        keys = throttle.keys(settings.secret_key.get_secret_value(), "reauth", str(user.id), ip)
        if await throttle.blocked(db, keys, pair_limit=limit, account_limit=limit, ip_limit=REAUTH_IP_LIMIT):
            raise AuthError("too_many_attempts", 429)
        ok = bool(password) and await passwords.verify_password_async(user.password_hash, password or "")
        throttle.record(db, keys, succeeded=ok)
        if not ok:
            raise AuthError("current_password_required", 403)
    elif clock.utcnow() - live.row.created_at > REAUTH_WINDOW:
        raise AuthError("recent_sign_in_required", 403)


async def ensure_fresh_proof(
    db: AsyncSession, settings: Settings, user: User, live: sessions.LiveSession, password: str | None, *, ip: str
) -> None:
    """Adding or removing a sign-in method, or replacing the recovery codes: a second factor within
    STEP_UP_MAX_AGE_HOURS when TOTP is on (the ADR-002 step-up rule), and the current password when the account has
    one (``require_reauth``, throttled like a login; the caller commits even on failure). A password-less account
    without TOTP needs a sign-in within the last 15 minutes instead; a password-less account with TOTP needs only the
    fresh second factor."""
    if user.totp_enabled_at is not None:
        if not sessions.mfa_fresh(live.row, timedelta(hours=settings.step_up_max_age_hours)):
            raise AuthError("step_up_required", 403)
        if user.password_hash is None:
            return
    await require_reauth(db, settings, user, live, password, ip=ip)


def notice_email(settings: Settings, user: User, what: str, dedupe_key: str | None = None) -> PendingEmail:
    return PendingEmail(
        user.id, user.email, emails.security_notice(settings.product_name, what), "auth.security_notice", dedupe_key
    )


async def set_password(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, current: str | None, new: str, *, ip: str
) -> list[PendingEmail]:
    user = await lock_user(db, live.user.id)
    await require_reauth(db, settings, user, live, current, ip=ip)
    try:
        passwords.check_policy(new, email=user.email)
    except passwords.PasswordPolicyError as exc:
        raise AuthError("weak_password", 422) from exc
    user.password_hash = await passwords.hash_password_async(new)
    await sessions.revoke_all(db, user.id, except_id=live.row.id)
    await audit(db, "auth.password_set", actor_user_id=user.id, subject_type="user", subject_id=user.id)
    return [notice_email(settings, user, "Your password was changed.")]


async def begin_totp_enrolment(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, password: str | None, *, ip: str
) -> tuple[str, str]:
    user = await lock_user(db, live.user.id)
    if user.totp_enabled_at is not None:
        raise AuthError("totp_already_enabled", 409)
    await require_reauth(db, settings, user, live, password, ip=ip)
    secret = totp.new_secret()
    seal_pending_secret(settings, user, secret)
    return secret, totp.provisioning_uri(secret, user.email, settings.product_name)


def seal_pending_secret(settings: Settings, user: User, secret: str) -> None:
    """Store ``secret`` as the pending TOTP secret with the time setup began, sealed together in one AES-GCM envelope
    bound to ``PENDING_LABEL`` and the user id, so the time cannot be altered or detached and the envelope never opens
    as the active secret (or the active one as it); ``_pending_secret`` refuses it after ``PENDING_TOTP_TTL``. The one
    place that writes the envelope (setup, and the demo seed's fixed secrets); the caller holds ``lock_user``."""
    began = int(clock.utcnow().timestamp())
    user.totp_pending_enc = encrypt(_key(settings), f"{secret}|{began}".encode("ascii"), PENDING_LABEL + user.id.bytes)


def _pending_secret(settings: Settings, user: User) -> str | None:
    """The pending secret while its setup is fresh. One begun over ``PENDING_TOTP_TTL`` ago (a closed tab), stored
    without its start time, or one that does not open (sealed before ``PENDING_LABEL``, under another key, or altered)
    is cleared instead, the same answer as expired. The caller holds ``lock_user``."""
    if user.totp_pending_enc is None:
        return None
    try:
        opened = decrypt(_key(settings), user.totp_pending_enc, PENDING_LABEL + user.id.bytes).decode("ascii")
    except (InvalidTag, ValueError):  # ValueError: a blob too short to hold a nonce
        opened = ""
    secret, _, began = opened.partition("|")
    if began.isdigit() and clock.utcnow() - datetime.fromtimestamp(int(began), UTC) <= PENDING_TOTP_TTL:
        return secret
    user.totp_pending_enc = None
    return None


async def cancel_totp_enrolment(db: AsyncSession, live: sessions.LiveSession) -> None:
    """Cancel setup: clear the pending secret (follow-up 7). It takes ``lock_user`` like the confirmation, so the two
    serialise: behind a confirmation that committed first it answers 409 totp_already_enabled (two-step sign-in is on
    and that answer may have been lost, codes unseen); a confirmation behind it finds nothing pending."""
    user = await lock_user(db, live.user.id)
    if user.totp_enabled_at is not None:
        raise AuthError("totp_already_enabled", 409)
    if user.totp_pending_enc is None:
        raise AuthError("no_pending_enrolment", 409)
    user.totp_pending_enc = None


async def confirm_totp_enrolment(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, code: str, *, ip: str
) -> tuple[list[str], list[PendingEmail]]:
    """Turn two-step sign-in on with a code from the pending secret. Throttled in the second factor's budget (the
    "mfa" keys of ``complete_mfa``: 5 codes a minute for the account from one client IP), so a stolen session cannot
    guess codes against a setup the owner has begun (security review MAJOR); the throttled case is logged."""
    keys = throttle.keys(settings.secret_key.get_secret_value(), "mfa", str(live.user.id), ip)
    if await throttle.blocked(db, keys, pair_limit=settings.login_attempts_per_minute):
        # Looked up per call: the module logger is cached on first use (structlog), which hides it from capture_logs.
        get_logger(__name__).warning("auth.totp_confirm_throttled", user_id=str(live.user.id))
        raise AuthError("too_many_attempts", 429)
    user = await lock_user(db, live.user.id)
    secret = _pending_secret(settings, user)
    if secret is None:
        raise AuthError("no_pending_enrolment", 409)  # the router commits, so an expired secret stays cleared
    check = totp.verify(secret, code, last_counter=None)
    throttle.record(db, keys, succeeded=check.ok)  # the router commits on a refusal, so a wrong code stays counted
    if not check.ok:
        raise AuthError("invalid_code", 401)
    now = clock.utcnow()
    # Seal the secret alone (a fresh nonce): the pending envelope also carries its start time, which is not a secret
    # sign-in can decode.
    user.totp_secret_enc = encrypt(_key(settings), secret.encode("ascii"), user.id.bytes)
    user.totp_pending_enc = None
    user.totp_enabled_at = now
    user.totp_last_counter = check.counter
    codes = _issue_recovery_codes(settings, user)
    live.row.mfa_pending = False
    live.row.mfa_verified_at = now
    # Other sessions were created without the second factor: end them.
    await sessions.revoke_all(db, user.id, except_id=live.row.id)
    await audit(db, "auth.totp_enabled", actor_user_id=user.id, subject_type="user", subject_id=user.id)
    return codes, [notice_email(settings, user, "Two-step sign-in was turned on.")]


def _issue_recovery_codes(settings: Settings, user: User) -> list[str]:
    """Ten new codes whose hashes replace every stored one; the codes themselves are never stored. The caller holds
    ``lock_user``."""
    codes = totp.new_recovery_codes()
    key = settings.recovery_code_pepper.get_secret_value()
    user.totp_recovery_hashes = [totp.recovery_hash(c, key) for c in codes]
    return codes


async def replace_recovery_codes(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, password: str | None, *, ip: str
) -> tuple[list[str], list[PendingEmail]]:
    """Ten new recovery codes replace the old ones in one step (follow-up 8): the way back to codes after the
    confirmation's answer was lost, for roles that cannot turn two-step sign-in off and on again. The proof is
    ``ensure_fresh_proof``'s, as for linking and unlinking a sign-in method: a second factor within 12 h and the
    current password when the account has one, since a recovery code spent at step-up also makes the factor fresh
    (security review). Throttled like the re-auth checks (5 a minute for the account, from any IP;
    ``REAUTH_IP_LIMIT`` a minute from one client IP). Under ``lock_user``: a step-up spending an old code either
    commits first (its remaining hashes are then replaced here) or waits and re-reads only the new hashes, so it can
    never write the old ones back."""
    limit = settings.login_attempts_per_minute
    keys = throttle.keys(settings.secret_key.get_secret_value(), "recovery_codes", str(live.user.id), ip)
    if await throttle.blocked(db, keys, pair_limit=limit, account_limit=limit, ip_limit=REAUTH_IP_LIMIT):
        raise AuthError("too_many_attempts", 429)
    throttle.record(db, keys, succeeded=True)
    user = await lock_user(db, live.user.id)
    if user.totp_enabled_at is None:
        raise AuthError("totp_not_enabled", 409)
    await ensure_fresh_proof(db, settings, user, live, password, ip=ip)
    codes = _issue_recovery_codes(settings, user)
    await audit(db, "auth.recovery_codes_replaced", actor_user_id=user.id, subject_type="user", subject_id=user.id)
    # One notice per account and Nairobi day, however many replacements (security review; every one is audited).
    dedupe = f"auth.recovery_codes_replaced:{user.id}:{local_date(clock.utcnow()).isoformat()}"
    # [[COPY-REVIEW]] plain transactional copy
    return codes, [notice_email(settings, user, "New recovery codes were created.", dedupe)]


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
    return [notice_email(settings, user, "Two-step sign-in was turned off.")]


async def has_developer_profile(db: AsyncSession, user_id: UUID) -> bool:
    return (await db.get(DeveloperProfile, user_id)) is not None


async def logout(db: AsyncSession, live: sessions.LiveSession) -> None:
    await sessions.revoke(db, live.row)
    await audit(db, "auth.logout", actor_user_id=live.user.id, subject_type="user", subject_id=live.user.id)
