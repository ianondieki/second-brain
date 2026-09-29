"""REQ-LLM-01 P7 (D-37): the Anthropic route of ``RoutedLLMClient`` and batches on every route.

Anthropic runs only with ``LLM_PROVIDER=anthropic``, a key and prices marked verified in ``ai/models.yaml`` (fail
closed), under the T2.2 rules plus the USD 1 daily and USD 5 prototype caps; a failure falls back to the labelled fake
on local runs. Free providers and the fake have no batch API: a batch there gets a ``demo_fallback`` handle the fake
answers. Synthetic cassettes and fakes only (D-18: no paid calls; AC-SEC-5).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import respx

from bridge.llm import registry as registry_module
from bridge.llm.adapter import BatchState
from bridge.llm.anthropic_adapter import AnthropicAdapter
from bridge.llm.client import BatchHandle, BatchItem
from bridge.llm.demo_fallback import DEMO_FALLBACK_MODEL, fallback_output
from bridge.llm.errors import (
    ConsentRequired,
    LLMConfigError,
    LLMProviderError,
    LLMUnavailable,
    Tier2DemoOnly,
)
from bridge.llm.fakes import FakeAdapter
from bridge.llm.guard import StaticConsents
from bridge.llm.ledger import CallStatus, LedgerEntry
from bridge.llm.registry import Registry
from bridge.llm.types import CallContext, InputField, Instruction, Message, Result, Tier
from bridge.models.enums import ConsentPurpose
from tests.unit.llm.helpers import NOW, OTHER_OWNER, OWNER, SESSION, USER, settings
from tests.unit.llm.rig import registry_with, screen
from tests.unit.llm.routing_rig import OK, routed
from tests.unit.llm.schemas import Verdict, player
from tests.unit.llm.test_registry import raw

TASK = "moderation_prescreen"
DEMO = CallContext(user_id=USER, trace_id="anthropic-trace")


def unverified() -> Registry:
    data = raw()
    data["pricing_status"] = "placeholder-unverified"
    return registry_module.parse(data)


def spent(cost: str, *, days_ago: int = 0) -> LedgerEntry:
    return LedgerEntry(
        id=uuid4(),
        created_at=NOW - timedelta(days=days_ago),
        org_id=None,
        user_id=OTHER_OWNER,
        task=TASK,
        purpose="tier1_only",
        model="m",
        status=CallStatus.OK,
        stop_reason="end_turn",
        input_tokens=1,
        output_tokens=1,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=Decimal(cost),
        latency_ms=1,
        trace_id="earlier",
        attempt=1,
        inputs={},
    )


# ------------------------------------------------------------------------------------------------- Anthropic


async def test_verified_prices_and_a_key_send_to_anthropic_under_the_t22_rules() -> None:
    cassette = player("messages_verdict_ok")
    r = routed(provider="anthropic", anthropic=cassette.adapter(), demo=())  # no data rule on this route
    result = await r.client.complete(TASK, screen(), Verdict, ctx=CallContext(user_id=OTHER_OWNER))
    assert result.demo_fallback is False
    assert result.parsed.verdict == "clean"
    assert result.cost_usd > 0
    assert cassette.exhausted
    assert [e.status for e in r.ledger.entries] == [CallStatus.OK]


async def test_unverified_prices_keep_anthropic_off() -> None:
    adapter = FakeAdapter([OK])
    r = routed(provider="anthropic", anthropic=adapter, reg=unverified())
    result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert (result.demo_fallback, result.fallback_reason) == (True, "prices_unverified")
    assert adapter.requests == []
    with pytest.raises(LLMUnavailable, match="prices_unverified"):
        await routed(provider="anthropic", anthropic=adapter, reg=unverified(), demo_fallback=False).client.complete(
            TASK, screen(), Verdict, ctx=DEMO
        )
    assert adapter.requests == []


async def test_a_missing_key_falls_back_locally_and_is_refused_elsewhere() -> None:
    keyless = AnthropicAdapter(api_key=None, timeout_seconds=5.0, max_retries=0)
    r = routed(provider="anthropic", anthropic=keyless, anthropic_configured=False)
    result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert (result.demo_fallback, result.fallback_reason) == (True, "no_key")
    assert r.ledger.entries == []
    strict = routed(provider="anthropic", anthropic=keyless, anthropic_configured=False, demo_fallback=False)
    with pytest.raises(LLMUnavailable, match="ANTHROPIC_API_KEY"):
        await strict.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert [e.status for e in strict.ledger.entries] == [CallStatus.PROVIDER_ERROR]  # T2.2 behaviour


@pytest.mark.parametrize(
    ("earlier", "daily", "total"),
    [
        (spent("1.00"), "1.00", "5.00"),  # today's USD 1 is spent
        (spent("5.00", days_ago=40), "1.00", "5.00"),  # the USD 5 prototype total is spent
    ],
    ids=["daily-cap", "prototype-total"],
)
async def test_a_spent_cap_falls_back_before_anything_is_sent(earlier: LedgerEntry, daily: str, total: str) -> None:
    adapter = FakeAdapter([OK])
    cfg = settings(llm_global_daily_cap_usd=Decimal(daily), llm_prototype_total_cap_usd=Decimal(total))
    r = routed(provider="anthropic", anthropic=adapter, cfg=cfg)
    r.ledger.entries.append(earlier)
    result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert (result.demo_fallback, result.fallback_reason) == (True, "budget")
    assert adapter.requests == []
    assert [e.status for e in r.ledger.entries[1:]] == [CallStatus.BLOCKED_BUDGET]


async def test_an_anthropic_provider_error_falls_back() -> None:
    r = routed(provider="anthropic", anthropic=FakeAdapter([LLMProviderError("HTTP 529", transient=True)]))
    result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert (result.demo_fallback, result.fallback_reason, result.model) == (True, "provider_error", DEMO_FALLBACK_MODEL)
    assert [e.status for e in r.ledger.entries] == [CallStatus.PROVIDER_ERROR]


# --------------------------------------------------------------------------------------------------- batches


def batchable() -> Registry:
    return registry_with(moderation_prescreen={"batchable": True})


def items(*ids: str, owner: object = None) -> list[BatchItem]:
    parts: list[InputField | Instruction] = [Instruction("Screen:"), InputField("teaser.summary", "Solar kiosks.")]
    if owner is not None:
        parts.append(InputField("confidential.m", "secret", tier=Tier.TIER2, owner_id=owner))  # type: ignore[arg-type]
    return [BatchItem(i, [Message.system("You screen teasers."), Message.user(*parts)]) for i in ids]


@pytest.mark.parametrize(("provider", "reason"), [("free", "no_batch_api"), ("fake", "fake_provider")])
async def test_a_batch_without_a_batch_api_gets_a_fallback_handle(provider: str, reason: str) -> None:
    r = routed(provider=provider, reg=batchable())  # type: ignore[arg-type]
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        handle = await r.client.batch_submit(TASK, items("a", "b"), Verdict, ctx=DEMO)
        poll = await r.client.batch_poll(BatchHandle.model_validate_json(handle.model_dump_json()), Verdict)
    assert not route.called
    assert (handle.demo_fallback, handle.fallback_reason, handle.model) == (True, reason, DEMO_FALLBACK_MODEL)
    assert handle.inputs == {"a": {}, "b": {}}  # no input is kept
    assert handle.batch_id.startswith("demo-fallback-")
    assert poll.state is BatchState.ENDED
    assert set(poll.results) == {"a", "b"}
    for outcome in poll.results.values():
        assert isinstance(outcome, Result)
        assert (outcome.demo_fallback, outcome.fallback_reason) == (True, reason)
        assert outcome.parsed == fallback_output(Verdict)
    assert r.ledger.entries == []


async def test_a_fallback_batch_is_checked_as_a_real_one() -> None:
    r = routed(reg=batchable())
    with pytest.raises(LLMConfigError, match="not batchable"):
        await routed().client.batch_submit(TASK, items("a"), Verdict, ctx=DEMO)
    with pytest.raises(LLMConfigError, match="unique custom ids"):
        await r.client.batch_submit(TASK, items("a", "a"), Verdict, ctx=DEMO)
    with pytest.raises(LLMConfigError, match="unique custom ids"):
        await r.client.batch_submit(TASK, [], Verdict, ctx=DEMO)


async def test_a_fallback_batch_keeps_the_tier2_rules() -> None:
    reg = registry_with(submission_assistant={"batchable": True})
    with pytest.raises(ConsentRequired):
        await routed(reg=reg).client.batch_submit("submission_assistant", items("a", owner=USER), Verdict, ctx=DEMO)
    consents = StaticConsents([(OWNER, ConsentPurpose.TIER2_LLM_ASSISTANT, SESSION)])
    ctx = CallContext(user_id=USER, session_id=SESSION)
    with pytest.raises(Tier2DemoOnly):
        await routed(reg=reg, consents=consents).client.batch_submit(
            "submission_assistant", items("a", owner=OWNER), Verdict, ctx=ctx
        )


async def test_an_anthropic_batch_is_real_and_polled_through_the_service() -> None:
    adapter = FakeAdapter([OK, OK])
    r = routed(provider="anthropic", anthropic=adapter, reg=batchable())
    handle = await r.client.batch_submit(TASK, items("a", "b"), Verdict, ctx=DEMO)
    assert handle.demo_fallback is False
    poll = await r.client.batch_poll(handle, Verdict)
    assert poll.state is BatchState.ENDED
    assert all(isinstance(o, Result) and not o.demo_fallback for o in poll.results.values())


async def test_an_anthropic_batch_that_fails_to_submit_falls_back_or_raises() -> None:
    failing = FakeAdapter()

    async def refuse(requests: object) -> str:
        raise LLMProviderError("HTTP 500", transient=True)

    failing.batch_create = refuse  # type: ignore[method-assign]
    r = routed(provider="anthropic", anthropic=failing, reg=batchable())
    handle = await r.client.batch_submit(TASK, items("a"), Verdict, ctx=DEMO)
    assert (handle.demo_fallback, handle.fallback_reason) == (True, "provider_error")
    strict = routed(provider="anthropic", anthropic=failing, reg=batchable(), demo_fallback=False)
    with pytest.raises(LLMProviderError):
        await strict.client.batch_submit(TASK, items("a"), Verdict, ctx=DEMO)
    with pytest.raises(LLMUnavailable, match="no_batch_api"):
        await routed(reg=batchable(), demo_fallback=False).client.batch_submit(TASK, items("a"), Verdict, ctx=DEMO)


async def test_a_handle_with_an_unknown_reason_polls_as_no_batch_api() -> None:
    handle = BatchHandle(
        batch_id="demo-fallback-x",
        task=TASK,
        model=DEMO_FALLBACK_MODEL,
        trace_id="t",
        org_id=None,
        user_id=USER,
        inputs={"a": {}},
        demo_fallback=True,
        fallback_reason="made-up",
    )
    poll = await routed(provider="fake").client.batch_poll(handle, Verdict)
    [outcome] = poll.results.values()
    assert isinstance(outcome, Result)
    assert outcome.fallback_reason == "no_batch_api"
