"""REQ-PROP-05: the submission assistant's rules without a database (``bridge.proposals.assistant``).

Code decides what the owner is shown: a demo fallback and ``injection_suspected`` are "no suggestion"; a suggested
teaser must pass the Tier-1 sanitiser; placement hints only move a field with text away from its tier. LLM refusals
map to fixed messages (a global or total budget never shows the platform's figures). Fakes only (D-18).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

import pytest

from bridge.errors import ApiError
from bridge.llm.adapter import ModelResponse
from bridge.llm.demo_fallback import FallbackReason, fallback_result
from bridge.llm.errors import (
    ConsentRequired,
    LLMBudgetExceeded,
    LLMKillSwitch,
    LLMProviderError,
    LLMRefused,
    LLMRequestCapReached,
    LLMUnavailable,
    NotDemoData,
    Tier2DemoOnly,
)
from bridge.llm.fakes import FakeLLMClient
from bridge.llm.guard import StaticConsents
from bridge.llm.types import InputField, Tier, TokenUsage
from bridge.models.enums import ConsentPurpose
from bridge.proposals import assistant
from bridge.proposals.assistant import DraftText, Move, PlacementField, SuggestionStatus, TeaserSuggestion
from tests.unit.proposals.assistant_fixtures import DRAFT, OWNER, SECRET, SESSION, answer, detail_of, result

# --- the call ----------------------------------------------------------------------------------------------------


def test_every_field_is_owned_by_the_owner_and_tier2_is_tagged() -> None:
    """D-37: fields carry their owner (a free provider takes only a demo account's fields); Tier 2 is tagged."""
    [system, user] = assistant.messages(DRAFT)
    assert not system.fields
    fields = {f.name: f for f in user.fields}
    assert set(fields) == {
        "teaser.title",
        "teaser.problem_statement",
        "teaser.summary",
        "confidential.approach",
        "confidential.pricing",
    }
    assert all(f.owner_id == OWNER and not f.public for f in fields.values())
    assert {n for n, f in fields.items() if f.tier is Tier.TIER2} == {"confidential.approach", "confidential.pricing"}


async def test_no_teaser_text_asks_nothing() -> None:
    llm = FakeLLMClient(consents=StaticConsents([(OWNER, assistant.PURPOSE, SESSION)]))
    empty = DraftText(DRAFT.owned, tier1={"problem_statement": "Milk spoils."}, tier2={"approach": SECRET})
    got = await assistant.suggest(llm, empty, session_id=SESSION)
    assert (got.status, got.reason, llm.requests) == (SuggestionStatus.NO_SUGGESTION, "no_text", [])


# --- what code accepts ---------------------------------------------------------------------------------------------


def test_a_demo_fallback_is_no_suggestion_labelled() -> None:
    fallback = fallback_result(TeaserSuggestion, reason=FallbackReason.NOT_DEMO_DATA, trace_id="t")
    got = assistant.evaluate(fallback, DRAFT)
    assert got.status is SuggestionStatus.DEMO_FALLBACK
    assert got.demo_fallback is True
    assert (got.title, got.summary, got.placement) == (None, None, ())
    assert got.reason == "demo_fallback:not_demo_data"


def test_the_placeholder_is_the_safe_answer() -> None:
    placeholder = TeaserSuggestion.demo_fallback()
    assert placeholder.injection_suspected is True
    assert (placeholder.has_suggestion, placeholder.title, placeholder.placement) == (False, "", [])


def test_injection_suspected_is_no_suggestion_even_with_a_teaser() -> None:
    got = assistant.evaluate(result(answer(injection_suspected=True)), DRAFT)
    assert got.status is SuggestionStatus.INJECTION_SUSPECTED
    assert (got.title, got.placement) == (None, ())


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"summary": "Call 0712 345 678 to pilot it."}, "rejected:contains_phone"),
        ({"summary": "See https://evil.example/pilot for details."}, "rejected:contains_url"),
        ({"title": "x" * 121}, "rejected:too_long"),
        ({"summary": "word " * 151}, "rejected:too_many_words"),
        ({"title": "<b></b>"}, "rejected:empty"),
        ({"title": "Cold chain", "summary": "Alerts when a cooler warms."}, "unchanged"),
        ({"has_suggestion": False}, "none"),
    ],
)
def test_a_teaser_the_tier1_rules_refuse_is_not_shown(overrides: dict[str, Any], reason: str) -> None:
    got = assistant.evaluate(result(answer(**overrides)), DRAFT)
    assert (got.status, got.reason, got.title) == (SuggestionStatus.NO_SUGGESTION, reason, None)


def test_a_clean_teaser_is_shown_as_plain_text() -> None:
    got = assistant.evaluate(result(answer(title="Cold-chain <i>alerts</i>")), DRAFT)
    assert got.status is SuggestionStatus.SUGGESTED
    assert got.title == "Cold-chain alerts"
    assert got.summary is not None
    assert got.summary.startswith("Farmers get an SMS")


def test_placement_hints_move_a_field_with_text_away_from_its_tier_once() -> None:
    hints = [
        {"field": "problem_statement", "move": "to_tier2", "reason": "It explains how it works."},
        {"field": "problem_statement", "move": "to_tier2", "reason": "Twice."},  # once per field
        {"field": "summary", "move": "to_tier1", "reason": "Already Tier 1."},  # wrong direction
        {"field": "impact_claims", "move": "to_tier2", "reason": "No text there."},  # empty field
        {"field": "pricing", "move": "to_tier1", "reason": "Email me at a@b.co for prices."},  # contact detail
        {"field": "approach", "move": "to_tier1", "reason": "<b>It only says what it does.</b>" + "x" * 400},
    ]
    got = assistant.evaluate(result(answer(has_suggestion=False, placement=hints)), DRAFT)
    assert got.status is SuggestionStatus.SUGGESTED
    assert got.title is None
    assert [(h.field, h.move) for h in got.placement] == [
        (PlacementField.PROBLEM_STATEMENT, Move.TO_TIER2),
        (PlacementField.APPROACH, Move.TO_TIER1),
    ]
    assert got.placement[1].reason.startswith("It only says what it does.")
    assert len(got.placement[1].reason) <= assistant.MAX_REASON_CHARS


# --- errors --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ConsentRequired("submission_assistant", ConsentPurpose.TIER2_LLM_ASSISTANT, ("x",)), 403, "consent_required"),
        (Tier2DemoOnly("submission_assistant", ("confidential.approach",)), 403, "assistant_demo_only"),
        (NotDemoData("submission_assistant"), 403, "assistant_demo_only"),
        (LLMKillSwitch(), 503, "assistant_off"),
        (LLMBudgetExceeded("tenant", spent_usd=Decimal("4.20"), cap_usd=Decimal("5.00")), 429, "assistant_budget"),
        (LLMBudgetExceeded("global", spent_usd=Decimal("0.99"), cap_usd=Decimal("1.00")), 503, "assistant_paused"),
        (LLMBudgetExceeded("total", spent_usd=Decimal("4.99"), cap_usd=Decimal("5.00")), 503, "assistant_paused"),
        (LLMRequestCapReached("free1:vendor/m"), 503, "assistant_paused"),
    ],
)
def test_refusals_have_fixed_messages_without_figures(error: Exception, status: int, code: str) -> None:
    mapped = assistant.refusal(error)  # type: ignore[arg-type]
    assert mapped is not None
    assert (mapped.status_code, detail_of(mapped)["code"]) == (status, code)
    message = detail_of(mapped)["message"]
    assert not re.search(r"\d", message), message  # never a spend, a cap or a model
    assert str(error) not in message


@pytest.mark.parametrize(
    "error",
    [
        LLMProviderError("free1 answered 502", transient=True, status_code=502),
        LLMUnavailable("no provider"),
        LLMRefused("refused", task="submission_assistant", trace_id="t"),
    ],
)
async def test_a_provider_that_is_down_is_no_suggestion(error: Exception) -> None:
    assert assistant.refusal(error) is None  # type: ignore[arg-type]
    llm = FakeLLMClient(consents=StaticConsents([(OWNER, assistant.PURPOSE, SESSION)]))
    if isinstance(error, LLMRefused):  # the model refuses; the task has no fallback model, so no retry
        llm.queue(ModelResponse(text="", stop_reason="refusal", usage=TokenUsage(), model="m"))
    else:
        llm.queue(error)
    got = await assistant.suggest(llm, DRAFT, session_id=SESSION)
    assert got.status is SuggestionStatus.UNAVAILABLE
    assert got.message == assistant.UNAVAILABLE
    assert got.reason == f"llm_error:{getattr(error, 'code', '')}"


async def test_a_global_budget_through_the_client_gives_the_fixed_message() -> None:
    from tests.unit.llm.helpers import settings

    cfg = settings(llm_global_daily_cap_usd=Decimal("0"), llm_prototype_total_cap_usd=Decimal("1000"))
    llm = FakeLLMClient([answer()], settings=cfg, consents=StaticConsents([(OWNER, assistant.PURPOSE, SESSION)]))
    with pytest.raises(ApiError) as caught:
        await assistant.suggest(llm, DRAFT, session_id=SESSION)
    assert detail_of(caught.value) == {"code": "assistant_paused", "message": assistant.PAUSED}
    assert llm.requests == []


def test_field_reprs_never_print_text() -> None:
    assert SECRET not in repr(DRAFT)
    assert SECRET not in repr(InputField("confidential.approach", SECRET, tier=Tier.TIER2, owner_id=OWNER))
