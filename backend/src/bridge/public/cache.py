"""One value held in process for a while (REQ-UX-03, P24-B): the public reads' cache.

Each API worker keeps its own copy of a public response for ``ttl_seconds`` (monotonic clock), so a flood of landing
page views costs one database read per minute per worker. Concurrent misses wait on one lock and share one load; a
load that raises leaves nothing behind, so the next read tries again. Nothing per visitor is ever cached here: only
responses that are the same for everyone.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class Cached[T]:
    def __init__(self, ttl_seconds: float, *, now: Callable[[], float] = time.monotonic) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Cached: the time-to-live must be positive")
        self._ttl = ttl_seconds
        self._now = now
        self._entry: tuple[float, T] | None = None  # (expires at, value)
        self._lock = asyncio.Lock()

    def _fresh(self) -> tuple[float, T] | None:
        entry = self._entry
        return entry if entry is not None and self._now() < entry[0] else None

    def fresh(self) -> T | None:
        """The held value while it is fresh, else None (nothing is loaded). For values that are never None."""
        entry = self._fresh()
        return None if entry is None else entry[1]

    async def get(self, load: Callable[[], Awaitable[T]]) -> T:
        """The held value while it is fresh; otherwise ``load()`` once (other readers wait for it) and hold that."""
        entry = self._fresh()
        if entry is None:
            async with self._lock:
                entry = self._fresh()
                if entry is None:
                    value = await load()
                    entry = self._entry = (self._now() + self._ttl, value)
        return entry[1]
