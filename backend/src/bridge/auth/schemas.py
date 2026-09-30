"""Request and response bodies for the auth API (REQ-AUTH-01, OAuth REQ-AUTH-02)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from bridge.models.enums import AuthProvider, ConsentPurpose, OrgKind, OrgRole, StaffRole

# Where a successful OAuth sign-in may land (an allow-list; anything else is refused with 422).
ReturnPath = Literal["/dev", "/org", "/settings/security"]


class OrgSignup(BaseModel):
    legal_name: str = Field(min_length=2, max_length=200)
    kind: OrgKind


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=120)
    side: Literal["developer", "org"]
    org: OrgSignup | None = None
    consents: dict[ConsentPurpose, bool] = Field(default_factory=dict)
    # The consents.yaml version whose texts the form showed; a stale form gets 409 consent_text_changed.
    consents_version: str | None = None
    locale: Literal["en", "sw"] = "en"
    accept_terms: bool


class AcceptedResponse(BaseModel):
    status: Literal["check_email"] = "check_email"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=200)


class CodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=20)


class MembershipOut(BaseModel):
    org_id: UUID
    org_name: str
    roles: list[OrgRole]


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    locale: str
    email_verified: bool
    password_set: bool  # False after a verification link cleared a password set in another browser
    staff_role: StaffRole | None
    totp_enabled: bool


class MfaState(BaseModel):
    required: bool
    enrolled: bool
    verified: bool


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]
    mfa: MfaState
    side: Literal["developer", "org", "staff", "pending"]  # pending: second factor not given yet


class SessionResponse(BaseModel):
    user: UserOut
    mfa_required: bool


class TotpEnrolResponse(BaseModel):
    secret: str
    otpauth_uri: str


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


class CsrfResponse(BaseModel):
    csrf_token: str


class SetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str | None = Field(default=None, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class TotpEnrolRequest(BaseModel):
    """Enrolment is a privilege change: the current password is required when the account has one."""

    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=256)


class RecoveryCodesRequest(BaseModel):
    """New recovery codes: the current password when the account has one (with a second factor within 12 hours)."""

    model_config = ConfigDict(extra="forbid")

    current_password: str | None = Field(default=None, max_length=256)


class OAuthSignup(BaseModel):
    """The signup form's choices for an OAuth signup (the address comes from the provider): replayed at the callback
    only if no account exists yet. Sealed in the flow cookie meanwhile."""

    model_config = ConfigDict(extra="forbid")

    side: Literal["developer", "org"]
    org: OrgSignup | None = None
    consents: dict[ConsentPurpose, bool] = Field(default_factory=dict)
    consents_version: str | None = Field(default=None, max_length=64)
    locale: Literal["en", "sw"] = "en"
    accept_terms: bool


class OAuthStartRequest(BaseModel):
    """``login``: sign in (a new person is sent to signup); ``signup``: sign in or create an account with ``signup``'s
    choices; ``link``: add the provider to the signed-in account (a fresh second factor with TOTP, the current
    password when the account has one, otherwise a recent sign-in)."""

    model_config = ConfigDict(extra="forbid")

    intent: Literal["login", "signup", "link"] = "login"
    return_to: ReturnPath | None = None
    signup: OAuthSignup | None = None
    current_password: str | None = Field(default=None, max_length=256)  # link only; ignored otherwise


class UnlinkRequest(BaseModel):
    """Removing a sign-in method: the current password when the account has one."""

    model_config = ConfigDict(extra="forbid")

    current_password: str | None = Field(default=None, max_length=256)


class OAuthStartResponse(BaseModel):
    authorize_url: str  # the provider's consent page; the browser navigates there


class OAuthProvidersResponse(BaseModel):
    providers: list[AuthProvider]  # only the configured ones; hide the other buttons


class IdentityOut(BaseModel):
    id: UUID
    provider: AuthProvider
    linked_at: datetime
