"""Where failed and refused calls go (ADR-005 decision 3).

``DeadLetterSink`` receives a request whose retries are exhausted (refusal, ``max_tokens``, schema failure, an
unsupported stop reason) so a job can be replayed or a person can look. ``HumanQueue`` hears about every refusal as
it happens. Both carry sanitised inputs only (the ledger's form: never a Tier-2 value). The in-memory versions log and
keep a list; the SQL dead-letter table and the moderation-queue hook come with the schema (T2.1, T2.3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from bridge.logging import get_logger

log = get_logger("bridge.llm")


@dataclass(frozen=True, slots=True)
class DeadLetter:
    id: UUID
    created_at: datetime
    task: str
    trace_id: str
    org_id: UUID | None
    user_id: UUID | None
    reason: str
    model: str | None
    attempts: int
    detail: str
    inputs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RefusalEvent:
    task: str
    trace_id: str
    org_id: UUID | None
    user_id: UUID | None
    model: str
    category: str | None
    will_retry_on: str | None


class DeadLetterSink(Protocol):
    async def put(self, letter: DeadLetter) -> None: ...


class HumanQueue(Protocol):
    async def refusal(self, event: RefusalEvent) -> None: ...


class InMemoryDeadLetters:
    def __init__(self) -> None:
        self.letters: list[DeadLetter] = []

    async def put(self, letter: DeadLetter) -> None:
        self.letters.append(letter)
        log.warning(
            "llm.dead_letter",
            task=letter.task,
            reason=letter.reason,
            model=letter.model,
            attempts=letter.attempts,
            trace_id=letter.trace_id,
        )


class InMemoryHumanQueue:
    def __init__(self) -> None:
        self.events: list[RefusalEvent] = []

    async def refusal(self, event: RefusalEvent) -> None:
        self.events.append(event)
        log.warning(
            "llm.refusal",
            task=event.task,
            model=event.model,
            category=event.category,
            will_retry_on=event.will_retry_on,
            trace_id=event.trace_id,
        )
