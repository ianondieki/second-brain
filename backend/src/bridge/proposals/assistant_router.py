"""The submission assistant's API (REQ-PROP-05; PLAN §8 P13; ``bridge.proposals.assistant`` holds the rules).

Owner only: every route answers 404 for anyone else's proposal (or none), published or not, and 409
``proposal_hidden`` for a deleted one (except ``DELETE``, which always turns the assistant off). The two ``POST``
routes also carry the ``tier2`` tag and ``access.tier2_gate``: 403 ``tier2_disabled`` while ``FEATURE_TIER2_ENABLED``
is off, before anything else (AC-SEC-2; ``integration/test_feature_flags.py`` enumerates them).

The opt-in is per login session, not per proposal (ADR-005 decision 4): the proposal in the path is where the owner
turned it on (``from_proposal_id`` in the audit event) and it covers the owner's proposals until the session ends.

- ``GET /api/me/proposals/{id}/assistant/consent``: whether the assistant is on for this sign-in, with the consent
  wording and its version to show.
- ``POST /api/me/proposals/{id}/assistant/consent``: turn it on for this login session only (ADR-005 decision 4). The
  body names the ``consents.yaml`` version whose wording was shown (409 ``consent_text_changed`` otherwise). Writes
  the ``tier2_llm_assistant`` row through ``grant_session_consent`` and a ``consent.changed`` audit event
  (``scope: "session"``). The opt-in ends when the session does (sign-out, expiry, revocation) or when it is turned
  off.
- ``DELETE /api/me/proposals/{id}/assistant/consent``: turn it off (a withdrawal row and an audit event).
- ``POST /api/me/proposals/{id}/assistant/suggestions``: one suggested clearer teaser and placement hints for the
  saved draft (or the current version when there is no draft). 403 ``consent_required`` without a live opt-in for
  this session, before anything is read or sent. A demo fallback is "no suggestion" with ``demo_fallback: true``.
  Never writes the proposal: the owner applies a suggestion through ``PATCH /api/me/proposals/{id}``. Refusals: 403
  ``assistant_demo_only`` (D-37: a non-demo account's confidential text never goes to a free provider), 429
  ``assistant_budget``, 503 ``assistant_paused`` or ``assistant_off``, each with a fixed message and a
  ``proposal.assistant_suggested`` audit event with status ``refused`` (the confidential text was read). Before the
  confidential text is read: 429 ``assistant_busy`` while the user's previous suggestion is still running and 429
  ``assistant_rate_limited`` past the daily limit (``policy.yaml`` ``assistant``).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from bridge.audit.service import record as audit
from bridge.auth.deps import CurrentSession, Db, SettingsDep
from bridge.auth.sessions import LiveSession
from bridge.config import Settings
from bridge.errors import ERROR_RESPONSES, ApiError, ApiErrorBody
from bridge.llm.demo_fallback import DemoFallbackFlag
from bridge.llm.deps import LLMDep
from bridge.llm.guard import SessionConsentChecker, grant_session_consent, withdraw_session_consent
from bridge.models.enums import ConsentPurpose
from bridge.profiles import consents
from bridge.proposals import access, assistant
from bridge.proposals.assistant import InFlight, Move, PlacementField, SuggestionStatus
from bridge.proposals.assistant_policy import get_assistant_policy
from bridge.proposals.deps import WrapperDep

router = APIRouter(tags=["assistant"], responses=ERROR_RESPONSES)
gated = APIRouter(tags=["assistant", "tier2"], responses=ERROR_RESPONSES, dependencies=[Depends(access.tier2_gate)])
PATH = "/api/me/proposals/{proposal_id}/assistant"
UNAVAILABLE: dict[int | str, dict[str, Any]] = {503: {"model": ApiErrorBody}}


class AssistantConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(max_length=64, description="The consents.yaml version whose wording was shown")


class AssistantConsentOut(BaseModel):
    purpose: Literal[ConsentPurpose.TIER2_LLM_ASSISTANT] = ConsentPurpose.TIER2_LLM_ASSISTANT
    granted: bool = Field(description="True while the assistant is on for this sign-in")
    scope: Literal["this_session"] = "this_session"
    text: str
    version: str


class SuggestedTeaserOut(BaseModel):
    title: str
    summary: str


class PlacementHintOut(BaseModel):
    field: PlacementField
    move: Move
    reason: str = Field(description="AI-drafted; plain text")


class AssistantSuggestionOut(DemoFallbackFlag):
    status: SuggestionStatus
    message: str | None = Field(description="Why there is no suggestion, in plain words")
    ai_drafted: bool = Field(description="True when a model wrote the teaser or a reason (label it 'AI-drafted')")
    version_id: UUID = Field(description="The version the suggestion was made for")
    teaser: SuggestedTeaserOut | None
    placement: list[PlacementHintOut]


async def _state(db: Db, settings: Settings, live: LiveSession) -> AssistantConsentOut:
    shown = consents.load_texts(settings.consents_file)[assistant.PURPOSE]
    granted = await SessionConsentChecker(db).has_live_consent(live.user.id, assistant.PURPOSE, session_id=live.row.id)
    return AssistantConsentOut(granted=granted, text=shown.text, version=shown.version)


def in_flight(request: Request) -> InFlight:
    """The process's running suggestions (``app.state``; created on first use)."""
    running: InFlight | None = getattr(request.app.state, "assistant_in_flight", None)
    if running is None:
        running = InFlight()
        request.app.state.assistant_in_flight = running
    return running


async def _audit_decision(db: Db, live: LiveSession, proposal_id: UUID, *, granted: bool, version: str) -> None:
    await audit(
        db,
        "consent.changed",
        actor_user_id=live.user.id,
        subject_type="user",
        subject_id=live.user.id,
        payload={
            assistant.PURPOSE.value: granted,
            "scope": "session",
            "text_version": version,
            "from_proposal_id": str(proposal_id),  # where it was turned on or off; the scope is the session
        },
    )


@router.get(f"{PATH}/consent")
async def assistant_consent(
    proposal_id: UUID, live: CurrentSession, db: Db, settings: SettingsDep
) -> AssistantConsentOut:
    """Whether the writing assistant is on for this sign-in, with the wording to show before turning it on."""
    await assistant.owned(db, live.user.id, proposal_id)
    return await _state(db, settings, live)


@gated.post(f"{PATH}/consent")
async def grant_assistant_consent(
    proposal_id: UUID, body: AssistantConsentIn, live: CurrentSession, db: Db, settings: SettingsDep
) -> AssistantConsentOut:
    """Turn the writing assistant on for this sign-in only: it may read the confidential (Tier 2) text of your
    proposals until you sign out or turn it off."""
    await assistant.owned(db, live.user.id, proposal_id)
    current = consents.consents_version(settings)
    if body.version != current:
        raise ApiError(409, "consent_text_changed", "The consent wording has changed. Reload and choose again.")
    await grant_session_consent(db, settings, user_id=live.user.id, session_id=live.row.id)
    await _audit_decision(db, live, proposal_id, granted=True, version=current)
    await db.commit()
    return await _state(db, settings, live)


@router.delete(f"{PATH}/consent")
async def withdraw_assistant_consent(
    proposal_id: UUID, live: CurrentSession, db: Db, settings: SettingsDep
) -> AssistantConsentOut:
    """Turn the writing assistant off (it also ends when you sign out). Works from a deleted proposal too."""
    await assistant.owned(db, live.user.id, proposal_id, allow_hidden=True)
    await withdraw_session_consent(db, settings, user_id=live.user.id, session_id=live.row.id)
    await _audit_decision(db, live, proposal_id, granted=False, version=consents.consents_version(settings))
    await db.commit()
    return await _state(db, settings, live)


@gated.post(f"{PATH}/suggestions", responses=UNAVAILABLE)
async def suggest_teaser(
    proposal_id: UUID,
    live: CurrentSession,
    db: Db,
    wrapper: WrapperDep,
    llm: LLMDep,
    running: Annotated[InFlight, Depends(in_flight)],
) -> AssistantSuggestionOut:
    """One suggested clearer teaser and which fields might move between Tier 1 and Tier 2. Nothing is saved."""
    user_id = live.user.id
    own = await assistant.owned(db, user_id, proposal_id)
    await assistant.require_consent(SessionConsentChecker(db), user_id, session_id=live.row.id)
    policy = get_assistant_policy()
    if not running.claim(user_id, policy.max_in_flight_per_user):
        raise ApiError(429, "assistant_busy", assistant.BUSY)
    try:
        await assistant.check_daily_limit(db, user_id, policy)
        draft = await assistant.load_text(db, wrapper, own)
        await db.commit()  # ends the read before the model call (the ledger writes on its own connection)
        try:
            suggestion = await assistant.suggest(llm, draft, session_id=live.row.id)
        except ApiError as refused:  # the confidential text was read: the refusal is audited too
            code = refused.detail["code"] if isinstance(refused.detail, dict) else "refused"
            await _audit_suggestion(db, live, own, draft, status="refused", reason=str(code), demo_fallback=False)
            await db.commit()
            raise
        await _audit_suggestion(
            db,
            live,
            own,
            draft,
            status=suggestion.status.value,
            reason=suggestion.reason,
            demo_fallback=suggestion.demo_fallback,
            trace_id=suggestion.trace_id,
        )
        await db.commit()
    finally:
        running.release(user_id)
    teaser = None
    if suggestion.title is not None and suggestion.summary is not None:
        teaser = SuggestedTeaserOut(title=suggestion.title, summary=suggestion.summary)
    placement = [PlacementHintOut(field=h.field, move=h.move, reason=h.reason) for h in suggestion.placement]
    return AssistantSuggestionOut(
        demo_fallback=suggestion.demo_fallback,
        status=suggestion.status,
        message=suggestion.message,
        ai_drafted=teaser is not None or bool(placement),
        version_id=own.version_id,
        teaser=teaser,
        placement=placement,
    )


async def _audit_suggestion(
    db: Db,
    live: LiveSession,
    own: assistant.Owned,
    draft: assistant.DraftText,
    *,
    status: str,
    reason: str,
    demo_fallback: bool,
    trace_id: str | None = None,
) -> None:
    """Codes and names only: never the text."""
    await audit(
        db,
        "proposal.assistant_suggested",
        actor_user_id=live.user.id,
        subject_type="proposal",
        subject_id=own.proposal_id,
        payload={
            "version_id": str(own.version_id),
            "status": status,
            "reason": reason,
            "demo_fallback": demo_fallback,
            "trace_id": trace_id,
            "tier2_fields_read": sorted(draft.tier2),  # read for the call; whether any left is in llm_calls
        },
    )


router.include_router(gated)  # last: routes added to gated after this line would be missed
