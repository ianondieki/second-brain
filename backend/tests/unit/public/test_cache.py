"""REQ-UX-03 (P24-B): the public reads' in-process cache. One load per minute per worker: a second read within the
time-to-live is served from memory, a read after it loads again, concurrent misses share one load, and a failed load
is not remembered."""

from __future__ import annotations

import asyncio

import pytest

from bridge.public.cache import Cached, Keyed


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


async def test_a_peek_never_loads() -> None:
    clock, load = Clock(), Loader()
    cached: Cached[int] = Cached(60, now=clock)
    assert cached.fresh() is None
    await cached.get(load)
    assert cached.fresh() == 1
    clock.now += 60
    assert cached.fresh() is None
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


async def test_a_keyed_cache_keeps_one_value_per_key() -> None:
    keyed: Keyed[str, int] = Keyed(60, cap=4, now=Clock())
    first, again = keyed.slot("a"), keyed.slot("a")
    assert first is again
    assert keyed.slot("b") is not first
    load = Loader()
    assert await first.get(load) == 1
    assert keyed.slot("a").fresh() == 1
    assert keyed.slot("b").fresh() is None


def test_a_keyed_cache_holds_at_most_cap_keys_dropping_the_least_recently_used() -> None:
    keyed: Keyed[int, int] = Keyed(60, cap=256, now=Clock())
    slots = {key: keyed.slot(key) for key in range(256)}
    keyed.slot(0)  # used again: now the most recent
    keyed.slot(256)  # one key too many: the least recently used (1) leaves
    assert len(keyed) == 256
    assert keyed.slot(0) is slots[0]
    assert keyed.slot(2) is slots[2]
    assert keyed.slot(1) is not slots[1]  # made again
    assert len(keyed) == 256


def test_a_dropped_key_is_forgotten_and_the_arguments_are_checked() -> None:
    keyed: Keyed[str, int] = Keyed(60, cap=2, now=Clock())
    slot = keyed.slot("a")
    keyed.drop("a")
    keyed.drop("never")
    assert len(keyed) == 0
    assert keyed.slot("a") is not slot
    with pytest.raises(ValueError, match="cap"):
        Keyed[str, int](60, cap=0)
    with pytest.raises(ValueError, match="positive"):
        Keyed[str, int](0, cap=1)
