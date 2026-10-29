"""The originality check's answer and its optional explainer sentence (REQ-PROP-04; docs/spec/09).

``run`` is the check a route performs: ``originality.assess`` (plain code: the band and the pool's size), then, only
when the band is not ``none``, one call of the ``originality_explainer`` task (``ai/models.yaml``: Tier 1 only, no
tools). The model sees the submitter's Tier-1 teaser fields and the matched teasers' Tier-1 fields, each an
``InputField`` owned by its author: the LLM layer refuses any Tier-2 field for this task (``guard.check_tier2``),
sanitises and frames every field, checks the caps first and records the call in ``llm_calls``; on a free provider the
D-37 rule sends only demo accounts' text and anything else gets the labelled demo fallback.

Code decides what is shown (``accept``): one plain sentence of at most ``explanation_max_chars``, with no digit (no
score, share or count can slip through), no contact details, and no run of ``SHINGLE_WORDS`` words copied from any
matched teaser. Anything else, a demo fallback, ``injection_suspected`` or a failed call is "no sentence"; the band
stands on its own. The response (``OriginalityOut``) has no field that could carry a score, an id or another owner's
text beyond that one checked sentence.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Self
from uuid import UUID

from pydantic import Field

from bridge.ids import uuid7
from bridge.llm.client import LLMClient
from bridge.llm.demo_fallback import DemoFallbackFlag
from bridge.llm.embeddings import Embedder
from bridge.llm.errors import ConsentRequired, LLMBatchNotOwned, LLMConfigError, LLMError, Tier2NotAllowed
from bridge.llm.types import CallContext, InputField, Instruction, LLMOutput, Message, Part
from bridge.logging import get_logger
from bridge.models.enums import OriginalityBand
from bridge.proposals.originality import SHINGLE_WORDS, Assessment, PublishedTeaser, TeaserPool, assess, words
from bridge.proposals.originality_policy import OriginalityPolicy
from bridge.proposals.sanitise import TIER1_FIELDS, contact_findings, detection_skeleton, plain_text

TASK: Final = "originality_explainer"
_DIGIT: Final = re.compile(r"\d")

log = get_logger(__name__)


class OverlapExplanation(LLMOutput):
    """The model's answer: one sentence, or empty."""

    sentence: str = Field(description="One plain sentence for the developer (at most 40 words), or empty.")

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, sentence="")


SYSTEM: Final = (
    "You help a developer on a platform where developers publish short public teasers of their projects. Code has"
    " found that the developer's draft teaser overlaps with teasers other developers have already published. The"
    " first submission blocks hold the draft; the others hold the published teasers that overlap. Write one plain"
    " sentence of at most 40 words telling the developer, in general terms, what the overlap is about (the problem,"
    " the people served or the setting), so they can make their teaser more distinctive. Never quote or closely"
    " paraphrase the published teasers, never say who wrote them or how many there are, never give a number,"
    " percentage or score, and never include contact details or links. If there is nothing useful to say, leave"
    " sentence empty."
)


def messages(owner_id: UUID, fields: Mapping[str, object], matches: Iterable[PublishedTeaser]) -> list[Message]:
    """Trusted instructions around Tier-1 fields only, each owned by its author (D-37)."""
    parts: list[Part] = [Instruction("The developer's draft teaser:")]
    parts += [
        InputField(f"draft.{name}", value, owner_id=owner_id)
        for name in TIER1_FIELDS
        if isinstance(value := fields.get(name), str) and value.strip()
    ]
    parts.append(Instruction("Published teasers by other developers that overlap with the draft:"))
    for number, teaser in enumerate(matches, start=1):
        parts += [
            InputField(f"published.{number}.{name}", value, owner_id=teaser.owner_id)
            for name in TIER1_FIELDS
            if (value := teaser.fields.get(name))
        ]
    parts.append(Instruction("Write the one sentence."))
    return [Message.system(SYSTEM), Message.user(*parts)]


def _runs(value: str) -> set[tuple[str, ...]]:
    found = words(value)
    return {tuple(found[i : i + SHINGLE_WORDS]) for i in range(len(found) - SHINGLE_WORDS + 1)}


def accept(sentence: str, matches: Iterable[PublishedTeaser], policy: OriginalityPolicy) -> tuple[str | None, str]:
    """The sentence to show and why, or None and the reason code."""
    cleaned = plain_text(sentence).strip()
    if not cleaned:
        return None, "empty"
    if len(cleaned) > policy.explanation_max_chars:
        return None, "rejected:too_long"
    if _DIGIT.search(cleaned):
        return None, "rejected:number"
    if contact_findings(detection_skeleton(cleaned)):
        return None, "rejected:contact"
    theirs: set[tuple[str, ...]] = set()
    for teaser in matches:
        for value in teaser.fields.values():
            theirs |= _runs(value)
    if _runs(cleaned) & theirs:
        return None, "rejected:copies_teaser"
    return cleaned, "explained"


@dataclass(frozen=True, slots=True)
class Explained:
    sentence: str | None
    demo_fallback: bool
    reason: str  # a code for the log and the audit event, never text
    trace_id: str | None = None


async def explain(
    llm: LLMClient,
    assessment: Assessment,
    fields: Mapping[str, object],
    *,
    owner_id: UUID,
    session_id: UUID | None,
    policy: OriginalityPolicy,
) -> Explained:
    """One call when there is an overlap to explain; never raises for the provider's sake."""
    if assessment.band is OriginalityBand.NONE or not assessment.matches:
        return Explained(None, False, "not_asked")
    ctx = CallContext(user_id=owner_id, session_id=session_id, trace_id=uuid7().hex)
    try:
        result = await llm.complete(TASK, messages(owner_id, fields, assessment.matches), OverlapExplanation, ctx=ctx)
    except (LLMConfigError, LLMBatchNotOwned, Tier2NotAllowed, ConsentRequired):
        raise  # a code mistake: this task never carries Tier 2
    except LLMError as exc:
        log.info("proposals.originality.explainer", status="unavailable", code=exc.code, trace_id=ctx.trace_id)
        return Explained(None, False, f"llm_error:{exc.code}", ctx.trace_id)
    if result.demo_fallback:
        return Explained(None, True, f"demo_fallback:{result.fallback_reason}", result.trace_id)
    if result.parsed.injection_suspected:
        return Explained(None, False, "injection_suspected", result.trace_id)
    sentence, reason = accept(result.parsed.sentence, assessment.matches, policy)
    log.info("proposals.originality.explainer", status=reason, trace_id=result.trace_id)
    return Explained(sentence, False, reason, result.trace_id)


class OriginalityOut(DemoFallbackFlag):
    band: OriginalityBand = Field(description="Coarse band only; never a score")
    compared: int = Field(description="How many other owners' published teasers were compared (never which)")
    explanation: str | None = Field(description="AI-drafted; one plain sentence, or null")
    ai_drafted: bool = Field(description="True when a model wrote the explanation (label it 'AI-drafted')")
    checked_at: datetime


async def run(
    pool: TeaserPool,
    embedder: Embedder,
    llm: LLMClient,
    fields: Mapping[str, object],
    *,
    owner_id: UUID,
    proposal_id: UUID,
    session_id: UUID | None,
    policy: OriginalityPolicy,
    checked_at: datetime,
    assessed: Callable[[Assessment], Awaitable[None]] | None = None,
) -> tuple[OriginalityOut, Explained]:
    """The check; ``assessed`` runs between the band and the model call (the route records and commits there)."""
    assessment = await assess(pool, embedder, fields, owner_id=owner_id, proposal_id=proposal_id, policy=policy)
    if assessed is not None:
        await assessed(assessment)
    explained = await explain(llm, assessment, fields, owner_id=owner_id, session_id=session_id, policy=policy)
    out = OriginalityOut(
        demo_fallback=explained.demo_fallback,
        band=assessment.band,
        compared=assessment.compared,
        explanation=explained.sentence,
        ai_drafted=explained.sentence is not None,
        checked_at=checked_at,
    )
    return out, explained
