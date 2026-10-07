"""Consents with versioned text and separate purposes (REQ-CON-01; docs/spec/10 Data protection).

Each decision is a new row (append-only: the app role has INSERT and SELECT only) recording the purpose, the
decision, the text version and the SHA-256 of the exact wording shown. The current state of a purpose is its latest
row; no row means "not given". Purposes are never bundled: each needs its own decision.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final
from uuid import UUID

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.config import Settings
from bridge.models.enums import ConsentPurpose
from bridge.profiles.models import Consent

# Purposes decided for one login session only (ADR-005 decision 4; docs/spec/06 6.3): the submission assistant's
# opt-in is recorded by ``bridge.llm.guard.grant_session_consent`` from the assistant's own endpoint and ends with the
# session. The settings API neither lists nor records them (REQ-PROP-05): a settings or signup row never opens one.
SESSION_ONLY: Final = frozenset({ConsentPurpose.TIER2_LLM_ASSISTANT})
SETTINGS_PURPOSES: Final = tuple(p for p in ConsentPurpose if p not in SESSION_ONLY)
# ``consents.source`` of a per-session decision starts with this (``bridge.llm.guard.session_consent_source``).
SESSION_SOURCE_PREFIX: Final = "session:"
# The refusal's message wherever such a purpose is sent (the settings API; signup, REQ-AUTH-01). [[COPY-REVIEW]]
SESSION_ONLY_MESSAGE: Final = (
    "Turn the writing assistant on from the proposal editor: it lasts for one sign-in at a time."
)


@dataclass(frozen=True, slots=True)
class ConsentText:
    purpose: ConsentPurpose
    version: str
    text: str

    @property
    def sha256(self) -> bytes:
        return hashlib.sha256(self.text.encode("utf-8")).digest()


@lru_cache(maxsize=4)
def load_texts(path: Path) -> dict[ConsentPurpose, ConsentText]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    version = str(data["version"])
    texts = {
        ConsentPurpose(k): ConsentText(ConsentPurpose(k), version, str(v["text"])) for k, v in data["purposes"].items()
    }
    missing = set(ConsentPurpose) - set(texts)
    if missing:
        raise ValueError(f"consents.yaml lacks {sorted(missing)}")
    return texts


@lru_cache(maxsize=4)
def _file_meta(path: Path) -> dict[str, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {"version": str(data["version"]), "terms_version": str(data.get("terms_version", ""))}


def consents_version(settings: Settings) -> str:
    return _file_meta(settings.consents_file)["version"]


def terms_version(settings: Settings) -> str:
    return _file_meta(settings.consents_file)["terms_version"]


async def record_decisions(
    db: AsyncSession, settings: Settings, *, user_id: UUID, decisions: Mapping[ConsentPurpose, bool], source: str
) -> None:
    """Record one row per decision. A purpose decided per sign-in (``SESSION_ONLY``) is recorded only with a
    ``session:`` source, whatever its value: defence in depth behind the settings API's and signup's refusals
    (REQ-PROP-05, REQ-AUTH-01), so no lasting row of it is ever written."""
    if not source.startswith(SESSION_SOURCE_PREFIX) and any(purpose in SESSION_ONLY for purpose in decisions):
        raise ValueError("a purpose decided per sign-in is recorded only for a login session")
    texts = load_texts(settings.consents_file)
    for purpose, granted in decisions.items():
        shown = texts[ConsentPurpose(purpose)]
        db.add(
            Consent(
                user_id=user_id,
                purpose=shown.purpose,
                granted=bool(granted),
                text_version=shown.version,
                text_sha256=shown.sha256,
                source=source,
            )
        )
    await db.flush()


async def current(db: AsyncSession, user_id: UUID) -> dict[ConsentPurpose, bool]:
    """Latest decision per purpose; purposes never decided are False."""
    rows = await db.execute(
        select(Consent.purpose, Consent.granted)
        .where(Consent.user_id == user_id)
        .distinct(Consent.purpose)
        .order_by(Consent.purpose, Consent.created_at.desc(), Consent.id.desc())
    )
    state = dict.fromkeys(ConsentPurpose, False)
    for purpose, granted in rows.all():
        state[ConsentPurpose(purpose)] = bool(granted)
    return state


async def latest(db: AsyncSession, user_id: UUID, purpose: ConsentPurpose) -> Consent | None:
    """The current decision on one purpose (its latest row, ordered as in ``current``), or None if never decided."""
    rows = await db.execute(
        select(Consent)
        .where(Consent.user_id == user_id, Consent.purpose == purpose)
        .order_by(Consent.created_at.desc(), Consent.id.desc())
        .limit(1)
    )
    return rows.scalar_one_or_none()


async def has_live_consent(db: AsyncSession, user_id: UUID, purpose: ConsentPurpose) -> bool:
    return (await current(db, user_id))[purpose]


_CLEAR_PROFILE_EMBEDDING = text("SELECT app_clear_profile_embedding(:me)")


async def clear_profile_embedding(db: AsyncSession, user_id: UUID) -> None:
    """AC-PERS-3: personalisation off removes the profile embedding in the same transaction as the decision (revision
    0012's withdrawal trigger clears it too; this is the app's own step). The database function serves the bound user's
    own row only; a user without a developer profile is a no-op."""
    await db.execute(_CLEAR_PROFILE_EMBEDDING, {"me": user_id})
