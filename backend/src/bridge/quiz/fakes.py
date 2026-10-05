"""Scripted ``quiz_generation`` answers for tests (D-18: no paid calls; AC-SEC-5: no network).

``valid_answer(sample)`` is a fixed answer that passes every check for a day's sample: one question on each of the
sample's first five pages, written from the page's host and title only (true by construction), the correct option at
a different place each time. ``answer(sample, variant)`` is that answer with one fault, one variant per check of
``bridge.quiz.checks`` (``VARIANTS``: the variant's name is the ``Reason`` it triggers, plus ``"valid"``,
``"no_answer"`` (``answer_count`` with no option marked correct), ``"titled_person"`` (``names_a_person`` by a title)
and the text rules in an option and in the why (``option_``/``why_`` + ``control_character`` or ``non_latin_text``).
``FakeQuizClient`` is the real ``LLMService`` over ``FakeAdapter`` (``bridge.llm.fakes.FakeLLMClient``) answering
with those variants in order, so a test still goes through the registry, the kill switch, the caps, the sanitiser and
the ledger.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from typing import Any, Final

from bridge.llm.fakes import FakeLLMClient
from bridge.quiz.checks import MAX_WHY_CHARS, OPTIONS_PER_QUESTION, QUESTIONS_PER_SET
from bridge.quiz.generate import OptionOut, QuestionOut, QuizAnswer
from bridge.quiz.policy import QuizPolicy, get_quiz_policy
from bridge.quiz.sources import QuizSource, SourceList, get_sources, sample_for_day

VALID: Final = "valid"


def question(source: QuizSource, position: int) -> QuestionOut:
    """A true question on ``source`` (its host and title only), the answer at ``position % 4``."""
    wrong = (f"{source.topic}.example.org", f"docs.example.com/{source.topic}", f"wiki.example.net/{source.id}")
    correct = position % OPTIONS_PER_QUESTION
    texts = [*wrong[:correct], source.host, *wrong[correct:]]
    return QuestionOut(
        prompt=f'On which site is the official page "{source.title}" published?',
        options=[OptionOut(text=text, correct=index == correct) for index, text in enumerate(texts)],
        why=f'The page "{source.title}" is published on {source.host}, its project\'s own documentation site.',
        source_id=source.id,
        named_people=[],
    )


def valid_answer(sample: Sequence[QuizSource]) -> QuizAnswer:
    if len(sample) < QUESTIONS_PER_SET:
        raise ValueError(f"a fake answer needs {QUESTIONS_PER_SET} sampled pages")
    questions = [question(source, index) for index, source in enumerate(sample[:QUESTIONS_PER_SET])]
    return QuizAnswer(injection_suspected=False, questions=questions)


def edit_question(answer: QuizAnswer, index: int, **changes: Any) -> QuizAnswer:
    questions = list(answer.questions)
    questions[index] = questions[index].model_copy(update=changes)
    return answer.model_copy(update={"questions": questions})


def _options(answer: QuizAnswer, index: int, edit: Callable[[list[OptionOut]], list[OptionOut]]) -> QuizAnswer:
    return edit_question(answer, index, options=edit(list(answer.questions[index].options)))


def _all_correct(flag: bool) -> Callable[[list[OptionOut]], list[OptionOut]]:
    return lambda options: [o.model_copy(update={"correct": flag}) for o in options]


VARIANTS: Final[dict[str, Callable[[QuizAnswer], QuizAnswer]]] = {
    VALID: lambda a: a,
    "injection_suspected": lambda a: a.model_copy(update={"injection_suspected": True}),
    "question_count": lambda a: a.model_copy(update={"questions": a.questions[:4]}),
    "option_count": lambda a: _options(a, 1, lambda o: o[:3]),
    "control_character": lambda a: edit_question(a, 2, prompt="Which site\u200b publishes this page?"),
    "non_latin_text": lambda a: edit_question(a, 0, prompt="\u041a\u0430\u043a\u043e\u0439 site publishes this page?"),
    "option_control_character": lambda a: _options(
        a, 1, lambda o: [o[0], o[1].model_copy(update={"text": "docs\u0007.example.org"}), o[2], o[3]]
    ),
    "option_non_latin_text": lambda a: _options(
        a, 2, lambda o: [o[0], o[1], o[2], o[3].model_copy(update={"text": "d\u043ecs.example.org"})]
    ),
    "why_control_character": lambda a: edit_question(a, 3, why="The page\u202e says so on its own site."),
    "why_non_latin_text": lambda a: edit_question(a, 4, why="The page says so on its own \u0441ite."),
    "text_out_of_bounds": lambda a: edit_question(a, 3, why="A long why. " * (MAX_WHY_CHARS // 10)),
    "duplicate_options": lambda a: _options(
        a, 4, lambda o: [o[0], o[1], o[2], o[1].model_copy(update={"text": f"  {o[1].text} ", "correct": False})]
    ),
    "answer_count": lambda a: _options(a, 2, _all_correct(True)),
    "no_answer": lambda a: _options(a, 2, _all_correct(False)),
    "unknown_source": lambda a: edit_question(a, 1, source_id="not-in-the-list"),
    "names_a_person": lambda a: edit_question(a, 0, named_people=["Jane Wanjiru"]),
    "titled_person": lambda a: edit_question(a, 3, why="Dr Achieng wrote that this page explains it."),
    "duplicate_prompt": lambda a: edit_question(a, 4, prompt=f"  {a.questions[0].prompt.upper()} "),
}


def answer(sample: Sequence[QuizSource], variant: str = VALID) -> QuizAnswer:
    return VARIANTS[variant](valid_answer(sample))


def day_sample(
    day: date, sources: SourceList | None = None, policy: QuizPolicy | None = None
) -> tuple[QuizSource, ...]:
    policy = policy or get_quiz_policy()
    return sample_for_day(sources or get_sources(), day, policy.sources_per_prompt)


class FakeQuizClient(FakeLLMClient):
    """``FakeLLMClient`` answering ``quiz_generation`` for ``day`` with ``variants`` in order (``VARIANTS`` keys);
    other keyword arguments (``settings``, ``caps``, ...) go to ``FakeLLMClient``."""

    def __init__(
        self,
        day: date,
        *variants: str,
        sources: SourceList | None = None,
        policy: QuizPolicy | None = None,
        **kwargs: Any,
    ) -> None:
        sample = day_sample(day, sources, policy)
        super().__init__([answer(sample, variant) for variant in variants], **kwargs)
