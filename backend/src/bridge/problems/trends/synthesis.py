"""The trends' one model call a week (REQ-DEV-02; D-60; P22 card B, default (5); docs/spec/09).

Task ``trend_synthesis`` (``ai/models.yaml``: Sonnet 5 at medium effort on Anthropic, as ``research_synthesis``; free
slots 1-3 on local runs; purpose ``tier1_only``; ``confidential`` false; no tools, so nothing is searched or fetched).
The model reads the week's saved excerpts of official technology publishers and answers ``TrendSynthesis``: up to
``trends.max_cards_per_run`` drafted trends, each a title, a short summary, a topic slug of the excerpts, the
organisations it names and one to five citations of an ``excerpt_ref`` with a ``support`` phrase copied from that
excerpt. Code then decides (``bridge.problems.trends.checks``).

What reaches the model: the week (an instruction written here from the date) and, per excerpt, its id, topic slug,
publisher, published date and verbatim quote, all from ``backend/seed/trend_excerpts.yaml`` and nothing else (no tenant,
user or run data). ``select_excerpts`` picks at most ``trends.max_excerpts`` published by the week's Monday and not
archived on it, spread over the topics (each topic's freshest first, the topics in turn) and sends them freshest first.
Each is an ``InputField(public=True)``: public platform data with no owner, which a free provider may take (D-37;
``bridge.llm.demo_data``). ``excerpt_fields`` is the trends' only place that marks a field public, and it accepts
``TECH`` ``Excerpt`` objects only (made by ``bridge.problems.research.sources`` from the saved file; the P7 rule,
checked by ``tests/unit/problems/research/test_synthesis.py``). The LLM layer sanitises and nonce-frames every field and
puts the output schema in the request (native structured output; in the system prompt for a free slot); the schema
carries ``injection_suspected``, and a flagged answer makes no card.

``TrendSynthesis.demo_fallback()`` is the router's placeholder on local runs (no model answered): no trends and
``injection_suspected=True``, so a demo fallback never becomes a card.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field

from bridge.llm.types import InputField, Instruction, LLMOutput, Message
from bridge.problems.research.checks import Citation
from bridge.problems.research.policy import ResearchPolicy
from bridge.problems.research.sources import TECH, Catalogue, Excerpt, Freshness, freshness
from bridge.problems.trends.checks import (
    MAX_CITATIONS,
    MAX_SENTENCES,
    MAX_SUMMARY_CHARS,
    MAX_TITLE_CHARS,
    MIN_SENTENCES,
    AnswerDraft,
    Reason,
    TrendDraft,
)

TASK: Final = "trend_synthesis"
FIELD_PREFIX: Final = "trend_excerpt"
_WEEKDAYS: Final = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class TrendCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    excerpt_ref: str = Field(description="The id of an excerpt from this message.")
    support: str = Field(
        description="Words copied exactly, in order, from that excerpt's quote that support the trend (a phrase of at"
        " least a few words, never paraphrased)."
    )


class TrendOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(description=f"A plain title of at most {MAX_TITLE_CHARS} characters.")
    summary: str = Field(
        description=f"{MIN_SENTENCES} to {MAX_SENTENCES} plain sentences, at most {MAX_SUMMARY_CHARS} characters: what"
        " changed and why a developer in Kenya might care, using only facts the cited excerpts state."
    )
    topic_slug: str = Field(description="The topic_slug of the excerpts this trend is about, copied from them.")
    named_orgs: list[str] = Field(
        description="Every company, organisation or project body the trend names; else empty."
    )
    citations: list[TrendCitation] = Field(
        description=f"1 to {MAX_CITATIONS} excerpts the trend relies on, each with its support."
    )

    def draft(self) -> TrendDraft:
        return TrendDraft(
            title=self.title,
            summary=self.summary,
            topic_slug=self.topic_slug,
            named_orgs=tuple(self.named_orgs),
            citations=tuple(Citation(c.excerpt_ref, c.support) for c in self.citations),
        )


class TrendSynthesis(LLMOutput):
    """The model's answer. ``demo_fallback`` is the router's placeholder on local runs: no trends, flagged."""

    trends: list[TrendOut] = Field(description="The drafted trends; empty when the excerpts support none.")

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, trends=[])

    def draft(self) -> AnswerDraft:
        return AnswerDraft(self.injection_suspected, tuple(t.draft() for t in self.trends))


def system_prompt(max_cards: int, min_support_words: int) -> str:
    return (
        "You write short technology trend cards for software developers in Kenya. Each submission block below is one"
        " short public excerpt from an official technology publisher (a vendor's or a project's own site) with its"
        f" id, topic_slug, publisher, published date and a verbatim quote. Draft at most {max_cards} trends that the"
        " excerpts clearly support, each on a different development, or none."
        f" Each trend has a title of at most {MAX_TITLE_CHARS} characters and a summary of {MIN_SENTENCES} to"
        f" {MAX_SENTENCES} plain sentences (at most {MAX_SUMMARY_CHARS} characters) that says what changed and why a"
        " developer in Kenya might care; its topic_slug is copied from the excerpts it cites."
        f" Rules: use only facts the excerpts state; cite 1 to {MAX_CITATIONS} excerpts a trend relies on by their id"
        f" as excerpt_ref, with support copied word for word from that excerpt's quote (at least {min_support_words}"
        " words); copy every number, version included, exactly as an excerpt writes it, with the word that follows it"
        " there, or end the sentence after it, and never combine, round or average figures; name a company,"
        " organisation or project body only when a cited excerpt names it in its quote or publishes it, and list"
        " every name you use in named_orgs; make no claim about a company beyond what a quote states; never name or"
        " describe a private individual; no advice to buy, subscribe or switch, no prices you were not given, no"
        " speculation, no hype; never write a link, URL or web address; plain English, Latin letters, no emoji."
    )


def select_excerpts(
    catalogue: Catalogue,
    as_of: date,
    scoring: ResearchPolicy,
    limit: int,
    *,
    exclude_refs: frozenset[str] = frozenset(),
) -> tuple[Excerpt, ...]:
    """At most ``limit`` saved TECH excerpts published by ``as_of``, not archived on it (``scoring`` carries the
    trends' ages) and not in ``exclude_refs`` (excerpts a stored card already cites), spread over the topics: the
    topics in order of their freshest excerpt, each topic's excerpts freshest first, taken one topic at a time in
    turn; returned freshest first (then by id). Deterministic: a retry sees the same excerpts."""
    by_topic: dict[str, list[Excerpt]] = defaultdict(list)
    for excerpt in catalogue.excerpts:
        live = excerpt.published_date <= as_of and freshness(excerpt, as_of, scoring) is not Freshness.ARCHIVED
        if excerpt.country == TECH and live and excerpt.id not in exclude_refs:
            by_topic[excerpt.topic_slug].append(excerpt)
    queues = [sorted(group, key=lambda e: (-e.published_date.toordinal(), e.id)) for group in by_topic.values()]
    queues.sort(key=lambda q: (-q[0].published_date.toordinal(), q[0].topic_slug))
    chosen: list[Excerpt] = []
    turn = 0
    while len(chosen) < limit and any(turn < len(q) for q in queues):
        chosen += [q[turn] for q in queues if turn < len(q)][: limit - len(chosen)]
        turn += 1
    return tuple(sorted(chosen, key=lambda e: (-e.published_date.toordinal(), e.id)))


def excerpt_fields(excerpts: Sequence[Excerpt]) -> list[InputField]:
    """The week's saved TECH excerpts as public fields (see the module docstring): the trends' only public fields."""
    if not all(isinstance(e, Excerpt) for e in excerpts):
        raise TypeError("only saved excerpts (bridge.problems.research.sources.Excerpt) are public fields")
    if not excerpts or any(e.country != TECH for e in excerpts):
        raise ValueError(f"a trend call reads saved {TECH} excerpts, at least one")
    return [
        InputField(
            f"{FIELD_PREFIX}.{index}",
            f"id: {e.id}\ntopic_slug: {e.topic_slug}\npublisher: {e.publisher}\n"
            f"published: {e.published_date.isoformat()}\nquote: {e.quote}",
            public=True,
        )
        for index, e in enumerate(excerpts, start=1)
    ]


def week_instruction(week_start: date) -> Instruction:
    weekday = _WEEKDAYS[week_start.weekday()]  # not strftime: the process locale must not change the prompt
    return Instruction(f"The trends are for the week starting {weekday} {week_start.isoformat()}. The excerpts:")


def retry_instruction(reason: Reason) -> Instruction:
    """Added on a retry: the reason code of the refused draft (a code constant, never model text)."""
    return Instruction(f"An earlier draft for this week was refused by the checks ({reason.value}). Write a new one.")


def messages(
    week_start: date,
    excerpts: Sequence[Excerpt],
    *,
    max_cards: int,
    min_support_words: int,
    refused: Reason | None = None,
) -> list[Message]:
    parts: list[Instruction | InputField] = [week_instruction(week_start), *excerpt_fields(excerpts)]
    if refused is not None:
        parts.append(retry_instruction(refused))
    return [Message.system(system_prompt(max_cards, min_support_words)), Message.user(*parts)]
