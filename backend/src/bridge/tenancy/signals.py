"""Cross-organisation signals (docs/spec/08 Tenancy; the P12 trends read them through ``app_trend_aggregates``).

``record`` inserts one ``signal_events`` row (``bridge_app`` may only INSERT; no RETURNING) in the caller's
transaction, so the signal exists if and only if its source event commits. A row holds ids, a kind code and two
pseudonyms, never a name:

- ``actor_hash``: the acting user's salted digest (``app_subject_digest``, the database's per-user salt; bridge_app
  computes only the current user's own), or none for a system signal such as a scout match;
- ``org_hash``: ``HMAC-SHA-256(k, org_id)`` with ``k = HMAC-SHA-256(SECRET_KEY, "bridge.signal_events.org_hash.v1")``:
  stable per organisation (so ``app_trend_aggregates`` can count distinct organisations, and shows a count only from
  3), and unlinkable to an organisation without the server key. Rotating ``SECRET_KEY`` starts new pseudonyms.

Kinds written so far: ``proposal_published`` and ``proposal_version_published`` (P2), ``scout_match`` (a scout matched
a proposal, P10) and ``org_interest`` (an organisation expressed interest, P10).
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bridge.config import Settings
from bridge.ids import uuid7

SCOUT_MATCH: Final = "scout_match"
ORG_INTEREST: Final = "org_interest"
ACTOR_LABEL: Final = b"signal_events.actor"  # the proposals' signal label (bridge.proposals.service.SIGNAL_ACTOR)
ORG_LABEL: Final = b"bridge.signal_events.org_hash.v1"
_INSERT = text(
    "INSERT INTO signal_events (id, item_id, kind, actor_hash, org_hash) VALUES (:id, :item, :kind, :actor, :org)"
)
_ACTOR = text("SELECT app_subject_digest(:user, :data)")


def org_hash(settings: Settings, org_id: UUID) -> bytes:
    """The organisation's pseudonym in ``signal_events.org_hash``."""
    key = hmac.new(settings.secret_key.get_secret_value().encode("utf-8"), ORG_LABEL, hashlib.sha256).digest()
    return hmac.new(key, org_id.bytes, hashlib.sha256).digest()


async def actor_hash(db: AsyncSession, user_id: UUID) -> bytes | None:
    """The current user's own salted digest (the database refuses anyone else's)."""
    digest = (await db.execute(_ACTOR, {"user": user_id, "data": ACTOR_LABEL})).scalar_one_or_none()
    return None if digest is None else bytes(digest)


async def record(
    db: AsyncSession,
    settings: Settings,
    *,
    item_id: UUID,
    kind: str,
    org_id: UUID | None = None,
    actor: bytes | None = None,
) -> None:
    """One signal in the caller's transaction (insert only)."""
    org = None if org_id is None else org_hash(settings, org_id)
    await db.execute(_INSERT, {"id": uuid7(), "item": item_id, "kind": kind, "actor": actor, "org": org})
