"""Browse repo and Inbox cursors (REQ-REPO-02, REQ-PROP-03): what the API writes reads back exactly, and anything else
a caller sends is a ValueError (the routes' 400 ``invalid_cursor``), never another exception (a 500)."""

from __future__ import annotations

import base64
import contextlib
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from bridge.proposals import inbox, search

# hypothesis takes naive bounds and attaches the time zone itself
MOMENTS = st.datetimes(
    min_value=datetime(2020, 1, 1),  # noqa: DTZ001
    max_value=datetime(2100, 1, 1),  # noqa: DTZ001
    timezones=st.just(UTC),
)
RANKS = st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False)
JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats() | st.text(max_size=40),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=5), inner, max_size=3),
    max_leaves=10,
)


@given(rank=RANKS, moment=MOMENTS, proposal_id=st.uuids())
def test_a_search_cursor_reads_back_exactly(rank: float, moment: datetime, proposal_id: UUID) -> None:
    cursor = search.Cursor(rank, moment, proposal_id)
    assert search.decode_cursor(search.encode_cursor(cursor)) == cursor


@given(moment=MOMENTS, tag_id=st.uuids())
def test_an_inbox_cursor_reads_back_exactly(moment: datetime, tag_id: UUID) -> None:
    cursor = inbox.Cursor(moment, tag_id)
    assert inbox.decode_cursor(inbox.encode_cursor(cursor)) == cursor


def _as_cursor(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


@given(st.one_of(st.text(max_size=80), JSON.map(_as_cursor)))
def test_anything_else_is_a_value_error(value: str) -> None:
    for decode in (search.decode_cursor, inbox.decode_cursor):
        with contextlib.suppress(ValueError):  # anything but ValueError fails the test
            decode(value)


@pytest.mark.parametrize(
    "value",
    [
        [float("inf"), "2026-09-29T10:00:00+00:00", "01920000-0000-7000-8000-000000000000"],
        [False, "2026-09-29T10:00:00+00:00", "01920000-0000-7000-8000-000000000000"],
        [0.5, "2026-09-29T10:00:00+00:00", "not-a-uuid"],
        [0.5, "yesterday", "01920000-0000-7000-8000-000000000000"],
        [0.5, "2026-09-29T10:00:00+00:00"],
    ],
)
def test_forged_search_cursors_are_refused(value: list[object]) -> None:
    with pytest.raises(ValueError, match="invalid cursor"):
        search.decode_cursor(_as_cursor(value))
