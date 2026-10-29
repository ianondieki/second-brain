"""UUIDv7 primary keys (docs/spec/08: "UUIDv7 PKs"), generated in the application.

Python 3.12 has no ``uuid.uuid7`` and Postgres 16 has no ``uuidv7()``, so ids are made here (RFC 9562 §5.7):
48-bit Unix time in milliseconds, version 7, 74 random bits. Ids made in the same millisecond are ordered by a
monotonic counter held in the 12-bit ``rand_a`` field, so ids from one process sort in creation order.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """Return a new time-ordered UUID (version 7, RFC 9562 variant)."""
    global _last_ms, _counter
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms > _last_ms:
            _last_ms, _counter = ms, int.from_bytes(os.urandom(2), "big") & 0x3FF  # leave room to count up
        else:
            ms = _last_ms  # clock went back or same millisecond: keep order
            _counter += 1
            if _counter > 0xFFF:  # 4096 ids in one millisecond: borrow the next millisecond
                _last_ms += 1
                ms, _counter = _last_ms, 0
        rand_a = _counter
    rand_b = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | rand_a << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)
