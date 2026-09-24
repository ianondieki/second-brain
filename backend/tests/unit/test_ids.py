"""UUIDv7 ids (docs/spec/08)."""

from __future__ import annotations

import time

from bridge.ids import uuid7


def test_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_timestamp_is_now() -> None:
    ms = uuid7().int >> 80
    assert abs(ms - time.time_ns() // 1_000_000) < 5_000


def test_ids_sort_in_creation_order() -> None:
    ids = [uuid7() for _ in range(5_000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
