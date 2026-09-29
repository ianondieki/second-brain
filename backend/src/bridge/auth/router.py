"""Auth API (REQ-AUTH-01, OAuth REQ-AUTH-02): /api/auth/* and /api/me/identities. Every state-changing call needs
the CSRF header (see bridge.main). Emails are sent after the response (``BackgroundTasks`` + ``bridge.auth.mailer``)."""

from __future__ import annotations

import hmac
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from bridge import clock
from bridge.auth import identities, oauth, service, sessions
from bridge.auth.cookies import (
    clear_oauth_flow,
    clear_session,
    set_csrf,
    set_oauth_flow,
    set_session,
    set_signup_binding,
    signup_cookie_name,
)
from bridge.auth.deps import (
    CurrentSession,
    Db,
    EmailDep,
    PendingSession,
    SettingsDep,
    StepUpSession,
    client_ip,
    optional_session,
)
from bridge.auth.mailer import PendingEmail, deliver
from bridge.auth.models import User
from bridge.auth.schemas import (
    AcceptedResponse,
    CodeRequest,
    CsrfResponse,
    EmailRequest,
    IdentityOut,
    LoginRequest,
    MembershipOut,
    MeResponse,
    MfaState,
    OAuthProvidersResponse,
    OAuthStartRequest,
    OAuthStartResponse,
    RecoveryCodesResponse,
    SessionResponse,
    SetPasswordRequest,
    SignupRequest,
    TokenRequest,
    TotpEnrolRequest,
    TotpEnrolResponse,
    UnlinkRequest,
    UserOut,
)
from bridge.errors import ERROR_RESPONSES, ApiError, not_found
from bridge.notifications.email import EmailProvider
from bridge.profiles.router import SESSION_ONLY_MESSAGE
from bridge.tenancy.service import my_memberships

router = APIRouter(prefix="/api/auth", tags=["auth"], responses=ERROR_RESPONSES)
me_router = APIRouter(prefix="/api/me", tags=["me"], responses=ERROR_RESPONSES)
OptionalSession = Annotated[sessions.LiveSession | None, Depends(optional_session)]
MAX_CALLBACK_PARAM_CHARS = 2048

MESSAGES = {
    "invalid_email": "Enter a standard email address, such as name@example.com.",
    "terms_not_accepted": "Accept the terms to create an account.",
    "org_details_required": "Enter your organisation's name and type.",
    "consents_version_required": "Reload the page to see the current consent wording.",
    "consent_text_changed": "The consent wording has changed. Reload the page and choose again.",
    "consent_session_only": SESSION_ONLY_MESSAGE,  # the settings API's words (REQ-PROP-05)
    "weak_password": "Use a password of at least 12 characters that is not your email address.",
    "invalid_credentials": "That email and password do not match an account.",
    "email_unverified": "Confirm your email first. We have sent you a new link.",
    "too_many_attempts": "Too many attempts. Wait a minute and try again.",
    "invalid_or_expired_link": "This link has expired or was already used. Ask for a new one.",
    "invalid_code": "That code is not valid. Check your authenticator app and try again.",
    "totp_already_enabled": "Two-step sign-in is already on.",
    "no_pending_enrolment": "Start two-step sign-in setup first.",
    "totp_not_enabled": "Turn on two-step sign-in first.",  # [[COPY-REVIEW]] plain transactional copy
    "mfa_mandatory_for_role": "Your role requires two-step sign-in, so it cannot be turned off.",
    "current_password_required": "Enter your current password to make this change.",
    "recent_sign_in_required": "Sign in again with an emailed link to make this change.",
    "unauthenticated": "Sign in to continue.",
    "mfa_required": "Enter the code from your authenticator app.",
    "step_up_required": "Confirm with your authenticator code to continue.",
    "last_sign_in_method": "Set a password or link another account before removing this one.",
    "not_found": "Not found.",
}


def _fail(exc: service.AuthError) -> ApiError:
    return ApiError(exc.status, exc.code, MESSAGES.get(exc.code, "The request could not be completed."))


def _send_later(tasks: BackgroundTasks, request: Request, provider: EmailProvider, pending: list[PendingEmail]) -> None:
    if pending:
        tasks.add_task(deliver, request.app.state.session_factory, provider, pending)


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        email_verified=user.email_verified_at is not None,
        password_set=user.password_hash is not None,
        staff_role=user.staff_role,
        totp_enabled=user.totp_enabled_at is not None,
    )


@router.get("/csrf")
async def csrf_token(request: Request, response: Response, settings: SettingsDep) -> CsrfResponse:
    """Issue a CSRF cookie bound to the current session (or to the anonymous visitor)."""
    return CsrfResponse(csrf_token=set_csrf(response, settings, request.cookies.get(settings.session_cookie_name)))


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
async def signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    tasks: BackgroundTasks,
    db: Db,
    settings: SettingsDep,
    email: EmailDep,
) -> AcceptedResponse:
    """Create an account and email its link; 202 "check your email" whether or not the address has an account. 422
    invalid_email, terms_not_accepted, org_details_required, weak_password, consents_version_required, or
    consent_session_only (a purpose decided per sign-in, such as tier2_llm_assistant); 409 consent_text_changed."""
    try:
        outcome = await service.signup(db, settings, body, client_ip(request))
    except service.AuthError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    set_signup_binding(response, settings, outcome.binding)
    _send_later(tasks, request, email, outcome.pending)
    return AcceptedResponse()


@router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
async def magic_link(
    body: EmailRequest, request: Request, tasks: BackgroundTasks, db: Db, settings: SettingsDep, email: EmailDep
) -> AcceptedResponse:
    """Email a sign-in link (or a fresh verification link to an unverified account). Always 202."""
    pending = await service.request_magic_link(db, settings, body.email, client_ip(request))
    await db.commit()
    _send_later(tasks, request, email, pending)
    return AcceptedResponse()


@router.post("/verify-email/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    body: EmailRequest, request: Request, tasks: BackgroundTasks, db: Db, settings: SettingsDep, email: EmailDep
) -> AcceptedResponse:
    """Same behaviour as /magic-link: unverified accounts get a verification link. Always 202."""
    return await magic_link(body, request, tasks, db, settings, email)


@router.post("/magic-link/consume")
async def consume(
    body: TokenRequest, request: Request, response: Response, db: Db, settings: SettingsDep
) -> SessionResponse:
    try:
        outcome = await service.consume_link(
            db,
            settings,
            body.token,
            request.headers.get("user-agent"),
            request.cookies.get(signup_cookie_name(settings)),
        )
    except service.AuthError as exc:
        raise _fail(exc) from exc
    await db.commit()
    set_session(response, settings, outcome.session.token)
    response.delete_cookie(signup_cookie_name(settings), path="/", secure=settings.cookie_secure, httponly=True)
    return SessionResponse(user=user_out(outcome.session.user), mfa_required=outcome.mfa_required)


@router.post("/login", response_model=SessionResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    tasks: BackgroundTasks,
    db: Db,
    settings: SettingsDep,
    email: EmailDep,
) -> SessionResponse | JSONResponse:
    try:
        outcome = await service.login(
            db, settings, body.email, body.password, client_ip(request), request.headers.get("user-agent")
        )
    except service.AuthError as exc:
        await db.commit()  # keep the throttle ledger entry and any fresh verification link even on failure
        _send_later(tasks, request, email, exc.pending)
        if exc.binding is None:
            raise _fail(exc) from exc
        # Unverified account, right password: the new verification link is bound to this browser.
        failure = JSONResponse(
            status_code=exc.status,
            content={"detail": {"code": exc.code, "message": MESSAGES[exc.code]}},
            background=tasks,
        )
        set_signup_binding(failure, settings, exc.binding)
        return failure
    await db.commit()
    set_session(response, settings, outcome.session.token)
    return SessionResponse(user=user_out(outcome.session.user), mfa_required=outcome.mfa_required)


@router.post("/mfa/verify")
async def mfa_verify(
    body: CodeRequest, request: Request, response: Response, live: PendingSession, db: Db, settings: SettingsDep
) -> SessionResponse:
    """Second step of sign-in. A new session (and cookie) replaces the pending one."""
    try:
        fresh = await service.complete_mfa(db, settings, live, body.code, client_ip(request), rotate=True)
    except service.AuthError as exc:
        await db.commit()
        raise _fail(exc) from exc
    await db.commit()
    set_session(response, settings, fresh.token)
    return SessionResponse(user=user_out(fresh.user), mfa_required=False)


@router.post("/step-up")
async def step_up(
    body: CodeRequest, request: Request, live: CurrentSession, db: Db, settings: SettingsDep
) -> SessionResponse:
    try:
        await service.complete_mfa(db, settings, live, body.code, client_ip(request), rotate=False)
    except service.AuthError as exc:
        await db.commit()
        raise _fail(exc) from exc
    await db.commit()
    return SessionResponse(user=user_out(live.user), mfa_required=False)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response, live: PendingSession, db: Db, settings: SettingsDep) -> None:
    await service.logout(db, live)
    await db.commit()
    clear_session(response, settings)


@router.get("/me")
async def me(live: PendingSession, db: Db) -> MeResponse:
    """Who is signed in. Before the second factor only the MFA state is shown (no organisations or roles)."""
    user = live.user
    required = await service.mfa_required_for(db, user)
    mfa = MfaState(
        required=required,
        enrolled=user.totp_enabled_at is not None,
        verified=not live.row.mfa_pending and live.row.mfa_verified_at is not None,
    )
    if live.row.mfa_pending:
        # Before the second factor: no organisations, roles or staff status.
        pending = user_out(user).model_copy(update={"staff_role": None})
        return MeResponse(user=pending, memberships=[], mfa=mfa, side="pending")
    memberships = await my_memberships(db, user.id)
    if user.staff_role:
        side = "staff"
    elif await service.has_developer_profile(db, user.id):
        side = "developer"
    else:
        side = "org" if memberships else "developer"
    return MeResponse(
        user=user_out(user),
        memberships=[MembershipOut(org_id=m.org.id, org_name=m.org.legal_name, roles=m.roles) for m in memberships],
        mfa=mfa,
        side=side,
    )


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def set_password(
    body: SetPasswordRequest,
    request: Request,
    tasks: BackgroundTasks,
    live: CurrentSession,
    db: Db,
    settings: SettingsDep,
    email: EmailDep,
) -> None:
    """Set or change the password: the current one is required when set; a password-less account needs a sign-in
    within the last 15 minutes. Other sessions end; the account gets a notice."""
    try:
        pending = await service.set_password(
            db, settings, live, body.current_password, body.new_password, ip=client_ip(request)
        )
    except service.AuthError as exc:
        await db.commit()  # keep the re-auth throttle entry
        raise _fail(exc) from exc
    await db.commit()
    _send_later(tasks, request, email, pending)


@router.post("/totp/enrol")
async def totp_enrol(
    body: TotpEnrolRequest, request: Request, live: CurrentSession, db: Db, settings: SettingsDep
) -> TotpEnrolResponse:
    try:
        secret, uri = await service.begin_totp_enrolment(db, settings, live, body.password, ip=client_ip(request))
    except service.AuthError as exc:
        await db.commit()  # keep the re-auth throttle entry
        raise _fail(exc) from exc
    await db.commit()
    return TotpEnrolResponse(secret=secret, otpauth_uri=uri)


@router.delete("/totp/enrol", status_code=status.HTTP_204_NO_CONTENT)
async def totp_enrol_cancel(live: CurrentSession, db: Db) -> None:
    """Cancel setup: clear the pending secret. It waits for a confirmation still in progress; 409
    totp_already_enabled when two-step sign-in is on (a confirmation committed first and its answer, with the recovery
    codes, may have been lost); 409 no_pending_enrolment when nothing is pending."""
    try:
        await service.cancel_totp_enrolment(db, live)
    except service.AuthError as exc:
        raise _fail(exc) from exc
    await db.commit()


@router.post("/totp/confirm")
async def totp_confirm(
    body: CodeRequest,
    request: Request,
    tasks: BackgroundTasks,
    live: CurrentSession,
    db: Db,
    settings: SettingsDep,
    email: EmailDep,
) -> RecoveryCodesResponse:
    """Turn two-step sign-in on with a code from the pending secret; returns the recovery codes, shown once. 409
    no_pending_enrolment when nothing is pending or setup began over 15 minutes ago (the expired secret is cleared);
    429 too_many_attempts after 5 codes a minute, counted with the second step and step-up codes."""
    try:
        codes, pending = await service.confirm_totp_enrolment(db, settings, live, body.code, ip=client_ip(request))
    except service.AuthError as exc:
        await db.commit()  # keep the throttle entry, and an expired pending secret cleared
        raise _fail(exc) from exc
    await db.commit()
    _send_later(tasks, request, email, pending)
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/totp/recovery-codes")
async def totp_recovery_codes(
    request: Request, tasks: BackgroundTasks, live: StepUpSession, db: Db, settings: SettingsDep, email: EmailDep
) -> RecoveryCodesResponse:
    """Ten new recovery codes replace the old ones, which stop working; shown once. Needs a second factor within
    12 hours (403 step_up_required) and two-step sign-in on (409 totp_not_enabled); 429 too_many_attempts after 5 a
    minute for the account. The account gets a security notice."""
    try:
        codes, pending = await service.replace_recovery_codes(db, settings, live, ip=client_ip(request))
    except service.AuthError as exc:
        await db.commit()  # keep the throttle entry
        raise _fail(exc) from exc
    await db.commit()
    _send_later(tasks, request, email, pending)
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(
    request: Request, tasks: BackgroundTasks, live: StepUpSession, db: Db, settings: SettingsDep, email: EmailDep
) -> None:
    try:
        pending = await service.disable_totp(db, settings, live)
    except service.AuthError as exc:
        raise _fail(exc) from exc
    await db.commit()
    _send_later(tasks, request, email, pending)


# ------------------------------------------------------------------------------------------------ OAuth (REQ-AUTH-02)


@router.get("/oauth/providers")
async def oauth_providers(settings: SettingsDep) -> OAuthProvidersResponse:
    """The OAuth providers this deployment has credentials for; the web app shows only their buttons."""
    return OAuthProvidersResponse(providers=oauth.enabled(settings))


@router.post("/oauth/{provider}/start")
async def oauth_start(
    provider: str,
    body: OAuthStartRequest,
    request: Request,
    response: Response,
    db: Db,
    settings: SettingsDep,
    live: OptionalSession,
) -> OAuthStartResponse:
    """Begin a sign-in, signup or link with ``provider`` (github or google; 404 when not configured). Sets the
    short-lived flow cookie; the browser then navigates to ``authorize_url``. ``link`` needs a signed-in session with
    a fresh second factor (TOTP accounts) and ``current_password`` (accounts with a password), or a sign-in within
    15 minutes (password-less accounts without TOTP); ``signup`` needs the accepted terms and no purpose decided per
    sign-in (422 consent_session_only). 429 too_many_attempts after 10 starts a minute from one IP."""
    client = oauth.configured(settings, provider)
    if client is None:
        raise not_found()
    if not await identities.allow_request(db, settings, "start", client_ip(request)):
        raise _fail(service.AuthError("too_many_attempts", 429))
    try:
        flow = await identities.begin(db, settings, client.provider.name, body, live, ip=client_ip(request))
    except service.AuthError as exc:
        await db.commit()  # keep the re-auth throttle entry
        raise _fail(exc) from exc
    await db.commit()
    set_oauth_flow(response, settings, oauth.seal(settings, flow), int(oauth.FLOW_TTL.total_seconds()))
    return OAuthStartResponse(authorize_url=oauth.authorize_url(client, flow))


def _state_matches(presented: str | None, flow: oauth.Flow) -> bool:
    if presented is None or len(presented) > MAX_CALLBACK_PARAM_CHARS:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), flow.state.encode("utf-8"))


@router.get(
    "/oauth/{provider}/callback",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
    responses={302: {"description": "To a fixed page of the web app; errors as ?oauth_error=CODE&provider=NAME"}},
)
async def oauth_callback(
    provider: str,
    request: Request,
    tasks: BackgroundTasks,
    db: Db,
    settings: SettingsDep,
    email: EmailDep,
    live: OptionalSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """The provider sends the browser here. Always redirects to a fixed page on PUBLIC_BASE_URL. The flow cookie is
    spent when the callback presents its state, or when it is missing, unreadable or expired; a callback with another
    state (or none) leaves it, so a forged one cannot end a flow in progress. The first callback carrying a code also
    spends its state server-side, so a replay gets oauth_state.
    Error codes: oauth_state, oauth_cancelled, oauth_failed, oauth_no_email, oauth_email_unverified,
    oauth_no_account, oauth_session, identity_in_use, provider_already_linked, consent_text_changed,
    consents_version_required, consent_session_only, too_many_attempts (10 callbacks a minute from one IP that would
    reach the provider).
    Success: the return path (or /auth/mfa), /signup/check-email, or /settings/security?linked=PROVIDER."""
    client = oauth.configured(settings, provider)
    if client is None:
        raise not_found()
    now = clock.utcnow()
    flow = oauth.unseal(settings, request.cookies.get(settings.oauth_cookie_name), now=now)
    presented = flow is not None and _state_matches(state, flow)
    # The checks up to the throttle charge no throttle row and never reach the provider, so a forged callback (a page
    # loading this URL in someone's browser with a junk state) never uses up that person's budget.
    if flow is None or flow.provider != client.provider.name or not presented:
        outcome = identities.failed(None, "oauth_state", client.provider.name)
    elif error is not None:
        outcome = identities.failed(flow.intent, "oauth_cancelled", flow.provider)  # never the provider's own text
    elif not code or len(code) > MAX_CALLBACK_PARAM_CHARS:
        outcome = identities.failed(flow.intent, "oauth_failed", flow.provider)
    elif not await identities.allow_request(db, settings, "callback", client_ip(request)):
        outcome = identities.failed(flow.intent, "too_many_attempts", flow.provider)
    elif not await identities.spend_state(db, settings, flow):
        outcome = identities.failed(None, "oauth_state", flow.provider)  # a replay, like a missing cookie
    else:
        # Keep the throttle entry and release the connection (and any row or advisory lock) before the provider call.
        await db.commit()
        try:
            ident = await oauth.fetch_identity(client, flow, code, now=now)
        except oauth.ProviderError:
            outcome = identities.failed(flow.intent, "oauth_failed", flow.provider)
        else:
            outcome = await identities.complete(
                db,
                settings,
                flow,
                ident,
                live=await identities.reload_session(db, live),  # it may have ended during the provider call
                ip=client_ip(request),
                user_agent=request.headers.get("user-agent"),
            )
    await db.commit()
    response = RedirectResponse(
        oauth.web_url(settings, outcome.path, outcome.params), status_code=status.HTTP_302_FOUND, background=tasks
    )
    response.headers["Referrer-Policy"] = "no-referrer"  # the callback URL carries the code and state
    if flow is None or presented:
        # Spent or unusable. A sealed, unexpired flow whose state was not presented stays: SameSite=Lax sends the
        # cookie with a forged top-level GET too, and deleting it would fail the person's genuine return.
        clear_oauth_flow(response, settings)
    if outcome.session is not None:
        set_session(response, settings, outcome.session.token)
    if outcome.check_email:
        set_signup_binding(response, settings, outcome.binding)
    _send_later(tasks, request, email, outcome.pending)
    return response


@router.delete("/identities/{identity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_identity(
    identity_id: UUID,
    request: Request,
    tasks: BackgroundTasks,
    live: CurrentSession,
    db: Db,
    settings: SettingsDep,
    email: EmailDep,
    body: UnlinkRequest | None = None,
) -> None:
    """Unlink a provider (the same proof as linking: ``current_password`` when the account has one); the account's
    other sessions end. 409 last_sign_in_method when nothing else could sign in."""
    try:
        password = body.current_password if body else None
        pending = await identities.unlink(db, settings, live, identity_id, password, ip=client_ip(request))
    except service.AuthError as exc:
        await db.commit()  # keep the re-auth throttle entry
        raise _fail(exc) from exc
    await db.commit()
    _send_later(tasks, request, email, pending)


@me_router.get("/identities")
async def my_identities(live: CurrentSession, db: Db) -> list[IdentityOut]:
    """The providers linked to the signed-in account (provider tokens are never stored)."""
    rows = await identities.list_for(db, live.user.id)
    return [IdentityOut(id=row.id, provider=row.provider, linked_at=row.created_at) for row in rows]
