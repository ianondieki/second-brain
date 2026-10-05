"""Today's five: the checks in code that decide whether a draft becomes a set (REQ-DEV-01; D-59; P22 card A).

The model drafts; this module decides. Any failure discards the whole draft with one reason code (``Reason``); the
job (``bridge.quiz.run``) then tries once more and otherwise gives up for the day. In order:

1. ``injection_suspected``: the model flagged a submission block as instructions (docs/spec/09), so nothing of the
   answer is used.
2. ``question_count``: exactly five questions.
3. Per question, in order (the reason names the first failure):
   - ``option_count``: exactly four options;
   - the text rules of the research agent (``bridge.problems.research.text``), after NFKC and whitespace collapsing:
     ``control_character`` (a C0/C1 control, a format or default-ignorable character anywhere), ``non_latin_text``
     (a letter outside the Latin script, a combining mark or a non-ASCII digit in the prompt, an option or the why);
   - ``text_out_of_bounds``: a prompt of 1 to 300 characters, options of 1 to 120, a why of 1 to 600 (revision
     0009's CHECKs);
   - ``duplicate_options``: the four options are distinct after NFKC and whitespace collapsing (case is kept: in code,
     ``git -c`` and ``git -C`` are different answers);
   - ``answer_count``: exactly one option marked correct (none or two discard), so the answer index is 0 to 3;
   - ``unknown_source``: the ``source_id`` is one of the pages sent in this call; the title, URL and topic stored with
     the question are copied from the curated list, never from the model;
   - ``names_a_person``: the model declared a person in ``named_people`` (the prompt asks it to name nobody, the way
     the research agent declares ``named_orgs``), or the text carries a title followed by a capitalised word
     ("Dr Achieng", "Mr. Smith", "Bwana Otieno"). Residual: a person named without a title and not declared passes
     these checks; telling a private person's name from a technical term ("Ada", "Debian", "Linus") is not a rule
     code can keep, so the staff admin's approval of every set is the backstop (D-59).
4. ``duplicate_prompt``: two questions of the draft with the same prompt hash.
5. ``repeated_prompt``: a prompt hash drafted in the last ``quiz.no_repeat_days`` days (the caller passes them in).

``prompt_hash`` is the SHA-256 (hex) of the prompt after NFKC, whitespace collapsing and lower-casing; it is exposed on
each accepted question for the 60-day rule the storing part keeps (``quiz_questions.prompt_hash``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from bridge.problems.research.text import collapse, has_control, non_latin
from bridge.quiz.sources import QuizSource

QUESTIONS_PER_SET: Final = 5
OPTIONS_PER_QUESTION: Final = 4
MAX_PROMPT_CHARS: Final = 300
MAX_OPTION_CHARS: Final = 120
MAX_WHY_CHARS: Final = 600
# A courtesy or professional title before a capitalised word names a person ("Dr Achieng", "Prof. Wangari").
_TITLED_NAME: Final = re.compile(
    r"(?<![^\W_])(?:Mr|Mrs|Ms|Mx|Miss|Dr|Prof|Professor|Sir|Dame|Lord|Lady|Hon|Bwana|Bi|Mzee)\.?\s+[A-Z][a-z]"
)


class Reason(StrEnum):
    INJECTION_SUSPECTED = "injection_suspected"
    QUESTION_COUNT = "question_count"
    OPTION_COUNT = "option_count"
    CONTROL_CHARACTER = "control_character"
    NON_LATIN_TEXT = "non_latin_text"
    TEXT_OUT_OF_BOUNDS = "text_out_of_bounds"
    DUPLICATE_OPTIONS = "duplicate_options"
    ANSWER_COUNT = "answer_count"
    UNKNOWN_SOURCE = "unknown_source"
    NAMES_A_PERSON = "names_a_person"
    DUPLICATE_PROMPT = "duplicate_prompt"
    REPEATED_PROMPT = "repeated_prompt"


@dataclass(frozen=True, slots=True)
class DraftOption:
    text: str
    correct: bool


@dataclass(frozen=True, slots=True)
class DraftQuestion:
    """One question as the model wrote it (``bridge.quiz.generate.QuestionOut``)."""

    prompt: str
    options: tuple[DraftOption, ...]
    why: str
    source_id: str
    named_people: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Draft:
    injection_suspected: bool
    questions: tuple[DraftQuestion, ...]


@dataclass(frozen=True, slots=True)
class AcceptedQuestion:
    """A question that passed every check: text collapsed, ``answer`` the index (0-3) of the correct option, the
    source's title, URL and topic copied from the curated list, and the prompt hash of the no-repeat rule."""

    position: int  # 1-5, the order of the draft
    prompt: str
    options: tuple[str, str, str, str]
    answer: int
    why: str
    source_id: str
    source_title: str
    source_url: str
    topic: str
    prompt_hash: str


@dataclass(frozen=True, slots=True)
class Discarded:
    """Why a draft was discarded; ``position`` (1-5) names the question when one check of a question failed."""

    reason: Reason
    position: int | None = None


def prompt_hash(prompt: str) -> str:
    """SHA-256 (hex) of the prompt after NFKC, whitespace collapsing and lower-casing."""
    return hashlib.sha256(collapse(prompt).lower().encode("utf-8")).hexdigest()


def names_a_person(texts: Sequence[str], declared: Sequence[str]) -> bool:
    """Whether a question names a person by the rule in the module docstring (declared, or a title and a name)."""
    if any(collapse(name) for name in declared):
        return True
    return any(_TITLED_NAME.search(collapse(text)) for text in texts)


def check_question(question: DraftQuestion, position: int, sent: Mapping[str, QuizSource]) -> AcceptedQuestion | Reason:
    """One question's checks (3 in the module docstring), or the reason of the first that failed."""
    if len(question.options) != OPTIONS_PER_QUESTION:
        return Reason.OPTION_COUNT
    prompt, why = collapse(question.prompt), collapse(question.why)
    options = tuple(collapse(option.text) for option in question.options)
    texts = (prompt, *options, why)
    if any(has_control(text) for text in texts):
        return Reason.CONTROL_CHARACTER
    if any(non_latin(text) for text in texts):
        return Reason.NON_LATIN_TEXT
    if (
        not 0 < len(prompt) <= MAX_PROMPT_CHARS
        or not all(0 < len(option) <= MAX_OPTION_CHARS for option in options)
        or not 0 < len(why) <= MAX_WHY_CHARS
    ):
        return Reason.TEXT_OUT_OF_BOUNDS
    if len(set(options)) != OPTIONS_PER_QUESTION:
        return Reason.DUPLICATE_OPTIONS
    correct = [index for index, option in enumerate(question.options) if option.correct]
    if len(correct) != 1:
        return Reason.ANSWER_COUNT
    source = sent.get(question.source_id)
    if source is None:
        return Reason.UNKNOWN_SOURCE
    if names_a_person(texts, question.named_people):
        return Reason.NAMES_A_PERSON
    first, second, third, fourth = options
    return AcceptedQuestion(
        position=position,
        prompt=prompt,
        options=(first, second, third, fourth),
        answer=correct[0],
        why=why,
        source_id=source.id,
        source_title=source.title,
        source_url=source.url,
        topic=source.topic,
        prompt_hash=prompt_hash(prompt),
    )


def check_draft(
    draft: Draft, sent: Mapping[str, QuizSource], recent_hashes: Set[str] = frozenset()
) -> tuple[AcceptedQuestion, ...] | Discarded:
    """The draft's five accepted questions, or why the whole draft is discarded (see the module docstring).
    ``sent``: the pages of this call by id; ``recent_hashes``: the prompt hashes of the no-repeat window."""
    if draft.injection_suspected:
        return Discarded(Reason.INJECTION_SUSPECTED)
    if len(draft.questions) != QUESTIONS_PER_SET:
        return Discarded(Reason.QUESTION_COUNT)
    accepted: list[AcceptedQuestion] = []
    for position, question in enumerate(draft.questions, start=1):
        verdict = check_question(question, position, sent)
        if isinstance(verdict, Reason):
            return Discarded(verdict, position)
        accepted.append(verdict)
    hashes = [question.prompt_hash for question in accepted]
    if len(set(hashes)) != len(hashes):
        return Discarded(Reason.DUPLICATE_PROMPT)
    repeated = next((q.position for q in accepted if q.prompt_hash in recent_hashes), None)
    if repeated is not None:
        return Discarded(Reason.REPEATED_PROMPT, repeated)
    return tuple(accepted)
