"""REQ-PROP-04: the plain-Python MinHash LSH (D-36: no dependency) and the band thresholds of policy.yaml."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bridge.models.enums import OriginalityBand
from bridge.proposals import originality as o
from bridge.proposals.originality_policy import load_originality_policy

POLICY = load_originality_policy()
TEXT = "Milk spoils before it reaches a cooler in rural Kenya"


def numbered(prefix: str, count: int) -> frozenset[str]:
    return frozenset(f"{prefix} shingle {i}" for i in range(count))


def test_identical_text_is_one() -> None:
    a = o.signature(o.shingles(TEXT))
    assert len(a) == o.NUM_HASHES
    assert o.estimate(a, o.signature(o.shingles(TEXT.upper()))) == 1.0
    assert o.jaccard(o.shingles(TEXT), o.shingles(f"  {TEXT.lower()} ")) == 1.0


@pytest.mark.parametrize(("shared", "own"), [(100, 100), (300, 50), (400, 0), (20, 200)])
def test_the_estimate_is_close_to_the_exact_jaccard(shared: int, own: int) -> None:
    """128 hashes: the standard error is at most 0.045; the tolerance is about three of them."""
    common = numbered("common", shared)
    a, b = common | numbered("a", own), common | numbered("b", own)
    exact = o.jaccard(a, b)
    assert o.estimate(o.signature(a), o.signature(b)) == pytest.approx(exact, abs=0.13)


def test_signatures_and_buckets_are_fixed_across_runs() -> None:
    """Fixed salts: the same text gives the same buckets on every run and machine (stored rows stay valid)."""
    sig = o.signature(o.shingles(TEXT))
    assert sig[0] == 1672783989001887538
    bands = o.lsh_bands(sig)
    assert len(bands) == o.BANDS
    assert bands[0] == (0, -5782400983966835576)
    assert all(-(2**63) <= bucket < 2**63 for _, bucket in bands)


def test_identical_teasers_share_every_bucket_and_distinct_ones_none() -> None:
    a = o.lsh_bands(o.signature(o.shingles(TEXT)))
    other = "Fishers in Kisumu sell their catch late because the market opens after the boats return"
    assert a == o.lsh_bands(o.signature(o.shingles(TEXT)))
    assert not set(a) & set(o.lsh_bands(o.signature(o.shingles(other))))


def test_shingles_are_five_words_and_a_short_text_is_one() -> None:
    assert o.shingles("one two three four five six") == {"one two three four five", "two three four five six"}
    assert o.shingles("Cold chain") == {"cold chain"}
    assert o.shingles("  ") == frozenset()
    assert o.signature(()) == ()
    assert o.lsh_bands(()) == []


def test_submission_text_reads_the_four_tier1_fields_only() -> None:
    fields = {
        "summary": "<b>Alerts</b> when a cooler warms.",
        "title": "Cold chain",
        "approach": "TIER2 LoRa relays",
        "pricing": "KES 25,000",
        "impact_claims": None,
    }
    assert o.submission_text(fields) == "Cold chain\nAlerts when a cooler warms."


@pytest.mark.parametrize(
    ("jaccard", "cosine", "band"),
    [
        (0.79, None, OriginalityBand.NONE),
        (0.80, None, OriginalityBand.HIGH_OVERLAP),
        (0.0, 0.87, OriginalityBand.SOME_OVERLAP),
        (0.0, 0.88, OriginalityBand.HIGH_OVERLAP),
        (0.0, 0.74, OriginalityBand.NONE),
        (0.0, 0.75, OriginalityBand.SOME_OVERLAP),
        (0.79, 0.87, OriginalityBand.SOME_OVERLAP),
        (0.80, 0.10, OriginalityBand.HIGH_OVERLAP),
    ],
)
def test_the_bands_at_the_thresholds(jaccard: float, cosine: float | None, band: OriginalityBand) -> None:
    assert o.band_for(jaccard, cosine, POLICY) is band


@pytest.mark.parametrize(
    ("now", "start"),
    [
        (datetime(2026, 10, 2, 20, 59, tzinfo=UTC), datetime(2026, 10, 1, 21, 0, tzinfo=UTC)),  # 23:59 in Nairobi
        (datetime(2026, 10, 2, 21, 0, tzinfo=UTC), datetime(2026, 10, 2, 21, 0, tzinfo=UTC)),  # 00:00 the next day
    ],
)
def test_the_daily_limit_counts_from_nairobi_midnight(now: datetime, start: datetime) -> None:
    assert o.nairobi_day_start(now) == start
