"""The teaser over-disclosure check's API (REQ-REPO-01, warn only; ``bridge.proposals.disclosure`` holds the rules).

``POST /api/me/proposals/{id}/disclosure-check``: whether the saved teaser (the draft, else the current version)
reads like how the project works rather than what it does. Owner only, like the originality check: 403
``not_owner`` for another owner's published proposal, 404 for one the caller cannot see, 409 ``proposal_hidden`` once
deleted. Not behind the Tier-2 gate: only the four Tier-1 fields are read. The rules answer first without a model;
otherwise the ``over_disclosure_check`` task runs, at most one per user at a time (429 ``disclosure_busy``) and
within the assistant's daily limit (429 ``disclosure_rate_limited``); a refused call answers with the assistant's
fixed refusals (429 ``assistant_budget``, 503 ``assistant_paused`` or ``assistant_off``). Nothing is written to the
proposal and nothing blocks publishing.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field

from bridge.auth.deps import CurrentSession, Db
from bridge.errors import ERROR_RESPONSES, ApiError, ApiErrorBody
from bridge.llm.demo_fallback import DemoFallbackFlag
from bridge.llm.deps import LLMDep
from bridge.proposals import disclosure, originality
from bridge.proposals.assistant import InFlight
from bridge.proposals.assistant_policy import get_assistant_policy
from bridge.proposals.disclosure import Disclosure, DisclosureSource, TeaserField

router = APIRouter(tags=["originality"], responses=ERROR_RESPONSES)
UNAVAILABLE: dict[int | str, dict[str, Any]] = {503: {"model": ApiErrorBody}}


class DisclosureCheckOut(DemoFallbackFlag):
    flagged: bool = Field(description="True when the teaser reads like how it works; a warning only")
    fields: list[TeaserField] = Field(description="The teaser fields to look at again")
    why: str | None = Field(description="Plain words for the owner (AI-drafted when ai_drafted)")
    source: DisclosureSource
    ai_drafted: bool
    version_id: UUID = Field(description="The version that was checked")


def in_flight(request: Request) -> InFlight:
    """The process's running teaser checks, keyed by user (``app.state``; created on first use)."""
    running: InFlight | None = getattr(request.app.state, "disclosure_in_flight", None)
    if running is None:
        running = InFlight()
        request.app.state.disclosure_in_flight = running
    return running


@router.post("/api/me/proposals/{proposal_id}/disclosure-check", responses=UNAVAILABLE)
async def check_disclosure(
    proposal_id: UUID,
    live: CurrentSession,
    db: Db,
    llm: LLMDep,
    running: Annotated[InFlight, Depends(in_flight)],
) -> DisclosureCheckOut:
    """A warning when the public teaser gives away how the project works. Nothing is saved."""
    user_id = live.user.id
    own = await originality.owned_by(db, user_id, proposal_id)
    fields = await originality.load_teaser(db, own)
    hits = disclosure.precheck(fields)
    answer: Disclosure
    if not fields:
        answer = disclosure.NOTHING_TO_CHECK
    elif hits:
        answer = disclosure.by_rules(hits)
    else:
        policy = get_assistant_policy()
        if not running.claim(user_id, policy.max_in_flight_per_user):
            raise ApiError(429, "disclosure_busy", disclosure.BUSY)
        try:
            await disclosure.check_daily_limit(db, user_id, policy)
            await db.commit()  # ends the read before the model call (the ledger writes on its own connection)
            answer = await disclosure.ask_model(llm, user_id, fields, session_id=live.row.id, policy=policy)
        finally:
            running.release(user_id)
    return DisclosureCheckOut(
        demo_fallback=answer.demo_fallback,
        flagged=answer.flagged,
        fields=list(answer.fields),
        why=answer.why,
        source=answer.source,
        ai_drafted=answer.ai_drafted,
        version_id=own.version_id,
    )
