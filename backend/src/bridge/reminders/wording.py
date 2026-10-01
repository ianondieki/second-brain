"""The LLM's part of the developer's EM7: a choice among code-rendered variants (REQ-REM-01; docs/spec/09).

Prototype deviation (orchestrator ruling after the P6 re-review): to guarantee docs/spec/09's 100% factual
consistency, the model writes no text. Task ``reminder_nudge`` (``ai/models.yaml``: Haiku 4.5 on Anthropic, free
slots on local runs, D-37) reads ``Nudge.fact_lines`` (today's date, item ids with code briefs, the next step: counts,
codes, dates, milestone numbers and the developer's own titles, as one Tier-1 field owned by the developer, so the
D-37 rule sends a non-demo account's facts to no free provider; sanitised and nonce-framed by the LLM layer; no tools)
and returns ``NudgeWording``:

- ``opening``: one of ``OPENINGS``, short neutral phrases with no facts, names or verbs about the parties;
- ``order``: item ids, most urgent first; every "needs you" item must be listed, no id twice, no unknown id;
- ``next_step_variant``: one of ``NEXT_STEP_VARIANTS``, fixed phrasings around the code-rendered next step.

Code validates the choice (``check_wording``) and renders every word (``choose``): the headline is the opening
followed by the code's own summary line, the next step its variant around the code's step, and each section of the
email lists its items in the chosen order (items not named keep the code order after them; nothing is dropped). Free
wording returns with the REQ-EVAL-01 progress-reporter eval set.

The fixed text (``nudge.fallback_wording``) answers whenever the model's choice cannot be used, and the reason is kept
(``Wording.reason``, logged ``reminders.nudge_worded``): ``not_eligible`` (no client), ``demo_fallback:<reason>`` (the
router's placeholder: never a choice), ``llm_error:<code>`` (a typed LLM error, including an answer outside the
schema), ``injection_suspected``, or ``rejected:<check>`` (``missing_item``, ``unknown_item``, ``duplicate_item``).
A caller's mistake (``LLMConfigError``) is a bug and propagates.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Self

from pydantic import Field

from bridge.llm.client import LLMClient
from bridge.llm.errors import LLMConfigError, LLMError
from bridge.llm.types import CallContext, InputField, Instruction, LLMOutput, Message
from bridge.logging import get_logger
from bridge.reminders.nudge import Nudge, Wording, fallback_wording

TASK: Final = "reminder_nudge"
MAX_FACTS_CHARS: Final = 4000


class Opening(StrEnum):
    YOUR_DAY = "your_day"
    QUICK_LOOK = "quick_look"
    UPDATE_READY = "update_ready"
    ON_YOUR_LIST = "on_your_list"
    STEP_BY_STEP = "step_by_step"


class NextStepVariant(StrEnum):
    PLAIN = "plain"
    START_WITH = "start_with"
    WHEN_READY = "when_ready"
    FOCUS = "focus"


# [[COPY-REVIEW]] fixed phrases: no fact, no name, no verb about either party, no time of day.
OPENINGS: Final[dict[Opening, str]] = {
    Opening.YOUR_DAY: "Here is your day on Wazo.",
    Opening.QUICK_LOOK: "A quick look at your engagements.",
    Opening.UPDATE_READY: "Your daily update is ready.",
    Opening.ON_YOUR_LIST: "Here is what is on your list.",
    Opening.STEP_BY_STEP: "One step at a time: here is your list.",
}
NEXT_STEP_VARIANTS: Final[dict[NextStepVariant, str]] = {
    NextStepVariant.PLAIN: "{step}",
    NextStepVariant.START_WITH: "Start with this: {step}",
    NextStepVariant.WHEN_READY: "When you have a moment: {step}",
    NextStepVariant.FOCUS: "Your focus for today: {step}",
}

SYSTEM: Final = (
    "You arrange a developer's daily progress email on a platform where developers pitch projects to organisations."
    " Code writes every sentence of the email; you only choose among fixed options, by id. The submission block lists"
    " today's date, the email's items (an id and a short description each: ids starting n need the developer, w wait"
    " on the other party, h give an engagement's health, d are unpublished drafts) and the suggested next step."
    " Reply with: opening, the id of one opening ("
    + "; ".join(f"{o.value}: {text}" for o, text in OPENINGS.items())
    + "); order, the ids of the items from most to least urgent, listing every item whose id starts with n and no id"
    " twice (you may leave out other items); and next_step_variant, the id of one phrasing of the suggested next step ("
    + "; ".join(f"{v.value}: {text.format(step='<the step>')}" for v, text in NEXT_STEP_VARIANTS.items())
    + "). Use only ids from this message."
)


class NudgeWording(LLMOutput):
    """The model's choice: ids only, no free text. ``demo_fallback`` is the router's placeholder (the fixed default
    choices, flagged): never used."""

    opening: Opening = Field(description="The id of one opening.")
    order: list[str] = Field(description="Item ids, most urgent first; every id starting with n; no id twice.")
    next_step_variant: NextStepVariant = Field(description="The id of one phrasing of the suggested next step.")

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(
            injection_suspected=True, opening=Opening.YOUR_DAY, order=[], next_step_variant=NextStepVariant.PLAIN
        )


def messages(nudge: Nudge) -> list[Message]:
    facts = "\n".join(nudge.fact_lines)
    return [
        Message.system(SYSTEM),
        Message.user(
            Instruction("Today's email:"),
            InputField("reminder.facts", facts, owner_id=nudge.user_id, max_chars=MAX_FACTS_CHARS),
        ),
    ]


def check_wording(output: NudgeWording, nudge: Nudge) -> str | None:
    """Why the model's choice cannot be used, or None when it can. The enums are the schema's (a value outside them
    never parses); the order must name known items, each once, every "needs you" item among them."""
    if output.injection_suspected:
        return "injection_suspected"
    known = set(nudge.item_ids)
    if len(set(output.order)) != len(output.order):
        return "duplicate_item"
    if not set(output.order) <= known:
        return "unknown_item"
    if not set(nudge.needs_ids) <= set(output.order):
        return "missing_item"
    return None


def choose(nudge: Nudge, output: NudgeWording) -> Wording:
    """The email's wording from a valid choice: every word is code's (``OPENINGS``, the summary line, the variant
    around the next step)."""
    return Wording(
        headline=f"{OPENINGS[output.opening]} {nudge.fallback_headline}",
        next_step=NEXT_STEP_VARIANTS[output.next_step_variant].format(step=nudge.next_step),
        source="model",
        order=tuple(output.order),
    )


async def word_nudge(client: LLMClient | None, nudge: Nudge, *, ctx: CallContext) -> Wording:
    """The email's wording: the model's choice rendered by code when usable, else the fixed text with its reason."""
    log = get_logger(__name__)
    wording = await _word(client, nudge, ctx)
    log.info("reminders.nudge_worded", source=wording.source, reason=wording.reason, trace_id=ctx.trace_id)
    return wording


async def _word(client: LLMClient | None, nudge: Nudge, ctx: CallContext) -> Wording:
    if client is None:
        return fallback_wording(nudge, "not_eligible")
    try:
        result = await client.complete(TASK, messages(nudge), NudgeWording, ctx=ctx)
    except LLMConfigError:
        raise
    except LLMError as exc:
        return fallback_wording(nudge, f"llm_error:{exc.code}")
    if result.demo_fallback:
        return fallback_wording(nudge, f"demo_fallback:{result.fallback_reason}")
    problem = check_wording(result.parsed, nudge)
    if problem is not None:
        return fallback_wording(nudge, problem if problem == "injection_suspected" else f"rejected:{problem}")
    return choose(nudge, result.parsed)
