"""The one place that reads the wall clock. Callers use ``clock.utcnow()`` (module attribute, looked up at call time),
so tests and the Phase 3 test clock can replace it with ``monkeypatch.setattr(bridge.clock, "utcnow", ...)``."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)
