"""A test rig: ``LLMService`` over any adapter with in-memory ledger, sinks, consents and caps."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import yaml

from bridge.config import Settings, get_settings
from bridge.llm import registry as registry_module
from bridge.llm.adapter import ModelAdapter
from bridge.llm.budget import RecordingBudgetListener, StaticCaps
from bridge.llm.client import LLMService
from bridge.llm.demo_data import DataRule
from bridge.llm.guard import StaticConsents
from bridge.llm.ledger import InMemoryLedger
from bridge.llm.registry import Registry
from bridge.llm.sinks import InMemoryDeadLetters, InMemoryHumanQueue
from bridge.llm.types import InputField, Instruction, Message
from tests.unit.llm.helpers import NOW, real_registry, settings

NONCE = "0123456789abcdef"


@dataclass
class Rig:
    service: LLMService
    ledger: InMemoryLedger = field(default_factory=InMemoryLedger)
    dead_letters: InMemoryDeadLetters = field(default_factory=InMemoryDeadLetters)
    human_queue: InMemoryHumanQueue = field(default_factory=InMemoryHumanQueue)
    listener: RecordingBudgetListener = field(default_factory=RecordingBudgetListener)
    consents: StaticConsents = field(default_factory=StaticConsents)


def rig(
    adapter: ModelAdapter,
    *,
    reg: Registry | None = None,
    cfg: Settings | None = None,
    caps: StaticCaps | None = None,
    consents: StaticConsents | None = None,
    nonce: Callable[[], str] = lambda: NONCE,
    data_rule: DataRule | None = None,
) -> Rig:
    ledger, letters, queue = InMemoryLedger(), InMemoryDeadLetters(), InMemoryHumanQueue()
    listener, held = RecordingBudgetListener(), consents or StaticConsents()
    ticks = iter(range(10**6))
    service = LLMService(
        adapter=adapter,
        registry=reg or real_registry(),
        settings=cfg or settings(),
        ledger=ledger,
        consents=held,
        caps=caps or StaticCaps(),
        dead_letters=letters,
        human_queue=queue,
        budget_listener=listener,
        nonce=nonce,
        now=lambda: NOW,
        monotonic=lambda: next(ticks) * 0.25,  # every call takes 250 ms
        data_rule=data_rule,
    )
    return Rig(service, ledger, letters, queue, listener, held)


def registry_with(**task_changes: dict[str, Any]) -> Registry:
    """The real registry with some task keys changed (``task_name={key: value}``)."""
    data = copy.deepcopy(yaml.safe_load(get_settings().llm_models_file.read_text(encoding="utf-8")))
    for task, changes in task_changes.items():
        data["tasks"][task].update(changes)
    return registry_module.parse(data)


def screen(summary: str = "<b>Solar</b> kiosks for [markets](https://evil.example)") -> list[Message]:
    return [
        Message.system("You screen teasers for policy issues."),
        Message.user(Instruction("Screen this teaser:"), InputField("teaser.summary", summary)),
    ]


ZERO = Decimal(0)
