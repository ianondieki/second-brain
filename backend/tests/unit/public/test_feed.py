"""REQ-UX-03 (P24-B): what the public activity feed and the Explore summary are made of.

The rows as the database returns them become anonymised items (an opaque key, never a record id; a niche label; no
stage: stage events are deferred); ``seeded`` follows the demo seed's marks; Explore groups by county and top-level
niche with the newest three each, most first.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from bridge.public import feed
from bridge.public.schemas import ActivityItem

NOW = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)


def activity_row(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "row_id": uuid4(),
        "kind": "problem_posted",
        "at": NOW,
        "county": "Nairobi City",
        "niche_name": "Networks & Telecommunications",
        "parent_name": "ICT",
        "title": "Rural towers lose power at night",
        "example": False,
    }
    return SimpleNamespace(**(values | overrides))


def test_an_item_carries_only_public_fields_under_an_opaque_key() -> None:
    row = activity_row()
    [item] = feed.activity_items([row], demo=False)
    assert item.model_dump() == {
        "id": item.id,
        "kind": "problem_posted",
        "at": NOW,
        "county": "Nairobi City",
        "niche": "ICT › Networks & Telecommunications",
        "title": "Rural towers lose power at night",
        "stage": None,
        "seeded": False,
    }
    assert str(row.row_id) not in item.id
    assert row.row_id.hex not in item.id
    assert item.id == feed.event_id("problem_posted", row.row_id)  # stable between reads
    assert feed.event_id("version_registered", row.row_id) != item.id


def test_an_item_without_a_county_or_niche_says_so() -> None:
    [item] = feed.activity_items([activity_row(county=None, niche_name=None, parent_name=None)], demo=False)
    assert (item.county, item.niche) == (None, None)
    [top] = feed.activity_items([activity_row(parent_name=None, niche_name="Health")], demo=False)
    assert top.niche == "Health"


@pytest.mark.parametrize(
    ("demo", "examples", "expected"),
    [
        pytest.param(False, [False, False], [False, False], id="real"),
        pytest.param(False, [True, False], [True, False], id="one-seeded-example-card"),
        pytest.param(True, [False, False], [True, True], id="demo-deployment"),
    ],
)
def test_an_item_is_seeded_when_the_demo_seed_wrote_it(demo: bool, examples: list[bool], expected: list[bool]) -> None:
    rows = [activity_row(example=example) for example in examples]
    assert [item.seeded for item in feed.activity_items(rows, demo=demo)] == expected


def test_the_feed_is_seeded_only_when_every_item_is() -> None:
    seeded, real = (feed.activity_items([activity_row(example=flag)], demo=False)[0] for flag in (True, False))
    assert feed.activity_feed([seeded, seeded], NOW).seeded is True
    assert feed.activity_feed([seeded, real], NOW).seeded is False
    assert feed.activity_feed([], NOW).seeded is False
    assert feed.activity_feed([seeded], NOW).generated_at == NOW


def test_a_deployment_is_a_demo_only_where_the_demo_seed_may_run() -> None:
    assert [feed.demo_deployment(SimpleNamespace(app_env=env)) for env in ("dev", "test", "staging", "production")] == [  # type: ignore[arg-type]
        True,
        True,
        False,
        False,
    ]


def explore_row(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": uuid4(),
        "title": "A problem",
        "posted_at": NOW,
        "county_code": "KE-30",
        "county_name": "Nairobi City",
        "niche_name": "Microfinance & SACCOs",
        "parent_name": None,
        "top_id": UUID(int=1),
        "top_name": "Microfinance & SACCOs",
        "county_count": 1,
        "county_rank": 1,
        "niche_count": 1,
        "niche_rank": 1,
        "total": 1,
        "unmarked": 1,
    }
    return SimpleNamespace(**(values | overrides))


def test_explore_groups_by_county_and_top_level_niche_with_the_newest_three() -> None:
    ict, health = UUID(int=2), UUID(int=3)
    common = {"total": 6, "unmarked": 6}
    rows = [  # newest first, as the statement orders them
        explore_row(
            title="N1",
            county_count=4,
            county_rank=1,
            top_id=ict,
            top_name="ICT",
            niche_count=5,
            niche_rank=1,
            niche_name="Networks",
            parent_name="ICT",
            **common,
        ),
        explore_row(
            title="N2",
            county_count=4,
            county_rank=2,
            top_id=ict,
            top_name="ICT",
            niche_count=5,
            niche_rank=2,
            niche_name="Networks",
            parent_name="ICT",
            **common,
        ),
        explore_row(
            title="M1",
            county_code="KE-28",
            county_name="Mombasa",
            county_count=1,
            county_rank=1,
            top_id=ict,
            top_name="ICT",
            niche_count=5,
            niche_rank=3,
            **common,
        ),
        explore_row(
            title="N3",
            county_count=4,
            county_rank=3,
            top_id=health,
            top_name="Health",
            niche_count=1,
            niche_rank=1,
            niche_name="Health",
            **common,
        ),
        explore_row(
            title="X1",
            county_code=None,
            county_name=None,
            county_count=1,
            county_rank=1,
            top_id=None,
            top_name=None,
            niche_name=None,
            niche_count=1,
            niche_rank=1,
            **common,
        ),
    ]
    summary = feed.explore_summary(rows, demo=False)
    assert summary.totals.model_dump() == {"problems": 6, "counties": 2, "niches": 2}
    assert [(c.code, c.name, c.count, [t.title for t in c.newest]) for c in summary.counties] == [
        ("KE-30", "Nairobi City", 4, ["N1", "N2", "N3"]),
        ("KE-28", "Mombasa", 1, ["M1"]),
    ]
    assert [(n.id, n.name, n.count, [t.title for t in n.newest]) for n in summary.niches] == [
        (ict, "ICT", 5, ["N1", "N2", "M1"]),
        (health, "Health", 1, ["N3"]),
    ]
    assert summary.counties[0].newest[0].niche == "ICT › Networks"
    assert summary.seeded is False


def test_explore_breaks_ties_by_name_and_says_when_it_is_seeded() -> None:
    rows = [
        explore_row(
            county_code="KE-28", county_name="Mombasa", top_id=UUID(int=5), top_name="Zebra", total=2, unmarked=0
        ),
        explore_row(
            county_code="KE-22", county_name="Kiambu", top_id=UUID(int=4), top_name="Agriculture", total=2, unmarked=0
        ),
    ]
    summary = feed.explore_summary(rows, demo=False)
    assert [c.name for c in summary.counties] == ["Kiambu", "Mombasa"]
    assert [n.name for n in summary.niches] == ["Agriculture", "Zebra"]
    assert summary.seeded is True  # every problem is a seeded example card
    assert feed.explore_summary([explore_row(unmarked=1)], demo=True).seeded is True


def test_an_empty_platform_has_an_empty_unseeded_summary() -> None:
    summary = feed.explore_summary([], demo=True)
    assert summary.model_dump() == {
        "totals": {"problems": 0, "counties": 0, "niches": 0},
        "counties": [],
        "niches": [],
        "seeded": False,
    }


def test_items_validate_as_the_schema_says() -> None:
    item = feed.activity_items([activity_row()], demo=False)[0]
    assert ActivityItem.model_validate(item.model_dump()) == item


async def test_the_loaders_shape_what_the_public_reader_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    statements: list[str] = []

    async def read(factory: Any, statement: Any) -> list[Any]:
        statements.append(str(statement).split()[1])
        return [activity_row()] if factory == "activity" else []

    monkeypatch.setattr(feed, "read", read)
    got = await feed.activity("activity", generated_at=NOW, demo=False)  # type: ignore[arg-type]
    assert ([item.kind for item in got.items], got.generated_at) == (["problem_posted"], NOW)
    summary = await feed.explore("explore", demo=False)  # type: ignore[arg-type]
    assert summary.totals.problems == 0
    assert statements == ["feed.row_id,", "ranked.id,"]
