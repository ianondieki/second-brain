"""Idempotent reference-data seed: ``python -m bridge.seed`` (docs/spec/08 Migrations; X1-3).

Runs as the owner role (``DATABASE_OWNER_URL`` from the environment or ``backend/.env``) and upserts regions (KE + 47
counties), niches (two-level ISIC taxonomy), holidays (2026-2027 as observed), plans (``config/plans.yaml``) and the
placeholder legal and NDA templates (``seed/legal_templates.yaml``). With ``APP_ENV`` set explicitly to dev or test it
then loads the provisional directory (``seed/ke_provisional.yaml``, E0 organisations only; REQ-DIR-02); in staging and
production, or when ``APP_ENV`` is not set at all, it skips the directory and says why (staging keeps its fixture
organisations; gate G6 approves the production list).
Running it twice leaves the same rows. Everything runs in one transaction.

``python -m bridge.seed --demo`` then loads the demo dataset (``bridge.seed.demo``: demo developers, fixture
organisations, published proposals, tags) for ``make demo``, through the application as ``bridge_app``
(``DATABASE_URL``) where a path exists. Dev and test only: with ``--demo`` anywhere else nothing is written at all.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from bridge.config import Settings, get_settings
from bridge.seed.demo import DemoReport, demo_refusal, seed_demo
from bridge.seed.demo.data import DEMO_PASSWORD, all_accounts
from bridge.seed.directory import directory_loadable, directory_refusal, seed_directory
from bridge.seed.reference import SEED_TABLES, seed_all


async def run(url: str, settings: Settings) -> tuple[dict[str, int], dict[str, int] | None]:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            counts = await seed_all(connection, settings)
            directory = await seed_directory(connection, settings) if directory_loadable(settings) else None
            return counts, directory
    finally:
        await engine.dispose()


async def run_demo(owner_url: str, settings: Settings) -> DemoReport:
    owner = create_async_engine(owner_url)
    app = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True, hide_parameters=True)
    try:
        return await seed_demo(settings, owner_engine=owner, app_engine=app)
    finally:
        await app.dispose()
        await owner.dispose()


def print_demo(report: DemoReport) -> None:
    for what in report.created:
        print(f"demo: {what}")
    for note in report.notes:
        print(f"demo: note: {note}")
    if not report.created:
        print("demo: already seeded (nothing to add)")
    for key, cert_id in sorted(report.cert_ids.items()):
        print(f"demo: proposal {key} certificate {cert_id}")
    print(f"demo: every demo login below uses the password {DEMO_PASSWORD} (dev-only, public on purpose)")
    print("demo: second factor: python -m bridge.demo totp <address>  (make demo-totp from the repository)")
    for email, name, what in all_accounts():
        print(f"demo:   {email:30}  {name:16}  {what}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m bridge.seed", description="Seed reference data (idempotent).")
    parser.add_argument("--demo", action="store_true", help="also load the demo dataset (APP_ENV dev or test only)")
    args = parser.parse_args([] if argv is None else argv)  # None: no options (tests call main())
    settings = get_settings()
    owner_url = settings.database_owner_url
    if owner_url is None:
        print("DATABASE_OWNER_URL is not set: the seed runs as the owner role (bridge_owner).", file=sys.stderr)
        return 2
    if args.demo and (reason := demo_refusal(settings)) is not None:
        print(f"seed: --demo refused: {reason}", file=sys.stderr)
        return 2
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    counts, directory = asyncio.run(run(owner_url.get_secret_value(), settings), loop_factory=loop_factory)
    for table in SEED_TABLES:
        print(f"seed: {table} = {counts[table]} rows")
    if directory is None:
        print(f"seed: provisional directory skipped ({directory_refusal(settings)})")
    else:
        for table, count in directory.items():
            print(f"seed: {table} (provisional directory) = {count} rows")
    if args.demo:
        print_demo(asyncio.run(run_demo(owner_url.get_secret_value(), settings), loop_factory=loop_factory))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
