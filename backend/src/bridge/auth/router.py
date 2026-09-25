"""Auth API (REQ-AUTH-01): /api/auth/*. Every state-changing call needs the CSRF header (see bridge.main).
Emails are sent after the response (``BackgroundTasks`` + ``bridge.auth.mailer``)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request, Response, status
from fastapi.responses import JSONResponse

from bridge.auth import service
from bridge.auth.cookies import clear_session, set_csrf, set_session, set_signup_binding, signup_cookie_name
from bridge.auth.deps import CurrentSession, Db, EmailDep, PendingSession, SettingsDep, StepUpSession, client_ip
from bridge.auth.mailer import PendingEmail, deliver
from bridge.auth.models import User
from bridge.auth.schemas import (
    AcceptedResponse,
    CodeRequest,
    CsrfResponse,
    EmailRequest,
    LoginRequest,
    MembershipOut,
    MeResponse,
    MfaState,
    RecoveryCodesResponse,
    SessionResponse,
    SetPasswordRequest,
    SignupRequest,
    TokenRequest,
    TotpEnrolRequest,
    TotpEnrolResponse,
    UserOut,
)
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.notifications.email import EmailProvider
from bridge.tenancy.service import my_memberships

router = APIRouter(prefix="/api/auth", tags=["auth"], responses=ERROR_RESPONSES)

MESSAGES = {
    "invalid_email": "Enter a standard email address, such as name@example.com.",
    "terms_not_accepted": "Accept the terms to create an account.",
    "org_details_required": "Enter your organisation's name and type.",
    "consents_version_required": "Reload the page to see the current consent wording.",
    "consent_text_changed": "The consent wording has changed. Reload the page and choose again.",
    "weak_password": "Use a password of at least 12 characters that is not your email address.",
    "invalid_credentials": "That email and password do not match an account.",
    "email_unverified": "Confirm your email first. We have sent you a new link.",
    "too_many_attempts": "Too many attempts. Wait a minute and try again.",
    "invalid_or_expired_link": "This link has expired or was already used. Ask for a new one.",
    "invalid_code": "That code is not valid. Check your authenticator app and try again.",
    "totp_already_enabled": "Two-step sign-in is already on.",
    "no_pending_enrolment": "Start two-step sign-in setup first.",
    "mfa_mandatory_for_role": "Your role requires two-step sign-in, so it cannot be turned off.",
    "current_password_required": "Enter your current password to make this change.",
    "recent_sign_in_required": "Sign in again with an emailed link to make this change.",
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
        pending = await service.set_password(db, settings, live, body.current_password, body.new_password)
    except service.AuthError as exc:
        await db.commit()  # keep the re-auth throttle entry
        raise _fail(exc) from exc
    await db.commit()
    _send_later(tasks, request, email, pending)


@router.post("/totp/enrol")
async def totp_enrol(body: TotpEnrolRequest, live: CurrentSession, db: Db, settings: SettingsDep) -> TotpEnrolResponse:
    try:
        secret, uri = await service.begin_totp_enrolment(db, settings, live, body.password)
    except service.AuthError as exc:
        await db.commit()  # keep the re-auth throttle entry
        raise _fail(exc) from exc
    await db.commit()
    return TotpEnrolResponse(secret=secret, otpauth_uri=uri)


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
    try:
        codes, pending = await service.confirm_totp_enrolment(db, settings, live, body.code)
    except service.AuthError as exc:
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
