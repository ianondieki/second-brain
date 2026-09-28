"""Provenance: signing keys, registration records, chain anchors, transparency roots and ownership attestations
(REQ-PROV-01, REQ-PROV-02, REQ-AUD-01; docs/spec/06 6.4; ADR-003).

``provenance_records``, ``chain_anchors`` and ``transparency_roots`` are evidence: triggers refuse DELETE and TRUNCATE,
and UPDATE except filling a record's still-empty signature/TSA columns and moving its status forward
(hashed -> signed -> timestamped). ``bridge_app`` reads every record (``/verify``, anonymous); ``provenance_worker``
reads and writes only the records of versions its bound owner (``app.user_id``) owns (RLS, tenancy EVIDENCE).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy
from bridge.models.enums import ProvenanceStatus
from bridge.models.types import pg_enum

SYSTEM = {"info": {"tenancy": Tenancy.SYSTEM}}


class ProvenanceKey(CreatedMixin, Base):
    """An Ed25519 public key that signs manifests (served at ``/.well-known/provenance-keys.json``). Keys are
    registered by an owner-run command, never by the app role."""

    __tablename__ = "provenance_keys"
    __table_args__ = (
        CheckConstraint("algorithm = 'ed25519'", name="algorithm"),
        CheckConstraint("octet_length(public_key) = 32", name="public_key_length"),
        {"info": {"tenancy": Tenancy.GLOBAL}},
    )

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    algorithm: Mapped[str] = mapped_column(String(16), server_default="ed25519")
    public_key: Mapped[bytes] = mapped_column(LargeBinary)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProvenanceRecord(IdMixin, CreatedMixin, Base):
    """The registration record of one version: manifest hash, server signature and RFC 3161 token."""

    __tablename__ = "provenance_records"
    __table_args__ = (
        CheckConstraint("octet_length(content_hash) = 32", name="content_hash_length"),
        CheckConstraint("status = 'hashed' OR (signature IS NOT NULL AND key_id IS NOT NULL)", name="signed_has_key"),
        CheckConstraint("status <> 'timestamped' OR (tsa_token IS NOT NULL AND tsa_time IS NOT NULL)", name="tsa"),
        # The record's cert_id is its version's; its content_hash equals the version's once both are set (triggers).
        ForeignKeyConstraint(
            ["version_id", "cert_id"],
            ["proposal_versions.id", "proposal_versions.cert_id"],
            name="fk_provenance_records_version_cert",
        ),
        {"info": {"tenancy": Tenancy.EVIDENCE, "via": "proposal_versions"}},
    )

    version_id: Mapped[UUID] = mapped_column(ForeignKey("proposal_versions.id"), unique=True)
    cert_id: Mapped[str] = mapped_column(String(24), unique=True)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary)
    signature: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_id: Mapped[str | None] = mapped_column(ForeignKey("provenance_keys.key_id"))
    status: Mapped[ProvenanceStatus] = mapped_column(
        pg_enum(ProvenanceStatus, "provenance_status"), server_default=ProvenanceStatus.HASHED.value
    )
    tsa_token: Mapped[bytes | None] = mapped_column(LargeBinary)  # DER TimeStampResp (.tsr)
    tsa_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tsa_serial: Mapped[str | None] = mapped_column(String(128))
    tsa_url: Mapped[str | None] = mapped_column(String(500))
    ots_proof: Mapped[bytes | None] = mapped_column(LargeBinary)  # OpenTimestamps (Release 2)
    evidence_s3_key: Mapped[str | None] = mapped_column(String(500))


class ChainAnchor(IdMixin, CreatedMixin, Base):
    """Hourly RFC 3161 anchor of an audit chain head (``provenance.anchor_chain_heads``). Append-only."""

    __tablename__ = "chain_anchors"
    # Inserted by callers that may not read the new row back (no SELECT grant or policy), so the ORM must not add
    # RETURNING for server defaults.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = (
        UniqueConstraint("chain_id", "seq"),
        CheckConstraint("octet_length(event_hash) = 32", name="event_hash_length"),
        SYSTEM,
    )

    chain_id: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(BigInteger)
    event_hash: Mapped[bytes] = mapped_column(LargeBinary)
    tsa_token: Mapped[bytes] = mapped_column(LargeBinary)
    tsa_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    tsa_serial: Mapped[str] = mapped_column(String(128))


class TransparencyRoot(CreatedMixin, Base):
    """Nightly signed Merkle root over the day's chain heads (``/api/transparency``). Append-only."""

    __tablename__ = "transparency_roots"
    # Inserted by callers that may not read the new row back (no SELECT grant or policy), so the ORM must not add
    # RETURNING for server defaults.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = (CheckConstraint("octet_length(merkle_root) = 32", name="merkle_root_length"), SYSTEM)

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    merkle_root: Mapped[bytes] = mapped_column(LargeBinary)
    signature: Mapped[bytes] = mapped_column(LargeBinary)
    key_id: Mapped[str] = mapped_column(ForeignKey("provenance_keys.key_id"))


class Attestation(IdMixin, CreatedMixin, Base):
    """Ownership attestations made at a registration (docs/spec/06 6.4 item 7). Append-only; ``created_at`` is the
    database's (evidence_time_guard: now() on insert, whatever is sent)."""

    __tablename__ = "attestations"
    __table_args__ = (
        CheckConstraint("octet_length(text_sha256) = 32", name="text_sha256_length"),
        {"info": {"tenancy": Tenancy.USER, "tenant_column": "user_id"}},
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    version_id: Mapped[UUID] = mapped_column(ForeignKey("proposal_versions.id"), index=True)
    created_it: Mapped[bool] = mapped_column(Boolean)
    not_owned_by_employer_or_client: Mapped[bool] = mapped_column(Boolean)
    no_third_party_confidential: Mapped[bool] = mapped_column(Boolean)
    text_version: Mapped[str] = mapped_column(String(32))
    text_sha256: Mapped[bytes] = mapped_column(LargeBinary)
