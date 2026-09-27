"""The runtime model registry from ``backend/ai/models.yaml`` (ADR-005 decision 1; REQ-LLM-01).

Every model id, effort, token budget, price, cap ratio and length cap lives in the YAML; code asks the registry and
never names a model. ``parse`` validates strictly (unknown keys, models and purposes fail), so a typo cannot silently
change behaviour.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from bridge.llm.errors import LLMConfigError
from bridge.llm.types import TokenUsage
from bridge.models.enums import ConsentPurpose

Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})
MILLION = Decimal(1_000_000)
COST_QUANTUM = Decimal("0.000001")  # llm_calls.cost_usd is numeric(12,6)


class Purpose(StrEnum):
    """Why a task processes data. Only the two consent purposes may read Tier-2 fields (AC-SEC-6)."""

    TIER1_ONLY = "tier1_only"
    TIER2_LLM_ASSISTANT = "tier2_llm_assistant"
    TIER2_LLM_MODERATION = "tier2_llm_moderation"

    @property
    def consent(self) -> ConsentPurpose | None:
        """The consent a Tier-2 field's owner must hold, or None when the purpose reads Tier 1 only."""
        return None if self is Purpose.TIER1_ONLY else ConsentPurpose(self.value)


@dataclass(frozen=True, slots=True)
class Prices:
    """USD per million tokens."""

    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write_5m: Decimal
    cache_write_1h: Decimal


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    supports_effort: bool
    max_output_tokens: int
    prices: Prices


@dataclass(frozen=True, slots=True)
class TaskSpec:
    name: str
    model: str
    effort: Effort | None
    max_tokens: int
    batchable: bool
    confidential: bool
    purpose: Purpose
    fallback_model: str | None
    fallback_effort: Effort | None
    allowed_tools: tuple[str, ...]
    max_field_chars: int


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    soft_cap_ratio: Decimal
    chars_per_token: int


@dataclass(frozen=True, slots=True)
class SanitiserPolicy:
    max_field_chars: int
    base64_run_chars: int


@dataclass(frozen=True, slots=True)
class TransportPolicy:
    timeout_seconds: float
    max_retries: int


@dataclass(frozen=True)
class Registry:
    models: Mapping[str, ModelSpec]
    tasks: Mapping[str, TaskSpec]
    batch_price_ratio: Decimal
    budget: BudgetPolicy
    sanitiser: SanitiserPolicy
    transport: TransportPolicy
    pricing_status: str

    def task(self, name: str) -> TaskSpec:
        try:
            return self.tasks[name]
        except KeyError:
            raise LLMConfigError(f"unknown LLM task {name!r}; register it in ai/models.yaml") from None

    def model(self, model_id: str) -> ModelSpec:
        try:
            return self.models[model_id]
        except KeyError:
            raise LLMConfigError(f"model {model_id!r} is not in ai/models.yaml") from None

    def cost_usd(self, model_id: str, usage: TokenUsage, *, batch: bool = False) -> Decimal:
        """What ``usage`` costs on ``model_id``; batch requests at ``batch_price_ratio``."""
        p = self.model(model_id).prices
        write_1h = min(usage.cache_creation_1h_input_tokens, usage.cache_creation_input_tokens)
        write_5m = usage.cache_creation_input_tokens - write_1h
        total = (
            usage.input_tokens * p.input
            + usage.output_tokens * p.output
            + usage.cache_read_input_tokens * p.cache_read
            + write_5m * p.cache_write_5m
            + write_1h * p.cache_write_1h
        ) / MILLION
        if batch:
            total *= self.batch_price_ratio
        return total.quantize(COST_QUANTUM, rounding=ROUND_HALF_UP)

    def estimate_usd(self, model_id: str, *, input_chars: int, max_tokens: int, batch: bool = False) -> Decimal:
        """A pre-call upper estimate: every requested output token plus the input at ``chars_per_token``."""
        input_tokens = math.ceil(input_chars / self.budget.chars_per_token)
        return self.cost_usd(model_id, TokenUsage(input_tokens=input_tokens, output_tokens=max_tokens), batch=batch)


# ------------------------------------------------------------------------------------------------------- parsing

_TASK_KEYS = {
    "model",
    "effort",
    "max_tokens",
    "batchable",
    "confidential",
    "purpose",
    "fallback_model",
    "fallback_effort",
    "allowed_tools",
    "max_field_chars",
}
_PRICE_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def _decimal(value: Any, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{where} must be a number")
    number = Decimal(str(value))
    if number < 0:
        raise ValueError(f"{where} must be zero or more")
    return number


def _positive_int(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{where} must be a positive integer")
    return value


def _effort(model: ModelSpec, value: Any, where: str) -> Effort | None:
    if model.supports_effort:
        if value not in EFFORTS:
            raise ValueError(f"{where} must be one of {sorted(EFFORTS)} for {model.id} (effort is set explicitly)")
        return cast(Effort, value)
    if value is not None:
        raise ValueError(f"{where} must be null: {model.id} has no effort parameter")
    return None


def _model(model_id: str, raw: Mapping[str, Any]) -> ModelSpec:
    prices = raw["price_usd_per_mtok"]
    if set(prices) != set(_PRICE_KEYS):
        raise ValueError(f"{model_id} prices need exactly {', '.join(_PRICE_KEYS)}")
    return ModelSpec(
        id=model_id,
        supports_effort=bool(raw["supports_effort"]),
        max_output_tokens=_positive_int(raw["max_output_tokens"], f"{model_id}.max_output_tokens"),
        prices=Prices(*(_decimal(prices[key], f"{model_id}.{key}") for key in _PRICE_KEYS)),
    )


def _task(name: str, raw: Mapping[str, Any], models: Mapping[str, ModelSpec], default_cap: int) -> TaskSpec:
    unknown = set(raw) - _TASK_KEYS
    if unknown:
        raise ValueError(f"task {name} has unknown keys {sorted(unknown)}")
    for key in ("model", "effort", "max_tokens", "purpose"):
        if key not in raw:
            raise ValueError(f"task {name} must set {key} explicitly")
    if raw["model"] not in models:
        raise ValueError(f"task {name} uses unknown model {raw['model']!r}")
    model = models[raw["model"]]
    max_tokens = _positive_int(raw["max_tokens"], f"{name}.max_tokens")
    if max_tokens > model.max_output_tokens:
        raise ValueError(f"task {name} max_tokens exceeds {model.id} max_output_tokens")
    fallback_id = raw.get("fallback_model")
    fallback_effort: Effort | None = None
    if fallback_id is not None:
        if fallback_id not in models or fallback_id == model.id:
            raise ValueError(f"task {name} fallback_model must be another model in the registry")
        fallback_effort = _effort(models[fallback_id], raw.get("fallback_effort"), f"{name}.fallback_effort")
    elif raw.get("fallback_effort") is not None:
        raise ValueError(f"task {name} sets fallback_effort without fallback_model")
    cap = _positive_int(raw.get("max_field_chars", default_cap), f"{name}.max_field_chars")
    tools = raw.get("allowed_tools") or []
    if not isinstance(tools, list) or not all(isinstance(tool, str) and tool for tool in tools):
        raise ValueError(f"task {name} allowed_tools must be a list of tool type names")
    return TaskSpec(
        name=name,
        model=model.id,
        effort=_effort(model, raw["effort"], f"{name}.effort"),
        max_tokens=max_tokens,
        batchable=bool(raw.get("batchable", False)),
        confidential=bool(raw.get("confidential", True)),
        purpose=Purpose(raw["purpose"]),
        fallback_model=fallback_id,
        fallback_effort=fallback_effort,
        allowed_tools=tuple(tools),
        max_field_chars=min(cap, default_cap),
    )


def parse(data: Mapping[str, Any]) -> Registry:
    """Build and validate the registry; raises ``ValueError`` naming the first problem."""
    if data.get("version") != 1:
        raise ValueError("ai/models.yaml version must be 1")
    models = {str(model_id): _model(str(model_id), raw) for model_id, raw in data["models"].items()}
    sanitiser = SanitiserPolicy(
        max_field_chars=_positive_int(data["sanitiser"]["max_field_chars"], "sanitiser.max_field_chars"),
        base64_run_chars=_positive_int(data["sanitiser"]["base64_run_chars"], "sanitiser.base64_run_chars"),
    )
    ratio = _decimal(data["budget"]["soft_cap_ratio"], "budget.soft_cap_ratio")
    if not 0 < ratio <= 1:
        raise ValueError("budget.soft_cap_ratio must be in (0, 1]")
    batch_ratio = _decimal(data["batch_price_ratio"], "batch_price_ratio")
    if not 0 < batch_ratio <= 1:
        raise ValueError("batch_price_ratio must be in (0, 1]")
    tasks = {str(name): _task(str(name), raw, models, sanitiser.max_field_chars) for name, raw in data["tasks"].items()}
    return Registry(
        models=models,
        tasks=tasks,
        batch_price_ratio=batch_ratio,
        budget=BudgetPolicy(
            soft_cap_ratio=ratio,
            chars_per_token=_positive_int(data["budget"]["chars_per_token"], "budget.chars_per_token"),
        ),
        sanitiser=sanitiser,
        transport=TransportPolicy(
            timeout_seconds=float(_decimal(data["transport"]["timeout_seconds"], "transport.timeout_seconds")),
            max_retries=int(_decimal(data["transport"]["max_retries"], "transport.max_retries")),
        ),
        pricing_status=str(data.get("pricing_status", "")),
    )


@lru_cache(maxsize=4)
def load(path: Path) -> Registry:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
