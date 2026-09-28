"""The Tier-2 guard (AC-SEC-6; ADR-005 decision 4; ADR-002 consents; docs/spec/09 ground rules).

A Tier-2 field reaches a model only when the task's purpose is consent-covered (``tier2_llm_assistant`` or
``tier2_llm_moderation``) and every owner of a Tier-2 field holds a live consent for exactly that purpose. Tier-1-only
tasks (classifiers, the over-disclosure check, the originality explainer) refuse any Tier-2 field. The check runs
before sanitising, budgeting or sending, so a refused value is never framed, logged or recorded.

Consent scope (ADR-002): ``tier2_llm_moderation`` is persistent; ``tier2_llm_assistant`` is per session, so it is live
only for the session in which the owner granted it. The per-use decision is recorded (REQ-PROP-05) with
``source = session_consent_source(session_id)``; the checker compares the latest decision's source with the current
session, so a grant from another or an earlier session does not count.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.llm.errors import ConsentRequired, Tier2NotAllowed
from bridge.llm.registry import TaskSpec
from bridge.llm.types import Message, Tier
from bridge.models.enums import ConsentPurpose
from bridge.profiles import consents
from bridge.profiles.models import Consent

PER_SESSION = frozenset({ConsentPurpose.TIER2_LLM_ASSISTANT})
SESSION_SOURCE_PREFIX = "session:"


def session_consent_source(session_id: UUID) -> str:
    """``consents.source`` of a per-session decision: the prefix and the session id in unpadded base64url (30
    characters, within the column's 32)."""
    return SESSION_SOURCE_PREFIX + base64.urlsafe_b64encode(session_id.bytes).rstrip(b"=").decode("ascii")


class ConsentChecker(Protocol):
    async def has_live_consent(self, user_id: UUID, purpose: ConsentPurpose, *, session_id: UUID | None) -> bool:
        """``session_id`` is the caller's login session; per-session purposes are live only for that session."""
        ...


class SessionConsentChecker:
    """Reads ``consents`` with the caller's database session. RLS applies: a session not scoped to the owner reads no
    rows, so the check fails closed."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def has_live_consent(self, user_id: UUID, purpose: ConsentPurpose, *, session_id: UUID | None) -> bool:
        if purpose not in PER_SESSION:
            return await consents.has_live_consent(self._db, user_id, purpose)
        if session_id is None:
            return False
        latest = (
            await self._db.execute(
                select(Consent.granted, Consent.source)
                .where(Consent.user_id == user_id, Consent.purpose == purpose)
                .order_by(Consent.created_at.desc(), Consent.id.desc())
                .limit(1)
            )
        ).first()
        return latest is not None and bool(latest.granted) and latest.source == session_consent_source(session_id)


class StaticConsents:
    """Consents held in memory (tests and fakes). Entries are ``(user, purpose)`` or ``(user, purpose, session)``; a
    per-session purpose is live only for the session it was granted in."""

    def __init__(self, granted: Iterable[tuple[UUID, ConsentPurpose] | tuple[UUID, ConsentPurpose, UUID]] = ()) -> None:
        self.granted: dict[tuple[UUID, ConsentPurpose], UUID | None] = {}
        for entry in granted:
            self.grant(entry[0], entry[1], session_id=entry[2] if len(entry) == 3 else None)

    def grant(self, user_id: UUID, purpose: ConsentPurpose, *, session_id: UUID | None = None) -> None:
        self.granted[(user_id, purpose)] = session_id

    def withdraw(self, user_id: UUID, purpose: ConsentPurpose) -> None:
        self.granted.pop((user_id, purpose), None)

    async def has_live_consent(self, user_id: UUID, purpose: ConsentPurpose, *, session_id: UUID | None) -> bool:
        if (user_id, purpose) not in self.granted:
            return False
        if purpose in PER_SESSION:
            granted_in = self.granted[(user_id, purpose)]
            return granted_in is not None and granted_in == session_id
        return True


async def check_tier2(
    task: TaskSpec, messages: Sequence[Message], checker: ConsentChecker, *, session_id: UUID | None = None
) -> None:
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
            decided[owner] = await checker.has_live_consent(owner, purpose, session_id=session_id)
        if owner is None or not decided[owner]:  # InputField already refuses a Tier-2 field without an owner
            refused.add(item.name)
    if refused:
        raise ConsentRequired(task.name, purpose, tuple(sorted(refused)))
