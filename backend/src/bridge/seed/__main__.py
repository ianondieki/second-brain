"""Idempotent reference-data seed: ``python -m bridge.seed`` (docs/spec/08 Migrations; X1-3).

Runs as the owner role (``DATABASE_OWNER_URL`` from the environment or ``backend/.env``) and upserts regions (KE + 47
counties), niches (two-level ISIC taxonomy), holidays (2026-2027 as observed), plans (``config/plans.yaml``) and the
placeholder legal and NDA templates (``seed/legal_templates.yaml``). With ``APP_ENV`` dev or test it then loads the
provisional directory (``seed/ke_provisional.yaml``, E0 organisations only; REQ-DIR-02); in staging and production it
skips the directory and says so (staging keeps its fixture organisations; gate G6 approves the production list).
Running it twice leaves the same rows. Everything runs in one transaction.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from bridge.config import Settings, get_settings
from bridge.seed.directory import directory_loadable, seed_directory
from bridge.seed.reference import SEED_TABLES, seed_all


async def run(url: str, settings: Settings) -> tuple[dict[str, int], dict[str, int] | None]:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            counts = await seed_all(connection, settings)
            directory = await seed_directory(connection, settings) if directory_loadable(settings.app_env) else None
            return counts, directory
    finally:
        await engine.dispose()


def main() -> int:
    settings = get_settings()
    owner_url = settings.database_owner_url
    if owner_url is None:
        print("DATABASE_OWNER_URL is not set: the seed runs as the owner role (bridge_owner).", file=sys.stderr)
        return 2
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    counts, directory = asyncio.run(run(owner_url.get_secret_value(), settings), loop_factory=loop_factory)
    for table in SEED_TABLES:
        print(f"seed: {table} = {counts[table]} rows")
    if directory is None:
        print(
            f"seed: provisional directory skipped (APP_ENV={settings.app_env}; it loads only in dev and test,"
            " and gate G6 approves the production list)"
        )
    else:
        for table, count in directory.items():
            print(f"seed: {table} (provisional directory) = {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
