"""The Tier-2 guard (AC-SEC-6; ADR-005 decision 4; docs/spec/09 ground rules).

A Tier-2 field reaches a model only when the task's purpose is consent-covered (``tier2_llm_assistant`` or
``tier2_llm_moderation``) and every owner of a Tier-2 field holds a live consent for exactly that purpose. Tier-1-only
tasks (classifiers, the over-disclosure check, the originality explainer) refuse any Tier-2 field. The check runs
before sanitising, budgeting or sending, so a refused value is never framed, logged or recorded.

Consent scope (ADR-005 decision 4; docs/spec/06 §6.3): ``tier2_llm_moderation`` is persistent; ``tier2_llm_assistant``
is an explicit per-use opt-in that expires with the login session. Consents stay append-only rows of
``bridge.profiles.consents`` (REQ-CON-01, latest row wins); this module owns the session rule. The opt-in is written
only by ``grant_session_consent`` with ``source = session_consent_source(session_id)``, and it is live only while that
row is the owner's latest ``tier2_llm_assistant`` decision, the call carries the same session and that session is a
live login session of the owner (``bridge.auth.sessions.is_live``: not revoked, not expired, the owner active). A grant
from another or an earlier session, a grant naming another user's session, a revoked or expired session, a grant from
the settings page (no session) and any call without a session (a job) do not count.
"""

from __future__ import annotations

import base64
from collections.abc import Iterable, Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from bridge.auth import sessions as login_sessions
from bridge.config import Settings
from bridge.llm.errors import ConsentRequired, Tier2NotAllowed
from bridge.llm.registry import TaskSpec
from bridge.llm.types import Message, Tier
from bridge.models.enums import ConsentPurpose
from bridge.profiles import consents

PER_SESSION = consents.SESSION_ONLY
SESSION_SOURCE_PREFIX = consents.SESSION_SOURCE_PREFIX


def session_consent_source(session_id: UUID) -> str:
    """``consents.source`` of a per-session decision: the prefix and the session id in unpadded base64url (30
    characters, within the column's 32; the hex form would not fit)."""
    return SESSION_SOURCE_PREFIX + base64.urlsafe_b64encode(session_id.bytes).rstrip(b"=").decode("ascii")


async def grant_session_consent(db: AsyncSession, settings: Settings, *, user_id: UUID, session_id: UUID) -> None:
    """Record the owner's per-use opt-in to ``tier2_llm_assistant`` for one login session (REQ-PROP-05).

    The only writer of a per-session decision, so the source always matches what the checker compares. An interactive
    endpoint (the submission assistant, T2.9) takes both ids from its authenticated ``CurrentSession``: ``user_id`` is
    ``live.user.id`` and ``session_id`` is ``live.row.id`` (``sessions.id``, a UUID; never the cookie token). The
    same ``live.row.id`` goes into ``CallContext(session_id=...)`` for ``LLMService.complete``; jobs pass none. ``db``
    must be bound to ``user_id`` (``bind_tenant``): RLS refuses a row for anyone else. The endpoint checks the text
    version the user saw (as ``PUT /api/me/consents`` does), writes its audit event and commits; this only adds the
    row.
    """
    await _record_session_decision(db, settings, user_id=user_id, session_id=session_id, granted=True)


async def withdraw_session_consent(db: AsyncSession, settings: Settings, *, user_id: UUID, session_id: UUID) -> None:
    """Record the end of the opt-in (the user turns the assistant off) before the session itself ends."""
    await _record_session_decision(db, settings, user_id=user_id, session_id=session_id, granted=False)


async def _record_session_decision(
    db: AsyncSession, settings: Settings, *, user_id: UUID, session_id: UUID, granted: bool
) -> None:
    await consents.record_decisions(
        db,
        settings,
        user_id=user_id,
        decisions={ConsentPurpose.TIER2_LLM_ASSISTANT: granted},  # one purpose per decision, never bundled
        source=session_consent_source(session_id),
    )


class ConsentChecker(Protocol):
    async def has_live_consent(self, user_id: UUID, purpose: ConsentPurpose, *, session_id: UUID | None) -> bool:
        """``session_id`` is the caller's login session; per-session purposes are live only for that session."""
        ...


class SessionConsentChecker:
    """Reads ``consents`` through ``bridge.profiles.consents`` with the caller's database session (``db``; not to be
    confused with the login ``session_id``). RLS applies: a database session not bound to the owner reads no rows, so
    the check fails closed."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def has_live_consent(self, user_id: UUID, purpose: ConsentPurpose, *, session_id: UUID | None) -> bool:
        if purpose not in PER_SESSION:
            return await consents.has_live_consent(self._db, user_id, purpose)
        if session_id is None or not await login_sessions.is_live(self._db, session_id, user_id=user_id):
            return False
        latest = await consents.latest(self._db, user_id, purpose)
        return latest is not None and latest.granted and latest.source == session_consent_source(session_id)


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
