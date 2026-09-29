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


# --- Schema v2 (revision 0002; docs/spec/06 6.1-6.4, 6.9, 6.12) ---------------------------------------------------


class LegalTemplateKind(StrEnum):
    """Versioned, hashed legal instruments (docs/spec/06 6.9 "Instruments per stage"). Bodies are placeholders
    until the advocate's review (G2); no LLM-generated contract text."""

    MASTER_ENTERPRISE_TERMS = "master_enterprise_terms"
    EVALUATION_NDA = "evaluation_nda"
    MUTUAL_NDA = "mutual_nda"
    TOS = "tos"
    AUP = "aup"


class NdaKind(StrEnum):
    EVALUATION = "evaluation"  # per person, per proposal (Tier 2)
    MUTUAL = "mutual"  # opens the deal room (Tier 3)


class ProblemSource(StrEnum):
    RESEARCH_AGENT = "research_agent"
    ORG_BRIEF = "org_brief"
    DEVELOPER = "developer"


class ProblemStatus(StrEnum):
    CANDIDATE = "candidate"  # research output awaiting staff review; never readable by non-staff
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class ModerationState(StrEnum):
    """Changed only by staff through SECURITY DEFINER functions; the app may only raise a hold."""

    CLEAR = "clear"
    HELD = "held"
    REJECTED = "rejected"


class BriefVisibility(StrEnum):
    PUBLIC = "public"
    INVITED = "invited"


class BriefStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


class ProposalStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    HIDDEN = "hidden"  # "deleted" after registration: evidence kept (AC-IP-6)
    ARCHIVED = "archived"


class ProposalMaturity(StrEnum):
    IDEA = "idea"
    PROTOTYPE = "prototype"
    MVP = "mvp"
    LIVE = "live"


class ProposalAsk(StrEnum):
    SALE = "sale"
    LICENCE = "licence"
    CO_BUILD = "co_build"
    PILOT = "pilot"
    HIRE = "hire"


class Tier2Policy(StrEnum):
    """The owner's disclosure policy (docs/spec/06 6.1)."""

    AUTO_TAGGED = "auto_tagged"  # auto-grant to orgs I tagged (default)
    MANUAL = "manual"
    NICHE_E2 = "niche_e2"  # any E2 org in my niche


class VersionStatus(StrEnum):
    DRAFT = "draft"  # Tier 0, owner only
    REGISTERED = "registered"  # immutable (AC-IP-2)


class AvStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    PENDING_SCAN = "pending_scan"
    CLEAN = "clean"
    INFECTED = "infected"
    FAILED = "failed"


class OriginalityBand(StrEnum):
    """Coarse bands only, never numeric scores (docs/spec/06 6.3)."""

    NONE = "none"
    SOME_OVERLAP = "some_overlap"
    HIGH_OVERLAP = "high_overlap"


class ProvenanceStatus(StrEnum):
    """Registration pipeline progress; only moves forward (the trigger refuses going back)."""

    HASHED = "hashed"
    SIGNED = "signed"
    TIMESTAMPED = "timestamped"


class TagStatus(StrEnum):
    """docs/spec/06 6.9 Codes: a projection of the engagement (the source of truth from Phase 3)."""

    HELD_UNCLAIMED = "held_unclaimed"
    HELD_PENDING_VERIFICATION = "held_pending_verification"
    DELIVERED = "delivered"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    RELEASED = "released"


# Statuses an open tag can have. Whether a tag is open is ``tags.closed_at IS NULL`` (revision 0002): a delivered tag
# closes when its engagement ends, and the closing statuses below always close it.
OPEN_TAG_STATUSES = (TagStatus.HELD_UNCLAIMED, TagStatus.HELD_PENDING_VERIFICATION, TagStatus.DELIVERED)
CLOSING_TAG_STATUSES = (TagStatus.WITHDRAWN, TagStatus.EXPIRED, TagStatus.RELEASED)


class EngagementOrigin(StrEnum):
    TAGGED = "tagged"
    ORG_AGENT_MATCH = "org_agent_match"
    ORG_BROWSE = "org_browse"


class EngagementState(StrEnum):
    """Every stage and side-branch state of docs/spec/06 6.9, spelled as the spec's codes."""

    ORG_INTEREST = "ORG_INTEREST"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INTEREST_CONFIRMED = "INTEREST_CONFIRMED"
    PROCUREMENT_ROUTE = "PROCUREMENT_ROUTE"
    CONTACT_MADE = "CONTACT_MADE"
    NDA_PENDING = "NDA_PENDING"
    NDA_SIGNED = "NDA_SIGNED"
    NEGOTIATION = "NEGOTIATION"
    AGREEMENT_SIGNING = "AGREEMENT_SIGNING"
    IN_IMPLEMENTATION = "IN_IMPLEMENTATION"
    DELIVERED = "DELIVERED"
    SIGN_OFF = "SIGN_OFF"
    PAYMENT_FINAL = "PAYMENT_FINAL"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    ON_HOLD = "ON_HOLD"
    DISPUTED = "DISPUTED"
    TERMINATED = "TERMINATED"
    INFO_REQUESTED = "INFO_REQUESTED"


# No Tier-2 access for an org with an engagement in one of these states (docs/spec/06 6.1).
TIER2_BLOCKING_STATES = (EngagementState.WITHDRAWN, EngagementState.DECLINED, EngagementState.TERMINATED)


class EngagementEndReason(StrEnum):
    """docs/spec/06 6.9 ``end_reason``: DECLINED codes, then EXPIRED codes."""

    NOT_PRIORITY = "NOT_PRIORITY"
    ALREADY_IN_PROGRESS_INTERNALLY = "ALREADY_IN_PROGRESS_INTERNALLY"
    BUDGET = "BUDGET"
    NOT_RELEVANT = "NOT_RELEVANT"
    NEEDS_MATURITY = "NEEDS_MATURITY"
    OTHER = "OTHER"
    BY_DEVELOPER = "BY_DEVELOPER"
    NO_REVIEW = "NO_REVIEW"
    NO_DECISION = "NO_DECISION"
    CONTACT_NOT_MADE = "CONTACT_NOT_MADE"
    NO_DEV_RESPONSE = "NO_DEV_RESPONSE"


# docs/spec/06 6.9 Codes: no event follows one of these (revision 0003 refuses it) and ``engagements.ended_at`` is set
# exactly while the engagement is in one.
TERMINAL_STATES = (
    EngagementState.DECLINED,
    EngagementState.WITHDRAWN,
    EngagementState.EXPIRED,
    EngagementState.TERMINATED,
    EngagementState.CLOSED,
)


class EngagementActorRole(StrEnum):
    """Who acted in a tracker row (revision 0003): the developer, an organisation member in one of their roles
    (``OrgRole`` spellings; viewers never act), or the system (a job; the row names no user)."""

    DEVELOPER = "developer"
    OWNER = "owner"
    ADMIN = "admin"
    REVIEWER = "reviewer"
    SIGNATORY = "signatory"
    FINANCE = "finance"
    SYSTEM = "system"


class EngagementParty(StrEnum):
    """The two sides of an engagement (docs/spec/06 6.9: releasing party / receiving party)."""

    DEVELOPER = "developer"
    ORG = "org"


class EndorsementMethod(StrEnum):
    CLICK = "click"
    TOTP = "totp"
    PASSKEY = "passkey"
    AUTO = "auto"  # a timed auto-confirmation by a job (docs/spec/06 6.9 stage 4); names no user


class ContactChannel(StrEnum):
    """How the organisation's named contact will reach the developer (docs/spec/06 6.9 stage 3)."""

    EMAIL = "email"
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    VIDEO_CALL = "video_call"
    IN_PERSON = "in_person"


class IpTerms(StrEnum):
    """docs/spec/06 6.9 stage 8. The internal e-signature refuses ``assignment`` and ``exclusive_licence``."""

    ASSIGNMENT = "assignment"
    EXCLUSIVE_LICENCE = "exclusive_licence"
    NON_EXCLUSIVE_LICENCE = "non_exclusive_licence"
    DEVELOPMENT_CONTRACT = "development_contract"
    REVENUE_SHARE = "revenue_share"


class AgreementStatus(StrEnum):
    DRAFT = "draft"
    FINAL = "final"  # frozen: IP terms, deemed-acceptance clause, PDF hash and milestones
    SIGNED = "signed"  # both parties signed the final PDF


class MilestoneState(StrEnum):
    """docs/spec/06 6.9 milestone sub-tracker, spelled as the spec's codes."""

    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED_FOR_REVIEW = "SUBMITTED_FOR_REVIEW"
    ACCEPTED = "ACCEPTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class SignatureDocumentKind(StrEnum):
    MUTUAL_NDA = "mutual_nda"
    AGREEMENT = "agreement"
    ACCEPTANCE_CERTIFICATE = "acceptance_certificate"
    MILESTONE_CONFIRMATION = "milestone_confirmation"


class StepUpMethod(StrEnum):
    """The step-up that preceded an internal e-signature (docs/spec/06 6.9 SignatureProvider)."""

    TOTP = "totp"
    PASSKEY = "passkey"


class PaymentMethod(StrEnum):
    """How the organisation says it paid. The platform records payments, it never moves money."""

    MPESA = "mpesa"
    BANK = "bank"
    OTHER = "other"


class GrantStatus(StrEnum):
    REQUESTED = "requested"
    ACTIVE = "active"
    REVOKED = "revoked"
    DENIED = "denied"


class GrantSource(StrEnum):
    AUTO_TAGGED = "auto_tagged"
    MANUAL = "manual"
    NICHE_E2 = "niche_e2"
    ORG_INTEREST = "org_interest"


class RenderKind(StrEnum):
    HTML = "html"
    PDF = "pdf"
    ATTACHMENT = "attachment"


class ViewDuration(StrEnum):
    """Coarse viewing-time buckets shown to the owner ("Who has seen this")."""

    UNDER_1M = "under_1m"
    UNDER_5M = "under_5m"
    UNDER_15M = "under_15m"
    OVER_15M = "over_15m"


class ModerationSource(StrEnum):
    PRESCREEN = "prescreen"
    REGEX = "regex"
    REPORT = "report"
    CLAIM_DISPUTE = "claim_dispute"
    TIER2_SIMILARITY = "tier2_similarity"


class ModerationCaseStatus(StrEnum):
    OPEN = "open"
    HELD = "held"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


class ClaimLevel(StrEnum):
    E1 = "e1"
    E2 = "e2"


class ClaimStatus(StrEnum):
    OTP_SENT = "otp_sent"
    DNS_PENDING = "dns_pending"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"  # set only by app_approve_claim_e1() or app_decide_claim()
    REJECTED = "rejected"  # set only by app_decide_claim()
    DISPUTED = "disputed"
    WITHDRAWN = "withdrawn"


class DirectoryInvitationStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    SENT = "sent"
    REFUSED = "refused"


class KycStatus(StrEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"  # set only by app_decide_kyc()
    REJECTED = "rejected"
