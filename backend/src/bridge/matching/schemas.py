"""API shapes of the scouts and their matches (REQ-SCOUT-01..03; docs/spec/06 6.8).

A scout is a form, never a prompt. Keywords are normalised (NFKC, one line, lower case, 1 to 60 characters, distinct);
counties are region codes, niches ids, the budget band a code from ``config/matching/weights_v1.yaml``. Match shapes
carry the current teaser (Tier 1 only, ``TeaserOut``), the niche label, the score, "why this matches" with who wrote
it, and ``demo_fallback`` (the UI's "demo fallback" label when no model wrote the why).
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from bridge.llm.demo_fallback import DemoFallbackFlag
from bridge.models.enums import AgentRunStatus, MatchFeedback, ProposalMaturity, ScoutFrequency
from bridge.proposals.schemas import NicheOut, TeaserOut

MAX_KEYWORD_CHARS = 60
# "Not relevant: reason" (docs/spec/06 6.8 feedback loop): codes the frontend labels ([[COPY-REVIEW]]).
FeedbackReason = Literal["wrong_niche", "wrong_county", "too_early", "not_a_priority", "already_solved", "other"]


def normalise_keyword(value: str) -> str:
    """NFKC, control and invisible characters dropped, one line, lower case."""
    text = unicodedata.normalize("NFKC", value)
    kept = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch.isspace())
    cleaned = " ".join(kept.split()).lower()
    if not 1 <= len(cleaned) <= MAX_KEYWORD_CHARS:
        raise ValueError(f"a keyword is 1 to {MAX_KEYWORD_CHARS} characters")
    return cleaned


def _distinct_keywords(values: list[str]) -> list[str]:
    return list(dict.fromkeys(normalise_keyword(v) for v in values))


def _distinct[T](values: list[T]) -> list[T]:
    return list(dict.fromkeys(values))


Keywords = Annotated[list[str], Field(max_length=20), AfterValidator(_distinct_keywords)]
Counties = Annotated[list[Annotated[str, Field(min_length=1, max_length=8)]], Field(max_length=47)]
Niches = Annotated[list[UUID], Field(min_length=1, max_length=5), AfterValidator(_distinct)]
Recipients = Annotated[list[UUID], Field(max_length=20), AfterValidator(_distinct)]
Maturities = Annotated[list[ProposalMaturity], Field(max_length=4), AfterValidator(_distinct)]


class ScoutForm(BaseModel):
    """A scout's settings: the body of create and of Preview."""

    model_config = ConfigDict(extra="forbid")

    niches: Niches
    counties: Annotated[Counties, AfterValidator(_distinct)] = Field(default_factory=list)
    include_keywords: Keywords = Field(default_factory=list)
    exclude_keywords: Keywords = Field(default_factory=list)
    maturity: Maturities = Field(default_factory=list)
    budget_band: str | None = Field(default=None, description="A code from GET /api/orgs/{org_id}/scouts.")
    min_fit: int = Field(default=60, ge=0, le=100)
    frequency: ScoutFrequency = ScoutFrequency.WEEKLY
    language: Literal["en", "sw"] = "en"
    recipients: Recipients = Field(default_factory=list, description="Reviewer seats of the organisation.")


class ScoutPatch(BaseModel):
    """A partial update: a field left out stays as it is. ``paused`` pauses or resumes the scout."""

    model_config = ConfigDict(extra="forbid")

    niches: Niches | None = None
    counties: Annotated[Counties, AfterValidator(_distinct)] | None = None
    include_keywords: Keywords | None = None
    exclude_keywords: Keywords | None = None
    maturity: Maturities | None = None
    budget_band: str | None = None
    min_fit: int | None = Field(default=None, ge=0, le=100)
    frequency: ScoutFrequency | None = None
    language: Literal["en", "sw"] | None = None
    recipients: Recipients | None = None
    paused: bool | None = None


class RunOut(BaseModel):
    id: UUID
    trigger: ScoutFrequency
    status: AgentRunStatus
    started_at: datetime
    finished_at: datetime | None
    scanned_count: int
    matched_count: int


class ScoutOut(BaseModel):
    id: UUID
    org_id: UUID
    niches: list[NicheOut]
    counties: list[str]
    include_keywords: list[str]
    exclude_keywords: list[str]
    maturity: list[ProposalMaturity]
    budget_band: str | None
    min_fit: int
    frequency: ScoutFrequency
    language: str
    recipients: list[UUID]
    paused: bool
    paused_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    last_run: RunOut | None


class BudgetBandOut(BaseModel):
    code: str
    label: str


class ScoutPlanOut(BaseModel):
    """What the organisation's plan allows (``entitlement_tier`` from the subscription, not editable)."""

    plan: str
    scout_agents: int | None = Field(description="How many scouts the plan allows; null: no limit.")
    frequencies: list[ScoutFrequency]
    digest_size: int


class ScoutList(BaseModel):
    items: list[ScoutOut]
    plan: ScoutPlanOut
    budget_bands: list[BudgetBandOut]


class PreviewItem(BaseModel):
    proposal_id: UUID
    owner_handle: str | None
    published_at: datetime
    teaser: TeaserOut
    score: int = Field(description="The rules' score, 0 to 100 (Preview asks no model).")
    why: str = Field(description='The rules that fired ("Matched on ...").')
    keywords_found: list[str]


class PreviewOut(BaseModel):
    """The first digest this form would send: the last ``window_days`` days, rules only, nothing saved. An ``on_new``
    scout never runs over that window (it sends each new proposal as it is published), so ``note`` says so."""

    items: list[PreviewItem]
    total: int = Field(description="Matching proposals in the window; the digest lists the first digest_size.")
    window_days: int
    digest_size: int
    note: str | None = Field(
        default=None, description="Shown above the items when they are not what the scout will send (on_new)."
    )


class InterestState(BaseModel):
    """Whether the caller may express interest now, and why not (a stable code) when they may not."""

    allowed: bool
    reason: str | None


class MatchOut(DemoFallbackFlag):
    id: UUID
    scout_id: UUID
    proposal_id: UUID
    available: bool = Field(description="False once the proposal is no longer published and clear.")
    owner_handle: str | None
    teaser: TeaserOut | None
    niche: NicheOut | None
    score: int
    why: str | None
    why_source: Literal["model", "code"]
    injection_suspected: bool
    created_at: datetime
    digest_sent_at: datetime | None
    feedback: MatchFeedback | None
    feedback_reason: str | None


def _without_default(schema: dict[str, Any]) -> None:
    """Leave a field's default out of the OpenAPI document: always sent, it stays optional in the generated web types,
    so a client reads an older API as "not sent" (as ``problems.brief_schemas``)."""
    schema.pop("default", None)


class MatchDetail(MatchOut):
    rule_breakdown: dict[str, Any]
    engagement_id: UUID | None
    interest: InterestState
    today: date | None = Field(
        default=None,
        description="Today in Africa/Nairobi on the platform clock (the test clock where it is on): the day Express"
        " interest's contact-by date counts from",
        json_schema_extra=_without_default,
    )


class MatchList(BaseModel):
    items: list[MatchOut]


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: MatchFeedback
    reason: FeedbackReason | None = None
