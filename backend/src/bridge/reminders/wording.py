"""The LLM's part of the developer's EM7: two lines worded from code-computed facts (REQ-REM-01; docs/spec/09).

Task ``reminder_nudge`` (``ai/models.yaml``: Haiku 4.5 on Anthropic, free slots on local runs, D-37) rewords
``Nudge.fact_lines`` into a first line (``headline``) and the featured next step. It sees counts, codes, dates,
milestone numbers and the developer's own proposal titles, as one Tier-1 field owned by the developer (so the D-37
rule sends a non-demo account's facts to no free provider), sanitised and nonce-framed by the LLM layer; it has no
tools. Every fact in the email is rendered by code (``bridge.reminders.nudge``); the model decides nothing.

The fixed fallback text (``nudge.fallback_wording``) answers whenever the model's words cannot be used, and the
reason is kept (``Wording.reason``, logged ``reminders.nudge_worded``):

- ``not_eligible``: no client (the dispatcher words without an LLM);
- ``demo_fallback:<reason>``: the router's placeholder (fake provider, no slot, not demo data, a cap, the kill switch,
  a failed call; ``bridge.llm.demo_fallback``): a placeholder is never a wording;
- ``llm_error:<code>``: a typed LLM error (staging and production raise instead of falling back);
- ``injection_suspected`` or ``rejected:<check>``: the reply flags an injection, or fails ``check_wording``: each line
  is one line of plain text within its length (any whitespace but a space, any control or invisible character, a
  link, a contact detail or a symbol is refused), then grounded word by word in the facts
  (``bridge.reminders.grounding``: an allowlist of neutral words plus the facts' words, with counts, milestones and
  dates matched as whole units), and the next step keeps the suggested step's title, dates and numbers.

A caller's mistake (``LLMConfigError``) is a bug and propagates.
"""

from __future__ import annotations

import unicodedata
from typing import Final, Self

from pydantic import Field

from bridge.llm.client import LLMClient
from bridge.llm.demo_fallback import DEMO_TEXT
from bridge.llm.errors import LLMConfigError, LLMError
from bridge.llm.types import CallContext, InputField, Instruction, LLMOutput, Message
from bridge.logging import get_logger
from bridge.proposals.sanitise import contact_findings
from bridge.reminders.grounding import Grounding
from bridge.reminders.nudge import Nudge, Wording, fallback_wording

TASK: Final = "reminder_nudge"
MAX_HEADLINE_CHARS: Final = 160
MAX_NEXT_STEP_CHARS: Final = 240
MAX_FACTS_CHARS: Final = 2000

SYSTEM: Final = (
    "You word two lines of a developer's daily progress email on a platform where developers pitch projects to"
    " organisations. The submission block lists facts that code computed. Reply with: headline, one short, friendly"
    f" sentence of at most {MAX_HEADLINE_CHARS} characters that sums up the day from those facts; and next_step, the"
    f" suggested next step reworded as one clear instruction of at most {MAX_NEXT_STEP_CHARS} characters that keeps"
    " its milestone numbers, proposal titles and dates exactly. Use only the facts given: never add a fact, number,"
    " date, weekday, name, amount, link, deadline, status or promise that is not in them, and never give a percentage."
    " Write plain text: no markdown, no links, no emoji, no greeting by name."
)


class NudgeWording(LLMOutput):
    """The model's two lines. ``demo_fallback`` is the router's placeholder on local runs: never used as wording."""

    headline: str = Field(description="One short, friendly sentence summing up the day from the facts only.")
    next_step: str = Field(description="The suggested next step reworded as one instruction; same numbers and dates.")

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, headline=DEMO_TEXT, next_step=DEMO_TEXT)


def messages(nudge: Nudge) -> list[Message]:
    facts = "\n".join(nudge.fact_lines)
    return [
        Message.system(SYSTEM),
        Message.user(
            Instruction("Today's facts:"),
            InputField("reminder.facts", facts, owner_id=nudge.user_id, max_chars=MAX_FACTS_CHARS),
        ),
    ]


def _line_problem(field: str, text: str, limit: int, grounding: Grounding) -> str | None:
    if not text or len(text) > limit:
        return f"{field}_length"
    if any(unicodedata.category(ch)[0] == "C" or (ch.isspace() and ch != " ") for ch in text):
        return f"{field}_not_one_line"
    if contact_findings(text):
        return f"{field}_link_or_contact"
    if grounding.symbol(text):
        return f"{field}_symbol"
    return None


def check_wording(output: NudgeWording, nudge: Nudge) -> str | None:
    """Why the model's lines cannot be used (see the module docstring), or None when they can."""
    if output.injection_suspected:
        return "injection_suspected"
    grounding = Grounding.of("\n".join(nudge.fact_lines))
    headline, step = output.headline.strip(), output.next_step.strip()
    for field, text, limit in (("headline", headline, MAX_HEADLINE_CHARS), ("next_step", step, MAX_NEXT_STEP_CHARS)):
        problem = _line_problem(field, text, limit, grounding) or grounding.problem(text)
        if problem is not None:
            return problem
    if not grounding.covers(nudge.next_step, step):
        return "next_step_changed"
    return None


async def word_nudge(client: LLMClient | None, nudge: Nudge, *, ctx: CallContext) -> Wording:
    """The email's two lines: the model's when usable, else the fixed fallback with its reason."""
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
    return Wording(result.parsed.headline.strip(), result.parsed.next_step.strip(), "model")
