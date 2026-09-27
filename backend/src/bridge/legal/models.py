"""Legal templates, NDA templates and their acceptances (REQ-REPO-01, REQ-DIR-03; docs/spec/06 6.1, 6.9).

Bodies are placeholders until the advocate's review (G2): the seed writes only the DRAFT header and
``[[LEGAL-PLACEHOLDER:<id>]]`` markers (``backend/seed/legal_templates.yaml``). ``sha256`` is the SHA-256 of the UTF-8
body (a CHECK constraint keeps them in step). A template version is immutable once accepted: acceptances reference
``(template id, sha256)``, so changing an accepted body fails; publish a new version instead.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from bridge.models.base import Base, CreatedMixin, IdMixin, Tenancy
from bridge.models.enums import LegalTemplateKind, NdaKind
from bridge.models.types import pg_enum

GLOBAL = {"info": {"tenancy": Tenancy.GLOBAL}}
SHA256_OF_BODY = "sha256 = sha256(convert_to(body, 'UTF8'))"


class LegalTemplate(IdMixin, CreatedMixin, Base):
    __tablename__ = "legal_templates"
    __table_args__ = (
        UniqueConstraint("kind", "version"),
        UniqueConstraint("id", "sha256"),  # target of the (template, hash) foreign keys of acceptances
        CheckConstraint(SHA256_OF_BODY, name="sha256_of_body"),
        GLOBAL,
    )

    kind: Mapped[LegalTemplateKind] = mapped_column(pg_enum(LegalTemplateKind, "legal_template_kind"))
    version: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[bytes] = mapped_column(LargeBinary)
    body: Mapped[str] = mapped_column(Text)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, server_default="true")


class NdaTemplate(IdMixin, CreatedMixin, Base):
    """An NDA version; its hash is the hash of the legal template body it points at (composite foreign key)."""

    __tablename__ = "nda_templates"
    __table_args__ = (
        UniqueConstraint("kind", "version"),
        UniqueConstraint("id", "sha256"),
        ForeignKeyConstraint(
            ["legal_template_id", "sha256"],
            ["legal_templates.id", "legal_templates.sha256"],
            name="fk_nda_templates_legal_template",
        ),
        GLOBAL,
    )

    kind: Mapped[NdaKind] = mapped_column(pg_enum(NdaKind, "nda_kind"))
    version: Mapped[str] = mapped_column(String(32))
    legal_template_id: Mapped[UUID] = mapped_column()
    sha256: Mapped[bytes] = mapped_column(LargeBinary)


class LegalAcceptance(IdMixin, Base):
    """An organisation's acceptance of a legal template (Master Enterprise Terms by the Signatory). Append-only."""

    __tablename__ = "legal_acceptances"
    # Inserted by callers that may not read the new row back (no SELECT grant or policy), so the ORM must not add
    # RETURNING for server defaults.
    __mapper_args__ = {"eager_defaults": False}  # noqa: RUF012
    __table_args__ = (
        ForeignKeyConstraint(
            ["legal_template_id", "template_sha256"],
            ["legal_templates.id", "legal_templates.sha256"],
            name="fk_legal_acceptances_template",
        ),
        {"info": {"tenancy": Tenancy.ORG, "tenant_column": "org_id", "user_column": "user_id"}},
    )

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    legal_template_id: Mapped[UUID] = mapped_column()
    template_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NdaAcceptance(IdMixin, Base):
    """One person's Evaluation NDA for one proposal, on behalf of their organisation. Append-only."""

    __tablename__ = "nda_acceptances"
    __table_args__ = (
        ForeignKeyConstraint(
            ["nda_template_id", "template_sha256"],
            ["nda_templates.id", "nda_templates.sha256"],
            name="fk_nda_acceptances_template",
        ),
        {"info": {"tenancy": Tenancy.ORG_OR_USER, "tenant_column": "org_id", "user_column": "user_id"}},
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    proposal_id: Mapped[UUID] = mapped_column(ForeignKey("proposals.id"), index=True)
    nda_template_id: Mapped[UUID] = mapped_column()
    template_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    # The version of the "your name and viewing are logged and shown to the owner" notice shown at acceptance.
    logging_notice_version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
