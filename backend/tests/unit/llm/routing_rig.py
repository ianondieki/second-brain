"""A rig for ``RoutedLLMClient``: in-memory ledger, consents, caps and demo accounts; free slots over the real
``OpenAICompatibleAdapter`` (tests drive it through respx only); the Anthropic route over any adapter."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from pydantic import SecretStr

from bridge.config import FreeSlot, LLMProvider, Settings
from bridge.llm.adapter import ModelAdapter
from bridge.llm.budget import StaticCaps
from bridge.llm.client import LLMService
from bridge.llm.demo_data import DataRule, DemoDataRule, StaticDemoAccounts
from bridge.llm.fakes import FakeAdapter
from bridge.llm.guard import StaticConsents
from bridge.llm.ledger import InMemoryLedger
from bridge.llm.openai_adapter import OpenAICompatibleAdapter
from bridge.llm.registry import Registry
from bridge.llm.routing import FreeRoute, LLMRuntime, RoutedLLMClient
from tests.unit.llm.helpers import NOW, USER, real_registry, settings
from tests.unit.llm.rig import NONCE

BASES = {1: "https://free-one.example/v1", 2: "https://free-two.example/v1", 3: "https://free-three.example/v1"}
KEYS = {n: f"sk-free-{n}-key-not-real" for n in BASES}
OK = {"injection_suspected": False, "verdict": "clean", "reason": "fine"}


def url(n: int) -> str:
    return f"{BASES[n]}/chat/completions"


def slot(n: int = 1, requests: int = 10) -> FreeSlot:
    return FreeSlot(n, BASES[n], SecretStr(KEYS[n]), f"vendor/model-{n}", requests, "json_object")


def chat(body: Any = None, *, finish: str = "stop") -> httpx.Response:
    content = body if isinstance(body, str) else json.dumps(OK if body is None else body)
    choice = {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}
    usage = {"prompt_tokens": 50, "completion_tokens": 10}
    return httpx.Response(200, json={"id": "c", "choices": [choice], "usage": usage})


@dataclass
class Routed:
    client: RoutedLLMClient
    ledger: InMemoryLedger
    anthropic: ModelAdapter
    consents: StaticConsents
    built: list[str]  # the models of the services built, in order


def routed(
    *,
    provider: LLMProvider = "free",
    slots: Iterable[FreeSlot] = (slot(1),),
    demo: Iterable[UUID] = (USER,),
    anthropic: ModelAdapter | None = None,
    anthropic_configured: bool = True,
    demo_fallback: bool = True,
    reg: Registry | None = None,
    cfg: Settings | None = None,
    consents: StaticConsents | None = None,
    caps: StaticCaps | None = None,
) -> Routed:
    registry = reg or real_registry()
    ledger, held, built = InMemoryLedger(), consents or StaticConsents(), []
    config = cfg or settings()

    def build(service_registry: Registry, adapter: ModelAdapter, rule: DataRule | None) -> LLMService:
        built.append(",".join(sorted(service_registry.models)))
        return LLMService(
            adapter=adapter,
            registry=service_registry,
            settings=config,
            ledger=ledger,
            consents=held,
            caps=caps or StaticCaps(),
            nonce=lambda: NONCE,
            now=lambda: NOW,
            data_rule=rule,
        )

    routes = tuple(
        FreeRoute(s, registry.for_free_slot(s), OpenAICompatibleAdapter(s, timeout_seconds=5.0)) for s in slots
    )
    runtime = LLMRuntime(
        registry=registry,
        anthropic=anthropic or FakeAdapter(),
        anthropic_configured=anthropic_configured,
        provider=provider,
        demo_fallback=demo_fallback,
        free=routes,
    )
    client = RoutedLLMClient(
        runtime=runtime,
        services=build,
        ledger=ledger,
        consents=held,
        data_rule=DemoDataRule(StaticDemoAccounts(demo)),
        now=lambda: NOW,
    )
    return Routed(client, ledger, runtime.anthropic, held, built)
