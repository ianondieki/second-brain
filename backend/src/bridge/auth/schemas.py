"""Request and response bodies for the auth API (REQ-AUTH-01)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from bridge.models.enums import ConsentPurpose, OrgKind, OrgRole, StaffRole


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
