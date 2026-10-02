"""The originality check's API (REQ-PROP-04; docs/spec/06 6.3; ``bridge.proposals.originality`` holds the rules).

Informational, never blocking: nothing here changes the proposal or stands in the way of publishing. Not behind the
Tier-2 gate: only Tier-1 text is read (the saved draft's four teaser fields), so the route carries no ``tier2`` tag.

- ``POST /api/me/proposals/{id}/originality``: check the saved draft (or the current version when there is no draft)
  against other owners' published, clear teasers. Owner only: 403 ``not_owner`` for another owner's published
  proposal, 404 for one the caller cannot see, 409 ``proposal_hidden`` once deleted. 429 ``originality_busy`` while a
  check of this proposal is running (per API process) and 429 ``originality_limit`` past ``policy.yaml``
  ``originality.daily_limit`` checks per Nairobi day (one ``originality_checks`` row each, the band only). The
  answer: the band, how many teasers were compared, and at most one checked, AI-drafted sentence (none for the band
  ``none``: the explainer is not called), with the "demo fallback" label when no model wrote it. A
  ``proposal.originality_checked`` audit event keeps the band and the count; the sentence goes to its details.
- ``GET /api/me/proposals/{id}/originality``: today's last check of this proposal, so the editor can show it again
  (null when there is none today).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from bridge import clock
from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES, ApiError
from bridge.llm.deps import LLMDep
from bridge.models.enums import OriginalityBand
from bridge.proposals import originality
from bridge.proposals.assistant import InFlight
from bridge.proposals.deps import EmbedderDep
from bridge.proposals.originality import Assessment, SqlTeaserPool
from bridge.proposals.originality_explainer import OriginalityOut, run
from bridge.proposals.originality_policy import get_originality_policy

router = APIRouter(tags=["originality"], responses=ERROR_RESPONSES)
PATH = "/api/me/proposals/{proposal_id}/originality"
ACTION = "proposal.originality_checked"

_LAST = text(
    "SELECT e.payload, d.details FROM audit_events e LEFT JOIN event_details d ON d.event_id = e.id"
    " WHERE e.actor_user_id = :user AND e.action = :action AND e.subject_type = 'proposal' AND e.subject_id = :id"
    " ORDER BY e.occurred_at DESC, e.seq DESC LIMIT 1"
)


def in_flight(request: Request) -> InFlight:
    """The process's running checks, keyed by proposal (``app.state``; created on first use)."""
    running: InFlight | None = getattr(request.app.state, "originality_in_flight", None)
    if running is None:
        running = InFlight()
        request.app.state.originality_in_flight = running
    return running


@router.post(PATH)
async def check_originality(
    proposal_id: UUID,
    live: CurrentSession,
    db: Db,
    llm: LLMDep,
    embedder: EmbedderDep,
    running: Annotated[InFlight, Depends(in_flight)],
) -> OriginalityOut:
    """How much this teaser overlaps with other developers' published teasers: a coarse band, never a score."""
    user_id = live.user.id
    own = await originality.owned_by(db, user_id, proposal_id)
    policy = get_originality_policy()
    if not running.claim(proposal_id, 1):
        raise ApiError(429, "originality_busy", originality.BUSY)
    try:
        now = clock.utcnow()
        await originality.check_daily_limit(db, user_id, policy, now)
        fields = await originality.load_teaser(db, own)

        async def assessed(assessment: Assessment) -> None:
            await originality.record_check(db, user_id, assessment.band, now)
            await db.commit()  # the counter row and the lock end before the model call

        out, explained = await run(
            SqlTeaserPool(db),
            embedder,
            llm,
            fields,
            owner_id=user_id,
            proposal_id=proposal_id,
            session_id=live.row.id,
            policy=policy,
            checked_at=now,
            assessed=assessed,
        )
        await audit(
            db,
            ACTION,
            actor_user_id=user_id,
            subject_type="proposal",
            subject_id=proposal_id,
            payload={
                "version_id": str(own.version_id),
                "band": out.band.value,
                "compared": out.compared,
                "demo_fallback": out.demo_fallback,
                "explainer": explained.reason,
                "trace_id": explained.trace_id,
                "checked_at": now.isoformat(),
            },
            details={"explanation": out.explanation} if out.explanation is not None else None,
        )
        await db.commit()
    finally:
        running.release(proposal_id)
    return out


@router.get(PATH)
async def last_originality(proposal_id: UUID, live: CurrentSession, db: Db) -> OriginalityOut | None:
    """Today's last originality check of this proposal (Nairobi day), or null."""
    user_id = live.user.id
    await originality.owned_by(db, user_id, proposal_id)
    row = (await db.execute(_LAST, {"user": user_id, "action": ACTION, "id": proposal_id})).first()
    if row is None:
        return None
    payload: dict[str, Any] = row.payload
    checked_at = datetime.fromisoformat(payload["checked_at"])
    if checked_at < originality.nairobi_day_start(clock.utcnow()):
        return None
    explanation = (row.details or {}).get("explanation")
    return OriginalityOut(
        demo_fallback=bool(payload["demo_fallback"]),
        band=OriginalityBand(payload["band"]),
        compared=int(payload["compared"]),
        explanation=explanation if isinstance(explanation, str) else None,
        ai_drafted=isinstance(explanation, str),
        checked_at=checked_at,
    )
