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
- ``injection_suspected`` or ``rejected:<check>``: the reply flags an injection, or fails ``check_wording``: not one
  plain line within its length, a link or contact detail, a number, month, weekday, relative day, name or status the
  facts do not hold, a percentage, or a next step that lost the suggested step's numbers.

A caller's mistake (``LLMConfigError``) is a bug and propagates.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final, Self

from pydantic import Field

from bridge.llm.client import LLMClient
from bridge.llm.demo_fallback import DEMO_TEXT
from bridge.llm.errors import LLMConfigError, LLMError
from bridge.llm.types import CallContext, InputField, Instruction, LLMOutput, Message
from bridge.logging import get_logger
from bridge.proposals.sanitise import contact_findings
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
_NUMBER = re.compile(r"\d+")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_NUMBER_WORDS: Final = {
    word: str(n)
    for n, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
        ]
    )
}
_MONTHS: Final = {
    **{
        m: n
        for n, m in enumerate(
            ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
        )
    },
    **{
        m: n
        for n, m in enumerate(
            [
                "january",
                "february",
                "march",
                "april",
                "may",
                "june",
                "july",
                "august",
                "september",
                "october",
                "november",
                "december",
            ],
            start=1,
        )
    },
    "sept": 9,
}
_BANNED_WORDS: Final = frozenset(
    [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "tomorrow",
        "yesterday",
        "tonight",
        "weekend",
        "percent",
    ]
)
_STATUSES: Final = ("on track", "at risk", "off track", "overdue", "late", "behind")
_MARKUP: Final = re.compile(r"https?:|www\.|@|\]\(|[<>`*#|]|\[")
_ALLOWED_NAMES: Final = frozenset({"I", "NDA"})


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


def _line_problem(field: str, text: str, limit: int) -> str | None:
    if not text or len(text) > limit:
        return f"{field}_length"
    if any(unicodedata.category(ch)[0] == "C" for ch in text):
        return f"{field}_not_one_line"
    if _MARKUP.search(text) or contact_findings(text):
        return f"{field}_link_or_contact"
    return None


def _months(text: str) -> set[int]:
    return {_MONTHS[w.lower()] for w in _WORD.findall(text) if w.lower() in _MONTHS}


def _names(text: str) -> set[str]:
    """Capitalised words that do not start a sentence (names, places, organisations)."""
    found: set[str] = set()
    for sentence in re.split(r"(?<=[.!?:;])\s+", text):
        words = _WORD.findall(sentence)
        found |= {w for w in words[1:] if w[:1].isupper() and w not in _ALLOWED_NAMES}
    return found


def check_wording(output: NudgeWording, nudge: Nudge) -> str | None:
    """Why the model's lines cannot be used (see the module docstring), or None when they can."""
    if output.injection_suspected:
        return "injection_suspected"
    headline, step = output.headline.strip(), output.next_step.strip()
    problem = _line_problem("headline", headline, MAX_HEADLINE_CHARS) or _line_problem(
        "next_step", step, MAX_NEXT_STEP_CHARS
    )
    if problem:
        return problem
    facts = "\n".join(nudge.fact_lines)
    written = f"{headline} {step}"
    lower = written.lower()
    numbers = set(_NUMBER.findall(facts))
    words = [w.lower() for w in _WORD.findall(written)]
    if "%" in written or any(w in _BANNED_WORDS for w in words):
        return "invented_day_or_percentage"
    if not set(_NUMBER.findall(written)) <= numbers or any(
        _NUMBER_WORDS[w] not in numbers for w in words if w in _NUMBER_WORDS
    ):
        return "invented_number"
    if not _months(written) <= _months(facts):
        return "invented_date"
    if any(re.search(rf"\b{status}\b", lower) and status not in facts.lower() for status in _STATUSES):
        return "invented_status"
    if not _names(written) <= set(_WORD.findall(facts)):
        return "invented_name"
    if not set(_NUMBER.findall(nudge.next_step)) <= set(_NUMBER.findall(step)):
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
