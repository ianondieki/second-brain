"""REQ-UX-03 (P24-B): the public reads' in-process cache. One load per minute per worker: a second read within the
time-to-live is served from memory, a read after it loads again, concurrent misses share one load, and a failed load
is not remembered."""

from __future__ import annotations

import asyncio

import pytest

from bridge.public.cache import Cached


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Loader:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> int:
        self.calls += 1
        await asyncio.sleep(0)
        return self.calls


async def test_a_second_read_within_the_ttl_is_served_from_memory() -> None:
    clock, load = Clock(), Loader()
    cached: Cached[int] = Cached(60, now=clock)
    assert await cached.get(load) == 1
    clock.now += 59.9
    assert await cached.get(load) == 1
    assert load.calls == 1


async def test_a_read_after_the_ttl_loads_again() -> None:
    clock, load = Clock(), Loader()
    cached: Cached[int] = Cached(60, now=clock)
    await cached.get(load)
    clock.now += 60
    assert await cached.get(load) == 2
    assert load.calls == 2


async def test_concurrent_misses_share_one_load() -> None:
    load = Loader()
    cached: Cached[int] = Cached(60, now=Clock())
    results = await asyncio.gather(*(cached.get(load) for _ in range(5)))
    assert results == [1] * 5
    assert load.calls == 1


async def test_a_failed_load_is_not_remembered() -> None:
    cached: Cached[int] = Cached(60, now=Clock())

    async def broken() -> int:
        raise RuntimeError("database down")

    with pytest.raises(RuntimeError, match="database down"):
        await cached.get(broken)
    load = Loader()
    assert await cached.get(load) == 1


def test_the_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        Cached[int](0)
