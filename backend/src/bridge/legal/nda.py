"""The Evaluation NDA (REQ-REPO-01; docs/spec/06 6.1, 6.9 "Instruments per stage"): per person, per proposal, on behalf
of the organisation, before its Tier 2 opens.

The terms shown are the current ``nda_templates`` row of kind ``evaluation`` (``app_current_nda_template``: the most
recently created; its body is the seeded ``[[LEGAL-PLACEHOLDER]]`` until the advocate's review at G2) with the
viewer-logging notice (docs/spec/06 6.1: "each viewer is told at NDA acceptance that their name and viewing are logged
and shown to the owner"). Accepting echoes the template id, its SHA-256 and the notice version that were shown, so a
version published in between is refused (409 ``nda_outdated``) instead of being accepted unseen. One acceptance per
person, organisation, proposal and template version: a repeated acceptance returns the recorded one. A new version
needs a new acceptance (``can_view_tier2`` counts only the current one). The time is the database's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.errors import ApiError
from bridge.ids import uuid7

ACCEPTED: Final = "tier2.nda_accepted"
LOGGING_NOTICE_VERSION: Final = "v1"
# [[COPY-REVIEW]] the viewer-logging notice shown with the Evaluation NDA (docs/spec/10: recorded in lawful_basis.md).
LOGGING_NOTICE: Final = (
    "The owner of this proposal will see that you opened it: your name, your organisation and the date and time of "
    "each view. Every page of the full proposal carries a visible mark with your name, your organisation, the date "
    "and a view number."
)


class LoggingNotice(BaseModel):
    version: str
    text: str


class EvaluationNdaOut(BaseModel):
    """The Evaluation NDA to show before a proposal's Tier 2, and whether you accepted this version for it."""

    template_id: UUID
    version: str
    sha256: str = Field(description="Hex SHA-256 of the body; send it back to accept")
    body: str
    is_placeholder: bool
    logging_notice: LoggingNotice
    acceptance_id: UUID | None
    accepted_at: datetime | None


class NdaAcceptIn(BaseModel):
    """Exactly what was shown: a newer NDA version or notice is refused (409 ``nda_outdated``)."""

    template_id: UUID
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    logging_notice_version: str = Field(max_length=32)


class NdaAcceptanceOut(BaseModel):
    acceptance_id: UUID
    template_id: UUID
    version: str
    sha256: str
    logging_notice_version: str
    accepted_at: datetime


@dataclass(frozen=True, slots=True)
class Template:
    id: UUID
    version: str
    sha256: bytes
    body: str
    is_placeholder: bool


_CURRENT = text(
    "SELECT t.id, t.version, t.sha256, l.body, l.is_placeholder FROM nda_templates t"
    " JOIN legal_templates l ON l.id = t.legal_template_id WHERE t.id = app_current_nda_template('evaluation')"
)
_ACCEPTANCE = text(
    "SELECT id, accepted_at, logging_notice_version FROM nda_acceptances WHERE user_id = :user AND org_id = :org"
    " AND proposal_id = :proposal AND nda_template_id = :template ORDER BY accepted_at, id LIMIT 1"
)
_LOCK = text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))")
_INSERT = text(
    "INSERT INTO nda_acceptances (id, user_id, org_id, proposal_id, nda_template_id, template_sha256,"
    " logging_notice_version) VALUES (:id, :user, :org, :proposal, :template, :sha256, :notice)"
    " RETURNING accepted_at"
)


async def current(db: AsyncSession) -> Template:
    """The current Evaluation NDA; 503 ``not_configured`` when none is seeded (nothing can be accepted then)."""
    row = (await db.execute(_CURRENT)).one_or_none()
    if row is None:
        raise ApiError(503, "not_configured", "The Evaluation NDA is not set up on this server yet.")
    return Template(row.id, row.version, bytes(row.sha256), row.body, row.is_placeholder)


async def terms(db: AsyncSession, *, user_id: UUID, org_id: UUID, proposal_id: UUID) -> EvaluationNdaOut:
    template = await current(db)
    keys = {"user": user_id, "org": org_id, "proposal": proposal_id, "template": template.id}
    accepted = (await db.execute(_ACCEPTANCE, keys)).one_or_none()
    return EvaluationNdaOut(
        template_id=template.id,
        version=template.version,
        sha256=template.sha256.hex(),
        body=template.body,
        is_placeholder=template.is_placeholder,
        logging_notice=LoggingNotice(version=LOGGING_NOTICE_VERSION, text=LOGGING_NOTICE),
        acceptance_id=None if accepted is None else accepted.id,
        accepted_at=None if accepted is None else accepted.accepted_at,
    )


async def accept(
    db: AsyncSession, body: NdaAcceptIn, *, user_id: UUID, org_id: UUID, proposal_id: UUID
) -> tuple[NdaAcceptanceOut, bool]:
    """Record this person's acceptance (once per template version); the acceptance and whether it is new. Audited on
    the organisation's chain; does not commit."""
    template = await current(db)
    shown = (body.template_id, body.sha256, body.logging_notice_version)
    if shown != (template.id, template.sha256.hex(), LOGGING_NOTICE_VERSION):
        raise ApiError(409, "nda_outdated", "The Evaluation NDA changed. Read the current version and accept it.")
    keys = {"user": user_id, "org": org_id, "proposal": proposal_id, "template": template.id}
    await db.execute(_LOCK, {"key": f"tier2.nda:{user_id}:{org_id}:{proposal_id}"})
    existing = (await db.execute(_ACCEPTANCE, keys)).one_or_none()
    if existing is not None:
        acceptance_id, accepted_at, notice = existing.id, existing.accepted_at, existing.logging_notice_version
        created = False
    else:
        acceptance_id, notice, created = uuid7(), LOGGING_NOTICE_VERSION, True
        params = keys | {"id": acceptance_id, "sha256": template.sha256, "notice": notice}
        accepted_at = (await db.execute(_INSERT, params)).scalar_one()
        await audit(
            db,
            ACCEPTED,
            actor_user_id=user_id,
            org_id=org_id,
            subject_type="proposal",
            subject_id=proposal_id,
            payload={
                "acceptance_id": str(acceptance_id),
                "nda_template_id": str(template.id),
                "nda_version": template.version,
                "template_sha256": template.sha256.hex(),
                "logging_notice_version": notice,
            },
        )
    out = NdaAcceptanceOut(
        acceptance_id=acceptance_id,
        template_id=template.id,
        version=template.version,
        sha256=template.sha256.hex(),
        logging_notice_version=notice,
        accepted_at=accepted_at,
    )
    return out, created
