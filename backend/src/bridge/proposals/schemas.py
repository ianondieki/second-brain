"""Proposal API shapes (REQ-PROP-01, REQ-PROP-02; docs/spec/06 6.1, 6.3).

Tier-1 shapes (``TeaserOut``, ``TeaserCard``, ``MyProposalItem``, ``PublishOut``) never carry a Tier-2 field:
``ConfidentialOut`` appears only in the owner's own detail (``VersionOut``). Draft bodies are partial: a field that is
sent is applied (``null`` clears it), a field that is left out stays as it is.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from bridge.models.enums import (
    AvStatus,
    ModerationState,
    ProblemSource,
    ProposalAsk,
    ProposalMaturity,
    ProposalStatus,
    VersionStatus,
)

MAX_PROBLEMS = 5
MAX_LINKS = 10


def _http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("a link is an http or https address")
    return value


Link = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500), AfterValidator(_http_url)]


class TeaserIn(BaseModel):
    """Tier 1: shown to every signed-in user once published (plain text; no contact details or links)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, max_length=120)
    niche_id: UUID | None = None
    county_code: str | None = Field(default=None, pattern=r"^KE-\d{2}$")
    maturity: ProposalMaturity | None = None
    ask: ProposalAsk | None = None
    problem_statement: str | None = Field(default=None, max_length=2000)
    impact_claims: str | None = Field(default=None, max_length=1000)
    summary: str | None = Field(default=None, max_length=1500, description="At most 150 words: what, never how")


class ConfidentialIn(BaseModel):
    """Tier 2: encrypted per proposal; released only through the Tier-2 predicate (T2.5)."""

    model_config = ConfigDict(extra="forbid")

    approach: str | None = Field(default=None, max_length=20_000)
    architecture: str | None = Field(default=None, max_length=20_000)
    pricing: str | None = Field(default=None, max_length=5_000)
    notes: str | None = Field(default=None, max_length=5_000)
    links: list[Link] | None = Field(default=None, max_length=MAX_LINKS, description="Demo and repository links")


class NewProblemIn(BaseModel):
    """ "Describe a new problem": created with ``source=developer`` when the proposal is published."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=90)
    statement: str = Field(min_length=1, max_length=2000)
    niche_id: UUID | None = Field(default=None, description="Defaults to the proposal's niche")


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    teaser: TeaserIn | None = None
    confidential: ConfidentialIn | None = None
    problem_ids: list[UUID] | None = Field(default=None, max_length=MAX_PROBLEMS, description="Linked Problems")
    new_problem: NewProblemIn | None = None


class AttestationsIn(BaseModel):
    """The three ownership attestations of docs/spec/06 6.4 item 7; each must be true to publish."""

    model_config = ConfigDict(extra="forbid")

    created_it: bool
    not_owned_by_employer_or_client: bool
    no_third_party_confidential: bool


class PublishIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attestations: AttestationsIn
    attestation_text_version: str = Field(max_length=32, description="The version of the text the owner was shown")


class NicheOut(BaseModel):
    id: UUID
    slug: str
    label: str = Field(description="Two-level label, e.g. 'ICT › Networks & Telecommunications'")


class ProblemRef(BaseModel):
    id: UUID
    title: str
    source: ProblemSource
    label: str | None = Field(description="'Developer-reported' for problems developers described")
    niche: NicheOut | None


class TeaserOut(BaseModel):
    title: str | None
    niche: NicheOut | None
    country: str
    county_code: str | None
    maturity: ProposalMaturity | None
    ask: ProposalAsk | None
    problem_statement: str | None
    impact_claims: str | None
    summary: str | None


class ProvenanceOut(BaseModel):
    status: Literal["timestamped", "timestamp_pending"]
    label: str
    verify_path: str


class AttachmentOut(BaseModel):
    id: UUID
    file_name: str | None
    content_type: str
    size_bytes: int | None
    sha256: str | None
    av_status: AvStatus


class ConfidentialOut(BaseModel):
    approach: str | None
    architecture: str | None
    pricing: str | None
    notes: str | None
    links: list[str]
    attachments: list[AttachmentOut]


class NewProblemOut(BaseModel):
    title: str
    statement: str
    niche_id: UUID | None


class VersionOut(BaseModel):
    """One of your versions (owner only): Tier 1, links, and your own Tier 2."""

    id: UUID
    version_no: int
    status: VersionStatus
    cert_id: str | None
    registered_at: datetime | None
    provenance: ProvenanceOut | None
    teaser: TeaserOut
    problems: list[ProblemRef]
    new_problem: NewProblemOut | None
    confidential: ConfidentialOut


class ModerationOut(BaseModel):
    state: ModerationState
    message: str | None


class MyProposalOut(BaseModel):
    id: UUID
    status: ProposalStatus
    moderation: ModerationOut
    published_at: datetime | None
    hidden_at: datetime | None
    current: VersionOut | None = Field(description="The latest registered version")
    draft: VersionOut | None = Field(description="The version being edited")


class MyProposalItem(BaseModel):
    id: UUID
    status: ProposalStatus
    moderation_state: ModerationState
    title: str | None
    niche: NicheOut | None
    current_version_no: int | None
    cert_id: str | None
    has_draft: bool
    published_at: datetime | None
    updated_at: datetime


class MyProposals(BaseModel):
    items: list[MyProposalItem]


class PublishOut(BaseModel):
    proposal_id: UUID
    version_id: UUID
    version_no: int
    cert_id: str
    status: ProposalStatus
    moderation: ModerationOut
    provenance: ProvenanceOut
    new_problem_id: UUID | None


class TeaserCard(BaseModel):
    """A published teaser (Tier 1 only) with the owner's pseudonymous handle and the certificate id."""

    id: UUID
    owner_handle: str
    cert_id: str
    version_no: int
    registered_at: datetime
    provenance: ProvenanceOut
    teaser: TeaserOut
    problems: list[ProblemRef]


class AttestationStatement(BaseModel):
    key: str
    text: str


class AttestationText(BaseModel):
    version: str
    sha256: str
    statements: list[AttestationStatement]


class RemovedOut(BaseModel):
    status: Literal["hidden", "deleted"]
    message: str
