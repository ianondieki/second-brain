"""The moderation queue (REQ-MOD-01, REQ-PROP-02; docs/spec/06 6.12), the prototype's minimal staff part.

Staff admin or moderator list the unresolved cases (open, held, escalated) with a Tier-1 preview of their proposal or
problem, and decide one: approve (the subject becomes ``clear``; a problem ``published``) or reject (``rejected``).
The subject's state changes only through ``app_moderate_proposal`` / ``app_moderate_problem`` (SECURITY DEFINER:
staff only, never on their own content); the case records who decided and when, and the decision is audited on the
staff member's chain. Approving a held proposal writes its ``proposal_published`` signal, which publishing withheld.
Claims, research approval and reports arrive with P15.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.audit.service import record as audit
from bridge.errors import ApiError, not_found
from bridge.models.enums import AuditActor, ModerationCaseStatus, ModerationSource, ModerationState
from bridge.proposals.service import signal

UNRESOLVED: Final = ("open", "held", "escalated")
Decision = Literal["approve", "reject"]


class CasePreview(BaseModel):
    """Tier-1 text of the subject (never Tier 2)."""

    title: str | None
    text: str | None


class CaseOut(BaseModel):
    id: UUID
    subject_type: str
    subject_id: UUID
    reasons: list[str]
    source: ModerationSource
    status: ModerationCaseStatus
    created_at: datetime
    subject_state: ModerationState | None
    preview: CasePreview


class CaseList(BaseModel):
    items: list[CaseOut]


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Decision


class DecisionOut(BaseModel):
    id: UUID
    status: ModerationCaseStatus
    subject_state: ModerationState


_CASES = text(
    "SELECT m.id, m.subject_type, m.subject_id, m.reasons, m.source, m.status, m.created_at,"
    " coalesce(p.moderation_state, pr.moderation_state) AS subject_state, coalesce(p.title, pr.title) AS title,"
    " coalesce(p.summary, pr.statement) AS body"
    " FROM moderation_cases m"
    " LEFT JOIN proposals p ON m.subject_type = 'proposal' AND p.id = m.subject_id"
    " LEFT JOIN problems pr ON m.subject_type = 'problem' AND pr.id = m.subject_id"
    " WHERE (m.status IN ('open', 'held', 'escalated')) = :unresolved ORDER BY m.created_at, m.id LIMIT 200"
)


async def list_cases(db: AsyncSession, *, unresolved: bool) -> CaseList:
    rows = (await db.execute(_CASES, {"unresolved": unresolved})).all()
    return CaseList(
        items=[
            CaseOut(
                id=r.id,
                subject_type=r.subject_type,
                subject_id=r.subject_id,
                reasons=list(r.reasons),
                source=r.source,
                status=r.status,
                created_at=r.created_at,
                subject_state=r.subject_state,
                preview=CasePreview(title=r.title, text=r.body),
            )
            for r in rows
        ]
    )


_CASE = text("SELECT id, subject_type, subject_id, status FROM moderation_cases WHERE id = :id FOR UPDATE")
_PROPOSAL = text("SELECT owner_id, status, moderation_state FROM proposals WHERE id = :id")
_MODERATE_PROPOSAL = text("SELECT app_moderate_proposal(:id, CAST(:state AS moderation_state))")
_MODERATE_PROBLEM = text(
    "SELECT app_moderate_problem(:id, CAST(:state AS moderation_state), CAST(:status AS problem_status))"
)
_CLOSE = text(
    "UPDATE moderation_cases SET status = CAST(:status AS moderation_case_status), decided_by = :staff,"
    " decided_at = now(), updated_at = now() WHERE id = :id"
)


def _refusal(exc: DBAPIError) -> ApiError | None:
    sqlstate = getattr(exc.orig, "sqlstate", None)
    if sqlstate == "P0002":  # no_data_found: gone, or the moderator's own content
        return ApiError(403, "own_content", "You cannot moderate your own content or content that no longer exists.")
    if sqlstate == "42501":  # the database's staff check
        return not_found()
    return None


async def decide(db: AsyncSession, *, staff_id: UUID, case_id: UUID, decision: Decision) -> DecisionOut:
    case = (await db.execute(_CASE, {"id": case_id})).one_or_none()
    if case is None:
        raise not_found("No such case.")
    if case.status not in UNRESOLVED:
        raise ApiError(409, "already_decided", "This case was already decided.")
    approve = decision == "approve"
    state = ModerationState.CLEAR if approve else ModerationState.REJECTED
    proposal: Any = None
    try:
        if case.subject_type == "proposal":
            proposal = (await db.execute(_PROPOSAL, {"id": case.subject_id})).one_or_none()
            await db.execute(_MODERATE_PROPOSAL, {"id": case.subject_id, "state": state.value})
        elif case.subject_type == "problem":
            status = "published" if approve else "rejected"
            await db.execute(_MODERATE_PROBLEM, {"id": case.subject_id, "state": state.value, "status": status})
        else:
            raise ApiError(409, "unsupported_subject", "Decide this case from its own queue.")
    except DBAPIError as exc:
        refusal = _refusal(exc)
        if refusal is None:
            raise
        await db.rollback()
        raise refusal from None
    outcome = ModerationCaseStatus.APPROVED if approve else ModerationCaseStatus.REJECTED
    await db.execute(_CLOSE, {"status": outcome.value, "staff": staff_id, "id": case_id})
    if (
        approve
        and proposal is not None
        and proposal.status == "published"
        and proposal.moderation_state != ModerationState.CLEAR
    ):
        await signal(db, proposal_id=case.subject_id, owner_id=proposal.owner_id)
    await audit(
        db,
        "moderation.case_decided",
        actor_user_id=staff_id,
        actor_kind=AuditActor.STAFF,
        subject_type="moderation_case",
        subject_id=case_id,
        payload={"subject_type": case.subject_type, "subject_id": str(case.subject_id), "decision": decision},
    )
    await db.commit()
    return DecisionOut(id=case_id, status=outcome, subject_state=state)
