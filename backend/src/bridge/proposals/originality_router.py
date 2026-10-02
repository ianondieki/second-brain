"""The originality check's API (REQ-PROP-04; docs/spec/06 6.3; ``bridge.proposals.originality`` holds the rules).

Informational, never blocking: nothing here changes the proposal or stands in the way of publishing. Not behind the
Tier-2 gate: only Tier-1 text is read (the saved draft's four teaser fields), so the route carries no ``tier2`` tag.

- ``POST /api/me/proposals/{id}/originality``: check the saved draft (or the current version when there is no draft)
  against other owners' published, clear teasers. Owner only: 404 for anyone else's proposal, published or not
  (AC-SEC-1/b), 409 ``proposal_hidden`` once deleted. 429 ``originality_busy`` while a check of this proposal is
  running (per API process) and 429 ``originality_limit`` past ``policy.yaml`` ``originality.daily_limit`` checks per
  Nairobi day (one ``originality_checks`` row each, the band only, committed with its audit event). The answer: the
  band, how many teasers were compared, and at most one checked, AI-drafted sentence (none for the band ``none``: the
  explainer is not called), with the "demo fallback" label when no model wrote it. The
  ``proposal.originality_checked`` audit event keeps the band, the count and a SHA-256 of the checked Tier-1 text; the
  explainer's outcome (sentence, fallback label) goes to its details after the call.
- ``GET /api/me/proposals/{id}/originality``: today's last check of this proposal, so the editor can show it again;
  null when there is none today or when the saved Tier-1 text is no longer the text that was checked.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import insert, text

from bridge import clock
from bridge.audit.models import EventDetails
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

        digest = originality.text_digest(fields)
        event: list[UUID] = []

        async def assessed(assessment: Assessment) -> None:
            # The counter row and its audit event in one commit (the lock ends here too, before the model call): a
            # failure after this point never costs a check without its record.
            await originality.record_check(db, user_id, assessment.band, now)
            event_id = await audit(
                db,
                ACTION,
                actor_user_id=user_id,
                subject_type="proposal",
                subject_id=proposal_id,
                payload={
                    "version_id": str(own.version_id),
                    "band": assessment.band.value,
                    "compared": assessment.compared,
                    "checked_at": now.isoformat(),
                    "text_sha256": digest,
                },
            )
            await db.commit()
            event.append(event_id)

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
        if out.band is not OriginalityBand.NONE:  # the explainer's outcome joins the event (mutable details)
            details = {
                "explanation": out.explanation,
                "demo_fallback": out.demo_fallback,
                "explainer": explained.reason,
                "trace_id": explained.trace_id,
            }
            await db.execute(insert(EventDetails).values(event_id=event[0], details=details))
            await db.commit()
    finally:
        running.release(proposal_id)
    return out


@router.get(PATH)
async def last_originality(proposal_id: UUID, live: CurrentSession, db: Db) -> OriginalityOut | None:
    """Today's last originality check of this proposal (Nairobi day), or null, also once the teaser text changed."""
    user_id = live.user.id
    own = await originality.owned_by(db, user_id, proposal_id)
    row = (await db.execute(_LAST, {"user": user_id, "action": ACTION, "id": proposal_id})).first()
    if row is None:
        return None
    payload: dict[str, Any] = row.payload
    checked_at = datetime.fromisoformat(payload["checked_at"])
    if checked_at < originality.nairobi_day_start(clock.utcnow()):
        return None
    if payload.get("text_sha256") != originality.text_digest(await originality.load_teaser(db, own)):
        return None  # the band was about other text
    details: dict[str, Any] = row.details or {}
    explanation = details.get("explanation")
    return OriginalityOut(
        demo_fallback=details.get("demo_fallback") is True,
        band=OriginalityBand(payload["band"]),
        compared=int(payload["compared"]),
        explanation=explanation if isinstance(explanation, str) else None,
        ai_drafted=isinstance(explanation, str),
        checked_at=checked_at,
    )
