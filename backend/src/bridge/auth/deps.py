"""FastAPI dependencies for the signed-in user (REQ-AUTH-01): session cookie -> live session -> tenant context."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth import sessions
from bridge.config import Settings
from bridge.db import bind_tenant, get_session
from bridge.errors import ApiError
from bridge.notifications.email import EmailProvider

Db = Annotated[AsyncSession, Depends(get_session)]


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_email_provider(request: Request) -> EmailProvider:
    provider: EmailProvider = request.app.state.email_provider
    return provider


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
EmailDep = Annotated[EmailProvider, Depends(get_email_provider)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def optional_session(request: Request, db: Db, settings: SettingsDep) -> sessions.LiveSession | None:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    live = await sessions.lookup(db, token)
    if live is not None:
        await bind_tenant(db, user_id=live.user.id)
    return live


async def session_allow_mfa_pending(
    live: Annotated[sessions.LiveSession | None, Depends(optional_session)],
) -> sessions.LiveSession:
    """Signed in, possibly still waiting for the second factor (used only by /auth/mfa/verify, /me, /logout)."""
    if live is None:
        raise ApiError(401, "unauthenticated", "Sign in to continue.")
    return live


async def current_session(
    live: Annotated[sessions.LiveSession, Depends(session_allow_mfa_pending)],
) -> sessions.LiveSession:
    if live.row.mfa_pending:
        raise ApiError(401, "mfa_required", "Enter the code from your authenticator app.")
    return live


async def step_up_session(
    live: Annotated[sessions.LiveSession, Depends(current_session)], settings: SettingsDep
) -> sessions.LiveSession:
    """Sensitive actions (signing, endorsements, payment confirmations, access-policy and role changes) need a
    second factor within the last ``STEP_UP_MAX_AGE_HOURS`` (ADR-002: 12 h)."""
    if not sessions.mfa_fresh(live.row, timedelta(hours=settings.step_up_max_age_hours)):
        raise ApiError(403, "step_up_required", "Confirm with your authenticator code to continue.")
    return live


CurrentSession = Annotated[sessions.LiveSession, Depends(current_session)]
PendingSession = Annotated[sessions.LiveSession, Depends(session_allow_mfa_pending)]
StepUpSession = Annotated[sessions.LiveSession, Depends(step_up_session)]
