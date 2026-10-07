"""The public activity feed and the Explore summary as visitors see them (REQ-UX-03, REQ-DIR-01, REQ-REPO-02;
P24-B): rows of ``bridge.public.queries`` made into anonymised items and groups.

**Activity.** ``problem_posted`` (a problem published), ``brief_opened`` (a Brief's problem published: the Brief is
open to developers) and ``version_registered`` (a published proposal's registered version), newest first, 20 in all.
``stage_reached`` is in the contract but not listed yet (``bridge.public.queries``). An event's key is a digest of its
kind and record, never the record's id.

**Explore.** Counties with problems and top-level niches with problems (a child niche counts under its parent), most
first, then by name, each with its three newest; the totals count every readable problem.

**Seeded.** The demo seed runs only where ``APP_ENV`` is dev or test (``bridge.seed.demo.runtime.DEMO_ENVS``), so
there every row is the seed's (or a local developer's); elsewhere a row is seeded only when it carries the seed's own
mark: a research card whose every cited source is a saved demo excerpt (``excerpt_ref`` starting ``example:``, the
rule behind the cards' "Seeded example" label). ``users.demo_account`` is readable only by its own user, so it is not
used. A feed or a summary is seeded when it has rows and every one is.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bridge.config import Settings
from bridge.directory.service import niche_label
from bridge.public.queries import NEWEST, activity_statement, explore_statement, read
from bridge.public.schemas import (
    ActivityFeed,
    ActivityItem,
    Explore,
    ExploreCounty,
    ExploreNiche,
    ExploreTeaser,
    ExploreTotals,
)

DEMO_ENVS: Final = frozenset({"dev", "test"})  # where the demo seed may run (bridge.seed.demo.runtime)


def demo_deployment(settings: Settings) -> bool:
    return settings.app_env in DEMO_ENVS


def event_id(kind: str, row_id: UUID) -> str:
    """An opaque, stable key for an event (a digest: the feed names no record)."""
    return hashlib.sha256(f"{kind}:{row_id}".encode()).hexdigest()[:20]


def _label(name: str | None, parent_name: str | None) -> str | None:
    return None if name is None else niche_label(name, parent_name)


def activity_items(rows: Sequence[Any], *, demo: bool) -> list[ActivityItem]:
    return [
        ActivityItem(
            id=event_id(row.kind, row.row_id),
            kind=row.kind,
            at=row.at,
            county=row.county,
            niche=_label(row.niche_name, row.parent_name),
            title=row.title,
            stage=None,
            seeded=demo or bool(row.example),
        )
        for row in rows
    ]


def activity_feed(items: list[ActivityItem], generated_at: datetime) -> ActivityFeed:
    return ActivityFeed(
        generated_at=generated_at, items=items, seeded=bool(items) and all(item.seeded for item in items)
    )


def explore_summary(rows: Sequence[Any], *, demo: bool) -> Explore:
    """Group ``explore_statement``'s rows (newest first): counties and top-level niches with problems, most first."""
    counties: dict[str, ExploreCounty] = {}
    niches: dict[UUID, ExploreNiche] = {}
    for row in rows:
        teaser = ExploreTeaser(
            id=row.id, title=row.title, niche=_label(row.niche_name, row.parent_name), posted_at=row.posted_at
        )
        if row.county_code is not None and row.county_rank <= NEWEST:
            county = counties.setdefault(
                row.county_code,
                ExploreCounty(
                    code=row.county_code, name=row.county_name or row.county_code, count=row.county_count, newest=[]
                ),
            )
            county.newest.append(teaser)
        if row.top_id is not None and row.niche_rank <= NEWEST:
            niche = niches.setdefault(
                row.top_id, ExploreNiche(id=row.top_id, name=row.top_name, count=row.niche_count, newest=[])
            )
            niche.newest.append(teaser)
    total, unmarked = (int(rows[0].total), int(rows[0].unmarked)) if rows else (0, 0)
    return Explore(
        totals=ExploreTotals(problems=total, counties=len(counties), niches=len(niches)),
        counties=sorted(counties.values(), key=lambda c: (-c.count, c.name, c.code)),
        niches=sorted(niches.values(), key=lambda n: (-n.count, n.name, str(n.id))),
        seeded=total > 0 and (demo or unmarked == 0),
    )


async def activity(factory: async_sessionmaker[AsyncSession], *, generated_at: datetime, demo: bool) -> ActivityFeed:
    return activity_feed(activity_items(await read(factory, activity_statement()), demo=demo), generated_at)


async def explore(factory: async_sessionmaker[AsyncSession], *, demo: bool) -> Explore:
    return explore_summary(await read(factory, explore_statement()), demo=demo)
