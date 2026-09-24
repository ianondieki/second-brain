"""The one place that reads the wall clock, so tests (and the Phase 3 test clock) can move time."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
