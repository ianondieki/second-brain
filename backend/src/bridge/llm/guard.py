"""The Tier-2 guard (AC-SEC-6; ADR-005 decision 4; docs/spec/09 ground rules).

A Tier-2 field reaches a model only when the task's purpose is consent-covered (``tier2_llm_assistant`` or
``tier2_llm_moderation``) and every owner of a Tier-2 field holds a live consent for exactly that purpose. Tier-1-only
tasks (classifiers, the over-disclosure check, the originality explainer) refuse any Tier-2 field. The check runs
before sanitising, budgeting or sending, so a refused value is never framed, logged or recorded.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bridge.llm.errors import ConsentRequired, Tier2NotAllowed
from bridge.llm.registry import TaskSpec
from bridge.llm.types import Message, Tier
from bridge.models.enums import ConsentPurpose
from bridge.profiles import consents


class ConsentChecker(Protocol):
    async def has_live_consent(self, user_id: UUID, purpose: ConsentPurpose) -> bool: ...


class SessionConsentChecker:
    """Reads ``consents`` through ``bridge.profiles.consents`` with the caller's session. RLS applies: a session not
    scoped to the owner reads no rows, so the check fails closed."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def has_live_consent(self, user_id: UUID, purpose: ConsentPurpose) -> bool:
        return await consents.has_live_consent(self._db, user_id, purpose)


class StaticConsents:
    """Consents held in memory (tests and fakes)."""

    def __init__(self, granted: Iterable[tuple[UUID, ConsentPurpose]] = ()) -> None:
        self.granted: set[tuple[UUID, ConsentPurpose]] = set(granted)

    def grant(self, user_id: UUID, purpose: ConsentPurpose) -> None:
        self.granted.add((user_id, purpose))

    def withdraw(self, user_id: UUID, purpose: ConsentPurpose) -> None:
        self.granted.discard((user_id, purpose))

    async def has_live_consent(self, user_id: UUID, purpose: ConsentPurpose) -> bool:
        return (user_id, purpose) in self.granted


async def check_tier2(task: TaskSpec, messages: Sequence[Message], checker: ConsentChecker) -> None:
    """Raise ``Tier2NotAllowed`` or ``ConsentRequired`` unless every Tier-2 field may go to the model."""
    tier2 = [f for message in messages for f in message.fields if f.tier is Tier.TIER2]
    if not tier2:
        return
    purpose = task.purpose.consent
    if purpose is None:
        raise Tier2NotAllowed(task.name, tuple(sorted({f.name for f in tier2})))
    refused: set[str] = set()
    decided: dict[UUID, bool] = {}
    for item in tier2:
        owner = item.owner_id
        if owner is not None and owner not in decided:
            decided[owner] = await checker.has_live_consent(owner, purpose)
        if owner is None or not decided[owner]:  # InputField already refuses a Tier-2 field without an owner
            refused.add(item.name)
    if refused:
        raise ConsentRequired(task.name, purpose, tuple(sorted(refused)))
