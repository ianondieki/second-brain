"""Postgres enum types shared by models and migrations. Names are the glossary's (docs/spec/03)."""

from __future__ import annotations

from enum import StrEnum


class StaffRole(StrEnum):
    ADMIN = "admin"
    MODERATOR = "moderator"
    SUPPORT = "support"


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class AuthProvider(StrEnum):
    GITHUB = "github"
    GOOGLE = "google"


class LoginTokenPurpose(StrEnum):
    LOGIN = "login"
    VERIFY_EMAIL = "verify_email"


class OrgKind(StrEnum):
    """Axis 1, Org Type (docs/spec/03)."""

    COMPANY = "company"
    SME = "sme"
    SACCO_MFI = "sacco_mfi"
    UNIVERSITY_TVET = "university_tvet"
    SCHOOL = "school"
    NATIONAL_GOVT = "national_govt"
    COUNTY_GOVT = "county_govt"
    NGO_PBO = "ngo_pbo"
    DEVELOPMENT_PARTNER = "development_partner"


class OrgVerification(StrEnum):
    UNCLAIMED = "unclaimed"  # E0
    PENDING = "pending"
    E1 = "e1"
    E2 = "e2"
    REJECTED = "rejected"


class OrgSource(StrEnum):
    SELF_SIGNUP = "self_signup"
    SEED = "seed"
    ADMIN = "admin"


class OrgRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    REVIEWER = "reviewer"
    SIGNATORY = "signatory"
    FINANCE = "finance"
    VIEWER = "viewer"


# Org roles that must have TOTP (docs/spec/08 Auth).
MFA_REQUIRED_ORG_ROLES = frozenset({OrgRole.OWNER, OrgRole.ADMIN, OrgRole.SIGNATORY, OrgRole.REVIEWER})


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class DevVerification(StrEnum):
    D0 = "d0"
    D1 = "d1"
    D2 = "d2"
    D3 = "d3"


class NicheInterest(StrEnum):
    LIKED = "liked"
    FOLLOWED = "followed"


class RegionKind(StrEnum):
    COUNTRY = "country"
    COUNTY = "county"


class ConsentPurpose(StrEnum):
    """Separate purposes (docs/spec/10; REQ-CON-01)."""

    MARKETING = "marketing"
    REMINDERS = "reminders"
    WHATSAPP = "whatsapp"
    PROFILING = "profiling"
    GITHUB_IMPORT = "github_import"
    TIER2_LLM_ASSISTANT = "tier2_llm_assistant"
    TIER2_LLM_MODERATION = "tier2_llm_moderation"


class AuditActor(StrEnum):
    USER = "user"
    STAFF = "staff"
    SYSTEM = "system"


class NotificationChannel(StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    IN_APP = "in_app"


class DeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class SuppressionReason(StrEnum):
    BOUNCE = "bounce"
    COMPLAINT = "complaint"
    MANUAL = "manual"
    UNSUBSCRIBE = "unsubscribe"


class PlanSide(StrEnum):
    DEVELOPER = "developer"
    ORG = "org"


class BillingInterval(StrEnum):
    NONE = "none"
    MONTH = "month"
    YEAR = "year"


class SubscriptionStatus(StrEnum):
    """docs/spec/05: trialing -> active -> past_due(grace) -> downgraded | cancelled."""

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    DOWNGRADED = "downgraded"
    CANCELLED = "cancelled"


LIVE_SUBSCRIPTION_STATUSES = (SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)
