"""REQ-LLM-01: ai/models.yaml is the task -> model registry; parsing is strict and every effort is explicit."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest
import yaml

from bridge.config import get_settings
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
    assert reg.pricing_status.startswith("placeholder")
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
        (lambda d: d["budget"].update(soft_cap_ratio=1.5), "soft_cap_ratio"),
        (lambda d: d["embeddings"].update(precision="int4"), "embeddings.precision"),
        (lambda d: d["embeddings"].update(batch_size=0), "embeddings.batch_size"),
        (lambda d: d["embeddings"].update(model=""), "embeddings.model"),
        (lambda d: d["embeddings"].update(version=1), "embeddings.version"),
        (lambda d: d.update(batch_price_ratio=0), "batch_price_ratio"),
        (lambda d: next(iter(d["models"].values()))["price_usd_per_mtok"].pop("output"), "prices need"),
        (lambda d: next(iter(d["models"].values()))["price_usd_per_mtok"].update(input=-1), "zero or more"),
        (lambda d: next(iter(d["models"].values()))["price_usd_per_mtok"].update(input=True), "number"),
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
