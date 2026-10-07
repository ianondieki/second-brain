"""One value held in process for a while (REQ-UX-03, P24-B): the public reads' cache.

Each API worker keeps its own copy of a public response for ``ttl_seconds`` (monotonic clock), so a flood of landing
page views costs one database read per minute per worker. Concurrent misses wait on one lock and share one load; a
load that raises leaves nothing behind, so the next read tries again. Nothing per visitor is ever cached here: only
responses that are the same for everyone. ``Keyed`` holds one such value per key (a public problem page per id) for
at most ``cap`` keys, dropping the least recently used.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable


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


class Keyed[K: Hashable, T]:
    """One ``Cached`` per key, at most ``cap`` keys: the least recently used key leaves first."""

    def __init__(self, ttl_seconds: float, *, cap: int, now: Callable[[], float] = time.monotonic) -> None:
        if ttl_seconds <= 0 or cap < 1:
            raise ValueError("Keyed: the time-to-live must be positive and the cap at least 1")
        self._ttl, self._cap, self._now = ttl_seconds, cap, now
        self._slots: OrderedDict[K, Cached[T]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._slots)

    def slot(self, key: K) -> Cached[T]:
        """The key's cache (kept as the most recently used), made on first use; the oldest key beyond ``cap`` leaves."""
        found = self._slots.get(key)
        if found is None:
            found = self._slots[key] = Cached(self._ttl, now=self._now)
            while len(self._slots) > self._cap:
                self._slots.popitem(last=False)
        else:
            self._slots.move_to_end(key)
        return found

    def drop(self, key: K) -> None:
        """Forget the key (a load that found nothing keeps no slot)."""
        self._slots.pop(key, None)
