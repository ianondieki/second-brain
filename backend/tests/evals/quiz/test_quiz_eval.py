"""Today's five eval on a synthetic cassette (REQ-DEV-01; D-59; the docs/spec/09 eval pattern of the research agent).

The real ``AnthropicAdapter`` replays ``tests/fixtures/cassettes/quiz_generation_eval.json`` (hand-written,
``synthetic: true``; no network) through ``LLMService`` for one Nairobi day, five answers in turn: an invented source
id, a clean set, a question with two correct options, an answer that flags an injection, and a question about people.
The checks in code decide each. Measured:

- verdicts against the synthetic labels (``EXPECTED``): agreement 1.0;
- every accepted question's source is a page sent that day, its title and URL copied from the curated list (1.0);
- answers with an invented source, a flagged injection or a named person accepted: 0;
- every request carries no tools and frames each page in its own submission block.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Final

from bridge.llm.cassettes import CassettePlayer
from bridge.llm.types import CallContext
from bridge.quiz import generate
from bridge.quiz.checks import Discarded, check_draft
from bridge.quiz.policy import get_quiz_policy
from bridge.quiz.sources import get_sources, sample_for_day
from tests.unit.llm.rig import rig

CASSETTE: Final = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes" / "quiz_generation_eval.json"
DAY: Final = date(2026, 10, 6)
EXPECTED: Final = ("unknown_source", "accepted", "answer_count", "injection_suspected", "names_a_person")


async def test_quiz_eval_on_the_synthetic_cassette() -> None:
    tape = CassettePlayer.from_files(CASSETTE)
    service = rig(tape.adapter()).service
    sources = get_sources()
    sample = sample_for_day(sources, DAY, get_quiz_policy().sources_per_prompt)
    sent = {s.id: s for s in sample}
    verdicts: list[str] = []
    copied: list[bool] = []
    for index in range(len(EXPECTED)):
        result = await service.complete(
            generate.TASK,
            generate.messages(DAY, sample),
            generate.QuizAnswer,
            ctx=CallContext(trace_id=f"eval:quiz:{index}"),
        )
        verdict = check_draft(result.parsed.draft(), sent)
        if isinstance(verdict, Discarded):
            verdicts.append(verdict.reason.value)
            continue
        verdicts.append("accepted")
        listed = sources.by_id()
        copied += [
            q.source_id in sent
            and (q.source_title, q.source_url) == (listed[q.source_id].title, listed[q.source_id].url)
            for q in verdict
        ]
    assert tape.exhausted
    assert tape.errors == []
    for recorded in tape.requests:
        request = recorded.json()
        assert "tools" not in request
        text = "\n".join(block["text"] for m in request["messages"] for block in m["content"])
        assert text.count("<submission nonce=") == len(sample)

    unsafe = ("unknown_source", "injection_suspected", "names_a_person")
    metrics = {
        "label_agreement": sum(v == e for v, e in zip(verdicts, EXPECTED, strict=True)) / len(EXPECTED),
        "sets_accepted": verdicts.count("accepted"),
        "source_copy_validity": sum(copied) / len(copied),
        "unsafe_drafts_accepted": sum(
            1 for v, e in zip(verdicts, EXPECTED, strict=True) if e in unsafe and v == "accepted"
        ),
    }
    assert metrics == {
        "label_agreement": 1.0,
        "sets_accepted": 1,
        "source_copy_validity": 1.0,
        "unsafe_drafts_accepted": 0,
    }, (metrics, verdicts)
