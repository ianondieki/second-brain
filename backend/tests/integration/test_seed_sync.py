"""X1-3 follow-up: the seed keeps reference data in sync with its files without touching rows it does not own.

Each test runs inside a transaction that is rolled back, so the shared test database keeps the real reference data.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.config import get_settings
from bridge.seed.reference import load_reference, seed_all, seed_holidays, seed_plans

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
async def conn(owner_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with owner_engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await seed_all(connection, get_settings())
            yield connection
        finally:
            await transaction.rollback()


async def _holidays(conn: AsyncConnection) -> set[tuple[str, str]]:
    rows = await conn.execute(text("SELECT observed_on::text, name FROM holidays WHERE country = 'KE'"))
    return {(day, name) for day, name in rows.all()}


async def test_corrected_holiday_replaces_the_old_row_and_keeps_admin_rows(conn: AsyncConnection) -> None:
    rows = copy.deepcopy(load_reference()["holidays"])
    first = rows[0]
    old = (str(first.get("observed") or first["date"]), str(first["name"]))
    await conn.execute(
        text(
            "INSERT INTO holidays (id, country, holiday_on, observed_on, name, provisional, source_url) VALUES "
            "(gen_random_uuid(), 'KE', '2026-11-02', '2026-11-02', 'Admin day', false, NULL), "
            "(gen_random_uuid(), 'KE', '2026-11-03', '2026-11-03', 'Cited elsewhere', false, 'https://example.com/g')"
        )
    )
    first["name"] = f"{first['name']} (corrected)"

    await seed_holidays(conn, rows)

    holidays = await _holidays(conn)
    assert old not in holidays
    assert (old[0], first["name"]) in holidays
    assert ("2026-11-02", "Admin day") in holidays
    assert ("2026-11-03", "Cited elsewhere") in holidays


async def test_plans_missing_from_the_file_are_retired_and_the_default_can_move(
    conn: AsyncConnection, tmp_path: Path
) -> None:
    catalogue: dict[str, Any] = yaml.safe_load(get_settings().plans_file.read_text(encoding="utf-8"))
    catalogue["plans"] = [p for p in catalogue["plans"] if p["code"] != "dev_student"]
    for plan in catalogue["plans"]:
        if plan["side"] == "developer":
            plan["default"] = plan["code"] == "dev_pro_monthly"
    changed = tmp_path / "plans.yaml"
    changed.write_text(yaml.safe_dump(catalogue), encoding="utf-8")

    await seed_plans(conn, get_settings().model_copy(update={"plans_file": changed}))

    rows = await conn.execute(text("SELECT code, active, is_default FROM plans WHERE side = 'developer'"))
    state = {code: (active, default) for code, active, default in rows.all()}
    assert state["dev_student"] == (False, False)  # retired; the row stays for existing subscriptions
    assert state["dev_pro_monthly"] == (True, True)
    assert state["dev_free"] == (True, False)


def test_the_seed_command_runs_twice_with_the_same_counts(database_url: URL) -> None:
    env = {**os.environ, "DATABASE_OWNER_URL": database_url.render_as_string(hide_password=False)}
    runs = [
        subprocess.run(
            [sys.executable, "-m", "bridge.seed"], cwd=BACKEND, env=env, capture_output=True, text=True, check=False
        )
        for _ in range(2)
    ]
    assert [r.returncode for r in runs] == [0, 0], runs[0].stderr + runs[1].stderr
    assert runs[0].stdout == runs[1].stdout
    assert "seed: regions = 48 rows" in runs[0].stdout
