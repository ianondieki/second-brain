"""REQ-LLM-01: ai/models.yaml is the task -> model registry; parsing is strict and every effort is explicit."""

from __future__ import annotations

import copy
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import yaml
from pydantic import SecretStr

from bridge.config import FreeSlot, get_settings
from bridge.llm import registry
from bridge.llm.errors import LLMConfigError
from bridge.llm.registry import Purpose
from bridge.llm.types import TokenUsage
from bridge.models.enums import ConsentPurpose

PHASE_2_TASKS = {"moderation_prescreen", "over_disclosure_check", "originality_explainer", "submission_assistant"}
HAIKU, SONNET, OPUS = "claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5-5"
# docs/spec/09 model allocation per registered task. A refusal fallback must be null or another model the spec
# allocates to the same task (D-29); a new task must be added here with its allocation.
SPEC_09_ALLOCATION = {
    "moderation_prescreen": {HAIKU},  # injection/spam/moderation classifier (Tier 1 only)
    "over_disclosure_check": {HAIKU},  # teaser over-disclosure check
    "originality_explainer": {SONNET},  # originality overlap explanation
    "submission_assistant": {SONNET},  # submission assistant
}


def raw() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(get_settings().llm_models_file.read_text(encoding="utf-8"))
    return copy.deepcopy(data)


def test_the_real_file_loads_with_the_phase_2_tasks() -> None:
    reg = registry.load(get_settings().llm_models_file)
    assert set(reg.tasks) >= PHASE_2_TASKS
    assert reg.pricing_status == "verified"  # D-37: verified on 2026-09-29 (research/anthropic-prices-2026-09.md)
    assert reg.prices_verified is True
    tier1_only = {"moderation_prescreen", "over_disclosure_check", "originality_explainer"}
    for name in tier1_only:
        assert reg.task(name).purpose is Purpose.TIER1_ONLY
        assert reg.task(name).purpose.consent is None
    assert reg.task("submission_assistant").purpose.consent is ConsentPurpose.TIER2_LLM_ASSISTANT
    assert Purpose.TIER2_LLM_MODERATION.consent is ConsentPurpose.TIER2_LLM_MODERATION


def test_allocation_follows_the_spec_table() -> None:
    """docs/spec/09: Haiku for the classifiers, Sonnet for the explainer and the assistant (medium effort)."""
    reg = registry.parse(raw())
    haiku = reg.task("moderation_prescreen").model
    sonnet = reg.task("originality_explainer").model
    assert reg.task("over_disclosure_check").model == haiku
    assert reg.task("submission_assistant").model == sonnet
    assert haiku != sonnet
    assert "haiku" in haiku
    assert "sonnet" in sonnet
    assert reg.task("originality_explainer").effort == "medium"
    assert reg.task("submission_assistant").effort == "medium"
    assert reg.task("moderation_prescreen").effort is None  # n/a for Haiku, stated explicitly


def test_every_task_defaults_to_confidential_and_has_no_tools() -> None:
    data = raw()
    del data["tasks"]["moderation_prescreen"]["confidential"]
    reg = registry.parse(data)
    assert reg.task("moderation_prescreen").confidential is True
    assert all(task.allowed_tools == () for task in reg.tasks.values())  # explainers and classifiers have no tools
    assert all(task.json_schema_format for task in reg.tasks.values())  # native JSON-schema output by default


def test_unknown_task_is_a_config_error() -> None:
    with pytest.raises(LLMConfigError, match="register it"):
        registry.parse(raw()).task("nope")
    with pytest.raises(LLMConfigError, match=r"not in ai/models\.yaml"):
        registry.parse(raw()).model("nope")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(version=2), "version must be 1"),
        (lambda d: d["tasks"]["originality_explainer"].pop("effort"), "must set effort explicitly"),
        (lambda d: d["tasks"]["originality_explainer"].update(effort=None), "effort is set explicitly"),
        (lambda d: d["tasks"]["originality_explainer"].update(effort="turbo"), "must be one of"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(effort="low"), "has no effort parameter"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(model="gpt-x"), "unknown model"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(colour="red"), "unknown keys"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(max_tokens=10**9), "exceeds"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(max_tokens=0), "positive integer"),
        (lambda d: d["sanitiser"].update(max_input_ratio=0), "sanitiser.max_input_ratio"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(purpose="marketing"), "marketing"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(fallback_model="nope"), "another model"),
        (
            lambda d: d["tasks"]["moderation_prescreen"].update(
                fallback_model=d["tasks"]["moderation_prescreen"]["model"]
            ),
            "another model",
        ),
        (
            lambda d: d["tasks"]["moderation_prescreen"].update(fallback_model=SONNET, fallback_effort=None),
            "effort is set explicitly",
        ),
        (
            lambda d: d["tasks"]["moderation_prescreen"].update(fallback_model=None, fallback_effort="low"),
            "without fallback_model",
        ),
        (lambda d: d["tasks"]["moderation_prescreen"].update(allowed_tools="web"), "allowed_tools"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(json_schema_format="no"), "json_schema_format"),
        (lambda d: d["tasks"].update({"t" * 81: d["tasks"]["moderation_prescreen"]}), r"llm_calls\.task"),
        (lambda d: d["models"].update({"m" * 81: next(iter(d["models"].values()))}), r"llm_calls\.model"),
        (lambda d: d["budget"].update(soft_cap_ratio=1.5), "soft_cap_ratio"),
        (lambda d: d["embeddings"].update(precision="int4"), "embeddings.precision"),
        (lambda d: d["embeddings"].update(batch_size=0), "embeddings.batch_size"),
        (lambda d: d["embeddings"].update(model=""), "embeddings.model"),
        (lambda d: d["embeddings"].update(version=1), "embeddings.version"),
        (lambda d: d.update(batch_price_ratio=0), "batch_price_ratio"),
        (lambda d: next(iter(d["models"].values()))["price_usd_per_mtok"].pop("output"), "prices need"),
        (lambda d: next(iter(d["models"].values()))["price_usd_per_mtok"].update(input=-1), "zero or more"),
        (lambda d: next(iter(d["models"].values()))["price_usd_per_mtok"].update(input=True), "number"),
        (lambda d: next(iter(d["models"].values()))["price_usd_per_mtok"].update(input=0), "must be positive"),
        (lambda d: next(iter(d["models"].values()))["price_usd_per_mtok"].update(output=0), "must be positive"),
        (lambda d: d.update(pricing_status="guessed"), "pricing_status"),
        (lambda d: d.pop("pricing_verified_on"), "pricing_verified_on"),
        (lambda d: d.update(pricing_verified_on="yesterday"), "pricing_verified_on"),
        (lambda d: d.pop("pricing_source"), "pricing_source"),
        (lambda d: d.update(pricing_source="http://prices.example"), "pricing_source"),
        (lambda d: d.pop("free_providers"), "free_providers"),
        (lambda d: d["free_providers"].update(max_output_tokens=0), "free_providers.max_output_tokens"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(free_slots=[0]), "free_slots"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(free_slots=[4]), "free_slots"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(free_slots=[1, 1]), "free_slots"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(free_slots="1"), "free_slots"),
        (lambda d: d["tasks"]["moderation_prescreen"].update(free_slots=[True]), "free_slots"),
    ],
)
def test_strict_parsing_refuses(mutate: Any, message: str) -> None:
    data = raw()
    mutate(data)
    with pytest.raises(ValueError, match=message):
        registry.parse(data)


def test_task_field_cap_can_only_lower_the_default() -> None:
    data = raw()
    data["tasks"]["moderation_prescreen"]["max_field_chars"] = 500
    data["tasks"]["over_disclosure_check"]["max_field_chars"] = 10**6
    reg = registry.parse(data)
    assert reg.task("moderation_prescreen").max_field_chars == 500
    assert reg.task("over_disclosure_check").max_field_chars == reg.sanitiser.max_field_chars


def test_optional_tools_are_kept() -> None:
    data = raw()
    data["tasks"]["originality_explainer"]["allowed_tools"] = ["web_search"]
    assert registry.parse(data).task("originality_explainer").allowed_tools == ("web_search",)


def test_cost_counts_every_token_kind() -> None:
    data = raw()
    model_id = "m"
    data["models"] = {
        model_id: {
            "supports_effort": False,
            "max_output_tokens": 1000,
            "price_usd_per_mtok": {
                "input": 1,
                "output": 5,
                "cache_read": "0.1",
                "cache_write_5m": 1.25,
                "cache_write_1h": 2,
            },
        }
    }
    data["tasks"] = {}
    reg = registry.parse(data)
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=300_000,
        cache_creation_1h_input_tokens=100_000,
    )
    # 1 + 0.5 + 0.1 + 0.2 * 1.25 + 0.1 * 2
    assert reg.cost_usd(model_id, usage) == Decimal("2.050000")
    assert reg.cost_usd(model_id, usage, batch=True) == Decimal("1.025000")
    assert reg.cost_usd(model_id, TokenUsage()) == Decimal("0")
    # the estimate charges every requested output token and input at chars_per_token
    per_token = reg.budget.chars_per_token
    assert reg.estimate_usd(model_id, input_chars=per_token * 1000, max_tokens=1000) == Decimal("0.006000")
    # with cache breakpoints the input is priced at the highest cache-write rate (2 USD/M here): an upper bound
    assert reg.estimate_usd(model_id, input_chars=per_token * 1000, max_tokens=1000, cache_writes=True) == Decimal(
        "0.007000"
    )
    assert reg.estimate_usd(model_id, input_chars=0, max_tokens=0, tool_fees_usd=Decimal("0.01")) == Decimal("0.010000")
    assert reg.tool_fees_usd([{"type": "web_search_20260209"}]) == 0  # hook: no task allows tools yet


def test_load_is_cached() -> None:
    path = get_settings().llm_models_file
    assert registry.load(path) is registry.load(path)


def test_every_task_follows_the_spec_09_allocation() -> None:
    """D-29: the task model and any refusal fallback are models docs/spec/09 allocates to that task."""
    reg = registry.load(get_settings().llm_models_file)
    assert set(reg.tasks) == set(SPEC_09_ALLOCATION), "add new tasks to SPEC_09_ALLOCATION with their spec 09 models"
    for name, spec in reg.tasks.items():
        allowed = SPEC_09_ALLOCATION[name]
        assert spec.model in allowed, name
        assert spec.fallback_model is None or spec.fallback_model in allowed - {spec.model}, name
        assert spec.fallback_effort is None or spec.fallback_model is not None, name


# ---------------------------------------------------------------------------------------- D-37 (prototype track, P7)

SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
# research/anthropic-prices-2026-09.md (verified 2026-09-29): input, output, cache read, 5m and 1h writes
VERIFIED_PRICES = {
    SONNET: ("2", "10", "0.20", "2.50", "4"),
    HAIKU: ("1", "5", "0.10", "1.25", "2"),
    OPUS: ("4", "20", "0.20", "5", "8"),
}


def test_the_anthropic_prices_are_the_verified_list_prices() -> None:
    """D-37: the prices, the verification date and the source page of the research note; batch at 50%."""
    reg = registry.load(get_settings().llm_models_file)
    assert (reg.pricing_verified_on, reg.pricing_source) == (date(2026, 9, 29), SOURCE)
    for model_id, expected in VERIFIED_PRICES.items():
        p = reg.model(model_id).prices
        got = (p.input, p.output, p.cache_read, p.cache_write_5m, p.cache_write_1h)
        assert got == tuple(Decimal(v) for v in expected), model_id
    assert reg.batch_price_ratio == Decimal("0.5")


def test_placeholder_prices_still_parse_but_are_not_verified() -> None:
    data = raw()
    data["pricing_status"] = "placeholder-unverified"
    del data["pricing_verified_on"], data["pricing_source"]
    reg = registry.parse(data)
    assert reg.prices_verified is False
    assert (reg.pricing_verified_on, reg.pricing_source) == (None, None)


def test_every_task_lists_the_free_slots_that_may_serve_it() -> None:
    reg = registry.load(get_settings().llm_models_file)
    assert all(task.free_slots == (1, 2, 3) for task in reg.tasks.values())
    data = raw()
    del data["tasks"]["moderation_prescreen"]["free_slots"]
    assert registry.parse(data).task("moderation_prescreen").free_slots == ()  # never a free provider unless listed


def free_slot(number: int = 2, model: str = "vendor/demo-model", requests: int = 40) -> FreeSlot:
    return FreeSlot(number, "https://free.example/v1", SecretStr("k"), model, requests, "json_object")


def test_a_free_slot_registry_prices_at_zero_and_keeps_only_the_tasks_listing_the_slot() -> None:
    data = raw()
    data["tasks"]["originality_explainer"]["free_slots"] = [1]
    base = registry.parse(data)
    reg = base.for_free_slot(free_slot())
    key = registry.free_model_key(free_slot())
    assert key == "free2:vendor/demo-model"
    assert set(reg.models) == {key}
    spec = reg.model(key)
    assert (spec.supports_effort, spec.daily_requests, spec.max_output_tokens) == (False, 40, 8192)
    assert "originality_explainer" not in reg.tasks
    task = reg.task("submission_assistant")
    assert (task.model, task.effort, task.fallback_model, task.fallback_effort) == (key, None, None, None)
    assert task.json_schema_format is False  # the schema goes in the prompt for every free provider
    assert task.allowed_tools == ()
    assert task.purpose is base.task("submission_assistant").purpose
    assert task.max_tokens == base.task("submission_assistant").max_tokens
    usage = TokenUsage(input_tokens=10**6, output_tokens=10**6, cache_read_input_tokens=10**6)
    assert reg.cost_usd(key, usage) == 0
    assert reg.estimate_usd(key, input_chars=10**6, max_tokens=4096, cache_writes=True) == 0
    assert (reg.sanitiser, reg.budget, reg.transport) == (base.sanitiser, base.budget, base.transport)


def test_a_free_slot_lowers_a_task_budget_to_the_free_output_cap() -> None:
    data = raw()
    data["free_providers"]["max_output_tokens"] = 512
    reg = registry.parse(data).for_free_slot(free_slot())
    assert reg.task("moderation_prescreen").max_tokens == 512


def test_a_free_model_key_fits_the_ledger_column() -> None:
    assert len(registry.free_model_key(free_slot(3, "m" * 74))) <= registry.NAME_CHARS
