"""REQ-LLM-01: batch_submit / batch_poll (Batch API for nightly jobs, ADR-005 decision 5) over a synthetic cassette
and the scripted fake: same guard, framing, caps and ledger as synchronous calls; failed items are dead-lettered."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from bridge.llm.adapter import BatchItemError, BatchState, ModelResponse
from bridge.llm.budget import StaticCaps
from bridge.llm.client import BatchHandle, BatchItem
from bridge.llm.errors import (
    LLMBudgetExceeded,
    LLMConfigError,
    LLMKillSwitch,
    LLMProviderError,
    LLMRefused,
    LLMSchemaError,
    LLMTruncated,
    LLMUnsupportedStop,
    Tier2NotAllowed,
)
from bridge.llm.fakes import FakeAdapter
from bridge.llm.ledger import CallStatus
from bridge.llm.registry import Registry
from bridge.llm.types import CallContext, InputField, Message, Result, Tier, TokenUsage
from tests.unit.llm.helpers import ORG, OWNER, settings
from tests.unit.llm.rig import NONCE, registry_with, rig, screen
from tests.unit.llm.schemas import Verdict, player

TASK = "moderation_prescreen"
CTX = CallContext(org_id=ORG, trace_id="nightly-1")
IDS = ["item-ok", "item-refused", "item-bad", "item-errored", "item-expired"]
OK = {"injection_suspected": False, "verdict": "clean", "reason": "fine"}


def batchable() -> Registry:
    return registry_with(moderation_prescreen={"batchable": True})


def items(*ids: str) -> list[BatchItem]:
    return [BatchItem(custom_id, screen(f"teaser {custom_id}")) for custom_id in ids]


async def test_only_batchable_tasks_and_valid_ids() -> None:
    r = rig(FakeAdapter())
    with pytest.raises(LLMConfigError, match="not batchable"):
        await r.service.batch_submit(TASK, items("a"), Verdict, ctx=CTX)
    r = rig(FakeAdapter(), reg=batchable())
    for bad in ([], items("a", "a"), items("has space"), items("x" * 65)):
        with pytest.raises(LLMConfigError, match="custom ids"):
            await r.service.batch_submit(TASK, bad, Verdict, ctx=CTX)
    with pytest.raises(LLMConfigError, match="last message"):
        await r.service.batch_submit(TASK, [BatchItem("a", [Message.assistant("x")])], Verdict, ctx=CTX)


async def test_submit_poll_and_read_every_outcome() -> None:
    tape = player("batch_nightly")
    r = rig(tape.adapter(), reg=batchable())
    handle = await r.service.batch_submit(TASK, items(*IDS), Verdict, ctx=CTX, cache_breakpoints=[0])
    assert handle.batch_id == "msgbatch_syn_01"
    assert BatchHandle.model_validate_json(handle.model_dump_json()) == handle
    assert handle.inputs["item-ok"]["fields"][0]["value"] == "teaser item-ok"
    body = tape.requests[0].json()
    assert [req["custom_id"] for req in body["requests"]] == IDS
    params = body["requests"][0]["params"]
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert f'<submission nonce="{NONCE}"' in params["messages"][0]["content"][1]["text"]
    assert "tool_choice" not in params

    waiting = await r.service.batch_poll(handle, Verdict)
    assert waiting.state is BatchState.IN_PROGRESS
    assert waiting.results == {}

    done = await r.service.batch_poll(handle, Verdict)
    assert done.state is BatchState.ENDED
    ok = done.results["item-ok"]
    assert isinstance(ok, Result)
    assert ok.parsed.verdict == "clean"
    reg = batchable()
    expected = reg.cost_usd(handle.model, TokenUsage(700, 30), batch=True)
    assert ok.cost_usd == expected
    assert ok.cost_usd < reg.cost_usd(handle.model, TokenUsage(700, 30))
    assert isinstance(done.results["item-refused"], LLMRefused)
    assert isinstance(done.results["item-bad"], LLMSchemaError)
    errored, expired = done.results["item-errored"], done.results["item-expired"]
    assert isinstance(errored, LLMProviderError)
    assert not errored.transient
    assert isinstance(expired, LLMProviderError)
    assert expired.transient
    assert tape.exhausted

    assert {e.batch_id for e in r.ledger.entries} == {"msgbatch_syn_01"}
    assert sorted(e.status.value for e in r.ledger.entries) == sorted(
        ["ok", "refusal", "schema_error", "provider_error", "provider_error"]
    )
    assert sorted(letter.reason for letter in r.dead_letters.letters) == ["refusal", "schema_error"]
    assert [event.will_retry_on for event in r.human_queue.events] == [None]


async def test_batch_is_guarded_like_a_call() -> None:
    adapter = FakeAdapter()
    r = rig(adapter, reg=batchable(), cfg=settings(llm_kill_switch=True))
    with pytest.raises(LLMKillSwitch):
        await r.service.batch_submit(TASK, items("a"), Verdict, ctx=CTX)
    r = rig(adapter, reg=batchable())
    secret = InputField("confidential.method", "SECRET", tier=Tier.TIER2, owner_id=OWNER)
    with pytest.raises(Tier2NotAllowed):
        await r.service.batch_submit(TASK, [BatchItem("a", [Message.user("x", secret)])], Verdict, ctx=CTX)
    assert "SECRET" not in json.dumps([e.inputs for e in r.ledger.entries])
    r = rig(adapter, reg=batchable(), cfg=settings(llm_global_daily_cap_usd=Decimal(0)))
    with pytest.raises(LLMBudgetExceeded):
        await r.service.batch_submit(TASK, items("a", "b"), Verdict, ctx=CTX)
    [blocked] = r.ledger.entries
    assert blocked.status is CallStatus.BLOCKED_BUDGET
    assert set(blocked.inputs["batch_items"]) == {"a", "b"}
    assert adapter.requests == []


async def test_submit_provider_error_is_recorded() -> None:
    r = rig(player("messages_overloaded").adapter(), reg=batchable())
    with pytest.raises(LLMProviderError):
        await r.service.batch_submit(TASK, items("a"), Verdict, ctx=CTX)
    assert [e.status for e in r.ledger.entries] == [CallStatus.PROVIDER_ERROR]


async def test_other_stop_reasons_outputs_and_the_soft_cap() -> None:
    def response(stop: str, text: str = json.dumps(OK)) -> ModelResponse:
        return ModelResponse(text=text, stop_reason=stop, usage=TokenUsage(output_tokens=4000), model="m")

    adapter = FakeAdapter(
        [
            response("end_turn"),
            response("max_tokens"),
            response("tool_use"),
            BatchItemError("errored", "overloaded_error"),
        ]
    )
    adapter.batch_states.extend([BatchState.CANCELING])
    reg = registry_with(moderation_prescreen={"batchable": True, "confidential": False})
    r = rig(adapter, reg=reg, caps=StaticCaps(caps={ORG: Decimal("0.02")}))
    handle = await r.service.batch_submit(TASK, items("a", "b", "c", "d"), Verdict, ctx=CTX)
    assert (await r.service.batch_poll(handle, Verdict)).state is BatchState.CANCELING
    done = await r.service.batch_poll(handle, Verdict)
    first = done.results["a"]
    assert isinstance(first, Result)
    assert first.budget.soft_cap_reached  # 4 x 4000 tokens x 5 USD/M x 0.5 = 0.02 of a 0.02 cap, read at poll time
    assert isinstance(done.results["b"], LLMTruncated)
    assert isinstance(done.results["c"], LLMUnsupportedStop)
    transient = done.results["d"]
    assert isinstance(transient, LLMProviderError)
    assert transient.transient
    assert r.ledger.entries[0].output == OK
    assert len(r.listener.events) == 1
