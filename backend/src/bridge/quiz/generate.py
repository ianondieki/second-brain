"""Today's five's one model call: the prompt for one Nairobi day and its answer (REQ-DEV-01; D-59; P22 card A).

Task ``quiz_generation`` (``ai/models.yaml``: Haiku 4.5 on Anthropic, free slots 1-3 on local runs; purpose
``tier1_only``; ``confidential`` false; no tools, so nothing is searched or fetched). The model reads the day's sample
of the curated source list (``bridge.quiz.sources.sample_for_day``) and answers ``QuizAnswer``: five questions, each
with four options of which one is marked correct, a why a reader can check on the chosen page, the page's id and the
people it names. Code then decides (``bridge.quiz.checks``).

What reaches the model: the day (an instruction written here from the date) and, per sampled page, its id, topic,
title and URL, all from ``backend/ai/quiz_sources.yaml`` and nothing else (no tenant, user or attempt data). Each page
is an ``InputField(public=True)``: public platform data with no owner, which a free provider may take (D-37;
``bridge.llm.demo_data``). ``source_fields`` is the quiz's only place that marks a field public, and it accepts
``QuizSource`` objects only (made by ``bridge.quiz.sources`` from the curated file; the P7 rule, checked by
``tests/unit/problems/research/test_synthesis.py``). The LLM layer sanitises and nonce-frames every field and puts the
output schema in the request (native structured output; in the system prompt for a free slot, per
``json_schema_format``); the schema carries ``injection_suspected``, and a flagged answer makes no set.

``QuizAnswer.demo_fallback()`` is the router's placeholder on local runs (no model answered): no questions and
``injection_suspected=True``, so a demo fallback never becomes a set.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field

from bridge.llm.types import InputField, Instruction, LLMOutput, Message
from bridge.quiz.checks import (
    MAX_OPTION_CHARS,
    MAX_PROMPT_CHARS,
    MAX_WHY_CHARS,
    OPTIONS_PER_QUESTION,
    QUESTIONS_PER_SET,
    Draft,
    DraftOption,
    DraftQuestion,
    Reason,
)
from bridge.quiz.sources import QuizSource

TASK: Final = "quiz_generation"
FIELD_PREFIX: Final = "source"
_WEEKDAYS: Final = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class OptionOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(description=f"The option, at most {MAX_OPTION_CHARS} characters.")
    correct: bool = Field(description="True for the one correct option of the question, false for the other three.")


class QuestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt: str = Field(description=f"The question, at most {MAX_PROMPT_CHARS} characters.")
    options: list[OptionOut] = Field(description=f"Exactly {OPTIONS_PER_QUESTION} distinct options, one correct.")
    why: str = Field(
        description="Why the correct option is right, in one to three sentences a reader can check on the chosen page,"
        f" at most {MAX_WHY_CHARS} characters."
    )
    source_id: str = Field(description="The id of the page from this message that the why can be checked on.")
    named_people: list[str] = Field(description="Every person the question, its options or its why names; else empty.")

    def draft(self) -> DraftQuestion:
        return DraftQuestion(
            prompt=self.prompt,
            options=tuple(DraftOption(o.text, o.correct) for o in self.options),
            why=self.why,
            source_id=self.source_id,
            named_people=tuple(self.named_people),
        )


class QuizAnswer(LLMOutput):
    """The model's answer. ``demo_fallback`` is the router's placeholder on local runs: no questions, flagged."""

    questions: list[QuestionOut] = Field(description=f"Exactly {QUESTIONS_PER_SET} questions, in the order to ask.")

    @classmethod
    def demo_fallback(cls) -> Self:
        return cls(injection_suspected=True, questions=[])

    def draft(self) -> Draft:
        return Draft(self.injection_suspected, tuple(q.draft() for q in self.questions))


SYSTEM_PROMPT: Final = (
    "You write a short daily quiz for software developers in Kenya, to help them learn. Each submission block below"
    " is one page of official technology documentation with its id, topic, title and URL. Write exactly"
    f" {QUESTIONS_PER_SET} multiple-choice questions about what those pages document, each with exactly"
    f" {OPTIONS_PER_QUESTION} distinct options of which exactly one is correct. Rules: base every question on one of"
    " the pages and give that page's id as source_id (use only ids from the submission blocks, never a URL or"
    " another source); write a why of one to three sentences that a reader can check on that page; spread the"
    " questions over different pages and topics, and mix easy, medium and hard; ask about how the technology works,"
    " never about a person, and name no person at all (list any name you use in named_people); make no claim about"
    " a company, its products, prices, market or conduct; no trick questions, no 'all of the above' or 'none of the"
    " above', no opinions; plain English, Latin letters, no emoji and no other scripts. A prompt has at most"
    f" {MAX_PROMPT_CHARS} characters, an option at most {MAX_OPTION_CHARS}, a why at most {MAX_WHY_CHARS}."
)


def source_fields(sample: Sequence[QuizSource]) -> list[InputField]:
    """The sampled pages as public fields (see the module docstring): the quiz's only ``public=True`` fields."""
    if not sample or not all(isinstance(s, QuizSource) for s in sample):
        raise TypeError("only curated pages (bridge.quiz.sources.QuizSource) are public quiz fields")
    return [
        InputField(
            f"{FIELD_PREFIX}.{index}",
            f"id: {s.id}\ntopic: {s.topic}\ntitle: {s.title}\nurl: {s.url}",
            public=True,
        )
        for index, s in enumerate(sample, start=1)
    ]


def day_instruction(day: date) -> Instruction:
    weekday = _WEEKDAYS[day.weekday()]  # not strftime: the process locale must not change the prompt
    return Instruction(f"The quiz is for {weekday} {day.isoformat()} (Nairobi). The pages you may use:")


def retry_instruction(reason: Reason) -> Instruction:
    """Added on a retry: the reason code of the discarded draft (a code constant, never model text)."""
    return Instruction(f"An earlier draft for this day was discarded by the checks ({reason.value}). Write a new one.")


def messages(day: date, sample: Sequence[QuizSource], *, discarded: Reason | None = None) -> list[Message]:
    parts: list[Instruction | InputField] = [day_instruction(day), *source_fields(sample)]
    if discarded is not None:
        parts.append(retry_instruction(discarded))
    return [Message.system(SYSTEM_PROMPT), Message.user(*parts)]
