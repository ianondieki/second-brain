"""Idempotent reference-data seed: ``python -m bridge.seed`` (docs/spec/08 Migrations; X1-3).

Runs as the owner role (``DATABASE_OWNER_URL`` from the environment or ``backend/.env``) and upserts regions (KE + 47
counties), niches (two-level ISIC taxonomy), holidays (2026-2027 as observed) and plans (``config/plans.yaml``).
Running it twice leaves the same rows. It creates no organisations; the directory seed (Phase 2, G6) will refuse to
set any organisation above ``unclaimed`` outside ``APP_ENV`` test/staging.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from bridge.config import get_settings
from bridge.seed.reference import SEED_TABLES, seed_all


async def run(url: str) -> dict[str, int]:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            return await seed_all(connection, get_settings())
    finally:
        await engine.dispose()


def main() -> int:
    owner_url = get_settings().database_owner_url
    if owner_url is None:
        print("DATABASE_OWNER_URL is not set: the seed runs as the owner role (bridge_owner).", file=sys.stderr)
        return 2
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    counts = asyncio.run(run(owner_url.get_secret_value()), loop_factory=loop_factory)
    for table in SEED_TABLES:
        print(f"seed: {table} = {counts[table]} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
