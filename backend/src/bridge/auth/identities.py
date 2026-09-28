"""OAuth identities (REQ-AUTH-02): which account a provider identity may reach, linking and unlinking.

Plain code decides (docs/spec/04 principle 1). For a ``login`` or ``signup`` callback, in order:

1. A known identity (provider, subject) signs in its account (MFA pending when TOTP is on), whatever its address is
   now. An account whose address is still unverified is not signed in: a verification link is sent instead.
2. Otherwise the provider's address decides, and only when the provider verified it. An account with that address
   and a verified address is signed in exactly as an emailed link would sign it in (MFA pending when TOTP is on) and
   nothing is attached to it: no identity, no "added" notice. An account that already holds another identity from
   this provider is refused (``provider_already_linked``). An unverified account gets nothing and its owner an
   emailed link. With no account, ``signup`` creates one (address verified by the provider) with the identity
   attached, and ``login`` sends the person to signup, where the terms and consents are chosen.
3. An address the provider has not verified never signs in to, creates or is matched to an existing account (account
   pre-hijacking). ``login`` answers ``oauth_email_unverified`` whether or not an account exists. ``signup`` answers
   "check your email" either way: a new account is created unverified, its identity bound to this browser
   (``__Host-bridge_signup``), so a verification link opened elsewhere drops the identity (``service.consume_link``);
   an existing owner gets a link.

An identity is attached to an account only when an OAuth signup creates the account, or through ``link`` from
``/settings/security`` (orchestrator decision, fix round 1 of T2.12), which does not depend on the provider's
address. Linking completes only in the session that started it, which gave a fresh second factor when TOTP is on (the
ADR-002 step-up rule) and the current password when the account has one (throttled like a login); a password-less
account without TOTP needs a sign-in within the last 15 minutes instead. An identity that belongs to another account
is refused, and an account holds one identity per provider. Unlinking needs the same proof and another way to sign
in: a password, another identity, or an emailed link to the verified address, so an account with a verified address
can always unlink. Each change emails a security notice. Audit events carry ids and the provider name only; provider
tokens are never stored.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.audit.service import record as audit
from bridge.auth import csrf, oauth, service, sessions, throttle
from bridge.auth.cookies import identity_binding
from bridge.auth.mailer import PendingEmail
from bridge.auth.models import AuthIdentity, User
from bridge.auth.schemas import OAuthSignup, OAuthStartRequest
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.logging import get_logger
from bridge.models.enums import AuthProvider, LoginTokenPurpose, UserStatus
from bridge.profiles.consents import consents_version

ERROR_PAGES: dict[oauth.Intent, str] = {"login": "/login", "signup": "/signup", "link": "/settings/security"}
CHECK_EMAIL = "/signup/check-email"
REQUESTS_PER_IP_PER_MINUTE = 10  # OAuth starts, and separately callbacks, from one client IP


@dataclass(slots=True)
class Outcome:
    """Where the callback sends the browser (one of ``oauth.WEB_PATHS``) and what it sets on the way."""

    path: str
    params: dict[str, str] = field(default_factory=dict)
    session: sessions.LiveSession | None = None  # sign in: the session cookie
    check_email: bool = False  # "check your email": the __Host-bridge_signup cookie (``binding`` or a random value)
    binding: str | None = None
    pending: list[PendingEmail] = field(default_factory=list)


def failed(intent: oauth.Intent | None, code: str, provider: AuthProvider) -> Outcome:
    """An error page with a stable code; provider text never reaches the page."""
    page = ERROR_PAGES[intent] if intent is not None else "/login"
    return Outcome(page, {"oauth_error": code, "provider": provider.value})


class _Taken(Exception):
    """The address or the identity was taken by a concurrent request: undo the whole signup."""


# ------------------------------------------------------------------------------------------------ throttle


async def allow_request(db: AsyncSession, settings: Settings, step: Literal["start", "callback"], ip: str) -> bool:
    """At most ``REQUESTS_PER_IP_PER_MINUTE`` OAuth starts, and as many callbacks, a minute from one client IP (the
    ``login_attempts`` ledger, HMAC digests only). Each allowed request is recorded; the caller commits. A refusal is
    logged as ``auth.oauth_throttled`` (not audited: an audit append per junk request would be its own flood).

    A callback is charged only once its ``state`` matched the flow cookie and it carries a code, just before the state
    is spent and the provider called (T2.12 follow-up): charged earlier, a page loading the callback URL with a junk
    state in someone's browser would use up that person's budget. The requests refused before that need no limit of
    their own: they touch no database and never reach the provider, and a 256-bit random state sealed in the cookie
    is nothing to guess."""
    keys = throttle.ip_keys(settings.secret_key.get_secret_value(), f"oauth_{step}", ip)
    if await throttle.ip_blocked(db, keys, limit=REQUESTS_PER_IP_PER_MINUTE):
        get_logger(__name__).info("auth.oauth_throttled", step=step)
        return False
    throttle.record(db, keys, succeeded=True)
    return True


async def spend_state(db: AsyncSession, settings: Settings, flow: oauth.Flow) -> bool:
    """The flow's first callback: record its ``state`` as used (an HMAC digest in the ``login_attempts`` ledger) and
    return True; any later callback with the same state, even with a copy of the cookie, gets False and is refused
    before a provider call. The record outlives the cookie (twice its ten minutes); the caller commits."""
    secret = settings.secret_key.get_secret_value()
    if await throttle.first_use(db, secret, "oauth_state", flow.state, window=2 * oauth.FLOW_TTL):
        return True
    get_logger(__name__).warning("auth.oauth_state_replayed", provider=flow.provider.value)
    return False


# ------------------------------------------------------------------------------------------------ start


async def ensure_fresh_proof(
    db: AsyncSession, settings: Settings, user: User, live: sessions.LiveSession, password: str | None
) -> None:
    """Adding or removing a sign-in method: a second factor within STEP_UP_MAX_AGE_HOURS when TOTP is on (the
    ADR-002 step-up rule), and the current password when the account has one (``service.require_reauth``, throttled
    like a login; the caller commits even on failure). A password-less account without TOTP needs a sign-in within
    the last 15 minutes instead; a password-less account with TOTP needs only the fresh second factor."""
    if user.totp_enabled_at is not None:
        if not sessions.mfa_fresh(live.row, timedelta(hours=settings.step_up_max_age_hours)):
            raise service.AuthError("step_up_required", 403)
        if user.password_hash is None:
            return
    await service.require_reauth(db, settings, user, live, password)


def _check_consents(settings: Settings, choices: OAuthSignup) -> None:
    if choices.consents and choices.consents_version is None:
        raise service.AuthError("consents_version_required", 422)
    if choices.consents_version is not None and choices.consents_version != consents_version(settings):
        raise service.AuthError("consent_text_changed", 409)


async def begin(
    db: AsyncSession,
    settings: Settings,
    provider: AuthProvider,
    req: OAuthStartRequest,
    live: sessions.LiveSession | None,
) -> oauth.Flow:
    """Check the request and create the flow to seal into the cookie. Raises ``service.AuthError``."""
    now = clock.utcnow()
    if req.intent == "link":
        if live is None:
            raise service.AuthError("unauthenticated", 401)
        if live.row.mfa_pending:
            raise service.AuthError("mfa_required", 401)
        await ensure_fresh_proof(db, settings, live.user, live, req.current_password)
        return oauth.new_flow(provider, "link", "/settings/security", now=now, session=csrf.binding_for(live.token))
    signup: OAuthSignup | None = None
    if req.intent == "signup":
        # The email form's checks, minus the address and password (the provider supplies the address).
        signup = req.signup
        if signup is None or not signup.accept_terms:
            raise service.AuthError("terms_not_accepted", 422)
        if signup.side == "org" and signup.org is None:
            raise service.AuthError("org_details_required", 422)
        _check_consents(settings, signup)
    return oauth.new_flow(provider, req.intent, req.return_to or "/dev", now=now, signup=signup)


# ------------------------------------------------------------------------------------------------ callback


async def complete(
    db: AsyncSession,
    settings: Settings,
    flow: oauth.Flow,
    ident: oauth.ProviderIdentity,
    *,
    live: sessions.LiveSession | None,
    ip: str,
    user_agent: str | None,
) -> Outcome:
    """Decide what an authenticated provider identity may do (rules in the module docstring)."""
    if flow.intent == "link":
        return await _link(db, settings, flow, ident, live)
    known = await _identity(db, ident.provider, ident.subject)
    if known is not None:
        return await _sign_in_known(db, settings, flow, known, ip, user_agent)
    if ident.email is None:
        return failed(flow.intent, "oauth_no_email", flow.provider)
    if not ident.email_verified:
        if flow.intent == "login":
            return failed(flow.intent, "oauth_email_unverified", flow.provider)
        return await _signup_unverified(db, settings, flow, ident, ident.email, ip)
    user = await service.user_by_email(db, ident.email)
    if user is None:
        if flow.intent == "login":
            return Outcome("/signup", {"oauth_error": "oauth_no_account", "provider": flow.provider.value})
        return await _signup_verified(db, settings, flow, ident, ident.email, user_agent)
    if user.status != UserStatus.ACTIVE:
        return failed(flow.intent, "oauth_failed", flow.provider)
    if user.email_verified_at is None:
        # Both sides must have proven the address before it signs anyone in: the owner gets a link.
        return Outcome(CHECK_EMAIL, pending=await service.request_magic_link(db, settings, user.email, ip))
    return await _sign_in_by_address(db, settings, flow, user, user_agent)


async def _identity(db: AsyncSession, provider: AuthProvider, subject: str) -> AuthIdentity | None:
    stmt = select(AuthIdentity).where(AuthIdentity.provider == provider, AuthIdentity.subject == subject)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _has_provider(db: AsyncSession, user_id: UUID, provider: AuthProvider) -> bool:
    stmt = (
        select(func.count())
        .select_from(AuthIdentity)
        .where(AuthIdentity.user_id == user_id, AuthIdentity.provider == provider)
    )
    return int((await db.execute(stmt)).scalar_one()) > 0


async def _attach(db: AsyncSession, user_id: UUID, ident: oauth.ProviderIdentity) -> AuthIdentity | None:
    """Insert the identity; None when a concurrent request attached the same (provider, subject) first."""
    identity = AuthIdentity(user_id=user_id, provider=ident.provider, subject=ident.subject)
    try:
        async with db.begin_nested():
            db.add(identity)
            await db.flush()
    except IntegrityError:
        return None
    return identity


def _notice(settings: Settings, user: User, provider: AuthProvider, what: str) -> PendingEmail:
    # [[COPY-REVIEW]] plain transactional copy
    return service.notice_email(settings, user, f"{oauth.PROVIDERS[provider].label} sign-in was {what} your account.")


async def _record_link(db: AsyncSession, user: User, identity: AuthIdentity) -> None:
    await audit(
        db,
        "auth.identity_linked",
        actor_user_id=user.id,
        subject_type="auth_identity",
        subject_id=identity.id,
        payload={"provider": identity.provider.value},
    )


async def _sign_in(
    db: AsyncSession,
    settings: Settings,
    flow: oauth.Flow,
    user: User,
    user_agent: str | None,
    *,
    via: Literal["identity", "email", "signup"],
) -> Outcome:
    """A new session (MFA pending when TOTP is on); ``via`` a linked identity, the verified address or a new account."""
    started = await service.start_session(db, settings, user, user_agent)
    await audit(
        db,
        "auth.oauth_login",
        actor_user_id=user.id,
        subject_type="user",
        subject_id=user.id,
        payload={"provider": flow.provider.value, "via": via},
    )
    return Outcome("/auth/mfa" if started.mfa_required else flow.return_to, session=started.session)


async def _sign_in_known(
    db: AsyncSession, settings: Settings, flow: oauth.Flow, identity: AuthIdentity, ip: str, user_agent: str | None
) -> Outcome:
    user = await db.get(User, identity.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        return failed(flow.intent, "oauth_failed", flow.provider)
    await bind_tenant(db, user_id=user.id)
    if user.email_verified_at is None:
        # Attached at an unverified signup: confirm the address first (as a password login does), and bind the new
        # link to this browser, which just proved the identity.
        pending: list[PendingEmail] = []
        if await service.allow_email(db, settings, "magic", user.email, ip):
            token = await service.issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
            pending = [service.verification_email(settings, user, token)]
        binding = identity_binding(settings, user.id, identity.id)
        return Outcome(CHECK_EMAIL, check_email=True, binding=binding, pending=pending)
    return await _sign_in(db, settings, flow, user, user_agent, via="identity")


async def _sign_in_by_address(
    db: AsyncSession, settings: Settings, flow: oauth.Flow, user: User, ua: str | None
) -> Outcome:
    """Provider and account both verified the same address: sign in as an emailed link would, attaching nothing (the
    second factor, when on, is still to come; an identity joins the account only through ``link``)."""
    await bind_tenant(db, user_id=user.id)
    if await _has_provider(db, user.id, flow.provider):
        # The account holds another identity from this provider: the address alone does not stand in for it.
        return failed(flow.intent, "provider_already_linked", flow.provider)
    return await _sign_in(db, settings, flow, user, ua, via="email")


async def _create(
    db: AsyncSession, settings: Settings, flow: oauth.Flow, ident: oauth.ProviderIdentity, email: str, *, verified: bool
) -> tuple[User, AuthIdentity]:
    """A new account with the identity attached, all or nothing. Raises ``_Taken`` on a concurrent signup."""
    choices = flow.signup
    assert choices is not None  # begin() requires the choices for a signup flow
    account = service.NewAccount(
        email=email,
        display_name=ident.display_name or email.partition("@")[0],
        locale=choices.locale,
        side=choices.side,
        org=choices.org,
        consents=choices.consents,
        method=flow.provider.value,
    )
    try:
        async with db.begin_nested():
            user = await service.create_account(
                db, settings, account, password_hash=None, verified_at=clock.utcnow() if verified else None
            )
            if user is None:
                raise _Taken
            identity = AuthIdentity(user_id=user.id, provider=ident.provider, subject=ident.subject)
            db.add(identity)
            await db.flush()
    except IntegrityError as exc:
        raise _Taken from exc
    await _record_link(db, user, identity)
    return user, identity


def _stale_consents(settings: Settings, flow: oauth.Flow) -> str | None:
    """The error code when the consent wording changed after the form was shown (within the 10 minutes)."""
    assert flow.signup is not None  # begin() requires the choices for a signup flow
    try:
        _check_consents(settings, flow.signup)
    except service.AuthError as exc:
        return exc.code
    return None


async def _signup_verified(
    db: AsyncSession, settings: Settings, flow: oauth.Flow, ident: oauth.ProviderIdentity, email: str, ua: str | None
) -> Outcome:
    stale = _stale_consents(settings, flow)
    if stale is not None:
        return failed(flow.intent, stale, flow.provider)
    try:
        user, _ = await _create(db, settings, flow, ident, email, verified=True)
    except _Taken:
        return failed(flow.intent, "oauth_failed", flow.provider)
    return await _sign_in(db, settings, flow, user, ua, via="signup")


async def _signup_unverified(
    db: AsyncSession, settings: Settings, flow: oauth.Flow, ident: oauth.ProviderIdentity, email: str, ip: str
) -> Outcome:
    """Signup with an address the provider has not verified: the same answer whether or not an account exists."""
    stale = _stale_consents(settings, flow)
    if stale is not None:
        return failed(flow.intent, stale, flow.provider)
    existing = await service.user_by_email(db, email)
    if existing is not None:
        # Never linked: the owner gets a sign-in (or verification) link, throttled; nothing else changes.
        return Outcome(CHECK_EMAIL, check_email=True, pending=await service.request_magic_link(db, settings, email, ip))
    if not await service.allow_email(db, settings, "signup", email, ip):
        return Outcome(CHECK_EMAIL, check_email=True)  # silent, as for an email signup
    try:
        user, identity = await _create(db, settings, flow, ident, email, verified=False)
    except _Taken:
        return Outcome(CHECK_EMAIL, check_email=True)
    token = await service.issue_link(db, settings, user, LoginTokenPurpose.VERIFY_EMAIL)
    return Outcome(
        CHECK_EMAIL,
        check_email=True,
        binding=identity_binding(settings, user.id, identity.id),
        pending=[service.verification_email(settings, user, token)],
    )


async def _link(
    db: AsyncSession,
    settings: Settings,
    flow: oauth.Flow,
    ident: oauth.ProviderIdentity,
    live: sessions.LiveSession | None,
) -> Outcome:
    """``link``: only in the session that started the flow (it passed the fresh-proof check then)."""
    if (
        live is None
        or live.row.mfa_pending
        or flow.session is None
        or not hmac.compare_digest(flow.session, csrf.binding_for(live.token))
    ):
        return failed(None, "oauth_session", flow.provider)
    user = await service.lock_user(db, live.user.id)
    await bind_tenant(db, user_id=user.id)
    linked = Outcome("/settings/security", {"linked": flow.provider.value})
    known = await _identity(db, ident.provider, ident.subject)
    if known is not None:
        return linked if known.user_id == user.id else failed("link", "identity_in_use", flow.provider)
    if await _has_provider(db, user.id, flow.provider):
        return failed("link", "provider_already_linked", flow.provider)
    identity = await _attach(db, user.id, ident)
    if identity is None:
        return failed("link", "identity_in_use", flow.provider)
    await _record_link(db, user, identity)
    linked.pending.append(_notice(settings, user, flow.provider, "added to"))
    return linked


# ------------------------------------------------------------------------------------------------ settings


async def list_for(db: AsyncSession, user_id: UUID) -> list[AuthIdentity]:
    stmt = select(AuthIdentity).where(AuthIdentity.user_id == user_id).order_by(AuthIdentity.created_at)
    return list((await db.execute(stmt)).scalars())


async def unlink(
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, identity_id: UUID, password: str | None
) -> list[PendingEmail]:
    """Remove one of the signed-in account's identities (404 for anyone else's), keeping a way to sign in. The
    account's other sessions end, so none opened with the removed identity outlives it."""
    user = await service.lock_user(db, live.user.id)
    stmt = select(AuthIdentity).where(AuthIdentity.id == identity_id, AuthIdentity.user_id == user.id)
    identity = (await db.execute(stmt)).scalar_one_or_none()
    if identity is None:
        raise service.AuthError("not_found", 404)
    await ensure_fresh_proof(db, settings, user, live, password)
    others = (
        select(func.count())
        .select_from(AuthIdentity)
        .where(AuthIdentity.user_id == user.id, AuthIdentity.id != identity.id)
    )
    has_other_identity = int((await db.execute(others)).scalar_one()) > 0
    if user.password_hash is None and not has_other_identity and user.email_verified_at is None:
        raise service.AuthError("last_sign_in_method", 409)
    provider = identity.provider
    await db.delete(identity)
    await sessions.revoke_all(db, user.id, except_id=live.row.id)  # as a password change does
    await audit(
        db,
        "auth.identity_unlinked",
        actor_user_id=user.id,
        subject_type="auth_identity",
        subject_id=identity_id,
        payload={"provider": provider.value},
    )
    return [_notice(settings, user, provider, "removed from")]
