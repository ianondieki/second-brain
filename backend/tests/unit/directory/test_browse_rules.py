"""REQ-DIR-01 rules in plain code: the responsiveness score shows only for E2 organisations with at least 10 eligible
tags, 60 days after E2 (docs/spec/06 6.2); the directory cursor round-trips and refuses anything else; niche labels
are two-level."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from bridge.directory.responsiveness import (
    MIN_ELIGIBLE_TAGS,
    MIN_TIME_SINCE_E2,
    FixtureResponsiveness,
    NoResponsivenessData,
    ResponsivenessStats,
    responsiveness_for,
    score_visible,
)
from bridge.directory.service import Cursor, decode_cursor, encode_cursor, niche_label
from bridge.models.enums import OrgVerification

NOW = datetime(2026, 9, 28, 9, 0, tzinfo=UTC)
STATS = ResponsivenessStats(eligible_tags=10, median_response_days=2.5, answered_share=0.755)


def visible(
    verification: OrgVerification = OrgVerification.E2,
    since: timedelta | None = MIN_TIME_SINCE_E2,
    stats: ResponsivenessStats | None = STATS,
) -> bool:
    return score_visible(
        verification=verification, e2_verified_at=None if since is None else NOW - since, stats=stats, now=NOW
    )


def test_the_thresholds_are_the_spec_values() -> None:
    assert MIN_ELIGIBLE_TAGS == 10
    assert timedelta(days=60) == MIN_TIME_SINCE_E2


def test_shown_for_e2_with_ten_eligible_tags_sixty_days_after_e2() -> None:
    assert visible()


@pytest.mark.parametrize(
    "verification", [OrgVerification.UNCLAIMED, OrgVerification.E1, OrgVerification.PENDING, OrgVerification.REJECTED]
)
def test_never_shown_below_e2(verification: OrgVerification) -> None:
    assert not visible(verification=verification)


def test_not_shown_before_sixty_days_or_without_an_e2_date() -> None:
    assert not visible(since=MIN_TIME_SINCE_E2 - timedelta(seconds=1))
    assert not visible(since=None)


def test_not_shown_with_nine_eligible_tags_or_no_data() -> None:
    assert not visible(stats=ResponsivenessStats(eligible_tags=9, median_response_days=1, answered_share=1))
    assert not visible(stats=None)


def test_the_score_text_follows_the_spec_copy() -> None:
    shown = responsiveness_for(
        verification=OrgVerification.E2, e2_verified_at=NOW - MIN_TIME_SINCE_E2, stats=STATS, now=NOW
    )
    assert shown is not None
    assert (shown.median_days, shown.answered_pct) == (3, 76)  # half-up rounding
    assert shown.text == "Responds in a median of 3 days · 76% answered"
    one_day = responsiveness_for(
        verification=OrgVerification.E2,
        e2_verified_at=NOW - MIN_TIME_SINCE_E2,
        stats=ResponsivenessStats(eligible_tags=40, median_response_days=1.2, answered_share=1),
        now=NOW,
    )
    assert one_day is not None
    assert one_day.text == "Responds in a median of 1 day · 100% answered"
    assert responsiveness_for(verification=OrgVerification.E1, e2_verified_at=None, stats=STATS, now=NOW) is None


@pytest.mark.parametrize(("tags", "days", "share"), [(-1, 1.0, 0.5), (10, -1.0, 0.5), (10, 1.0, 1.01)])
def test_stats_out_of_range_are_refused(tags: int, days: float, share: float) -> None:
    with pytest.raises(ValueError, match="out of range"):
        ResponsivenessStats(eligible_tags=tags, median_response_days=days, answered_share=share)


async def test_sources_return_only_what_they_hold() -> None:
    known, other = uuid4(), uuid4()
    assert await NoResponsivenessData().stats_for([known]) == {}
    assert await FixtureResponsiveness({known: STATS}).stats_for([known, other]) == {known: STATS}


def test_the_cursor_round_trips() -> None:
    cursor = Cursor(0, "ICT › Networks & Telecommunications", uuid4(), "Safaricom PLC", uuid4())
    encoded = encode_cursor(cursor)
    assert "=" not in encoded
    assert decode_cursor(encoded) == cursor


def _raw(value: object) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


@pytest.mark.parametrize(
    "value",
    [
        "not-a-cursor",
        "",
        "%%%",
        _raw({"rank": 0}),
        _raw([2, "x", str(uuid4()), "y", str(uuid4())]),
        _raw([0, 1, str(uuid4()), "y", str(uuid4())]),
        _raw([0, "x", "not-a-uuid", "y", str(uuid4())]),
        _raw([0, "x", str(uuid4()), None, str(uuid4())]),
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
    ],
)
def test_anything_else_is_not_a_cursor(value: str) -> None:
    with pytest.raises(ValueError, match="invalid cursor"):
        decode_cursor(value)


def test_niche_labels_are_two_level() -> None:
    assert niche_label("Networks & Telecommunications", "ICT") == "ICT › Networks & Telecommunications"
    assert niche_label("Social/NGO", None) == "Social/NGO"
