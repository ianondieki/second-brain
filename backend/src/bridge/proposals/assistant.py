"""The submission assistant (REQ-PROP-05; docs/spec/06 6.3, docs/spec/09; PLAN §8 P13): one suggested clearer teaser,
and which fields might move between Tier 1 and Tier 2. The model words; plain code decides what is shown.

Rules, in the order the route applies them (``bridge.proposals.assistant_router``):

1. **Owner only.** ``owned`` answers 404 for anyone else's proposal (or none) and 409 ``proposal_hidden`` for a
   deleted one; drafts and published proposals are served (a published proposal without a draft is read from its
   current version).
2. **Per-session consent** (ADR-005 decision 4). ``require_consent`` answers 403 ``consent_required`` unless the
   owner's latest ``tier2_llm_assistant`` decision is a grant from this very login session, still live
   (``bridge.llm.guard.SessionConsentChecker``). It runs before anything is read for the model, so without it nothing
   reaches any provider, not even the Tier-1 teaser (the LLM layer's own guard would refuse only Tier-2 fields).
3. **Only the owner's own saved text** is sent: the version's Tier-1 teaser fields and Tier-2 text fields (never the
   links or attachments), each an ``InputField`` owned by the owner, Tier-2 fields tagged ``Tier.TIER2``. The LLM
   layer sanitises and wraps each in a ``<submission nonce=...>`` block, records the call in ``llm_calls``, checks the
   caps first and, on a free provider, applies the D-37 rule (``bridge.llm.demo_data``): only a demo account's fields
   go there; another account's Tier-2 text is refused (403 ``assistant_demo_only``) and a non-demo account's Tier-1
   text is answered by the labelled demo fallback. No tools.
4. **Code decides** (``evaluate``). A demo fallback (``TeaserSuggestion.demo_fallback()``) is "no suggestion",
   labelled; ``injection_suspected`` is "no suggestion"; a suggested title and summary are kept only when the Tier-1
   sanitiser accepts them (no contact details or links, the length limits, 150 words) and they change something;
   a placement hint is kept only for a field that has text and only in the direction away from its tier, with a
   plain-text reason carrying no contact details.
5. **Nothing is written to the proposal**, and nothing is published: the owner applies a suggestion through the
   editor's own routes.

LLM errors map to fixed, plain messages (``refusal``): a budget (a global or total cap never shows the platform's
figures, T2.2 security MINOR 3), a request cap and the kill switch are refusals; a provider that is down, unavailable
or failing ends as "no suggestion" (on local runs the router has already answered with the labelled demo fallback).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.crypto.envelope import KeyWrapper
from bridge.errors import ApiError, not_found
from bridge.ids import uuid7
from bridge.llm.client import LLMClient
from bridge.llm.errors import (
    ConsentRequired,
    LLMBatchNotOwned,
    LLMBudgetExceeded,
    LLMConfigError,
    LLMError,
    LLMKillSwitch,
    LLMRequestCapReached,
    NotDemoData,
    Tier2DemoOnly,
    Tier2NotAllowed,
)
from bridge.llm.guard import ConsentChecker
from bridge.llm.types import CallContext, InputField, Instruction, LLMOutput, Message, Part, Result, Tier
from bridge.logging import get_logger
from bridge.models.enums import ConsentPurpose, ProposalStatus
from bridge.proposals import tier2
from bridge.proposals.sanitise import TIER1_FIELDS, contact_findings, detection_skeleton, plain_text, sanitise

TASK: Final = "submission_assistant"
PURPOSE: Final = ConsentPurpose.TIER2_LLM_ASSISTANT
TIER2_FIELDS: Final = tier2.TEXT_FIELDS
MAX_REASON_CHARS: Final = 300  # a placement reason is one sentence; longer text is cut

# [[COPY-REVIEW]] every message below is shown to the owner.
CONSENT_REQUIRED: Final = "Turn on the writing assistant for this sign-in first."
DEMO_ONLY: Final = "In this demo, the writing assistant works only with demo accounts."
BUDGET_TENANT: Final = "You have used this month's writing assistant allowance."
PAUSED: Final = "The writing assistant is paused for today. Try again tomorrow."
SWITCHED_OFF: Final = "The writing assistant is switched off for now."
NO_TEXT: Final = "Write a title or a summary first, then ask again."
NO_SUGGESTION: Final = "The assistant has no suggestion for this teaser."
DEMO_FALLBACK: Final = "Demo fallback: no model answered, so there is no suggestion."
INJECTION: Final = "Part of your proposal reads like instructions to the assistant, so it made no suggestion."
UNAVAILABLE: Final = "The writing assistant could not answer just now. Try again later."

log = get_logger(__name__)


class PlacementField(StrEnum):
    TITLE = "title"
    PROBLEM_STATEMENT = "problem_statement"
    IMPACT_CLAIMS = "impact_claims"
    SUMMARY = "summary"
    APPROACH = "approach"
    ARCHITECTURE = "architecture"
    PRICING = "pricing"
    NOTES = "notes"


class Move(StrEnum):
    TO_TIER1 = "to_tier1"
    TO_TIER2 = "to_tier2"


class PlacementHint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: PlacementField = Field(description="The field that might belong in the other tier.")
    move: Move = Field(description="to_tier2 for a Tier 1 field, to_tier1 for a Tier 2 field.")
    reason: str = Field(description="One plain sentence; never quote the confidential text.")


class TeaserSuggestion(LLMOutput):
    """The model's answer. ``demo_fallback`` is the router's placeholder on local runs: no suggestion, flagged."""

    has_suggestion: bool = Field(description="False when the teaser is already clear or there is too little text.")
    title: str = Field(description="The suggested title (at most 120 characters), or empty.")
    summary: str = Field(description="The suggested summary (at most 150 words: what it does, never how), or empty.")
    placement: list[PlacementHint] = Field(description="At most one entry per field; empty when all fit their tier.")

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, has_suggestion=False, title="", summary="", placement=[])


SYSTEM: Final = (
    "You help a developer improve the public teaser of a project proposal on a platform where developers pitch"
    " projects to organisations. Tier 1 fields (title, problem_statement, impact_claims, summary) are shown to every"
    " signed-in user. Tier 2 fields (approach, architecture, pricing, notes) are confidential: only organisations that"
    " accept an NDA see them. The submission blocks hold the developer's text. Suggest one clearer teaser: a title of"
    " at most 120 characters and a summary of at most 150 words saying what the project does and for whom, never how"
    " it works. Use only facts from the Tier 1 fields. Never copy Tier 2 details into the teaser, and never include"
    " contact details, links, phone numbers or payment numbers. If the teaser is already clear or there is too little"
    " to work with, set has_suggestion to false and leave title and summary empty. In placement, list at most one"
    " entry per field that might belong in the other tier: to_tier2 for a Tier 1 field that reveals how the project"
    " works, its pricing or other confidential detail; to_tier1 for a Tier 2 field that only says what the project"
    " does and would help organisations find it. Give a one-sentence reason without quoting Tier 2 text. Leave"
    " placement empty when every field fits its tier."
)


# --- the proposal ------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Owned:
    proposal_id: UUID
    owner_id: UUID
    version_id: UUID  # the draft version when there is one, else the current version


@dataclass(frozen=True, slots=True)
class DraftText:
    """The saved text the assistant reads: non-empty Tier-1 and Tier-2 text fields only."""

    owned: Owned
    tier1: Mapping[str, str]
    tier2: Mapping[str, str]

    def __repr__(self) -> str:  # never print the text (Tier 2)
        return f"DraftText(version={self.owned.version_id}, tier1={sorted(self.tier1)}, tier2={sorted(self.tier2)})"


_OWN = text(
    "SELECT id, status, current_version_id, draft_version_id FROM proposals WHERE id = :id AND owner_id = :user"
)
_TEASER = text("SELECT title, problem_statement, impact_claims, summary FROM proposal_versions WHERE id = :version")


async def owned(db: AsyncSession, user_id: UUID, proposal_id: UUID) -> Owned:
    """The caller's draft or published proposal; 404 for anyone else's (or none), 409 once it was deleted."""
    row = (await db.execute(_OWN, {"id": proposal_id, "user": user_id})).one_or_none()
    if row is None:
        raise not_found("No proposal of yours has this id.")
    if ProposalStatus(row.status) not in (ProposalStatus.DRAFT, ProposalStatus.PUBLISHED):
        raise ApiError(409, "proposal_hidden", "This proposal was deleted; its record is kept but it cannot change.")
    version_id = row.draft_version_id or row.current_version_id
    if version_id is None:  # a proposal always has one of them; fail closed if not
        raise not_found("No proposal of yours has this id.")
    return Owned(row.id, user_id, version_id)


async def require_consent(checker: ConsentChecker, owner_id: UUID, *, session_id: UUID) -> None:
    """403 ``consent_required`` unless this login session holds the owner's live per-session opt-in."""
    if not await checker.has_live_consent(owner_id, PURPOSE, session_id=session_id):
        raise ApiError(403, "consent_required", CONSENT_REQUIRED)


async def load_text(db: AsyncSession, wrapper: KeyWrapper, own: Owned) -> DraftText:
    """The version's Tier-1 teaser fields and its Tier-2 text fields (as ``tier2_reader``; never links or files)."""
    row = (await db.execute(_TEASER, {"version": own.version_id})).one()
    tier1 = {name: str(value) for name in TIER1_FIELDS if (value := getattr(row, name))}
    document = await tier2.load(db, wrapper, own.proposal_id, own.version_id)
    body = document.body if document is not None else {}
    confidential = {name: value for name in TIER2_FIELDS if isinstance(value := body.get(name), str) and value.strip()}
    return DraftText(own, tier1, confidential)


def messages(draft: DraftText) -> list[Message]:
    """Trusted instructions around the owner's fields, each owned by the owner (D-37), Tier 2 tagged as such."""
    owner = draft.owned.owner_id
    parts: list[Part] = [Instruction("Tier 1 fields (the public teaser):")]
    parts += [InputField(f"teaser.{name}", value, owner_id=owner) for name, value in draft.tier1.items()]
    if draft.tier2:
        parts.append(Instruction("Tier 2 fields (confidential):"))
        parts += [
            InputField(f"confidential.{name}", value, tier=Tier.TIER2, owner_id=owner)
            for name, value in draft.tier2.items()
        ]
    parts.append(Instruction("Suggest a clearer teaser, and any field that might belong in the other tier."))
    return [Message.system(SYSTEM), Message.user(*parts)]


# --- the answer --------------------------------------------------------------------------------------------------


class SuggestionStatus(StrEnum):
    SUGGESTED = "suggested"
    NO_SUGGESTION = "no_suggestion"
    DEMO_FALLBACK = "demo_fallback"
    INJECTION_SUSPECTED = "injection_suspected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Hint:
    field: PlacementField
    move: Move
    reason: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    """What the route returns. ``reason`` is a code for the log and the audit event, never text."""

    status: SuggestionStatus
    reason: str
    message: str | None = None
    title: str | None = None
    summary: str | None = None
    placement: tuple[Hint, ...] = ()
    demo_fallback: bool = False
    trace_id: str | None = None


def _teaser(output: TeaserSuggestion, draft: DraftText) -> tuple[tuple[str, str] | None, str]:
    if not output.has_suggestion:
        return None, "none"
    cleaned, errors = sanitise({"title": output.title, "summary": output.summary})
    if errors:
        return None, f"rejected:{errors[0].code}"
    title, summary = cleaned["title"] or "", cleaned["summary"] or ""
    if not title or not summary:
        return None, "rejected:empty"
    if (title, summary) == (draft.tier1.get("title"), draft.tier1.get("summary")):
        return None, "unchanged"
    return (title, summary), "suggested"


def _placement(hints: Sequence[PlacementHint], draft: DraftText) -> tuple[Hint, ...]:
    kept: dict[PlacementField, Hint] = {}
    for hint in hints:
        in_tier1 = hint.field.value in TIER1_FIELDS
        wanted = Move.TO_TIER2 if in_tier1 else Move.TO_TIER1
        has_text = hint.field.value in (draft.tier1 if in_tier1 else draft.tier2)
        reason = plain_text(hint.reason)[:MAX_REASON_CHARS].strip()
        if (
            hint.field in kept
            or hint.move is not wanted
            or not has_text
            or not reason
            or contact_findings(detection_skeleton(reason))
        ):
            continue
        kept[hint.field] = Hint(hint.field, hint.move, reason)
    return tuple(kept.values())


def evaluate(result: Result[TeaserSuggestion], draft: DraftText) -> Suggestion:
    """What the owner is shown: the model's output only when code accepts it."""
    trace = result.trace_id
    if result.demo_fallback:
        return Suggestion(
            SuggestionStatus.DEMO_FALLBACK,
            f"demo_fallback:{result.fallback_reason}",
            DEMO_FALLBACK,
            demo_fallback=True,
            trace_id=trace,
        )
    output = result.parsed
    if output.injection_suspected:
        return Suggestion(SuggestionStatus.INJECTION_SUSPECTED, "injection_suspected", INJECTION, trace_id=trace)
    teaser, why = _teaser(output, draft)
    hints = _placement(output.placement, draft)
    if teaser is None and not hints:
        return Suggestion(SuggestionStatus.NO_SUGGESTION, why, NO_SUGGESTION, trace_id=trace)
    title, summary = teaser if teaser is not None else (None, None)
    return Suggestion(SuggestionStatus.SUGGESTED, why, None, title, summary, hints, trace_id=trace)


def refusal(exc: LLMError) -> ApiError | None:
    """The fixed answer to a refused call, or None when the call simply produced nothing (a provider that is down,
    unavailable or failing). Never the error's own text: a budget error carries the platform's spend and cap."""
    if isinstance(exc, ConsentRequired):
        return ApiError(403, "consent_required", CONSENT_REQUIRED)
    if isinstance(exc, Tier2DemoOnly | NotDemoData):
        return ApiError(403, "assistant_demo_only", DEMO_ONLY)
    if isinstance(exc, LLMKillSwitch):
        return ApiError(503, "assistant_off", SWITCHED_OFF)
    if isinstance(exc, LLMBudgetExceeded):
        if exc.scope == "tenant":
            return ApiError(429, "assistant_budget", BUDGET_TENANT)
        return ApiError(503, "assistant_paused", PAUSED)  # global or total: never the platform's figures
    if isinstance(exc, LLMRequestCapReached):
        return ApiError(503, "assistant_paused", PAUSED)
    return None


async def suggest(client: LLMClient, draft: DraftText, *, session_id: UUID) -> Suggestion:
    """One call (no retries beyond the layer's own), evaluated by code. The consent was checked by the caller."""
    if "title" not in draft.tier1 and "summary" not in draft.tier1:
        return Suggestion(SuggestionStatus.NO_SUGGESTION, "no_text", NO_TEXT)
    ctx = CallContext(user_id=draft.owned.owner_id, session_id=session_id, trace_id=uuid7().hex)
    try:
        result = await client.complete(TASK, messages(draft), TeaserSuggestion, ctx=ctx)
    except (LLMConfigError, LLMBatchNotOwned):
        raise  # a code mistake, not the provider's
    except LLMError as exc:
        if isinstance(exc, Tier2NotAllowed) and not isinstance(exc, Tier2DemoOnly):
            raise  # the task's purpose covers Tier 2: this is a registry mistake
        error = refusal(exc)
        log.info(
            "proposals.assistant", status="refused" if error else "unavailable", code=exc.code, trace_id=ctx.trace_id
        )
        if error is not None:
            raise error from None
        return Suggestion(SuggestionStatus.UNAVAILABLE, f"llm_error:{exc.code}", UNAVAILABLE, trace_id=ctx.trace_id)
    suggestion = evaluate(result, draft)
    log.info("proposals.assistant", status=suggestion.status.value, reason=suggestion.reason, trace_id=ctx.trace_id)
    return suggestion
