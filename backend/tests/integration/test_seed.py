"""X1-3: ``python -m bridge.seed`` is idempotent (run twice, same row counts); reference data matches the spec."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.config import get_settings
from bridge.seed.reference import seed_all


async def test_seed_twice_gives_the_same_counts(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        first = await seed_all(conn, get_settings())
    async with owner_engine.begin() as conn:
        second = await seed_all(conn, get_settings())
    assert first == second
    async with owner_engine.connect() as conn:
        counties = (await conn.execute(text("SELECT count(*) FROM regions WHERE kind = 'county'"))).scalar_one()
        kenya = (await conn.execute(text("SELECT count(*) FROM regions WHERE code = 'KE'"))).scalar_one()
        plans = (
            await conn.execute(text("SELECT count(*) FROM plans WHERE code LIKE 'dev_%' OR code LIKE 'org_%'"))
        ).scalar_one()
        orgs = (await conn.execute(text("SELECT count(*) FROM organizations WHERE source = 'seed'"))).scalar_one()
    assert (counties, kenya) == (47, 1)
    assert plans == 9
    assert orgs == 0  # the directory seed arrives in Phase 2 (G6); this seed never creates organisations


async def test_holidays_include_gazetted_2026_dates(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await seed_all(conn, get_settings())
        rows = (await conn.execute(text("SELECT observed_on::text FROM holidays WHERE country = 'KE'"))).scalars().all()
    for day in ("2026-06-01", "2026-10-20", "2026-12-12", "2026-12-25"):
        assert day in rows
