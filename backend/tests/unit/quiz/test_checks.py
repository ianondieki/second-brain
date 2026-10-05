"""REQ-DEV-01 (D-59; P22 card A test A1): each check in code discards the whole draft with its reason code, and a
clean draft is accepted with the source's title, URL and topic copied from the curated list and a prompt hash per
question."""

from __future__ import annotations

import hashlib
from datetime import date

import pytest

from bridge.quiz import checks, fakes
from bridge.quiz.checks import Discarded, Reason, check_draft, names_a_person, prompt_hash
from bridge.quiz.sources import get_sources

DAY = date(2026, 10, 6)
SAMPLE = fakes.day_sample(DAY)
SENT = {s.id: s for s in SAMPLE}


@pytest.mark.parametrize(
    ("variant", "reason", "position"),
    [
        ("injection_suspected", Reason.INJECTION_SUSPECTED, None),
        ("question_count", Reason.QUESTION_COUNT, None),
        ("option_count", Reason.OPTION_COUNT, 2),
        ("control_character", Reason.CONTROL_CHARACTER, 3),
        ("non_latin_text", Reason.NON_LATIN_TEXT, 1),
        ("text_out_of_bounds", Reason.TEXT_OUT_OF_BOUNDS, 4),
        ("duplicate_options", Reason.DUPLICATE_OPTIONS, 5),
        ("answer_count", Reason.ANSWER_COUNT, 3),
        ("no_answer", Reason.ANSWER_COUNT, 3),
        ("unknown_source", Reason.UNKNOWN_SOURCE, 2),
        ("names_a_person", Reason.NAMES_A_PERSON, 1),
        ("titled_person", Reason.NAMES_A_PERSON, 4),
        ("duplicate_prompt", Reason.DUPLICATE_PROMPT, None),
    ],
)
def test_each_check_discards_the_whole_draft(variant: str, reason: Reason, position: int | None) -> None:
    assert check_draft(fakes.answer(SAMPLE, variant).draft(), SENT) == Discarded(reason, position)


def test_a_clean_draft_is_accepted_with_copied_sources_and_prompt_hashes() -> None:
    answer = fakes.answer(SAMPLE)
    accepted = check_draft(answer.draft(), SENT)
    assert isinstance(accepted, tuple)
    assert [q.position for q in accepted] == [1, 2, 3, 4, 5]
    for written, question, source in zip(answer.questions, accepted, SAMPLE, strict=False):
        assert (question.source_id, question.source_title, question.source_url, question.topic) == (
            source.id,
            source.title,
            source.url,
            source.topic,
        )
        assert question.options[question.answer] == source.host
        assert [o.correct for o in written.options].index(True) == question.answer
        assert question.prompt_hash == hashlib.sha256(question.prompt.lower().encode()).hexdigest()
    assert [q.answer for q in accepted] == [0, 1, 2, 3, 0]


def test_a_prompt_from_the_no_repeat_window_discards_the_draft() -> None:
    draft = fakes.answer(SAMPLE).draft()
    recent = {prompt_hash(f"  {draft.questions[2].prompt.upper()}  ")}
    assert check_draft(draft, SENT, recent) == Discarded(Reason.REPEATED_PROMPT, 3)
    assert isinstance(check_draft(draft, SENT, {prompt_hash("Another question?")}), tuple)


def test_a_source_known_to_the_list_but_not_sent_today_is_unknown() -> None:
    other = next(s for s in get_sources().sources if s.id not in SENT)
    answer = fakes.answer(SAMPLE)
    changed = fakes.edit_question(answer, 0, source_id=other.id)
    assert check_draft(changed.draft(), SENT) == Discarded(Reason.UNKNOWN_SOURCE, 1)


def test_the_prompt_hash_folds_case_width_and_whitespace() -> None:
    plain = prompt_hash("What does git bisect do?")
    assert prompt_hash("  WHAT does\tgit  bisect do?\n") == plain
    assert prompt_hash("What does git bisect do\uff1f") == plain  # NFKC folds the full-width question mark
    assert prompt_hash("What does git rebase do?") != plain
    assert len(plain) == 64


@pytest.mark.parametrize(
    ("texts", "declared", "named"),
    [
        (["What does git bisect do?"], [], False),
        (["Which Python feature is described here?"], [], False),  # a capitalised term is not a person
        (["Linus wrote it"], [], False),  # the documented residual: no title, not declared
        (["Ask Dr Achieng about it"], [], True),
        (["Prof. Wangari explains"], [], True),
        (["Bwana Otieno said so"], [], True),
        (["Mr  Smith said so"], [], True),
        (["Dr. no capital"], [], False),
        (["Any text"], ["Jane Wanjiru"], True),
        (["Any text"], ["   "], False),
    ],
)
def test_the_named_person_rule(texts: list[str], declared: list[str], named: bool) -> None:
    assert names_a_person(texts, declared) is named


def test_case_is_kept_when_options_are_compared() -> None:
    """``git -c`` and ``git -C`` are different answers: only NFKC and whitespace fold."""
    answer = fakes.answer(SAMPLE)
    options = list(answer.questions[0].options)
    options[1] = options[1].model_copy(update={"text": "git -c"})
    options[2] = options[2].model_copy(update={"text": "git -C"})
    changed = fakes.edit_question(answer, 0, options=options)
    assert isinstance(check_draft(changed.draft(), SENT), tuple)
    options[2] = options[2].model_copy(update={"text": "git\u00a0-c"})  # a no-break space is whitespace after NFKC
    assert check_draft(fakes.edit_question(answer, 0, options=options).draft(), SENT) == Discarded(
        Reason.DUPLICATE_OPTIONS, 1
    )


@pytest.mark.parametrize(("field", "limit"), [("prompt", checks.MAX_PROMPT_CHARS), ("why", checks.MAX_WHY_CHARS)])
def test_the_length_bounds_are_inclusive(field: str, limit: int) -> None:
    answer = fakes.answer(SAMPLE)
    assert isinstance(check_draft(fakes.edit_question(answer, 0, **{field: "a" * limit}).draft(), SENT), tuple)
    too_long = fakes.edit_question(answer, 0, **{field: "a" * (limit + 1)})
    assert check_draft(too_long.draft(), SENT) == Discarded(Reason.TEXT_OUT_OF_BOUNDS, 1)
    empty = fakes.edit_question(answer, 0, **{field: "   "})
    assert check_draft(empty.draft(), SENT) == Discarded(Reason.TEXT_OUT_OF_BOUNDS, 1)


def test_an_option_over_120_characters_is_out_of_bounds() -> None:
    answer = fakes.answer(SAMPLE)
    options = list(answer.questions[1].options)
    options[0] = options[0].model_copy(update={"text": "o" * (checks.MAX_OPTION_CHARS + 1)})
    assert check_draft(fakes.edit_question(answer, 1, options=options).draft(), SENT) == Discarded(
        Reason.TEXT_OUT_OF_BOUNDS, 2
    )
