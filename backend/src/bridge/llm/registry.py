"""The runtime model registry from ``backend/ai/models.yaml`` (ADR-005 decision 1; REQ-LLM-01).

Every model id, effort, token budget, price, cap ratio and length cap lives in the YAML; code asks the registry and
never names a model. ``parse`` validates strictly (unknown keys, models and purposes fail), so a typo cannot silently
change behaviour.

Free provider slots (D-37): a slot's model id comes from ``backend/.env`` (``bridge.config.FreeSlot``), never from code.
``Registry.for_free_slot`` derives the registry a slot's calls run under: one zero-priced model named
``free<N>:<model>`` (``free_model_key``, the ``llm_calls.model`` of its rows) with the slot's daily request cap, and
the tasks that list the slot in ``free_slots``, without effort, fallback or tools, and with the schema in the prompt.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from bridge.config import LLM_FREE_SLOTS, FreeSlot
from bridge.llm.errors import LLMConfigError
from bridge.llm.types import TokenUsage
from bridge.models.enums import ConsentPurpose

Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})
PRECISIONS: frozenset[str] = frozenset({"fp32", "fp16", "int8"})
MILLION = Decimal(1_000_000)
COST_QUANTUM = Decimal("0.000001")  # llm_calls.cost_usd is numeric(12,6)
NAME_CHARS = 80  # llm_calls.task and llm_calls.model are varchar(80): a longer name could not be recorded
VERIFIED = "verified"
PRICING_STATUSES = frozenset({VERIFIED, "placeholder-unverified"})


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


ZERO_PRICES = Prices(Decimal(0), Decimal(0), Decimal(0), Decimal(0), Decimal(0))


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """``daily_requests``: a free provider slot's cap on attempts per UTC day, counted in the ledger (None: no cap)."""

    id: str
    supports_effort: bool
    max_output_tokens: int
    prices: Prices
    daily_requests: int | None = None

    @property
    def paid(self) -> bool:
        """Whether an attempt on the model can cost anything (the spend caps apply); only free slots are not."""
        p = self.prices
        return any(price > 0 for price in (p.input, p.output, p.cache_read, p.cache_write_5m, p.cache_write_1h))


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
    json_schema_format: bool = True
    free_slots: tuple[int, ...] = ()  # the free provider slots that may serve the task (D-37), in order


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    soft_cap_ratio: Decimal
    chars_per_token: int


@dataclass(frozen=True, slots=True)
class SanitiserPolicy:
    max_field_chars: int
    base64_run_chars: int
    base64_segment_chars: int
    max_input_ratio: int  # the input is cut to this many times the field's cap before cleaning


@dataclass(frozen=True, slots=True)
class TransportPolicy:
    timeout_seconds: float
    max_retries: int


@dataclass(frozen=True, slots=True)
class EmbeddingPolicy:
    model: str
    version: str
    precision: Literal["fp32", "fp16", "int8"]
    batch_size: int
    reembed_batch_size: int
    # embed_model -> the cosine from which Recommended for you says "Similar to your profile" (P23-1 review round 1);
    # a model without one gets the ranker's default (``bridge.matching.ranker.SEMANTIC_CHIP_FLOOR``)
    chip_floors: Mapping[str, float] = field(default_factory=dict)

    def chip_floor(self, embed_model: str) -> float | None:
        return self.chip_floors.get(embed_model)


@dataclass(frozen=True, slots=True)
class FreePolicy:
    max_output_tokens: int  # a free model's output cap: a task's max_tokens is lowered to it


def free_model_key(slot: FreeSlot) -> str:
    """The registry and ledger name of a free slot's model (at most 80 characters: the settings cap the model id)."""
    return f"{slot.name}:{slot.model}"


@dataclass(frozen=True)
class Registry:
    models: Mapping[str, ModelSpec]
    tasks: Mapping[str, TaskSpec]
    batch_price_ratio: Decimal
    budget: BudgetPolicy
    sanitiser: SanitiserPolicy
    transport: TransportPolicy
    embeddings: EmbeddingPolicy
    pricing_status: str
    free: FreePolicy = FreePolicy(max_output_tokens=4096)
    pricing_verified_on: date | None = None
    pricing_source: str | None = None

    @property
    def prices_verified(self) -> bool:
        """Whether the price table was checked against the provider's page (the Anthropic provider needs it)."""
        return self.pricing_status == VERIFIED

    def for_free_slot(self, slot: FreeSlot) -> Registry:
        """The registry of one free slot's calls: its zero-priced model and the tasks listing the slot."""
        key = _name(free_model_key(slot), "model")
        spec = ModelSpec(key, False, self.free.max_output_tokens, ZERO_PRICES, daily_requests=slot.daily_requests)
        tasks = {
            name: replace(
                task,
                model=key,
                effort=None,
                max_tokens=min(task.max_tokens, spec.max_output_tokens),
                fallback_model=None,
                fallback_effort=None,
                allowed_tools=(),
                json_schema_format=False,  # the schema goes in the system prompt; the reply is validated as ever
            )
            for name, task in self.tasks.items()
            if slot.number in task.free_slots
        }
        return replace(self, models={key: spec}, tasks=tasks)

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

    def estimate_usd(
        self,
        model_id: str,
        *,
        input_chars: int,
        max_tokens: int,
        batch: bool = False,
        cache_writes: bool = False,
        tool_fees_usd: Decimal = Decimal(0),
    ) -> Decimal:
        """A pre-call upper bound: every requested output token, the input at ``chars_per_token`` priced at the
        highest cache-write rate when the request sets cache breakpoints (the whole prefix may be written), plus
        ``tool_fees_usd`` (see ``tool_fees_usd``)."""
        p = self.model(model_id).prices
        input_tokens = math.ceil(input_chars / self.budget.chars_per_token)
        input_rate = max(p.input, p.cache_write_5m, p.cache_write_1h) if cache_writes else p.input
        total = (input_tokens * input_rate + max_tokens * p.output) / MILLION
        if batch:
            total *= self.batch_price_ratio
        return (total + tool_fees_usd).quantize(COST_QUANTUM, rounding=ROUND_HALF_UP)

    def tool_fees_usd(self, tools: Sequence[Mapping[str, Any]]) -> Decimal:
        """Hook for per-use server-tool fees (web search and fetch, Phase 3 research): 0 while no registered task
        allows tools. When one does, price its tools here (from a YAML fee table) so the pre-call bound covers them."""
        return Decimal(0)


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
    "json_schema_format",
    "free_slots",
}
_PRICE_KEYS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")


def _decimal(value: Any, where: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{where} must be a number")
    number = Decimal(str(value))
    if number < 0:
        raise ValueError(f"{where} must be zero or more")
    return number


def _flag(value: Any, where: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be true or false")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} must be a non-empty string")
    return value


def _cosine(value: Any, where: str) -> float:
    number = _decimal(value, where)
    if number > 1:
        raise ValueError(f"{where} must be a cosine in [0, 1]")
    return float(number)


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


def _name(name: str, kind: str) -> str:
    if not 0 < len(name) <= NAME_CHARS:
        raise ValueError(f"{kind} names are 1-{NAME_CHARS} characters (llm_calls.{kind})")
    return name


def _model(model_id: str, raw: Mapping[str, Any]) -> ModelSpec:
    _name(model_id, "model")
    prices = raw["price_usd_per_mtok"]
    if set(prices) != set(_PRICE_KEYS):
        raise ValueError(f"{model_id} prices need exactly {', '.join(_PRICE_KEYS)}")
    parsed = Prices(*(_decimal(prices[key], f"{model_id}.{key}") for key in _PRICE_KEYS))
    if parsed.input <= 0 or parsed.output <= 0:
        # A zero price would take the model out of the spend caps; free slots are priced in code, never here.
        raise ValueError(f"{model_id} input and output prices must be positive")
    return ModelSpec(
        id=model_id,
        supports_effort=bool(raw["supports_effort"]),
        max_output_tokens=_positive_int(raw["max_output_tokens"], f"{model_id}.max_output_tokens"),
        prices=parsed,
    )


def _task(name: str, raw: Mapping[str, Any], models: Mapping[str, ModelSpec], default_cap: int) -> TaskSpec:
    _name(name, "task")
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
    slots = raw.get("free_slots", [])
    if (
        not isinstance(slots, list)
        or not all(isinstance(n, int) and not isinstance(n, bool) and n in LLM_FREE_SLOTS for n in slots)
        or len(set(slots)) != len(slots)
    ):
        raise ValueError(f"task {name} free_slots must be a list of distinct slot numbers from {list(LLM_FREE_SLOTS)}")
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
        json_schema_format=_flag(raw.get("json_schema_format", True), f"{name}.json_schema_format"),
        free_slots=tuple(slots),
    )


def _pricing(data: Mapping[str, Any]) -> tuple[str, date | None, str | None]:
    """The price table's status; a verified table names the day it was checked and the https page it came from."""
    status = data.get("pricing_status")
    if status not in PRICING_STATUSES:
        raise ValueError(f"pricing_status must be one of {sorted(PRICING_STATUSES)}")
    if status != VERIFIED:
        return str(status), None, None
    checked = data.get("pricing_verified_on")
    if isinstance(checked, str):
        try:
            checked = date.fromisoformat(checked)
        except ValueError:
            checked = None
    if not isinstance(checked, date):
        raise ValueError("pricing_verified_on must be the date the verified prices were checked (YYYY-MM-DD)")
    source = data.get("pricing_source")
    if not isinstance(source, str) or not source.startswith("https://"):
        raise ValueError("pricing_source must be the https page the verified prices come from")
    return VERIFIED, checked, source


def parse(data: Mapping[str, Any]) -> Registry:
    """Build and validate the registry; raises ``ValueError`` naming the first problem."""
    if data.get("version") != 1:
        raise ValueError("ai/models.yaml version must be 1")
    models = {str(model_id): _model(str(model_id), raw) for model_id, raw in data["models"].items()}
    sanitiser = SanitiserPolicy(
        max_field_chars=_positive_int(data["sanitiser"]["max_field_chars"], "sanitiser.max_field_chars"),
        base64_run_chars=_positive_int(data["sanitiser"]["base64_run_chars"], "sanitiser.base64_run_chars"),
        base64_segment_chars=_positive_int(data["sanitiser"]["base64_segment_chars"], "sanitiser.base64_segment_chars"),
        max_input_ratio=_positive_int(data["sanitiser"]["max_input_ratio"], "sanitiser.max_input_ratio"),
    )
    ratio = _decimal(data["budget"]["soft_cap_ratio"], "budget.soft_cap_ratio")
    if not 0 < ratio <= 1:
        raise ValueError("budget.soft_cap_ratio must be in (0, 1]")
    batch_ratio = _decimal(data["batch_price_ratio"], "batch_price_ratio")
    if not 0 < batch_ratio <= 1:
        raise ValueError("batch_price_ratio must be in (0, 1]")
    tasks = {str(name): _task(str(name), raw, models, sanitiser.max_field_chars) for name, raw in data["tasks"].items()}
    status, verified_on, source = _pricing(data)
    if not isinstance(data.get("free_providers"), Mapping):
        raise ValueError("free_providers must be set (max_output_tokens of a free model)")
    free = FreePolicy(
        _positive_int(data["free_providers"].get("max_output_tokens"), "free_providers.max_output_tokens")
    )
    embed = data["embeddings"]
    if embed["precision"] not in PRECISIONS:
        raise ValueError(f"embeddings.precision must be one of {sorted(PRECISIONS)}")
    chip_floors = embed.get("chip_floors") or {}
    if not isinstance(chip_floors, Mapping):
        raise ValueError("embeddings.chip_floors must map an embed_model to a cosine")
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
        embeddings=EmbeddingPolicy(
            model=_text(embed["model"], "embeddings.model"),
            version=_text(embed["version"], "embeddings.version"),
            precision=embed["precision"],
            batch_size=_positive_int(embed["batch_size"], "embeddings.batch_size"),
            reembed_batch_size=_positive_int(embed["reembed_batch_size"], "embeddings.reembed_batch_size"),
            chip_floors={
                _text(name, "embeddings.chip_floors key"): _cosine(value, f"embeddings.chip_floors.{name}")
                for name, value in chip_floors.items()
            },
        ),
        pricing_status=status,
        free=free,
        pricing_verified_on=verified_on,
        pricing_source=source,
    )


@lru_cache(maxsize=4)
def load(path: Path) -> Registry:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
