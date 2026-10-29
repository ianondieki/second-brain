"""The directory's responsiveness score (docs/spec/06 6.2 and 6.12; REQ-DIR-01).

Shown only for an E2 organisation with at least 10 eligible tags, once 60 days have passed since it reached E2
(``organizations.e2_verified_at``). The rules are plain code here; the numbers come from a ``ResponsivenessSource``:
none until Phase 3 computes them from ``signal_events`` (eligible tags: passed pre-delivery moderation and the
niche-match gate, minus tags the organisation marked spam or out of scope after moderator review), fixtures in tests.
The eligible-tag count itself is never shown (tags are never public, docs/spec/03).
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from bridge.directory.schemas import Responsiveness
from bridge.models.enums import OrgVerification

MIN_ELIGIBLE_TAGS: Final = 10
MIN_TIME_SINCE_E2: Final = timedelta(days=60)


@dataclass(frozen=True, slots=True)
class ResponsivenessStats:
    eligible_tags: int
    median_response_days: float
    answered_share: float  # 0..1 of eligible tags answered

    def __post_init__(self) -> None:
        if self.eligible_tags < 0 or self.median_response_days < 0 or not 0 <= self.answered_share <= 1:
            raise ValueError("responsiveness stats out of range")


class ResponsivenessSource(Protocol):
    async def stats_for(self, org_ids: Collection[UUID]) -> Mapping[UUID, ResponsivenessStats]: ...


class NoResponsivenessData:
    """Until Phase 3: no organisation has a score."""

    async def stats_for(self, org_ids: Collection[UUID]) -> Mapping[UUID, ResponsivenessStats]:
        return {}


@dataclass(frozen=True, slots=True)
class FixtureResponsiveness:
    """Fixed numbers per organisation (tests and the dev stack until Phase 3)."""

    stats: Mapping[UUID, ResponsivenessStats] = field(default_factory=dict)

    async def stats_for(self, org_ids: Collection[UUID]) -> Mapping[UUID, ResponsivenessStats]:
        return {org_id: self.stats[org_id] for org_id in org_ids if org_id in self.stats}


def score_visible(
    *,
    verification: OrgVerification,
    e2_verified_at: datetime | None,
    stats: ResponsivenessStats | None,
    now: datetime,
) -> bool:
    return (
        verification == OrgVerification.E2
        and e2_verified_at is not None
        and stats is not None
        and stats.eligible_tags >= MIN_ELIGIBLE_TAGS
        and now - e2_verified_at >= MIN_TIME_SINCE_E2
    )


def _half_up(value: float) -> int:
    return math.floor(value + 0.5)


def responsiveness_for(
    *,
    verification: OrgVerification,
    e2_verified_at: datetime | None,
    stats: ResponsivenessStats | None,
    now: datetime,
) -> Responsiveness | None:
    if stats is None or not score_visible(
        verification=verification, e2_verified_at=e2_verified_at, stats=stats, now=now
    ):
        return None
    days = _half_up(stats.median_response_days)
    answered = _half_up(stats.answered_share * 100)
    # Copy from docs/spec/06 6.2: "Responds in a median of N days · X% answered".
    text = f"Responds in a median of {days} {'day' if days == 1 else 'days'} · {answered}% answered"
    return Responsiveness(median_days=days, answered_pct=answered, text=text)
