"""REQ-DEV-01 (D-59; P22 card A test A1): ``draft_set`` makes one ``quiz_generation`` call through ``bridge.llm``,
retries a discarded draft once and then refuses the day; the kill switch and the daily cap refuse without a call; a
demo fallback is never a set. No database is touched; the synthetic cassette replays through the real SDK."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from bridge.llm.cassettes import CassettePlayer, load
from bridge.llm.demo_fallback import FallbackReason, fallback_result
from bridge.llm.errors import LLMConfigError
from bridge.llm.ledger import CallStatus
from bridge.llm.types import CallContext, LLMOutput, Message, Result
from bridge.quiz import fakes, generate
from bridge.quiz.checks import Reason, prompt_hash
from bridge.quiz.policy import QuizPolicy, get_quiz_policy
from bridge.quiz.run import Accepted, QuizDeps, Refused, draft_set
from bridge.quiz.sources import get_sources
from tests.unit.llm.helpers import settings
from tests.unit.llm.rig import rig

DAY: Final = date(2026, 10, 6)
CASSETTE: Final = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes" / "quiz_generation_eval.json"


def deps(client: Any, policy: QuizPolicy | None = None) -> QuizDeps:
    return QuizDeps(client=client, sources=get_sources(), policy=policy or get_quiz_policy())


async def test_a_clean_draft_is_accepted_in_one_call() -> None:
    client = fakes.FakeQuizClient(DAY, "valid")
    outcome = await draft_set(deps(client), DAY)
    assert isinstance(outcome, Accepted)
    assert (outcome.day, outcome.attempts, outcome.discarded, outcome.trace_id) == (DAY, 1, (), "quiz:2026-10-06:1")
    assert len(outcome.questions) == 5
    assert outcome.cost_usd > 0
    [entry] = client.ledger.entries
    assert (entry.task, entry.status, entry.trace_id) == (generate.TASK, CallStatus.OK, outcome.trace_id)
    assert (entry.user_id, entry.org_id) == (None, None)  # a platform job's call: the global caps apply


async def test_a_discarded_draft_is_retried_once_with_its_reason() -> None:
    client = fakes.FakeQuizClient(DAY, "duplicate_options", "valid")
    outcome = await draft_set(deps(client), DAY)
    assert isinstance(outcome, Accepted)
    assert (outcome.attempts, outcome.discarded, outcome.trace_id) == (
        2,
        (Reason.DUPLICATE_OPTIONS,),
        "quiz:2026-10-06:2",
    )
    first, second = client.requests
    assert not any("discarded by the checks" in b.text for m in first.messages for b in m.blocks)
    assert any("discarded by the checks (duplicate_options)" in b.text for m in second.messages for b in m.blocks)
    assert outcome.cost_usd == sum((e.cost_usd for e in client.ledger.entries), Decimal(0))


async def test_two_discarded_drafts_refuse_the_day() -> None:
    client = fakes.FakeQuizClient(DAY, "unknown_source", "names_a_person", "valid")
    outcome = await draft_set(deps(client), DAY)
    assert outcome == Refused(
        DAY, "names_a_person", 2, outcome.cost_usd, (Reason.UNKNOWN_SOURCE, Reason.NAMES_A_PERSON)
    )
    assert len(client.requests) == 2  # the third scripted answer is never asked for


async def test_a_repeated_prompt_is_refused_through_recent_hashes() -> None:
    sample = fakes.day_sample(DAY)
    recent = {prompt_hash(fakes.answer(sample).questions[0].prompt)}
    client = fakes.FakeQuizClient(DAY, "valid", "valid")
    outcome = await draft_set(deps(client), DAY, recent_hashes=recent)
    assert isinstance(outcome, Refused)
    assert (outcome.reason, outcome.discarded) == ("repeated_prompt", (Reason.REPEATED_PROMPT,) * 2)


async def test_the_day_gets_exactly_two_calls() -> None:
    """The card: a discarded draft is retried once, then the day gives up (``quiz.draft_attempts`` is pinned to 2)."""
    assert get_quiz_policy().draft_attempts == 2
    client = fakes.FakeQuizClient(DAY, "question_count", "question_count", "valid")
    outcome = await draft_set(deps(client), DAY)
    assert isinstance(outcome, Refused)
    assert (outcome.attempts, outcome.reason) == (2, "question_count")
    assert len(client.requests) == 2


async def test_the_kill_switch_refuses_without_a_call() -> None:
    client = fakes.FakeQuizClient(DAY, "valid", settings=settings(llm_kill_switch=True))
    outcome = await draft_set(deps(client), DAY)
    assert outcome == Refused(DAY, "llm_kill_switch", 1, Decimal(0))
    assert client.requests == []
    assert [e.status for e in client.ledger.entries] == [CallStatus.BLOCKED_KILL_SWITCH]


@pytest.mark.parametrize("cap", [Decimal(0), Decimal("0.005")])
async def test_the_daily_cap_refuses_without_a_call(cap: Decimal) -> None:
    """The pre-call estimate counts every requested output token (2048 at Haiku's 5 USD per million: 0.01 USD)."""
    client = fakes.FakeQuizClient(DAY, "valid", settings=settings(llm_global_daily_cap_usd=cap))
    outcome = await draft_set(deps(client), DAY)
    assert outcome == Refused(DAY, "llm_budget", 1, Decimal(0))
    assert client.requests == []
    assert [e.status for e in client.ledger.entries] == [CallStatus.BLOCKED_BUDGET]


class FallbackClient:
    """A local run's router when no model may answer: the schema's placeholder (D-37)."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete[OutputT: LLMOutput](
        self, task: str, messages: Sequence[Message], schema: type[OutputT], *, ctx: CallContext, **_: Any
    ) -> Result[OutputT]:
        self.calls += 1
        return fallback_result(schema, reason=FallbackReason.FAKE_PROVIDER, trace_id=ctx.trace_id or "t")


async def test_a_demo_fallback_is_never_a_set_and_not_retried() -> None:
    client = FallbackClient()
    outcome = await draft_set(deps(client), DAY)
    assert outcome == Refused(DAY, "demo_fallback", 1, Decimal(0))
    assert client.calls == 1


class MisconfiguredClient(FallbackClient):
    async def complete[OutputT: LLMOutput](
        self, task: str, messages: Sequence[Message], schema: type[OutputT], *, ctx: CallContext, **_: Any
    ) -> Result[OutputT]:
        raise LLMConfigError("unknown task")


async def test_a_callers_mistake_propagates() -> None:
    with pytest.raises(LLMConfigError):
        await draft_set(deps(MisconfiguredClient()), DAY)


async def test_the_cassette_replays_a_retry_through_the_real_sdk() -> None:
    """Interactions 1 and 2 of the eval cassette: an invented source id, then a clean set."""
    tape = CassettePlayer(load(CASSETTE)[:2])
    r = rig(tape.adapter())
    outcome = await draft_set(deps(r.service), DAY)
    assert tape.exhausted
    assert tape.errors == []
    assert isinstance(outcome, Accepted)
    assert (outcome.attempts, outcome.discarded, outcome.model) == (2, (Reason.UNKNOWN_SOURCE,), "claude-haiku-4-5")
    sources = get_sources().by_id()
    for question in outcome.questions:
        source = sources[question.source_id]
        assert (question.source_title, question.source_url, question.topic) == (source.title, source.url, source.topic)
    assert [q.source_id for q in outcome.questions] == [
        "pg-index-types",
        "mdn-http-status",
        "git-merge",
        "python-asyncio",
        "k8s-pods",
    ]
    assert [q.answer for q in outcome.questions] == [0, 1, 2, 3, 0]
    request: Mapping[str, Any] = tape.requests[0].json()
    assert "tools" not in request
    text = "\n".join(block["text"] for m in request["messages"] for block in m["content"])
    assert text.count("<submission nonce=") == get_quiz_policy().sources_per_prompt
    assert [e.status for e in r.ledger.entries] == [CallStatus.OK, CallStatus.OK]
