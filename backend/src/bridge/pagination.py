"""The API's one pagination style (REQ-FND-01, P16-E1): a list pages with ``?limit=`` and ``?cursor=`` and answers
``next_cursor`` (pass it as ``?cursor=`` for the next page; null on the last page). The cursor is opaque (base64url
of a JSON array) and keys the list's order, so a row inserted meanwhile never shifts a page; a cursor this server did
not write answers 400 ``invalid_cursor``.

This module holds the cursor of lists ordered by a moment and an id (newest first, the moment possibly null and then
last); the directory, the pitch picker, Browse and the Inbox keep their own (their sort keys differ), with the same
parameters, field and refusal.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import Query

from bridge.errors import ApiError

MAX_CURSOR_CHARS: Final = 2000
Cursor = Annotated[
    str | None, Query(max_length=MAX_CURSOR_CHARS, description="The previous page's next_cursor; omit it for the first")
]


def invalid_cursor() -> ApiError:
    return ApiError(400, "invalid_cursor", "Start again from the first page.")


@dataclass(frozen=True, slots=True)
class MomentCursor:
    """The last row of a page: its moment (None sorts last) and its id."""

    at: datetime | None
    id: UUID


def encode(at: datetime | None, row_id: UUID) -> str:
    raw = json.dumps([None if at is None else at.isoformat(), str(row_id)])
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def decode(value: str | None) -> MomentCursor | None:
    """The cursor in ``value`` (None for the first page); ``invalid_cursor`` for anything ``encode`` did not write."""
    if value is None:
        return None
    try:
        at, row_id = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if not (at is None or isinstance(at, str)) or not isinstance(row_id, str):
            raise ValueError("malformed cursor")  # UUID() raises AttributeError, not ValueError, on a non-string
        moment = None if at is None else datetime.fromisoformat(at)
        if moment is not None and moment.tzinfo is None:
            raise ValueError("malformed cursor")
        return MomentCursor(moment, UUID(row_id))
    except (binascii.Error, UnicodeDecodeError, TypeError, ValueError) as exc:  # JSONDecodeError is a ValueError
        raise invalid_cursor() from exc
