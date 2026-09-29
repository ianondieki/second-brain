"""REQ-PROP-05: the submission assistant's rules without a database (``bridge.proposals.assistant``).

Code decides what the owner is shown: a demo fallback and ``injection_suspected`` are "no suggestion"; a suggested
teaser must pass the Tier-1 sanitiser; placement hints only move a field with text away from its tier. LLM refusals
map to fixed messages (a global or total budget never shows the platform's figures). Fakes only (D-18).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any
from uuid import UUID

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
from bridge.llm.types import InputField, Result, Tier, TokenUsage
from bridge.models.enums import ConsentPurpose
from bridge.proposals import assistant
from bridge.proposals.assistant import DraftText, Move, Owned, PlacementField, SuggestionStatus, TeaserSuggestion

OWNER = UUID("01900000-0000-7000-8000-0000000000c1")
SESSION = UUID("01900000-0000-7000-8000-0000000000e1")
PROPOSAL = UUID("01900000-0000-7000-8000-0000000000f1")
VERSION = UUID("01900000-0000-7000-8000-0000000000f2")
SECRET = "TIER2-SECRET LoRa relays every 90 s"

DRAFT = DraftText(
    Owned(PROPOSAL, OWNER, VERSION),
    tier1={"title": "Cold chain", "problem_statement": "Milk spoils.", "summary": "Alerts when a cooler warms."},
    tier2={"approach": SECRET, "pricing": "KES 25,000 setup"},
)


def answer(**overrides: Any) -> TeaserSuggestion:
    values: dict[str, Any] = {
        "injection_suspected": False,
        "has_suggestion": True,
        "title": "Cold-chain alerts for dairy farmers",
        "summary": "Farmers get an SMS the moment a milk cooler starts to warm, so less milk spoils.",
        "placement": [],
    }
    return TeaserSuggestion.model_validate(values | overrides)


def detail_of(error: ApiError) -> dict[str, Any]:
    detail: dict[str, Any] = error.detail  # type: ignore[assignment]  # ApiError always sets a dict
    return detail


def result(output: TeaserSuggestion) -> Result[TeaserSuggestion]:
    return Result(output, "end_turn", TokenUsage(), (), "m", Decimal(0), 1, "trace-1")


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


def test_the_task_is_consent_covered_and_has_no_tools() -> None:
    from bridge.llm.registry import load
    from tests.unit.llm.helpers import settings

    spec = load(settings().llm_models_file).task(assistant.TASK)
    assert spec.purpose.consent is ConsentPurpose.TIER2_LLM_ASSISTANT
    assert not spec.allowed_tools  # docs/spec/09: explainers and writers have no tools


async def test_a_granted_session_sends_framed_sanitised_text_and_nothing_else() -> None:
    llm = FakeLLMClient([answer()], consents=StaticConsents([(OWNER, assistant.PURPOSE, SESSION)]))
    draft = DraftText(
        DRAFT.owned,
        tier1={"title": "Cold chain", "summary": "Alerts <b>now</b> [here](https://evil.example)"},
        tier2={"approach": SECRET},
    )
    got = await assistant.suggest(llm, draft, session_id=SESSION)
    assert got.status is SuggestionStatus.SUGGESTED
    [request] = llm.requests
    sent = "\n".join(block.text for message in request.messages for block in message.blocks)
    assert re.search(r'<submission nonce="[0-9a-f]{16}" field="confidential.approach" tier="tier2">', sent)
    assert "evil.example" not in sent  # the layer's sanitiser ran
    assert "<b>" not in sent
    assert SECRET in sent  # consent covers Tier 2 for this session
    assert not request.tools
    [entry] = llm.ledger.entries
    assert SECRET not in json.dumps(entry.inputs, default=str)  # the ledger keeps names and lengths only


async def test_without_the_sessions_consent_nothing_is_sent() -> None:
    """The layer's own guard refuses Tier 2 even if a caller forgot ``require_consent``; the answer is fixed."""
    other = UUID("01900000-0000-7000-8000-0000000000e2")
    for consents in (StaticConsents(), StaticConsents([(OWNER, assistant.PURPOSE, other)])):
        llm = FakeLLMClient([answer()], consents=consents)
        with pytest.raises(ApiError) as caught:
            await assistant.suggest(llm, DRAFT, session_id=SESSION)
        assert caught.value.status_code == 403
        assert detail_of(caught.value)["code"] == "consent_required"
        assert llm.requests == []


async def test_require_consent_is_per_session() -> None:
    held = StaticConsents([(OWNER, assistant.PURPOSE, SESSION)])
    await assistant.require_consent(held, OWNER, session_id=SESSION)
    with pytest.raises(ApiError) as caught:
        await assistant.require_consent(held, OWNER, session_id=UUID(int=7))
    assert detail_of(caught.value) == {
        "code": "consent_required",
        "message": assistant.CONSENT_REQUIRED,
    }


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
