"""REQ-LLM-01 P7 (D-37): ``RoutedLLMClient`` on the fake and the free providers, and the demo fallback.

Free slots are the real ``OpenAICompatibleAdapter`` behind respx (no network; the egress guard stays, AC-SEC-5). Every
failure path answers with the deterministic fake, flagged ``demo_fallback`` with its reason; a rule refusal is never
faked; data that is not seeded demo data never produces an HTTP request.
"""

from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
import respx

from bridge.llm.demo_fallback import DEMO_FALLBACK_MODEL, fallback_output
from bridge.llm.errors import (
    ConsentRequired,
    LLMConfigError,
    LLMProviderError,
    LLMUnavailable,
    Tier2DemoOnly,
    Tier2NotAllowed,
)
from bridge.llm.guard import StaticConsents
from bridge.llm.ledger import CallStatus
from bridge.llm.prepare import SCHEMA_INSTRUCTION
from bridge.llm.registry import free_model_key
from bridge.llm.types import CallContext, InputField, Instruction, Message, Tier
from bridge.models.enums import ConsentPurpose
from tests.unit.llm.helpers import ORG, OTHER_OWNER, OWNER, SESSION, USER, settings
from tests.unit.llm.rig import registry_with, screen
from tests.unit.llm.routing_rig import KEYS, OK, chat, routed, slot, url
from tests.unit.llm.schemas import Verdict

TASK = "moderation_prescreen"
ASSISTANT = "submission_assistant"
CANARY = "CANARY-P7-ROUTE-81c2"
DEMO = CallContext(user_id=USER, trace_id="demo-trace")


def tier2(owner: UUID) -> list[Message]:
    return [
        Message.system("You suggest placements."),
        Message.user(
            Instruction("Suggest:"),
            InputField("teaser.summary", "Public teaser."),
            InputField("confidential.method", f"The method is {CANARY}.", tier=Tier.TIER2, owner_id=owner),
        ),
    ]


def assert_fallback(result: object, reason: str) -> None:
    assert getattr(result, "demo_fallback", None) is True
    assert getattr(result, "fallback_reason", None) == reason
    assert getattr(result, "model", None) == DEMO_FALLBACK_MODEL
    assert getattr(result, "parsed", None) == fallback_output(Verdict)


# ------------------------------------------------------------------------------------------------ the fake


async def test_the_fake_provider_answers_every_call_without_sending_or_recording() -> None:
    r = routed(provider="fake")
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert_fallback(result, "fake_provider")
    assert result.trace_id == "demo-trace"
    assert not route.called
    assert r.ledger.entries == []
    assert r.built == []  # no service was even built


async def test_the_fake_provider_keeps_the_consent_guard() -> None:
    r = routed(provider="fake")
    with pytest.raises(ConsentRequired):
        await r.client.complete(ASSISTANT, tier2(USER), Verdict, ctx=DEMO)
    with pytest.raises(Tier2NotAllowed):  # a Tier-1-only task never reads Tier 2, fake or not
        await r.client.complete(TASK, tier2(USER), Verdict, ctx=DEMO)


async def test_without_the_demo_fallback_the_fake_provider_is_unavailable() -> None:
    r = routed(provider="fake", demo_fallback=False)
    with pytest.raises(LLMUnavailable, match="fake_provider"):
        await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)


async def test_unknown_tasks_and_bad_schemas_are_the_callers_mistake() -> None:
    r = routed(provider="fake")
    with pytest.raises(LLMConfigError):
        await r.client.complete("nope", screen(), Verdict, ctx=DEMO)
    with pytest.raises(LLMConfigError):
        await r.client.complete(TASK, screen(), dict, ctx=DEMO)  # type: ignore[type-var]


@pytest.mark.parametrize("provider", ["fake", "free"])
async def test_a_callers_mistake_is_refused_on_every_route_as_on_anthropic(provider: str) -> None:
    """Effort on a model without one, a bad cache breakpoint, a tool the task may not use, or messages in the wrong
    order are ``LLMConfigError`` whatever the provider, so a caller's tests on the fake catch them."""
    r = routed(provider=provider)  # type: ignore[arg-type]
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        with pytest.raises(LLMConfigError, match="no effort parameter"):
            await r.client.complete(TASK, screen(), Verdict, ctx=DEMO, effort="high")
        with pytest.raises(LLMConfigError, match="breakpoints"):
            await r.client.complete(TASK, screen(), Verdict, ctx=DEMO, cache_breakpoints=[7])
        with pytest.raises(LLMConfigError, match="may not use tool"):
            await r.client.complete(TASK, screen(), Verdict, ctx=DEMO, tools=[{"type": "web_search_20260209"}])
        with pytest.raises(LLMConfigError, match="last message"):
            await r.client.complete(TASK, [*screen(), Message.assistant(Instruction("x"))], Verdict, ctx=DEMO)
    assert not route.called
    assert r.ledger.entries == []


# ------------------------------------------------------------------------------------------ a free provider


async def test_a_demo_users_call_goes_to_the_free_slot_at_no_cost() -> None:
    r = routed()
    with respx.mock(assert_all_called=True) as router:
        route = router.post(url(1)).mock(return_value=chat())
        result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert result.demo_fallback is False
    assert result.fallback_reason is None
    assert (result.parsed.verdict, result.model) == ("clean", free_model_key(slot(1)))
    assert result.cost_usd == Decimal(0)
    sent = route.calls.last.request
    assert sent.headers["authorization"] == f"Bearer {KEYS[1]}"
    body = json.loads(sent.content)
    assert body["model"] == "vendor/model-1"
    assert SCHEMA_INSTRUCTION in body["messages"][0]["content"]  # the schema travels in the prompt
    assert "Solar kiosks for markets" in body["messages"][1]["content"]  # sanitised and framed as ever
    [row] = r.ledger.entries
    assert (row.status, row.model, row.user_id) == (CallStatus.OK, free_model_key(slot(1)), USER)
    assert row.cost_usd == Decimal(0)


@pytest.mark.parametrize(
    "ctx",
    [CallContext(user_id=OTHER_OWNER), CallContext(org_id=ORG, user_id=OTHER_OWNER), CallContext()],
    ids=["non-demo-user", "non-demo-member", "platform-job"],
)
async def test_data_that_is_not_seeded_demo_data_never_reaches_a_free_provider(ctx: CallContext) -> None:
    r = routed()
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        result = await r.client.complete(TASK, screen(), Verdict, ctx=ctx)
    assert not route.called
    assert_fallback(result, "not_demo_data")
    assert r.ledger.entries == []


@pytest.mark.parametrize("subject", [USER, OWNER], ids=["demo-caller", "the-owner-itself"])
async def test_tier2_text_of_a_non_demo_account_is_refused_before_any_request(subject: UUID) -> None:
    consents = StaticConsents([(OWNER, ConsentPurpose.TIER2_LLM_ASSISTANT, SESSION)])
    r = routed(consents=consents, demo=(USER,))
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        with pytest.raises(Tier2DemoOnly):  # the owner's consent holds: only D-37 refuses it
            await r.client.complete(
                ASSISTANT, tier2(OWNER), Verdict, ctx=CallContext(user_id=subject, session_id=SESSION)
            )
    assert not route.called
    [row] = r.ledger.entries
    assert row.status is CallStatus.BLOCKED_TIER2
    assert CANARY not in repr(row.inputs)


async def test_tier2_text_of_a_non_demo_account_is_refused_even_when_every_slot_is_capped() -> None:
    """Refused, not faked, whatever route the call would have taken."""
    consents = StaticConsents([(OWNER, ConsentPurpose.TIER2_LLM_ASSISTANT, SESSION)])
    r = routed(consents=consents, slots=())
    with pytest.raises(Tier2DemoOnly):
        await r.client.complete(ASSISTANT, tier2(OWNER), Verdict, ctx=CallContext(user_id=OWNER, session_id=SESSION))


async def test_a_demo_accounts_tier2_text_with_its_consent_goes_to_the_free_slot() -> None:
    consents = StaticConsents([(USER, ConsentPurpose.TIER2_LLM_ASSISTANT, SESSION)])
    r = routed(consents=consents)
    with respx.mock(assert_all_called=True) as router:
        route = router.post(url(1)).mock(return_value=chat())
        result = await r.client.complete(
            ASSISTANT, tier2(USER), Verdict, ctx=CallContext(user_id=USER, session_id=SESSION)
        )
    assert result.demo_fallback is False
    assert CANARY in route.calls.last.request.content.decode()
    assert all(CANARY not in repr(e.inputs) for e in r.ledger.entries)  # never in the ledger (AC-SEC-6)


async def test_slots_are_tried_in_order_until_each_has_used_its_daily_requests() -> None:
    r = routed(slots=(slot(1, requests=1), slot(2, requests=1)))
    with respx.mock(assert_all_called=True) as router:
        one = router.post(url(1)).mock(return_value=chat())
        two = router.post(url(2)).mock(return_value=chat())
        first = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
        second = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
        third = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert (first.model, second.model) == (free_model_key(slot(1)), free_model_key(slot(2)))
    assert_fallback(third, "request_cap")
    assert (one.call_count, two.call_count) == (1, 1)


async def test_a_slot_that_runs_out_during_a_retry_falls_back() -> None:
    r = routed(slots=(slot(1, requests=1),))
    with respx.mock(assert_all_called=True) as router:
        route = router.post(url(1)).mock(return_value=chat("not json"))
        result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert_fallback(result, "request_cap")
    assert route.call_count == 1
    assert [e.status for e in r.ledger.entries] == [CallStatus.SCHEMA_ERROR, CallStatus.BLOCKED_BUDGET]


async def test_a_task_listing_no_configured_slot_falls_back() -> None:
    r = routed(slots=(slot(2),), reg=registry_with(moderation_prescreen={"free_slots": [1]}))
    assert_fallback(await r.client.complete(TASK, screen(), Verdict, ctx=DEMO), "no_free_slot")
    r = routed(slots=())
    assert_fallback(await r.client.complete(TASK, screen(), Verdict, ctx=DEMO), "no_free_slot")


async def test_tools_never_go_to_a_free_provider() -> None:
    r = routed(reg=registry_with(moderation_prescreen={"allowed_tools": ["web_search_20260209"]}))
    result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO, tools=[{"type": "web_search_20260209"}])
    assert_fallback(result, "tools_unsupported")


async def test_an_effort_override_is_dropped_on_a_free_slot() -> None:
    """Valid for the task's Anthropic model, meaningless for a free model: sent without effort."""
    r = routed()
    with respx.mock(assert_all_called=True) as router:
        route = router.post(url(1)).mock(return_value=chat())
        result = await r.client.complete("originality_explainer", screen(), Verdict, ctx=DEMO, effort="high")
    assert result.demo_fallback is False
    assert "effort" not in route.calls.last.request.content.decode()


@pytest.mark.parametrize(
    ("replies", "reason"),
    [
        ([httpx.Response(500)], "provider_error"),
        ([httpx.Response(429)], "provider_error"),
        ([httpx.Response(401, json={"error": "bad key"})], "provider_error"),
        ([httpx.ReadTimeout("slow")], "provider_error"),
        ([httpx.ConnectError("down")], "provider_error"),
        ([httpx.Response(200, content=b"<html>")], "provider_error"),
        ([chat(finish="content_filter")], "call_failed"),
        ([chat(finish="length"), chat(finish="length")], "call_failed"),
        ([chat("not json"), chat('{"verdict": "maybe"}')], "call_failed"),
        ([chat(finish="tool_calls")], "call_failed"),
    ],
)
async def test_every_failed_call_falls_back_with_the_label(
    replies: list[httpx.Response | Exception], reason: str
) -> None:
    r = routed()
    with respx.mock(assert_all_called=True) as router:
        router.post(url(1)).mock(side_effect=replies)
        result = await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert_fallback(result, reason)
    assert result.trace_id == "demo-trace"


async def test_the_kill_switch_falls_back_and_keeps_the_consent_guard() -> None:
    r = routed(cfg=settings(llm_kill_switch=True))
    with respx.mock(assert_all_called=False) as router:
        route = router.route()
        assert_fallback(await r.client.complete(TASK, screen(), Verdict, ctx=DEMO), "kill_switch")
        with pytest.raises(ConsentRequired):  # the kill switch refused before the guard: the fallback runs it
            await r.client.complete(ASSISTANT, tier2(USER), Verdict, ctx=DEMO)
    assert not route.called
    assert [e.status for e in r.ledger.entries] == [CallStatus.BLOCKED_KILL_SWITCH] * 2


async def test_without_the_demo_fallback_errors_propagate() -> None:
    """Staging and production: nothing is faked (the free route itself only exists on local runs)."""
    r = routed(demo_fallback=False)
    with respx.mock(assert_all_called=True) as router:
        router.post(url(1)).mock(return_value=httpx.Response(503))
        with pytest.raises(LLMProviderError):
            await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    with pytest.raises(LLMUnavailable, match="no_free_slot"):
        await routed(demo_fallback=False, slots=()).client.complete(TASK, screen(), Verdict, ctx=DEMO)


async def test_one_service_per_route_per_client() -> None:
    r = routed(slots=(slot(1), slot(2)))
    with respx.mock(assert_all_called=True) as router:
        router.post(url(1)).mock(return_value=chat())
        for _ in range(3):
            await r.client.complete(TASK, screen(), Verdict, ctx=DEMO)
    assert r.built == [free_model_key(slot(1))]
    assert OK["verdict"] == "clean"
