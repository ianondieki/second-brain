"""REQ-LLM-01: batch_submit / batch_poll (Batch API for nightly jobs, ADR-005 decision 5) over a synthetic cassette
and the scripted fake: same guard, framing, caps and ledger as synchronous calls; failed items are dead-lettered.

Reservations (T2.2 review M2 and m3): submission reserves every item at its batch-price estimate, so both caps count a
batch in flight; a poll settles each item once (the settled row replaces the reservation in spend), and a repeat poll
returns every outcome again but writes, dead-letters, queues and counts nothing twice.
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest

from bridge.llm.adapter import BatchItemError, BatchState, ModelResponse
from bridge.llm.budget import StaticCaps, day_start, month_start
from bridge.llm.client import BatchHandle, BatchItem
from bridge.llm.errors import (
    LLMBatchNotOwned,
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
from bridge.llm.fakes import FakeAdapter, Reply
from bridge.llm.ledger import CallStatus, LedgerEntry
from bridge.llm.registry import Registry
from bridge.llm.types import CallContext, InputField, Instruction, Message, Result, Tier, TokenUsage
from tests.unit.llm.helpers import NOW, ORG, OWNER, settings
from tests.unit.llm.rig import NONCE, Rig, registry_with, rig, screen
from tests.unit.llm.schemas import Verdict, player

TASK = "moderation_prescreen"
CTX = CallContext(org_id=ORG, trace_id="nightly-1")
IDS = ["item-ok", "item-refused", "item-bad", "item-errored", "item-expired"]
OK = {"injection_suspected": False, "verdict": "clean", "reason": "fine"}
RESERVED = "batch_reserved"


def batchable() -> Registry:
    return registry_with(moderation_prescreen={"batchable": True})


def items(*ids: str) -> list[BatchItem]:
    return [BatchItem(custom_id, screen(f"teaser {custom_id}")) for custom_id in ids]


def reserved(r: Rig) -> list[LedgerEntry]:
    return [e for e in r.ledger.entries if e.status.value == RESERVED]


def settled(r: Rig) -> list[LedgerEntry]:
    return [e for e in r.ledger.entries if e.batch_id is not None and e.status.value != RESERVED]


def ids(entries: list[LedgerEntry]) -> list[str]:
    """The rows' custom ids, sorted (every batch item's row has one)."""
    return sorted(str(e.custom_id) for e in entries)


def total(entries: list[LedgerEntry]) -> Decimal:
    return sum((e.cost_usd for e in entries), Decimal(0))


async def spend(r: Rig) -> tuple[Decimal, Decimal]:
    """(the organisation's spend this month, the platform's today), as the caps read them."""
    tenant = await r.ledger.tenant_spent_usd(org_id=ORG, user_id=None, since=month_start(NOW))
    return tenant, await r.ledger.global_spent_usd(since=day_start(NOW))


async def test_only_batchable_tasks_and_valid_ids() -> None:
    r = rig(FakeAdapter())
    with pytest.raises(LLMConfigError, match="not batchable"):
        await r.service.batch_submit(TASK, items("a"), Verdict, ctx=CTX)
    r = rig(FakeAdapter(), reg=batchable())
    for bad in ([], items("a", "a"), items("has space"), items("x" * 65)):
        with pytest.raises(LLMConfigError, match="custom ids"):
            await r.service.batch_submit(TASK, bad, Verdict, ctx=CTX)
    with pytest.raises(LLMConfigError, match="last message"):
        await r.service.batch_submit(TASK, [BatchItem("a", [Message.assistant(Instruction("x"))])], Verdict, ctx=CTX)


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
    assert ids(reserved(r)) == sorted(IDS)
    assert sorted(e.status.value for e in settled(r)) == sorted(
        ["ok", "refusal", "schema_error", "provider_error", "provider_error"]
    )
    assert ids(settled(r)) == sorted(IDS)
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
        await r.service.batch_submit(TASK, [BatchItem("a", [Message.user(Instruction("x"), secret)])], Verdict, ctx=CTX)
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
    assert settled(r)[0].output == OK
    assert len(r.listener.events) == 1


class ResultsWithout(FakeAdapter):
    """The provider's results lack the items in ``missing`` (they never ran, or the results file was cut short)."""

    def __init__(self, replies: list[Reply], missing: set[str]) -> None:
        super().__init__(replies)
        self.missing = missing

    async def batch_results(self, batch_id: str) -> dict[str, ModelResponse | BatchItemError]:
        results = await super().batch_results(batch_id)
        return {custom_id: item for custom_id, item in results.items() if custom_id not in self.missing}


async def test_an_item_missing_from_the_results_is_reported_and_stays_reserved_until_a_poll_finds_it() -> None:
    """A missing item has not settled: the results may have been cut short (and the item billed), so its reservation
    keeps counting and every poll reports it as transient; a poll whose results hold it settles it."""
    adapter = ResultsWithout([OK] * 9, missing={"b"})  # three polls of three items
    r = rig(adapter, reg=batchable())
    handle = await r.service.batch_submit(TASK, items("a", "b", "c"), Verdict, ctx=CTX)
    [held] = [e for e in reserved(r) if e.custom_id == "b"]
    for _ in range(2):
        done = await r.service.batch_poll(handle, Verdict)
        assert set(done.results) == {"a", "b", "c"}
        assert isinstance(done.results["a"], Result)
        missing = done.results["b"]
        assert isinstance(missing, LLMProviderError)
        assert "batch item missing" in str(missing)
        assert missing.transient  # it may never have run: the caller may resubmit it
        assert ids(settled(r)) == ["a", "c"]
        assert await spend(r) == (held.cost_usd + total(settled(r)),) * 2  # its estimate still counts
    assert r.dead_letters.letters == []
    adapter.missing = set()
    found = await r.service.batch_poll(handle, Verdict)
    assert isinstance(found.results["b"], Result)
    assert ids(settled(r)) == ["a", "b", "c"]
    assert await spend(r) == (total(settled(r)),) * 2


async def test_submit_reserves_every_item_at_its_batch_estimate() -> None:
    reg = batchable()
    adapter = FakeAdapter()
    r = rig(adapter, reg=reg)
    handle = await r.service.batch_submit(TASK, items(*IDS), Verdict, ctx=CTX)
    rows = reserved(r)
    assert [e.custom_id for e in rows] == IDS
    assert r.ledger.entries == rows  # nothing else is written at submission
    for row, request in zip(rows, adapter.requests, strict=True):
        estimate = reg.estimate_usd(
            request.model,
            input_chars=request.text_chars,
            max_tokens=request.max_tokens,
            batch=True,
            cache_writes=request.cache_writes,
        )
        assert (row.batch_id, row.cost_usd, row.model, row.org_id, row.trace_id) == (
            handle.batch_id,
            estimate,
            handle.model,
            ORG,
            "nightly-1",
        )
        assert (row.input_tokens, row.output_tokens, row.stop_reason) == (0, 0, None)
        assert row.inputs == handle.inputs[str(row.custom_id)]
    assert total(rows) > 0
    assert await spend(r) == (total(rows), total(rows))  # both caps count the batch in flight


@pytest.mark.parametrize("scope", ["global", "tenant"])
async def test_the_caps_refuse_further_batches_while_one_is_in_flight(scope: str) -> None:
    """The review's scenario: room for about one and a half batches. The first submission passes and reserves; the
    next ones are refused until it settles, which frees its reservation (the settled cost is below the estimate)."""
    probe = rig(FakeAdapter(), reg=batchable())
    await probe.service.batch_submit(TASK, items(*IDS), Verdict, ctx=CTX)
    one = total(reserved(probe))
    room = one * Decimal("1.5")
    adapter = FakeAdapter([OK] * len(IDS))
    if scope == "global":
        r = rig(adapter, reg=batchable(), cfg=settings(llm_global_daily_cap_usd=room))
    else:
        r = rig(adapter, reg=batchable(), caps=StaticCaps(caps={ORG: room}))
    handle = await r.service.batch_submit(TASK, items(*IDS), Verdict, ctx=CTX)
    for _ in range(3):
        with pytest.raises(LLMBudgetExceeded) as info:
            await r.service.batch_submit(TASK, items(*IDS), Verdict, ctx=CTX)
        assert (info.value.scope, info.value.spent_usd, info.value.cap_usd) == (scope, one, room)
    assert len(adapter.requests) == len(IDS)  # only the first batch reached the provider
    assert [e.status.value for e in r.ledger.entries] == [RESERVED] * len(IDS) + ["blocked_budget"] * 3
    await r.service.batch_poll(handle, Verdict)
    assert total(settled(r)) < one
    assert await spend(r) == (total(settled(r)),) * 2
    await r.service.batch_submit(TASK, items(*IDS), Verdict, ctx=CTX)  # room again
    assert len(adapter.requests) == 2 * len(IDS)


def costly(stop: str = "end_turn", text: str = json.dumps(OK)) -> ModelResponse:
    """A result costing more than its reservation (4000 output tokens; the estimate counts max_tokens=1024)."""
    return ModelResponse(text=text, stop_reason=stop, usage=TokenUsage(300, 4000), model="m")


async def test_a_repeat_poll_returns_every_outcome_and_counts_nothing_twice() -> None:
    reg = batchable()
    names = ["ok", "refused", "bad", "errored"]
    replies: list[Reply] = [
        costly(),
        costly("refusal", ""),
        costly(text="not json"),
        BatchItemError("errored", "invalid_request"),
    ]
    adapter = FakeAdapter(replies * 2)  # an ended batch's results, fetched on each poll
    real = reg.cost_usd(reg.task(TASK).model, TokenUsage(300, 4000), batch=True) * 3
    r = rig(adapter, reg=reg, caps=StaticCaps(caps={ORG: real}))  # the settled costs reach the cap
    handle = await r.service.batch_submit(TASK, items(*names), Verdict, ctx=CTX)
    first = await r.service.batch_poll(handle, Verdict)
    rows, letters = list(r.ledger.entries), list(r.dead_letters.letters)
    refusals, crossings = list(r.human_queue.events), list(r.listener.events)
    assert (len(letters), len(refusals), len(crossings)) == (2, 1, 1)
    assert await spend(r) == (real, real)
    again = await r.service.batch_poll(handle, Verdict)
    assert r.ledger.entries == rows
    assert (r.dead_letters.letters, r.human_queue.events, r.listener.events) == (letters, refusals, crossings)
    assert await spend(r) == (real, real)
    assert ids(settled(r)) == sorted(names)  # one settlement per item
    assert set(again.results) == set(first.results) == set(names)
    for custom_id in names:
        assert type(again.results[custom_id]) is type(first.results[custom_id])
    ok, ok_again = first.results["ok"], again.results["ok"]
    assert isinstance(ok, Result)
    assert isinstance(ok_again, Result)
    assert (ok_again.parsed, ok_again.cost_usd) == (ok.parsed, ok.cost_usd)
    assert ok.budget.spent_usd == ok_again.budget.spent_usd == real
    assert ok.budget.soft_cap_reached
    assert ok_again.budget.soft_cap_reached
    refused, refused_again = first.results["refused"], again.results["refused"]
    assert isinstance(refused, LLMRefused)
    assert isinstance(refused_again, LLMRefused)
    assert refused.dead_letter_id == str(letters[0].id)
    assert refused_again.dead_letter_id is None  # dead-lettered by the first poll, not again
    assert isinstance(again.results["bad"], LLMSchemaError)
    errored = again.results["errored"]
    assert isinstance(errored, LLMProviderError)
    assert not errored.transient


class Watched(FakeAdapter):
    """Records which batches' state and results were read."""

    def __init__(self, replies: list[Reply]) -> None:
        super().__init__(replies)
        self.reads: list[str] = []

    async def batch_state(self, batch_id: str) -> BatchState:
        self.reads.append(f"state {batch_id}")
        return await super().batch_state(batch_id)

    async def batch_results(self, batch_id: str) -> dict[str, ModelResponse | BatchItemError]:
        self.reads.append(f"results {batch_id}")
        return await super().batch_results(batch_id)


async def test_another_tenant_polling_the_batch_cannot_settle_its_items() -> None:
    """A handle naming another tenant's batch (one provider account serves every tenant) is refused before the
    batch's state or results are read (``app_llm_batch_owned``); the owner's reservations keep counting and the
    owner's own poll settles them, as the owner."""
    adapter = Watched([OK] * 4)
    r = rig(adapter, reg=batchable())
    handle = await r.service.batch_submit(TASK, items("a", "b"), Verdict, ctx=CTX)
    held = total(reserved(r))
    forged = handle.model_copy(update={"org_id": None, "user_id": OWNER, "trace_id": "forged"})
    with pytest.raises(LLMBatchNotOwned) as info:
        await r.service.batch_poll(forged, Verdict)
    assert info.value.code == "llm_batch_not_owned"
    assert adapter.reads == []  # neither its state nor its results
    assert settled(r) == []
    assert await spend(r) == (held, held)
    await r.service.batch_poll(handle, Verdict)
    assert adapter.reads == [f"state {handle.batch_id}", f"results {handle.batch_id}"]
    assert ids(settled(r)) == ["a", "b"]
    assert {(e.org_id, e.user_id) for e in settled(r)} == {(ORG, None)}


async def test_a_later_reservation_of_another_tenant_does_not_take_the_batch() -> None:
    """Round 6: the batch is the tenant's of its earliest reservation. Another tenant that reserves an item of it
    afterwards (a squatted item) still cannot poll it, and its own reservation keeps counting against it."""
    adapter = Watched([OK] * 2)
    r = rig(adapter, reg=batchable())
    handle = await r.service.batch_submit(TASK, items("a", "b"), Verdict, ctx=CTX)
    [first] = [e for e in reserved(r) if e.custom_id == "a"]
    squat = replace(first, id=uuid4(), org_id=None, user_id=OWNER, trace_id="squat")
    await r.ledger.reserve([squat])
    forged = handle.model_copy(update={"org_id": None, "user_id": OWNER, "trace_id": "forged"})
    with pytest.raises(LLMBatchNotOwned):
        await r.service.batch_poll(forged, Verdict)
    assert adapter.reads == []
    await r.service.batch_poll(handle, Verdict)
    assert {(e.custom_id, e.org_id, e.user_id) for e in settled(r)} == {("a", ORG, None), ("b", ORG, None)}
    mine = await r.ledger.tenant_spent_usd(org_id=None, user_id=OWNER, since=month_start(NOW))
    assert mine == squat.cost_usd  # the squatter's reservation never settles
