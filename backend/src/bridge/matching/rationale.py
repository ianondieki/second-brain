"""The model's part of a scout match: "why this matches" and a bounded fit (REQ-SCOUT-02; docs/spec/09).

Task ``scout_fit_rationale`` (``ai/models.yaml``: Sonnet 5 on Anthropic, free slots on local runs, D-37) for the top
``limits.model_top_n`` matches of a run only; a proposal is matched once per scout, so each (scout, version) is asked
at most once (the match row is the cache). No tools. The input is Tier 1 and metadata only (D-43 (a)): the scout's
niche names and include keywords (the organisation's text, owned by the scout's creator) and the current version's
teaser (the developer's text, owned by the proposal's owner), each an ``InputField`` the LLM layer sanitises and
nonce-frames; the D-37 rule sends them to a free provider only when both owners are demo accounts.

Code decides; the model only words and scores within bounds (``ScoutFit``: ``fit`` 0-100, ``rationale`` at most 600
characters). The answer is used only when the model answered (not the router's ``demo_fallback()`` placeholder), did
not flag ``injection_suspected`` and passed the schema; then ``final = 0.4·fit + 0.6·deterministic``
(``pipeline.final_score``). Otherwise the match keeps its deterministic score and the code's "Matched on ..." line
(``pipeline.matched_on``), and the reason is kept (``Explanation.reason``). A caller's mistake (``LLMConfigError``)
is a bug and propagates. The model never selects, adds or removes a match: the rules did that already.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Final, Literal, Self
from uuid import UUID

from pydantic import Field

from bridge.llm.client import LLMClient
from bridge.llm.demo_fallback import DEMO_TEXT
from bridge.llm.errors import LLMConfigError, LLMError
from bridge.llm.types import CallContext, InputField, Instruction, LLMOutput, Message
from bridge.logging import get_logger
from bridge.matching.pipeline import Scored, matched_on

TASK: Final = "scout_fit_rationale"
MAX_RATIONALE: Final = 600  # agent_matches.rationale
MAX_PROFILE_CHARS: Final = 1500
MAX_TEASER_CHARS: Final = 3000
Source = Literal["model", "code"]

SYSTEM: Final = (
    "You help an organisation's scout on a platform where developers pitch projects to organisations. Code has"
    " already chosen this proposal for the scout by fixed rules; you do not decide whether it matches. The first"
    " submission block is the scout's profile (its niches and keywords); the second is the proposal's public teaser"
    " and metadata. Reply with fit, a whole number from 0 to 100 for how well the teaser fits the profile, and"
    " rationale, at most 80 words in plain English saying why it matches, using only facts written in the two"
    " blocks. Do not invent numbers, names, links or contact details, and do not address anyone."
)


class ScoutFit(LLMOutput):
    """The model's fit (0-100) and its "why this matches". ``demo_fallback`` is the router's placeholder: never used."""

    fit: int = Field(ge=0, le=100, description="How well the teaser fits the scout's profile, 0 to 100.")
    rationale: str = Field(
        min_length=1, max_length=MAX_RATIONALE, description="Why it matches, at most 80 words, from the blocks only."
    )

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, fit=0, rationale=DEMO_TEXT)


@dataclass(frozen=True, slots=True)
class Profile:
    """What the model may read about the scout: niche names and include keywords, owned by the scout's creator."""

    owner_id: UUID
    niche_labels: tuple[str, ...]
    include_keywords: tuple[str, ...]

    def text(self) -> str:
        lines = ["Niches: " + "; ".join(self.niche_labels)]
        if self.include_keywords:
            lines.append("Keywords: " + ", ".join(self.include_keywords))
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Explanation:
    """``text`` is the model's rationale (``source`` model) or the code's line; ``model_fit`` is None unless the
    model's answer was used; ``demo_fallback`` when the router answered with its placeholder; ``reason`` why the
    model's answer was not used (None when it was)."""

    text: str
    source: Source
    model_fit: int | None
    demo_fallback: bool
    injection_suspected: bool
    reason: str | None


def teaser_text(s: Scored) -> str:
    """The current version's Tier-1 teaser and metadata, as the model reads it."""
    c = s.candidate
    lines = [
        f"Title: {c.title or ''}",
        f"Niche: {c.niche_label or 'unknown'}",
        f"County: {c.county_name or c.county_code or 'not given'}",
        f"Maturity: {c.maturity.value if c.maturity else 'not given'}",
        f"Ask: {c.ask.value if c.ask else 'not given'}",
        f"Problem: {c.problem_statement or ''}",
        f"Summary: {c.summary or ''}",
        f"Impact claims: {c.impact_claims or ''}",
    ]
    return "\n".join(lines)


def messages(profile: Profile, s: Scored) -> list[Message]:
    return [
        Message.system(SYSTEM),
        Message.user(
            Instruction("The scout's profile:"),
            InputField("scout.profile", profile.text(), owner_id=profile.owner_id, max_chars=MAX_PROFILE_CHARS),
            Instruction("The proposal's public teaser:"),
            InputField("proposal.teaser", teaser_text(s), owner_id=s.candidate.owner_id, max_chars=MAX_TEASER_CHARS),
        ),
    ]


def clean(text: str) -> str:
    """The model's rationale on one line: NFKC, no control or invisible characters, at most 600 characters."""
    normalised = unicodedata.normalize("NFKC", text)
    kept = "".join(
        " " if ch.isspace() else ch for ch in normalised if unicodedata.category(ch)[0] != "C" or ch.isspace()
    )
    return " ".join(kept.split())[:MAX_RATIONALE]


def by_code(s: Scored, reason: str, *, demo_fallback: bool = False, injection: bool = False) -> Explanation:
    return Explanation(matched_on(s), "code", None, demo_fallback, injection, reason)


async def explain(client: LLMClient | None, profile: Profile, s: Scored, *, ctx: CallContext) -> Explanation:
    """The match's "why": the model's when usable, else the code's line with the reason."""
    explanation = await _explain(client, profile, s, ctx)
    get_logger(__name__).info(
        "scouts.rationale", source=explanation.source, reason=explanation.reason, trace_id=ctx.trace_id
    )
    return explanation


async def _explain(client: LLMClient | None, profile: Profile, s: Scored, ctx: CallContext) -> Explanation:
    if client is None:
        return by_code(s, "not_eligible")
    try:
        result = await client.complete(TASK, messages(profile, s), ScoutFit, ctx=ctx)
    except LLMConfigError:
        raise
    except LLMError as exc:
        return by_code(s, f"llm_error:{exc.code}")
    if result.demo_fallback:
        return by_code(s, f"demo_fallback:{result.fallback_reason}", demo_fallback=True)
    if result.parsed.injection_suspected:
        return by_code(s, "injection_suspected", injection=True)
    text = clean(result.parsed.rationale)
    if not text:
        return by_code(s, "rejected:empty")
    return Explanation(text, "model", result.parsed.fit, False, False, None)
