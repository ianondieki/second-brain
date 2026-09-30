"""The research agent's one model call per run (REQ-RES-01; docs/spec/06 6.5, docs/spec/09; PLAN §8 P11).

Task ``research_synthesis`` (``ai/models.yaml``: Sonnet 5 at medium effort on Anthropic, free slots 1-3 on local runs;
purpose ``tier1_only``; no tools, so nothing is searched or fetched). The model reads the niche's saved excerpts and
answers ``ResearchSynthesis``: up to a few drafted cards, each citing excerpt ids with a verbatim supporting span. Code
then decides (``bridge.problems.research.checks``).

What reaches the model: the niche's slug and, per excerpt, its id, publisher, source type, dates and verbatim quote,
all from the saved excerpts file and nothing else (no tenant, user or run data: docs/spec/06 6.5). Each is an
``InputField(public=True)``: public platform data with no owner, the only ownerless text a free provider may take
(D-37; ``bridge.llm.demo_data``). ``excerpt_fields`` is the only place in the code base that marks a field public,
and it accepts ``Excerpt`` objects only (made by ``bridge.problems.research.sources`` from the saved file), so nothing
else can pass as public (P7 MINOR, checked by ``tests/unit/problems/research/test_synthesis.py``). The LLM layer
sanitises and nonce-frames every field, so an excerpt that reads like instructions stays data; the schema carries
``injection_suspected``, and a suspected injection makes no card.

``ResearchSynthesis.demo_fallback()`` is the router's placeholder on local runs (no model answered): no drafts and
``injection_suspected=True``, so a demo fallback never creates a card.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field

from bridge.llm.types import InputField, Instruction, LLMOutput, Message
from bridge.problems.research.checks import MAX_GROUP_CHARS, MAX_STATEMENT_WORDS, MAX_TITLE_CHARS, Citation, Draft
from bridge.problems.research.sources import Excerpt

TASK: Final = "research_synthesis"
FIELD_PREFIX: Final = "excerpt"


class DraftCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    excerpt_id: str = Field(description="The id of an excerpt from this message.")
    supporting_text: str = Field(
        description="Words copied exactly, in order, from that excerpt's quote that support the card (a phrase of at"
        " least a few words, never paraphrased)."
    )


class ProblemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(description=f"A plain title of at most {MAX_TITLE_CHARS} characters.")
    statement: str = Field(
        description=f"The problem in at most {MAX_STATEMENT_WORDS} words, using only facts the cited excerpts state."
    )
    affected_group: str = Field(description=f"Who faces the problem, at most {MAX_GROUP_CHARS} characters.")
    named_orgs: list[str] = Field(description="Every company, organisation or public body the card names; else empty.")
    citations: list[DraftCitation] = Field(description="The excerpts the card relies on, each with supporting text.")

    def draft(self) -> Draft:
        return Draft(
            title=self.title,
            statement=self.statement,
            affected_group=self.affected_group,
            named_orgs=tuple(self.named_orgs),
            citations=tuple(Citation(c.excerpt_id, c.supporting_text) for c in self.citations),
        )


class ResearchSynthesis(LLMOutput):
    """The model's answer. ``demo_fallback`` is the router's placeholder on local runs: no drafts, flagged."""

    problems: list[ProblemDraft] = Field(description="The drafted problem cards; empty when the excerpts support none.")

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, problems=[])


def system_prompt(max_cards: int, min_support_words: int) -> str:
    return (
        "You draft problem cards for a platform where local developers find real problems that organisations in"
        " Kenya face. Each submission block below is one short public excerpt with its id, publisher, source type,"
        " published date and a verbatim quote; one block names the sector. Draft at most"
        f" {max_cards} problem cards that the excerpts clearly support, or none."
        " Rules: use only facts the excerpts state; copy every number exactly as an excerpt writes it, with the word"
        " that follows it there (such as million, percent or -kilogramme), and never combine, round or average"
        " figures from different excerpts; cite every excerpt a card relies on by its id,"
        f" with supporting_text copied word for word from its quote (at least {min_support_words} words); name no"
        " company, organisation or public body unless an excerpt whose source type is official supports the card, and"
        " list every name you use in named_orgs (otherwise describe them generally, for example 'the regulator');"
        " never name or describe a private individual; no advice, no blame, no speculation."
        f" A title has at most {MAX_TITLE_CHARS} characters, a statement at most {MAX_STATEMENT_WORDS} words, an"
        f" affected_group at most {MAX_GROUP_CHARS} characters."
    )


def excerpt_fields(niche: str, excerpts: Sequence[Excerpt]) -> list[InputField]:
    """The saved excerpts as public fields (see the module docstring): the only ``public=True`` fields there are."""
    if not all(isinstance(e, Excerpt) for e in excerpts):
        raise TypeError("only saved excerpts (bridge.problems.research.sources.Excerpt) are public fields")
    first = excerpts[0] if excerpts else None
    if first is None or any(e.niche != niche or e.country != first.country for e in excerpts):
        raise ValueError("a research call reads the saved excerpts of one niche and country")
    fields = [InputField(f"{FIELD_PREFIX}.niche", first.niche, public=True)]
    for index, excerpt in enumerate(excerpts, start=1):
        value = (
            f"id: {excerpt.id}\npublisher: {excerpt.publisher}\nsource type: {excerpt.source_type}\n"
            f"published: {excerpt.published_date.isoformat()}\nquote: {excerpt.quote}"
        )
        fields.append(InputField(f"{FIELD_PREFIX}.{index}", value, public=True))
    return fields


def messages(niche: str, excerpts: Sequence[Excerpt], *, max_cards: int, min_support_words: int) -> list[Message]:
    return [
        Message.system(system_prompt(max_cards, min_support_words)),
        Message.user(Instruction("The sector and the excerpts:"), *excerpt_fields(niche, excerpts)),
    ]
