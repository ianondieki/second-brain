"""The teaser over-disclosure check (REQ-PROP-02; docs/spec/06 6.1: warn only; docs/spec/09: Haiku, sync).

The teaser is public to every signed-in user before any NDA, so it should say what the project does, never how it
works. Warn only: nothing here blocks saving or publishing.

1. **Rules first** (``precheck``, plain code): words that give the method away ("algorithm", "architecture", "we
   use"), named libraries, frameworks and stores, and code (fences, backticks, calls) in any of the four Tier-1 fields.
   A hit answers at once with a fixed warning and no model call, so the fake provider still gives a useful demo answer.
2. **Then the model** (``over_disclosure_check`` in ``ai/models.yaml``: Tier 1 only, no tools): the saved teaser's
   four fields, each an ``InputField`` owned by the owner (D-37). The LLM layer refuses any Tier-2 field for this task,
   sanitises and frames the fields, checks the caps first and records the call; on a free provider only a demo
   account's text goes out, anything else gets the labelled demo fallback.
3. **Code decides** (``evaluate``): a demo fallback and ``injection_suspected`` warn of nothing (labelled); a flag
   counts only for fields that have text; the model's reason is kept as plain text within the assistant's
   ``max_reason_chars`` and without contact details, else the fixed warning stands in.

Refused calls map to the assistant's fixed answers (``assistant.refusal``); a provider that is down answers "could not
check". Calls count against the assistant's daily limit (``policy.yaml`` ``assistant.max_calls_per_user_day``, this
task's ``llm_calls`` rows, counted under the teaser checks' per-user lock). No per-session opt-in: only Tier-1 text
is sent (docs/spec/09 ground rules).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.errors import ApiError
from bridge.ids import uuid7
from bridge.llm.client import LLMClient
from bridge.llm.errors import ConsentRequired, LLMBatchNotOwned, LLMConfigError, LLMError, Tier2NotAllowed
from bridge.llm.types import CallContext, InputField, Instruction, LLMOutput, Message, Part, Result
from bridge.logging import get_logger
from bridge.proposals import assistant, originality
from bridge.proposals.assistant_policy import AssistantPolicy
from bridge.proposals.sanitise import TIER1_FIELDS, contact_findings, detection_skeleton, plain_text

TASK: Final = "over_disclosure_check"

# [[COPY-REVIEW]] shown to the owner.
RULES_WHY: Final = (
    "This reads like how it works, not what it does. Move methods, tools and code to the confidential part, which"
    " organisations see only after accepting the NDA."
)
CLEAR: Final = "Nothing in this teaser reads like how it works."
NO_TEXT: Final = "Write the teaser first, then check it."
DEMO_FALLBACK: Final = "Demo fallback: no model checked this teaser, and the quick check found nothing."
INJECTION: Final = "Part of this teaser reads like instructions to the checker, so it could not check it."
UNAVAILABLE: Final = "The teaser check could not finish just now. Try again later."
RATE_LIMITED: Final = "You have run many teaser checks today. Try again tomorrow."
BUSY: Final = "The teaser check is still running. Try again in a moment."

log = get_logger(__name__)


class TeaserField(StrEnum):
    TITLE = "title"
    PROBLEM_STATEMENT = "problem_statement"
    IMPACT_CLAIMS = "impact_claims"
    SUMMARY = "summary"


class DisclosureSource(StrEnum):
    RULES = "rules"  # the deterministic pre-check
    MODEL = "model"  # the over_disclosure_check task
    NONE = "none"  # no answer: no text, a fallback, a suspected injection or a provider that is down


class DisclosureVerdict(LLMOutput):
    """The model's answer."""

    flagged: bool = Field(description="True when any field reveals how the project works.")
    fields: list[TeaserField] = Field(description="The fields that reveal how it works; empty when not flagged.")
    why: str = Field(description="One plain sentence (at most 30 words) without quoting the teaser, or empty.")

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, flagged=False, fields=[], why="")


SYSTEM: Final = (
    "You check the public teaser of a project proposal on a platform where developers pitch projects to"
    " organisations. Every signed-in user sees the teaser before any NDA, so it should say what the project does and"
    " for whom, never how it works. The submission blocks hold the teaser's fields. Set flagged to true when any field"
    " reveals how the project works: algorithms, models, architecture, data pipelines, libraries, frameworks,"
    " hardware designs, code or other implementation detail, and list those fields in fields. In why, give one plain"
    " sentence of at most 30 words saying what kind of detail to move to the confidential part, without quoting the"
    " teaser. If nothing reveals how it works, set flagged to false, fields to an empty list and why to an empty"
    " string."
)

_TERMS: Final = (
    r"algorithms?",
    r"architecture",
    r"we use",
    r"we(?:'re| are) using",
    r"our (?:model|stack|pipeline)",
    r"source code",
    r"gradient[- ]boost(?:ed|ing)",
    r"neural networks?",
    r"random forests?",
    r"deep learning",
    r"machine[- ]learning models?",
    r"tensorflow",
    r"pytorch",
    r"keras",
    r"scikit[- ]learn",
    r"sklearn",
    r"xgboost",
    r"lightgbm",
    r"django",
    r"flask",
    r"fastapi",
    r"node\.js",
    r"kubernetes",
    r"docker",
    r"postgres(?:ql)?",
    r"mysql",
    r"mongodb",
    r"redis",
    r"kafka",
    r"lorawan",
    r"mqtt",
    r"microservices?",
    r"api endpoints?",
)
_HOW: Final = re.compile(r"\b(?:" + "|".join(_TERMS) + r")\b", re.IGNORECASE)
_CODE: Final = re.compile(r"```|`[^`\n]+`|\b\w+\(\)|=>|\bimport \w+|\bdef \w+\(")


def present(fields: Mapping[str, object]) -> dict[str, str]:
    """The four Tier-1 fields that have text; any other key (a Tier-2 field) is dropped."""
    return {name: value for name in TIER1_FIELDS if isinstance(value := fields.get(name), str) and value.strip()}


def precheck(fields: Mapping[str, str]) -> tuple[TeaserField, ...]:
    """The Tier-1 fields whose text plainly gives the method away (plain code; no model)."""
    return tuple(
        TeaserField(name)
        for name in TIER1_FIELDS
        if (value := fields.get(name)) and (_HOW.search(value) or _CODE.search(value))
    )


@dataclass(frozen=True, slots=True)
class Disclosure:
    flagged: bool
    fields: tuple[TeaserField, ...]
    why: str | None
    source: DisclosureSource
    reason: str  # a code for the log, never text
    demo_fallback: bool = False
    ai_drafted: bool = False


def by_rules(hits: tuple[TeaserField, ...]) -> Disclosure:
    return Disclosure(True, hits, RULES_WHY, DisclosureSource.RULES, "rules")


NOTHING_TO_CHECK: Final = Disclosure(False, (), NO_TEXT, DisclosureSource.NONE, "no_text")


def messages(owner_id: UUID, fields: Mapping[str, str]) -> list[Message]:
    parts: list[Part] = [Instruction("The teaser's fields:")]
    parts += [InputField(f"teaser.{name}", value, owner_id=owner_id) for name, value in present(fields).items()]
    parts.append(Instruction("Does any field reveal how the project works?"))
    return [Message.system(SYSTEM), Message.user(*parts)]


def evaluate(result: Result[DisclosureVerdict], fields: Mapping[str, str], policy: AssistantPolicy) -> Disclosure:
    """What the owner is shown: the model's flag only for fields with text, its reason only when code accepts it."""
    if result.demo_fallback:
        return Disclosure(
            False, (), DEMO_FALLBACK, DisclosureSource.NONE, f"demo_fallback:{result.fallback_reason}", True
        )
    output = result.parsed
    if output.injection_suspected:
        return Disclosure(False, (), INJECTION, DisclosureSource.NONE, "injection_suspected")
    kept = tuple(field for field in dict.fromkeys(output.fields) if field.value in present(fields))
    if not output.flagged or not kept:
        return Disclosure(False, (), CLEAR, DisclosureSource.MODEL, "clear")
    why = plain_text(output.why)[: policy.max_reason_chars].strip()
    if not why or contact_findings(detection_skeleton(why)):
        return Disclosure(True, kept, RULES_WHY, DisclosureSource.MODEL, "flagged:fixed_reason")
    return Disclosure(True, kept, why, DisclosureSource.MODEL, "flagged", ai_drafted=True)


async def check_daily_limit(db: AsyncSession, user_id: UUID, policy: AssistantPolicy) -> None:
    """429 ``disclosure_rate_limited`` once today's ``over_disclosure_check`` ledger rows reach the assistant's
    daily limit (every status counts; the rules and the demo fallback write no row). Takes the teaser checks'
    per-user lock (``originality.lock_teaser_checks``); the caller keeps its transaction open through the model call,
    whose ledger row is written on its own connection, so a second process waits and then counts that row: with one
    call left, only one passes."""
    await originality.lock_teaser_checks(db, user_id)
    if await assistant.calls_today(db, user_id, TASK) >= policy.max_calls_per_user_day:
        raise ApiError(429, "disclosure_rate_limited", RATE_LIMITED)


async def ask_model(
    llm: LLMClient, owner_id: UUID, fields: Mapping[str, str], *, session_id: UUID | None, policy: AssistantPolicy
) -> Disclosure:
    """One call of the Tier-1-only task, evaluated by code. Refusals raise the assistant's fixed answers."""
    ctx = CallContext(user_id=owner_id, session_id=session_id, trace_id=uuid7().hex)
    try:
        result = await llm.complete(TASK, messages(owner_id, fields), DisclosureVerdict, ctx=ctx)
    except (LLMConfigError, LLMBatchNotOwned, Tier2NotAllowed, ConsentRequired):
        raise  # a code mistake: this task never carries Tier 2
    except LLMError as exc:
        error = assistant.refusal(exc)
        log.info("proposals.disclosure", status="refused" if error else "unavailable", code=exc.code)
        if error is not None:
            raise error from None
        return Disclosure(False, (), UNAVAILABLE, DisclosureSource.NONE, f"llm_error:{exc.code}")
    answer = evaluate(result, fields, policy)
    log.info("proposals.disclosure", status=answer.reason, trace_id=result.trace_id)
    return answer
