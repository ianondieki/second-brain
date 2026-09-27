"""Proposals: Tier 0/1/2 storage, tags, disclosure grants and the access log (REQ-REPO-01, REQ-PROP-01..04,
REQ-PROV-03; docs/spec/06 6.1, 6.3, 6.4).

- ``proposals``, ``proposal_versions`` and ``proposal_problems`` are Tenancy PUBLISHED: the owner reads and writes
  them; every signed-in user reads published, clear proposals and their registered versions; staff admin/moderator
  read everything. ``moderation_state`` changes only through the SECURITY DEFINER functions of revision 0002.
- A registered version is immutable (trigger, AC-IP-2): only its fill-once hash columns may still be set.
- Tier-2 content lives only in ``proposal_confidential`` (per-proposal envelope key, ciphertext only). ``bridge_app``
  has no privilege on it at all: code switches to ``tier2_reader`` (or a worker role) with ``bridge.db.as_role``
  after ``can_view_tier2`` passes. ``proposal_confidential_embeddings`` is readable by ``tier2_moderation`` only.
- Object keys and file names of attachments live only inside the encrypted Tier-2 document.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy, TimestampsMixin
from bridge.models.enums import (
    AvStatus,
    GrantSource,
    GrantStatus,
    ModerationState,
    OriginalityBand,
    ProposalAsk,
    ProposalMaturity,
    ProposalStatus,
    RenderKind,
    TagStatus,
    Tier2Policy,
    VersionStatus,
    ViewDuration,
)
from bridge.models.types import CIText, Vector, pg_enum

# Keyword search over the current Tier-1 teaser (docs/spec/06 6.1 Browse repo). 'simple' config: no stemming, so
# English and Swahili terms match as typed.
SEARCH_TSV = (
    "setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A')"
    " || setweight(to_tsvector('simple'::regconfig, coalesce(problem_statement, '')), 'B')"
    " || setweight(to_tsvector('simple'::regconfig, coalesce(summary, '')), 'B')"
    " || setweight(to_tsvector('simple'::regconfig, coalesce(impact_claims, '')), 'C')"
)
OPEN_TAGS = "status IN ('held_unclaimed', 'held_pending_verification', 'delivered')"
LIVE_GRANTS = "status IN ('requested', 'active')"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # docs/spec/06 6.1: attachments <= 20 MB


def _version_fk(table: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    """(proposal_id, version_id) -> proposal_versions(proposal_id, id): the version belongs to that proposal."""
    return ForeignKeyConstraint(
        ["proposal_id", "version_id"],
        ["proposal_versions.proposal_id", "proposal_versions.id"],
        name=f"fk_{table}_version",
        ondelete=ondelete,
    )


class Proposal(IdMixin, TimestampsMixin, Base):
    """A proposal and a denormalised copy of its current Tier-1 teaser (search, cards, filters)."""

    __tablename__ = "proposals"
    __table_args__ = (
        # Circular with proposal_versions (created after both tables). Each points at a version of this proposal.
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_proposals_current_version",
            use_alter=True,
        ),
        ForeignKeyConstraint(
            ["id", "draft_version_id"],
            ["proposal_versions.proposal_id", "proposal_versions.id"],
            name="fk_proposals_draft_version",
            use_alter=True,
        ),
        CheckConstraint("status = 'draft' OR current_version_id IS NOT NULL", name="listed_has_version"),
        Index("ix_proposals_search_tsv", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_proposals_teaser_embedding",
            "teaser_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"teaser_embedding": "vector_cosine_ops"},
        ),
        {"info": {"tenancy": Tenancy.PUBLISHED, "user_column": "owner_id"}},
    )

    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[ProposalStatus] = mapped_column(
        pg_enum(ProposalStatus, "proposal_status"), server_default=ProposalStatus.DRAFT.value
    )
    moderation_state: Mapped[ModerationState] = mapped_column(
        pg_enum(ModerationState, "moderation_state"), server_default=ModerationState.CLEAR.value
    )
    current_version_id: Mapped[UUID | None] = mapped_column()  # the latest registered version
    draft_version_id: Mapped[UUID | None] = mapped_column()  # the version being edited, if any
    title: Mapped[str | None] = mapped_column(String(120))
    niche_id: Mapped[UUID | None] = mapped_column(ForeignKey("niches.id"), index=True)
    country: Mapped[str] = mapped_column(String(2), server_default="KE")
    county_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    maturity: Mapped[ProposalMaturity | None] = mapped_column(pg_enum(ProposalMaturity, "proposal_maturity"))
    ask: Mapped[ProposalAsk | None] = mapped_column(pg_enum(ProposalAsk, "proposal_ask"))
    problem_statement: Mapped[str | None] = mapped_column(Text)
    impact_claims: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    search_tsv: Mapped[str | None] = mapped_column(TSVECTOR, Computed(SEARCH_TSV, persisted=True))
    teaser_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    embed_model: Mapped[str | None] = mapped_column(String(80))
    embed_version: Mapped[str | None] = mapped_column(String(40))
    tier2_policy: Mapped[Tier2Policy] = mapped_column(
        pg_enum(Tier2Policy, "tier2_policy"), server_default=Tier2Policy.AUTO_TAGGED.value
    )
    raw_download_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProposalVersion(IdMixin, TimestampsMixin, Base):
    """One version: a draft (Tier 0, owner only) until registered, then immutable (AC-IP-2)."""

    __tablename__ = "proposal_versions"
    __table_args__ = (
        UniqueConstraint("proposal_id", "version_no"),
        UniqueConstraint("proposal_id", "id"),  # target of the (proposal_id, version_id) foreign keys
        CheckConstraint(
            "status = 'draft' OR (title IS NOT NULL AND niche_id IS NOT NULL AND maturity IS NOT NULL"
            " AND ask IS NOT NULL AND problem_statement IS NOT NULL AND summary IS NOT NULL"
            " AND owner_handle IS NOT NULL AND cert_id IS NOT NULL AND registered_at IS NOT NULL)",
            name="registered_is_complete",
        ),
        CheckConstraint("content_hash IS NULL OR octet_length(content_hash) = 32", name="content_hash_length"),
        CheckConstraint(
            "prev_version_hash IS NULL OR octet_length(prev_version_hash) = 32", name="prev_version_hash_length"
        ),
        {"info": {"tenancy": Tenancy.PUBLISHED, "via": "proposals"}},
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"))
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[VersionStatus] = mapped_column(
        pg_enum(VersionStatus, "version_status"), server_default=VersionStatus.DRAFT.value
    )
    # Tier-1 snapshot (docs/spec/06 6.1): never "how", never contact details (Tier-1 sanitiser).
    title: Mapped[str | None] = mapped_column(String(120))
    niche_id: Mapped[UUID | None] = mapped_column(ForeignKey("niches.id"))
    country: Mapped[str] = mapped_column(String(2), server_default="KE")
    county_code: Mapped[str | None] = mapped_column(ForeignKey("regions.code"))
    maturity: Mapped[ProposalMaturity | None] = mapped_column(pg_enum(ProposalMaturity, "proposal_maturity"))
    ask: Mapped[ProposalAsk | None] = mapped_column(pg_enum(ProposalAsk, "proposal_ask"))
    problem_statement: Mapped[str | None] = mapped_column(Text)
    impact_claims: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)  # <= 150 words (validated by the Tier-1 sanitiser)
    owner_handle: Mapped[str | None] = mapped_column(CIText())  # pseudonymous handle shown on Tier-1 cards
    # Registration (docs/spec/06 6.4 item 1). content_hash, prev_version_hash and manifest_version are fill-once:
    # the registration job may set them after the version is registered, never change them.
    prev_version_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    content_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    cert_id: Mapped[str | None] = mapped_column(String(24), unique=True)
    manifest_version: Mapped[str | None] = mapped_column(String(16))
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProposalProblem(Base):
    """A version's linked Problems; at least one is required to register the version (trigger)."""

    __tablename__ = "proposal_problems"
    __table_args__ = ({"info": {"tenancy": Tenancy.PUBLISHED, "via": "proposal_versions"}},)

    proposal_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("proposal_versions.id", ondelete="CASCADE"), primary_key=True
    )
    problem_id: Mapped[UUID] = mapped_column(ForeignKey("problems.id"), primary_key=True, index=True)


class ProposalConfidential(TimestampsMixin, Base):
    """Tier 2 of one version, encrypted with the proposal's data key (envelope encryption; KMS wraps the key).
    ``manifest_ciphertext``/``manifest_nonce`` hold the encrypted registration manifest (fill-once, set by the
    ``provenance_worker``); the nonce is separate so the data key never encrypts two messages under one nonce."""

    __tablename__ = "proposal_confidential"
    __table_args__ = (
        _version_fk("proposal_confidential", ondelete="CASCADE"),
        CheckConstraint("(manifest_ciphertext IS NULL) = (manifest_nonce IS NULL)", name="manifest_pair"),
        {"info": {"tenancy": Tenancy.USER, "user_column": "owner_id", "db_role": "tier2_reader"}},
    )

    version_id: Mapped[UUID] = mapped_column(primary_key=True)
    proposal_id: Mapped[UUID] = mapped_column(index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_dek: Mapped[bytes] = mapped_column(LargeBinary)
    kms_key_id: Mapped[str] = mapped_column(String(200))
    manifest_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    manifest_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)


class ProposalConfidentialEmbedding(CreatedMixin, Base):
    """Full-text (Tier-2) embedding for the moderator-only Tier-2-vs-Tier-2 similarity job. Readable only by
    ``tier2_moderation`` in a staff context; written by ``tier2_embed_worker``; never returned by any endpoint."""

    __tablename__ = "proposal_confidential_embeddings"
    # Inserted by callers that may not read the new row back (no SELECT grant or policy), so the ORM must not add
    # RETURNING for server defaults.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = (
        Index(
            "ix_proposal_confidential_embeddings_full_embedding",
            "full_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"full_embedding": "vector_cosine_ops"},
        ),
        {"info": {"tenancy": Tenancy.STAFF, "via": "proposal_confidential", "db_role": "tier2_moderation"}},
    )

    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("proposal_confidential.version_id", ondelete="CASCADE"), primary_key=True
    )
    embed_model: Mapped[str] = mapped_column(String(80), primary_key=True)
    embed_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    full_embedding: Mapped[list[float]] = mapped_column(Vector(1024))


class ProposalAttachment(IdMixin, TimestampsMixin, Base):
    """Attachment metadata (PDF/PNG/JPG/MD/TXT <= 20 MB, ClamAV-scanned, PDFs re-rendered). The object key and the
    file name live only inside the encrypted Tier-2 document."""

    __tablename__ = "proposal_attachments"
    __table_args__ = (
        _version_fk("proposal_attachments", ondelete="CASCADE"),
        CheckConstraint("sha256 IS NULL OR octet_length(sha256) = 32", name="sha256_length"),
        CheckConstraint(f"size_bytes IS NULL OR size_bytes BETWEEN 1 AND {MAX_ATTACHMENT_BYTES}", name="size_limit"),
        {"info": {"tenancy": Tenancy.USER, "user_column": "owner_id"}},
    )

    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    proposal_id: Mapped[UUID] = mapped_column(index=True)
    version_id: Mapped[UUID] = mapped_column(index=True)
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(100))
    av_status: Mapped[AvStatus] = mapped_column(
        pg_enum(AvStatus, "av_status"), server_default=AvStatus.PENDING_UPLOAD.value
    )
    rerendered: Mapped[bool] = mapped_column(Boolean, server_default="false")


class ProposalLshBand(Base):
    """MinHash LSH buckets over the Tier-1 teaser text only (originality check, REQ-PROP-04)."""

    __tablename__ = "proposal_lsh_bands"
    __table_args__ = (
        Index("ix_proposal_lsh_bands_band_bucket", "band", "bucket"),
        {"info": {"tenancy": Tenancy.SYSTEM}},
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id", ondelete="CASCADE"), primary_key=True)
    band: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    bucket: Mapped[int] = mapped_column(BigInteger)


class OriginalityCheck(IdMixin, CreatedMixin, Base):
    """One originality check (informational; <= 10 per developer per day). Coarse band only."""

    __tablename__ = "originality_checks"
    __table_args__ = (
        Index("ix_originality_checks_user_id_created_at", "user_id", "created_at"),
        {"info": {"tenancy": Tenancy.USER, "tenant_column": "user_id"}},
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    band: Mapped[OriginalityBand] = mapped_column(pg_enum(OriginalityBand, "originality_band"))


class Tag(IdMixin, TimestampsMixin, Base):
    """A "Pitch to company" tag of one organisation on one proposal. Readable by the developer, and by the
    organisation's members only once ``delivered``; an E1 organisation sees only a count (``app_held_tag_count``).
    One open tag per (developer, organisation)."""

    __tablename__ = "tags"
    __table_args__ = (
        Index("uq_tags_open_developer_org", "developer_id", "org_id", unique=True, postgresql_where=text(OPEN_TAGS)),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "developer_id"}},
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    developer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[TagStatus] = mapped_column(pg_enum(TagStatus, "tag_status"))
    sla_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DisclosureGrant(IdMixin, TimestampsMixin, Base):
    """Tier-2 (or Tier-3) disclosure of one proposal to one organisation. Visible to the owner and the grantee
    organisation's members; only the owner activates, denies or revokes."""

    __tablename__ = "disclosure_grants"
    __table_args__ = (
        CheckConstraint("tier IN (2, 3)", name="tier"),
        Index(
            "uq_disclosure_grants_live",
            "proposal_id",
            "org_id",
            "tier",
            unique=True,
            postgresql_where=text(LIVE_GRANTS),
        ),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "owner_id"}},
    )

    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    tier: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[GrantStatus] = mapped_column(pg_enum(GrantStatus, "grant_status"))
    source: Mapped[GrantSource] = mapped_column(pg_enum(GrantSource, "grant_source"))
    counts_as_unlock: Mapped[bool] = mapped_column(Boolean, server_default="false")  # REQ-BIL-03
    billing_month: Mapped[date | None] = mapped_column(Date)
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    granted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class DocumentView(IdMixin, Base):
    """The access log of Tier-2 renders ("Who has seen this"). ``id`` is the ``view_id`` printed on the render."""

    __tablename__ = "document_views"
    __table_args__ = (
        _version_fk("document_views"),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "viewer_user_id"}},
    )

    proposal_id: Mapped[UUID] = mapped_column(index=True)
    version_id: Mapped[UUID] = mapped_column()
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    viewer_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    nda_acceptance_id: Mapped[UUID | None] = mapped_column(ForeignKey("nda_acceptances.id"))
    nda_template_version: Mapped[str | None] = mapped_column(String(32))
    render_kind: Mapped[RenderKind] = mapped_column(pg_enum(RenderKind, "render_kind"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    duration_bucket: Mapped[ViewDuration | None] = mapped_column(pg_enum(ViewDuration, "view_duration"))
    fingerprint_seed: Mapped[bytes] = mapped_column(LargeBinary)
