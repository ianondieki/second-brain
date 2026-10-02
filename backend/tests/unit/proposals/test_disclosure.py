"""REQ-REPO-01 (warn only): the teaser over-disclosure check without a database (``bridge.proposals.disclosure``).

The rules answer the obvious without a model; the ``over_disclosure_check`` task's answer is parsed and kept only
when code accepts it; refusals map to the assistant's fixed answers; nothing confidential is ever sent. Fakes only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from bridge.errors import ApiError
from bridge.llm.demo_fallback import FallbackReason, fallback_result
from bridge.llm.errors import LLMBudgetExceeded, LLMKillSwitch, LLMProviderError, Tier2NotAllowed
from bridge.llm.fakes import FakeLLMClient
from bridge.llm.types import CallContext, InputField, Message, Result, Tier, TokenUsage
from bridge.proposals import disclosure
from bridge.proposals.assistant_policy import get_assistant_policy
from bridge.proposals.disclosure import DisclosureSource, DisclosureVerdict, TeaserField

OWNER = UUID("01900000-0000-7000-8000-00000000c001")
SESSION = UUID("01900000-0000-7000-8000-00000000c0e1")
CANARY = "T2CANARY-gradient"
POLICY = get_assistant_policy()
PLAIN = {
    "title": "Claims that get paid",
    "problem_statement": "Clinics lose claims because forms come back incomplete.",
    "summary": "Clinic staff see which claim forms will bounce before they send them.",
}


def verdict(**overrides: Any) -> DisclosureVerdict:
    values: dict[str, Any] = {
        "injection_suspected": False,
        "flagged": True,
        "fields": ["summary"],
        "why": "Say what the clinic gets, not which model scores the forms.",
    }
    return DisclosureVerdict.model_validate(values | overrides)


def result(output: DisclosureVerdict) -> Result[DisclosureVerdict]:
    return Result(output, "end_turn", TokenUsage(), (), "m", Decimal(0), 1, "trace-1")


# --- the rules -------------------------------------------------------------------------------------------------------


def test_the_rules_flag_the_method_and_not_the_problem() -> None:
    flagged = {**PLAIN, "summary": "We use a gradient-boosted model over two years of claims to score each form."}
    assert disclosure.precheck(flagged) == (TeaserField.SUMMARY,)
    assert disclosure.precheck({"problem_statement": "Clinics lose claims"}) == ()
    assert disclosure.precheck(PLAIN) == ()


@pytest.mark.parametrize(
    "text",
    [
        "Our ALGORITHM ranks forms.",
        "A three-tier architecture keeps it fast.",
        "Built on Django and PostgreSQL.",
        "Call ```score(form)``` on each claim.",
        "It runs `predict()` nightly.",
        "Sensors talk over LoRaWAN.",
    ],
)
def test_the_rules_catch_code_and_named_tools(text: str) -> None:
    assert disclosure.precheck({"problem_statement": text}) == (TeaserField.PROBLEM_STATEMENT,)


def test_only_the_four_tier1_fields_are_read() -> None:
    fields = {**PLAIN, "approach": "We use a neural network", "architecture": "microservices on kubernetes"}
    assert disclosure.precheck(disclosure.present(fields)) == ()
    assert set(disclosure.present(fields)) == set(PLAIN)


# --- the model ---------------------------------------------------------------------------------------------------


def test_every_field_is_tier1_and_owned_by_the_owner() -> None:
    [system, user] = disclosure.messages(OWNER, {**PLAIN, "approach": CANARY, "notes": CANARY})
    assert not system.fields
    assert {f.name for f in user.fields} == {f"teaser.{name}" for name in PLAIN}
    assert all(f.tier is Tier.TIER1 and f.owner_id == OWNER and not f.public for f in user.fields)
    assert CANARY not in "".join(f.value for f in user.fields)


async def test_a_flag_is_kept_for_fields_with_text_and_tier2_is_never_sent() -> None:
    llm = FakeLLMClient([verdict(fields=["summary", "impact_claims", "summary"])])
    got = await disclosure.ask_model(llm, OWNER, {**PLAIN, "approach": CANARY}, session_id=SESSION, policy=POLICY)
    assert (got.flagged, got.fields, got.source, got.ai_drafted) == (
        True,
        (TeaserField.SUMMARY,),  # impact_claims has no text; duplicates collapse
        DisclosureSource.MODEL,
        True,
    )
    assert got.why == "Say what the clinic gets, not which model scores the forms."
    [request] = llm.requests
    assert CANARY not in "".join(b.text for m in request.messages for b in m.blocks)


def test_code_decides_what_is_shown() -> None:
    clear = disclosure.evaluate(result(verdict(flagged=False, fields=[], why="")), PLAIN, POLICY)
    assert (clear.flagged, clear.why, clear.source) == (False, disclosure.CLEAR, DisclosureSource.MODEL)
    contact = disclosure.evaluate(result(verdict(why="Ask us at team@example.com.")), PLAIN, POLICY)
    assert (contact.flagged, contact.why, contact.ai_drafted) == (True, disclosure.RULES_WHY, False)
    steered = disclosure.evaluate(result(verdict(injection_suspected=True)), PLAIN, POLICY)
    assert (steered.flagged, steered.why, steered.source) == (False, disclosure.INJECTION, DisclosureSource.NONE)


def test_a_demo_fallback_is_labelled_and_warns_of_nothing() -> None:
    fallback = fallback_result(DisclosureVerdict, reason=FallbackReason.FAKE_PROVIDER, trace_id="t")
    got = disclosure.evaluate(fallback, PLAIN, POLICY)
    assert (got.flagged, got.demo_fallback, got.why, got.reason) == (
        False,
        True,
        disclosure.DEMO_FALLBACK,
        "demo_fallback:fake_provider",
    )
    assert DisclosureVerdict.demo_fallback().injection_suspected is True


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (LLMKillSwitch(), 503, "assistant_off"),
        (LLMBudgetExceeded("tenant", spent_usd=Decimal("4.20"), cap_usd=Decimal("5.00")), 429, "assistant_budget"),
        (LLMBudgetExceeded("global", spent_usd=Decimal("0.99"), cap_usd=Decimal("1.00")), 503, "assistant_paused"),
    ],
)
async def test_refusals_are_the_assistants(error: Exception, status: int, code: str) -> None:
    llm = FakeLLMClient([error])
    with pytest.raises(ApiError) as raised:
        await disclosure.ask_model(llm, OWNER, PLAIN, session_id=SESSION, policy=POLICY)
    assert raised.value.status_code == status
    assert raised.value.detail["code"] == code  # type: ignore[index]
    assert "4.20" not in str(raised.value.detail)


async def test_a_provider_that_is_down_could_not_check() -> None:
    llm = FakeLLMClient([LLMProviderError("down", transient=True)])
    got = await disclosure.ask_model(llm, OWNER, PLAIN, session_id=SESSION, policy=POLICY)
    assert (got.flagged, got.why, got.source) == (False, disclosure.UNAVAILABLE, DisclosureSource.NONE)


async def test_the_task_refuses_a_tier2_field() -> None:
    llm = FakeLLMClient()
    smuggled = [
        Message.system("x"),
        Message.user(InputField("confidential.approach", CANARY, tier=Tier.TIER2, owner_id=OWNER)),
    ]
    with pytest.raises(Tier2NotAllowed):
        await llm.complete(disclosure.TASK, smuggled, DisclosureVerdict, ctx=CallContext(user_id=OWNER))
    assert llm.requests == []
