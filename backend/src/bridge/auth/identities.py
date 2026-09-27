"""OAuth identities (REQ-AUTH-02): which account a provider identity may reach, linking and unlinking.

Plain code decides (docs/spec/04 principle 1). For a ``login`` or ``signup`` callback, in order:

1. A known identity (provider, subject) signs in its account (MFA pending when TOTP is on), whatever its address is
   now. An account whose address is still unverified is not signed in: a verification link is sent instead.
2. Otherwise the provider's address decides, and only when the provider verified it: an account with that address
   and a verified address gets the identity linked and the person signed in; an unverified account gets nothing
   linked and its owner an emailed link; with no account, ``signup`` creates one (address verified by the provider)
   and ``login`` sends the person to signup, where the terms and consents are chosen.
3. An address the provider has not verified never reaches an existing account (account pre-hijacking). ``login``
   answers ``oauth_email_unverified`` whether or not an account exists. ``signup`` answers "check your email" either
   way: a new account is created unverified, its identity bound to this browser (``__Host-bridge_signup``), so a
   verification link opened elsewhere drops the identity (``service.consume_link``); an existing owner gets a link.

Linking (``link``) completes only in the session that started it, which needed a fresh second factor (TOTP accounts,
the ADR-002 step-up rule) or a sign-in within the last 15 minutes (other accounts); an identity that belongs to
another account is refused, and an account holds one identity per provider. Unlinking needs the same proof and
another way to sign in: a password, another identity, or an emailed link to the verified address, so an account with
a verified address can always unlink. Each change emails a security notice. Audit events carry ids and the provider
name only; provider tokens are never stored.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge import clock
from bridge.audit.service import record as audit
from bridge.auth import csrf, oauth, service, sessions
from bridge.auth.cookies import identity_binding
from bridge.auth.mailer import PendingEmail
from bridge.auth.models import AuthIdentity, User
from bridge.auth.schemas import OAuthSignup, OAuthStartRequest
from bridge.config import Settings
from bridge.db import bind_tenant
from bridge.models.enums import AuthProvider, LoginTokenPurpose, UserStatus
from bridge.profiles.consents import consents_version

ERROR_PAGES: dict[oauth.Intent, str] = {"login": "/login", "signup": "/signup", "link": "/settings/security"}
CHECK_EMAIL = "/signup/check-email"


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


# ------------------------------------------------------------------------------------------------ start


def ensure_fresh_proof(settings: Settings, live: sessions.LiveSession) -> None:
    """Adding or removing a sign-in method: a second factor within STEP_UP_MAX_AGE_HOURS when TOTP is on (the
    step-up rule), otherwise a sign-in within the last 15 minutes (the rule for other credential changes)."""
    if live.user.totp_enabled_at is not None:
        if not sessions.mfa_fresh(live.row, timedelta(hours=settings.step_up_max_age_hours)):
            raise service.AuthError("step_up_required", 403)
    elif clock.utcnow() - live.row.created_at > service.REAUTH_WINDOW:
        raise service.AuthError("recent_sign_in_required", 403)


def _check_consents(settings: Settings, choices: OAuthSignup) -> None:
    if choices.consents and choices.consents_version is None:
        raise service.AuthError("consents_version_required", 422)
    if choices.consents_version is not None and choices.consents_version != consents_version(settings):
        raise service.AuthError("consent_text_changed", 409)


def begin(
    settings: Settings, provider: AuthProvider, req: OAuthStartRequest, live: sessions.LiveSession | None
) -> oauth.Flow:
    """Check the request and create the flow to seal into the cookie. Raises ``service.AuthError``."""
    now = clock.utcnow()
    if req.intent == "link":
        if live is None:
            raise service.AuthError("unauthenticated", 401)
        if live.row.mfa_pending:
            raise service.AuthError("mfa_required", 401)
        ensure_fresh_proof(settings, live)
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
        # Both sides must have proven the address before an identity joins an account: the owner gets a link.
        return Outcome(CHECK_EMAIL, pending=await service.request_magic_link(db, settings, user.email, ip))
    return await _link_and_sign_in(db, settings, flow, user, ident, user_agent)


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
    db: AsyncSession, settings: Settings, flow: oauth.Flow, user: User, user_agent: str | None
) -> Outcome:
    started = await service.start_session(db, settings, user, user_agent)
    await audit(
        db,
        "auth.oauth_login",
        actor_user_id=user.id,
        subject_type="user",
        subject_id=user.id,
        payload={"provider": flow.provider.value},
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
    return await _sign_in(db, settings, flow, user, user_agent)


async def _link_and_sign_in(
    db: AsyncSession, settings: Settings, flow: oauth.Flow, user: User, ident: oauth.ProviderIdentity, ua: str | None
) -> Outcome:
    """Provider and account both verified the same address: link, notify, sign in."""
    user = await service.lock_user(db, user.id)
    await bind_tenant(db, user_id=user.id)
    if await _has_provider(db, user.id, flow.provider):
        return failed(flow.intent, "provider_already_linked", flow.provider)
    identity = await _attach(db, user.id, ident)
    if identity is None:
        return failed(flow.intent, "oauth_failed", flow.provider)
    await _record_link(db, user, identity)
    outcome = await _sign_in(db, settings, flow, user, ua)
    outcome.pending.append(_notice(settings, user, flow.provider, "added to"))
    return outcome


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
    try:
        if flow.signup is not None:
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
    return await _sign_in(db, settings, flow, user, ua)


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
    db: AsyncSession, settings: Settings, live: sessions.LiveSession, identity_id: UUID
) -> list[PendingEmail]:
    """Remove one of the signed-in account's identities (404 for anyone else's), keeping a way to sign in."""
    user = await service.lock_user(db, live.user.id)
    stmt = select(AuthIdentity).where(AuthIdentity.id == identity_id, AuthIdentity.user_id == user.id)
    identity = (await db.execute(stmt)).scalar_one_or_none()
    if identity is None:
        raise service.AuthError("not_found", 404)
    ensure_fresh_proof(settings, live)
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
    await audit(
        db,
        "auth.identity_unlinked",
        actor_user_id=user.id,
        subject_type="auth_identity",
        subject_id=identity_id,
        payload={"provider": provider.value},
    )
    return [_notice(settings, user, provider, "removed from")]
