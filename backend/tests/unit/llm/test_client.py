"""REQ-LLM-01: LLMService.complete over synthetic cassettes (the real adapter and SDK) and the scripted fake.

Covers the ADR-005 retry rules (refusal -> human queue + one retry on the fallback model; max_tokens -> one retry at
2x; schema failure -> one retry with the error, then the dead-letter queue), the ledger row per attempt, the kill
switch and caps, the framing of untrusted text, and the caller-facing validation.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from pydantic import BaseModel

from bridge.llm.adapter import ModelResponse
from bridge.llm.budget import StaticCaps
from bridge.llm.errors import (
    LLMBudgetExceeded,
    LLMConfigError,
    LLMKillSwitch,
    LLMProviderError,
    LLMRefused,
    LLMSchemaError,
    LLMTruncated,
    LLMUnavailable,
    LLMUnsupportedStop,
)
from bridge.llm.fakes import FakeAdapter
from bridge.llm.ledger import CallStatus
from bridge.llm.sanitiser import FRAMING_RULES
from bridge.llm.types import CallContext, InputField, Instruction, LLMOutput, Message, TokenUsage
from tests.unit.llm.helpers import ORG, USER, real_registry, settings
from tests.unit.llm.rig import NONCE, registry_with, rig, screen
from tests.unit.llm.schemas import Verdict, player

TASK = "moderation_prescreen"
CTX = CallContext(org_id=ORG, user_id=USER, trace_id="trace-1")
OK = {"injection_suspected": False, "verdict": "clean", "reason": "fine"}


def statuses(entries: Any) -> list[CallStatus]:
    return [e.status for e in entries]


async def test_happy_path_frames_sanitises_records_and_prices() -> None:
    tape = player("messages_verdict_ok")
    r = rig(tape.adapter())
    result = await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert result.parsed == Verdict(
        injection_suspected=False, verdict="clean", reason="No policy issue found in the teaser."
    )
    assert (result.stop_reason, result.attempts, result.trace_id) == ("end_turn", 1, "trace-1")
    model = real_registry().task(TASK).model
    usage = TokenUsage(812, 31, 600, 300, 100)
    assert result.usage == usage
    assert result.cost_usd == real_registry().cost_usd(model, usage) > 0
    body = tape.requests[0].json()
    assert body["system"][0]["text"].startswith("You screen teasers for policy issues.")
    assert body["system"][0]["text"].endswith(FRAMING_RULES)
    assert NONCE in body["system"][1]["text"]
    user = body["messages"][0]["content"]
    assert user[0]["text"] == "Screen this teaser:"
    assert user[1]["text"] == (
        f'<submission nonce="{NONCE}" field="teaser.summary" tier="tier1">\nSolar kiosks for markets\n'
        f'</submission nonce="{NONCE}">'
    )
    [entry] = r.ledger.entries
    assert entry.status is CallStatus.OK
    assert (entry.org_id, entry.user_id, entry.task, entry.purpose, entry.model) == (
        ORG,
        USER,
        TASK,
        "tier1_only",
        model,
    )
    assert (entry.input_tokens, entry.output_tokens, entry.cache_read_tokens, entry.cache_creation_tokens) == (
        812,
        31,
        600,
        300,
    )
    assert entry.cost_usd == result.cost_usd
    assert entry.latency_ms == 250
    assert entry.stop_reason == "end_turn"
    assert entry.trace_id == "trace-1"
    assert entry.output is None  # confidential by default
    [field] = entry.inputs["fields"]
    assert field == {
        "name": "teaser.summary",
        "tier": "tier1",
        "chars": len("Solar kiosks for markets"),
        "removed": ["html", "markdown_link"],
        "value": "Solar kiosks for markets",
    }
    assert len(entry.inputs["prompt_sha256"]) == 64


async def test_injection_flag_reaches_the_caller() -> None:
    result = await rig(player("messages_verdict_injection").adapter()).service.complete(
        TASK, screen(), Verdict, ctx=CTX
    )
    assert result.parsed.injection_suspected is True


async def test_citations_are_returned() -> None:
    result = await rig(player("messages_with_citations").adapter()).service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert [c.source for c in result.citations] == ["Grid report", "https://example.org/t"]


FALLBACK = {"fallback_model": "claude-sonnet-5", "fallback_effort": "low"}  # the registry ships none (D-29)


async def test_refusal_goes_to_the_human_queue_and_retries_once_on_the_fallback() -> None:
    tape = player("messages_refusal_then_ok")
    reg = registry_with(moderation_prescreen=FALLBACK)
    r = rig(tape.adapter(), reg=reg)
    spec = reg.task(TASK)
    result = await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert result.model == spec.fallback_model
    assert result.attempts == 2
    first, second = (req.json() for req in tape.requests)
    assert first["model"] == spec.model
    assert second["model"] == spec.fallback_model
    assert second["output_config"]["effort"] == spec.fallback_effort
    assert statuses(r.ledger.entries) == [CallStatus.REFUSAL, CallStatus.OK]
    [event] = r.human_queue.events
    assert (event.category, event.will_retry_on, event.task) == ("cyber", spec.fallback_model, TASK)
    assert r.dead_letters.letters == []


async def test_second_refusal_is_dead_lettered() -> None:
    r = rig(player("messages_refusal_twice").adapter(), reg=registry_with(moderation_prescreen=FALLBACK))
    with pytest.raises(LLMRefused) as info:
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert statuses(r.ledger.entries) == [CallStatus.REFUSAL, CallStatus.REFUSAL]
    assert [e.will_retry_on for e in r.human_queue.events][1] is None
    [letter] = r.dead_letters.letters
    assert (letter.reason, letter.attempts, letter.task) == ("refusal", 2, TASK)
    assert info.value.dead_letter_id == str(letter.id)
    assert letter.inputs["fields"][0]["name"] == "teaser.summary"


async def test_refusal_without_a_fallback_is_dead_lettered_at_once() -> None:
    """The shipped registry: no fallback, so a refusal goes straight to the human queue and the dead-letter queue."""
    assert real_registry().task(TASK).fallback_model is None
    r = rig(player("messages_refusal_twice").adapter())
    with pytest.raises(LLMRefused):
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert statuses(r.ledger.entries) == [CallStatus.REFUSAL]
    assert r.human_queue.events[0].will_retry_on is None


async def test_max_tokens_retries_once_at_twice_the_budget() -> None:
    tape = player("messages_max_tokens_then_ok")
    r = rig(tape.adapter())
    result = await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    budget = real_registry().task(TASK).max_tokens
    assert [req.json()["max_tokens"] for req in tape.requests] == [budget, 2 * budget]
    assert result.attempts == 2
    assert statuses(r.ledger.entries) == [CallStatus.MAX_TOKENS, CallStatus.OK]
    assert result.usage.output_tokens == 1024 + 31


async def test_second_max_tokens_is_dead_lettered() -> None:
    r = rig(player("messages_max_tokens_twice").adapter())
    with pytest.raises(LLMTruncated):
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert [letter.reason for letter in r.dead_letters.letters] == ["max_tokens"]


async def test_max_tokens_at_the_model_ceiling_is_not_retried() -> None:
    reg = registry_with(moderation_prescreen={"max_tokens": 64000})
    r = rig(player("messages_max_tokens_twice").adapter(), reg=reg)
    with pytest.raises(LLMTruncated):
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert statuses(r.ledger.entries) == [CallStatus.MAX_TOKENS]


async def test_schema_failure_retries_once_with_the_error() -> None:
    tape = player("messages_schema_invalid_then_ok")
    r = rig(tape.adapter())
    result = await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert result.parsed.verdict == "clean"
    retry = tape.requests[1].json()["messages"][-1]["content"][-1]["text"]
    assert "did not match the required JSON schema" in retry
    assert "verdict: literal_error" in retry
    assert "reason: missing" in retry
    assert statuses(r.ledger.entries) == [CallStatus.SCHEMA_ERROR, CallStatus.OK]
    assert "verdict" in (r.ledger.entries[0].error or "")


async def test_second_schema_failure_is_dead_lettered() -> None:
    r = rig(player("messages_schema_invalid_twice").adapter())
    with pytest.raises(LLMSchemaError) as info:
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    [letter] = r.dead_letters.letters
    assert letter.reason == "schema_error"
    assert "injection_suspected" in letter.detail
    assert "missing the flag" not in letter.detail  # the model's text is not copied, only locations and messages
    assert info.value.trace_id == "trace-1"


async def test_unsupported_stop_reason_is_dead_lettered() -> None:
    r = rig(player("messages_tool_use").adapter())
    with pytest.raises(LLMUnsupportedStop):
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert statuses(r.ledger.entries) == [CallStatus.UNSUPPORTED_STOP]
    assert r.dead_letters.letters[0].reason == "unsupported_stop"


async def test_provider_errors_are_recorded_and_raised_without_dead_letter() -> None:
    r = rig(player("messages_overloaded").adapter())
    with pytest.raises(LLMProviderError) as info:
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert info.value.transient
    assert statuses(r.ledger.entries) == [CallStatus.PROVIDER_ERROR]
    assert r.ledger.entries[0].cost_usd == 0
    assert r.dead_letters.letters == []


async def test_no_key_is_recorded_as_unavailable() -> None:
    r = rig(FakeAdapter([LLMUnavailable("no key")]))
    with pytest.raises(LLMUnavailable):
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert r.ledger.entries[0].error == "no key"


async def test_kill_switch_refuses_before_sending() -> None:
    adapter = FakeAdapter([OK])
    r = rig(adapter, cfg=settings(llm_kill_switch=True))
    with pytest.raises(LLMKillSwitch):
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert adapter.requests == []
    [entry] = r.ledger.entries
    assert entry.status is CallStatus.BLOCKED_KILL_SWITCH
    assert (entry.cost_usd, entry.model, entry.attempt) == (Decimal(0), None, 0)
    assert "value" not in entry.inputs["fields"][0]


async def test_global_cap_refuses_before_sending() -> None:
    adapter = FakeAdapter([OK])
    r = rig(adapter, cfg=settings(llm_global_daily_cap_usd=Decimal(0)))
    with pytest.raises(LLMBudgetExceeded) as info:
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert info.value.scope == "global"
    assert adapter.requests == []
    assert statuses(r.ledger.entries) == [CallStatus.BLOCKED_BUDGET]


async def test_tenant_hard_cap_and_soft_cap() -> None:
    """Each answer costs 1200 output tokens (0.006 USD at the placeholder Haiku price); the monthly cap is 0.02, so
    the third answer crosses the 80% soft cap and the fourth attempt's estimate would pass the hard cap."""
    costly = ModelResponse(text=json.dumps(OK), stop_reason="end_turn", usage=TokenUsage(output_tokens=1200), model="m")
    adapter = FakeAdapter([costly] * 10)
    r = rig(adapter, caps=StaticCaps(caps={ORG: Decimal("0.02")}))
    results = [await r.service.complete(TASK, screen(), Verdict, ctx=CTX) for _ in range(3)]
    with pytest.raises(LLMBudgetExceeded) as info:
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert info.value.scope == "tenant"
    assert [res.budget.soft_cap_reached for res in results] == [False, False, True]
    assert results[0].budget.spent_usd == results[0].cost_usd == Decimal("0.006")
    assert results[0].budget.cap_usd == Decimal("0.02")
    assert len(r.listener.events) == 1
    assert len(adapter.requests) == 3
    assert r.ledger.entries[-1].status is CallStatus.BLOCKED_BUDGET


async def test_effort_override_rules() -> None:
    adapter = FakeAdapter([OK])
    r = rig(adapter)
    await r.service.complete("originality_explainer", screen(), Verdict, ctx=CTX, effort="high")
    assert adapter.requests[0].effort == "high"
    with pytest.raises(LLMConfigError, match="no effort parameter"):
        await r.service.complete(TASK, screen(), Verdict, ctx=CTX, effort="high")
    with pytest.raises(LLMConfigError, match="one of"):
        await r.service.complete("originality_explainer", screen(), Verdict, ctx=CTX, effort="turbo")


async def test_default_effort_comes_from_the_registry() -> None:
    adapter = FakeAdapter([OK, OK])
    r = rig(adapter)
    await r.service.complete("originality_explainer", screen(), Verdict, ctx=CTX)
    await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert [req.effort for req in adapter.requests] == ["medium", None]


async def test_tools_are_refused_unless_the_task_allows_them() -> None:
    tool = {"type": "web_search_20260209", "name": "web_search"}
    with pytest.raises(LLMConfigError, match="may not use tool"):
        await rig(FakeAdapter()).service.complete(TASK, screen(), Verdict, ctx=CTX, tools=[tool])
    reg = registry_with(moderation_prescreen={"allowed_tools": ["web_search_20260209", "lookup"]})
    adapter = FakeAdapter([OK])
    await rig(adapter, reg=reg).service.complete(TASK, screen(), Verdict, ctx=CTX, tools=[tool])
    assert adapter.requests[0].tools == (tool,)
    with pytest.raises(LLMConfigError, match="strict"):
        await rig(FakeAdapter(), reg=reg).service.complete(
            TASK, screen(), Verdict, ctx=CTX, tools=[{"name": "lookup", "input_schema": {}}]
        )
    with pytest.raises(LLMConfigError, match="unnamed"):
        await rig(FakeAdapter(), reg=reg).service.complete(TASK, screen(), Verdict, ctx=CTX, tools=[{}])
    custom = {"type": "custom", "name": "lookup", "input_schema": {"type": "object"}, "strict": True}
    adapter = FakeAdapter([OK])
    await rig(adapter, reg=reg).service.complete(TASK, screen(), Verdict, ctx=CTX, tools=[custom])
    assert adapter.requests[0].tools == (custom,)


class NoFlag(BaseModel):
    verdict: str


class WrongFlag(LLMOutput):
    injection_suspected: str  # type: ignore[assignment]


@pytest.mark.parametrize("schema", [NoFlag, WrongFlag])
async def test_every_schema_needs_injection_suspected(schema: Any) -> None:
    with pytest.raises(LLMConfigError, match="injection_suspected"):
        await rig(FakeAdapter()).service.complete(TASK, screen(), schema, ctx=CTX)


@pytest.mark.parametrize(
    ("messages", "match"),
    [
        ([], "at least one message"),
        ([Message.user(Instruction("a")), Message.system("b"), Message.user(Instruction("c"))], "first message"),
        ([Message.user(Instruction("a")), Message.assistant(Instruction("b"))], "last message"),
    ],
)
async def test_message_order_is_checked(messages: list[Message], match: str) -> None:
    with pytest.raises(LLMConfigError, match=match):
        await rig(FakeAdapter()).service.complete(TASK, messages, Verdict, ctx=CTX)


async def test_cache_breakpoints() -> None:
    adapter = FakeAdapter([OK, OK])
    r = rig(adapter)
    conversation = [*screen(), Message.assistant(Instruction("Noted.")), Message.user(Instruction("Now answer."))]
    await r.service.complete(TASK, conversation, Verdict, ctx=CTX, cache_breakpoints=[0, 1])
    request = adapter.requests[0]
    assert [b.cache for b in request.system] == [True, False]  # the nonce line stays after the breakpoint
    assert [b.cache for b in request.messages[0].blocks] == [False, True]
    assert not any(b.cache for m in request.messages[1:] for b in m.blocks)
    await r.service.complete(TASK, [Message.user(Instruction("no system"))], Verdict, ctx=CTX, cache_breakpoints=[0])
    no_system = adapter.requests[1]
    assert no_system.system[0].text == FRAMING_RULES
    assert not no_system.system[0].cache
    with pytest.raises(LLMConfigError, match="at most 4"):
        await r.service.complete(TASK, conversation, Verdict, ctx=CTX, cache_breakpoints=[0, 1, 2, 3, 4])
    with pytest.raises(LLMConfigError, match="indexes"):
        await r.service.complete(TASK, conversation, Verdict, ctx=CTX, cache_breakpoints=[9])


async def test_non_confidential_tasks_keep_the_output() -> None:
    reg = registry_with(moderation_prescreen={"confidential": False})
    r = rig(FakeAdapter([OK]), reg=reg)
    await r.service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert r.ledger.entries[0].output == OK


async def test_trace_id_is_generated_when_absent_and_unknown_tasks_fail() -> None:
    r = rig(FakeAdapter([OK]))
    result = await r.service.complete(TASK, screen(), Verdict, ctx=CallContext())
    assert len(result.trace_id) == 32
    assert result.budget.cap_usd is None  # a platform call: global cap only
    with pytest.raises(LLMConfigError, match="unknown LLM task"):
        await r.service.complete("nope", screen(), Verdict, ctx=CTX)


async def test_field_caps_and_long_input() -> None:
    adapter = FakeAdapter([OK])
    r = rig(adapter)
    field = InputField("teaser.summary", "word " * 500, max_chars=40)
    await r.service.complete(TASK, [Message.user(Instruction("Screen:"), field)], Verdict, ctx=CTX)
    recorded = r.ledger.entries[0].inputs["fields"][0]
    assert recorded["chars"] <= 40
    assert "truncated" in recorded["removed"]


async def test_scripted_model_response_passes_through() -> None:
    response = ModelResponse(
        text='{"injection_suspected": false, "verdict": "hold", "reason": "r"}',
        stop_reason="stop_sequence",
        usage=TokenUsage(1, 1),
        model="m",
    )
    result = await rig(FakeAdapter([response])).service.complete(TASK, screen(), Verdict, ctx=CTX)
    assert result.parsed.verdict == "hold"
