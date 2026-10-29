"""REQ-AUD-01: the hourly anchor takes pending chain heads oldest first (by the head's time when the heads function
provides it), then by chain id, so a run capped at MAX_ANCHORS_PER_RUN is deterministic and the heads that have waited
longest are timestamped first."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bridge.provenance.transparency import ChainHead, anchor_order

T0 = datetime(2026, 9, 28, 6, 0, tzinfo=UTC)


def head(chain_id: str, occurred_at: datetime | None) -> ChainHead:
    return ChainHead(chain_id, 1, bytes(32), occurred_at)


def test_the_oldest_head_comes_first_and_ties_go_by_chain_id() -> None:
    heads = [
        head("user:b", T0 + timedelta(minutes=5)),
        head("org:z", T0),
        head("global", T0 + timedelta(minutes=5)),
        head("org:y", T0 + timedelta(minutes=1)),
    ]
    assert [h.chain_id for h in anchor_order(heads)] == ["org:z", "org:y", "global", "user:b"]
    assert anchor_order(list(reversed(heads))) == anchor_order(heads)


def test_without_head_times_the_order_is_by_chain_id() -> None:
    heads = [head("user:a", None), head("global", None), head("org:b", None), head("org:a", None)]
    assert [h.chain_id for h in anchor_order(heads)] == ["global", "org:a", "org:b", "user:a"]


def test_a_head_of_unknown_age_counts_as_the_oldest() -> None:
    """It cannot be shown to be young, so it is not the one left for the next run."""
    heads = [head("org:a", T0), head("user:z", None)]
    assert [h.chain_id for h in anchor_order(heads)] == ["user:z", "org:a"]
