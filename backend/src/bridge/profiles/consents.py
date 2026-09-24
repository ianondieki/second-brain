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
from uuid import UUID

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.config import Settings
from bridge.models.enums import ConsentPurpose
from bridge.profiles.models import Consent


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


async def record_decisions(
    db: AsyncSession, settings: Settings, *, user_id: UUID, decisions: Mapping[ConsentPurpose, bool], source: str
) -> None:
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


async def has_live_consent(db: AsyncSession, user_id: UUID, purpose: ConsentPurpose) -> bool:
    return (await current(db, user_id))[purpose]
