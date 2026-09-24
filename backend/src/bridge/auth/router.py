"""Auth API (REQ-AUTH-01): /api/auth/*. Every state-changing call needs the CSRF header (see bridge.main)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from bridge.auth import service
from bridge.auth.cookies import clear_session, set_csrf, set_session
from bridge.auth.deps import CurrentSession, Db, EmailDep, PendingSession, SettingsDep, StepUpSession, client_ip
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
    SignupRequest,
    TokenRequest,
    TotpEnrolResponse,
    UserOut,
)
from bridge.errors import ApiError
from bridge.tenancy.service import my_memberships

router = APIRouter(prefix="/api/auth", tags=["auth"])

MESSAGES = {
    "invalid_email": "Enter a standard email address, such as name@example.com.",
    "terms_not_accepted": "Accept the terms to create an account.",
    "org_details_required": "Enter your organisation's name and type.",
    "weak_password": "Use a password of at least 12 characters that is not your email address.",
    "invalid_credentials": "That email and password do not match an account.",
    "email_unverified": "Confirm your email first. We have sent you a new link.",
    "too_many_attempts": "Too many attempts. Wait a minute and try again.",
    "invalid_or_expired_link": "This link has expired or was already used. Ask for a new one.",
    "invalid_code": "That code is not valid. Check your authenticator app and try again.",
    "totp_already_enabled": "Two-step sign-in is already on.",
    "no_pending_enrolment": "Start two-step sign-in setup first.",
    "mfa_mandatory_for_role": "Your role requires two-step sign-in, so it cannot be turned off.",
}


def _fail(exc: service.AuthError) -> ApiError:
    return ApiError(exc.status, exc.code, MESSAGES.get(exc.code, "The request could not be completed."))


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        email_verified=user.email_verified_at is not None,
        staff_role=user.staff_role,
        totp_enabled=user.totp_enabled_at is not None,
    )


@router.get("/csrf")
async def csrf_token(request: Request, response: Response, settings: SettingsDep) -> CsrfResponse:
    """Issue a CSRF cookie bound to the current session (or to the anonymous visitor)."""
    return CsrfResponse(csrf_token=set_csrf(response, settings, request.cookies.get(settings.session_cookie_name)))


@router.post("/signup", status_code=status.HTTP_202_ACCEPTED)
async def signup(body: SignupRequest, db: Db, settings: SettingsDep, email: EmailDep) -> AcceptedResponse:
    try:
        await service.signup(db, settings, email, body)
    except service.AuthError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return AcceptedResponse()


@router.post("/magic-link", status_code=status.HTTP_202_ACCEPTED)
async def magic_link(
    body: EmailRequest, request: Request, db: Db, settings: SettingsDep, email: EmailDep
) -> AcceptedResponse:
    """Email a sign-in link (or a fresh verification link to an unverified account). Always 202."""
    await service.request_magic_link(db, settings, email, body.email, client_ip(request))
    await db.commit()
    return AcceptedResponse()


@router.post("/verify-email/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    body: EmailRequest, request: Request, db: Db, settings: SettingsDep, email: EmailDep
) -> AcceptedResponse:
    """Same behaviour as /magic-link: unverified accounts get a verification link. Always 202."""
    return await magic_link(body, request, db, settings, email)


@router.post("/magic-link/consume")
async def consume(
    body: TokenRequest, request: Request, response: Response, db: Db, settings: SettingsDep
) -> SessionResponse:
    try:
        outcome = await service.consume_link(db, settings, body.token, request.headers.get("user-agent"))
    except service.AuthError as exc:
        raise _fail(exc) from exc
    await db.commit()
    set_session(response, settings, outcome.session.token)
    return SessionResponse(user=user_out(outcome.session.user), mfa_required=outcome.mfa_required)


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, db: Db, settings: SettingsDep, email: EmailDep
) -> SessionResponse:
    try:
        outcome = await service.login(
            db, settings, email, body.email, body.password, client_ip(request), request.headers.get("user-agent")
        )
    except service.AuthError as exc:
        await db.commit()  # keep the throttle ledger entry (and any verification email) even on failure
        raise _fail(exc) from exc
    await db.commit()
    set_session(response, settings, outcome.session.token)
    return SessionResponse(user=user_out(outcome.session.user), mfa_required=outcome.mfa_required)


@router.post("/mfa/verify")
async def mfa_verify(
    body: CodeRequest, request: Request, live: PendingSession, db: Db, settings: SettingsDep
) -> SessionResponse:
    try:
        await service.complete_mfa(db, settings, live, body.code, client_ip(request))
    except service.AuthError as exc:
        await db.commit()
        raise _fail(exc) from exc
    await db.commit()
    return SessionResponse(user=user_out(live.user), mfa_required=False)


@router.post("/step-up")
async def step_up(
    body: CodeRequest, request: Request, live: CurrentSession, db: Db, settings: SettingsDep
) -> SessionResponse:
    try:
        await service.complete_mfa(db, settings, live, body.code, client_ip(request))
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
    user = live.user
    memberships = await my_memberships(db, user.id)
    required = await service.mfa_required_for(db, user)
    side = "staff" if user.staff_role else ("org" if memberships else "developer")
    return MeResponse(
        user=user_out(user),
        memberships=[MembershipOut(org_id=m.org.id, org_name=m.org.legal_name, roles=m.roles) for m in memberships],
        mfa=MfaState(
            required=required,
            enrolled=user.totp_enabled_at is not None,
            verified=not live.row.mfa_pending and live.row.mfa_verified_at is not None,
        ),
        side=side,
    )


@router.post("/totp/enrol")
async def totp_enrol(live: CurrentSession, db: Db, settings: SettingsDep) -> TotpEnrolResponse:
    try:
        secret, uri = service.begin_totp_enrolment(settings, live.user)
    except service.AuthError as exc:
        raise _fail(exc) from exc
    await db.commit()
    return TotpEnrolResponse(secret=secret, otpauth_uri=uri)


@router.post("/totp/confirm")
async def totp_confirm(body: CodeRequest, live: CurrentSession, db: Db, settings: SettingsDep) -> RecoveryCodesResponse:
    try:
        codes = await service.confirm_totp_enrolment(db, settings, live, body.code)
    except service.AuthError as exc:
        raise _fail(exc) from exc
    await db.commit()
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(live: StepUpSession, db: Db) -> None:
    try:
        await service.disable_totp(db, live)
    except service.AuthError as exc:
        raise _fail(exc) from exc
    await db.commit()
