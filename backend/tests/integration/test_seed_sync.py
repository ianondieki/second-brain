"""X1-3 follow-up: the seed keeps reference data in sync with its files without touching rows it does not own.

Each test runs inside a transaction that is rolled back, so the shared test database keeps the real reference data.
"""

from __future__ import annotations

import copy
import hashlib
import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from bridge.config import get_settings
from bridge.ids import uuid7
from bridge.seed.legal import load_legal_templates, seed_legal_templates, template_body
from bridge.seed.reference import load_reference, seed_all, seed_holidays, seed_plans
from tests.hermetic import python_module

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


def _with_placeholders(data: dict[str, Any], kind: str, placeholders: list[str]) -> dict[str, Any]:
    changed = copy.deepcopy(data)
    for row in changed["legal_templates"]:
        if row["kind"] == kind:
            row["placeholders"] = placeholders
    return changed


async def test_an_unaccepted_template_follows_its_body_and_an_accepted_one_is_frozen(conn: AsyncConnection) -> None:
    """Editing a version nobody has accepted updates its hash (and its NDA template's, ON UPDATE CASCADE); once an
    organisation has accepted it, the (template id, sha256) foreign key makes the seed fail instead."""
    data = load_legal_templates()
    edited = _with_placeholders(data, "evaluation_nda", ["evaluation-nda-v1", "evaluation-nda-v1-annex"])
    await seed_legal_templates(conn, edited)
    row = (
        await conn.execute(
            text(
                "SELECT l.body, l.sha256 AS legal_sha, n.sha256 AS nda_sha FROM legal_templates l"
                " JOIN nda_templates n ON n.legal_template_id = l.id"
                " WHERE l.kind = 'evaluation_nda' AND l.version = 'v1'"
            )
        )
    ).one()
    assert row.body == template_body(str(data["header"]), ["evaluation-nda-v1", "evaluation-nda-v1-annex"])
    assert row.legal_sha == row.nda_sha == hashlib.sha256(row.body.encode("utf-8")).digest()

    user_id, org_id = uuid7(), uuid7()
    await conn.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'Signatory')"),
        {"id": user_id, "email": f"signatory-{user_id.hex}@example.test"},
    )
    await conn.execute(
        text(
            "INSERT INTO organizations (id, kind, legal_name, slug, source) VALUES (:id, 'company', 'Acme', :s, 'seed')"
        ),
        {"id": org_id, "s": f"acme-{org_id.hex}"},
    )
    await conn.execute(
        text(
            "INSERT INTO legal_acceptances (id, org_id, user_id, legal_template_id, template_sha256)"
            " SELECT :id, :org, :user, id, sha256 FROM legal_templates WHERE kind = 'master_enterprise_terms'"
            " AND version = 'v1'"
        ),
        {"id": uuid7(), "org": org_id, "user": user_id},
    )
    savepoint = await conn.begin_nested()
    with pytest.raises(IntegrityError, match="fk_legal_acceptances_template"):
        await seed_legal_templates(
            conn, _with_placeholders(data, "master_enterprise_terms", ["edited-after-acceptance"])
        )
    await savepoint.rollback()
    await seed_legal_templates(conn, data)  # the accepted body itself still seeds cleanly (idempotent)


def test_the_seed_command_runs_twice_with_the_same_counts(database_url: URL) -> None:
    env = {**os.environ, "DATABASE_OWNER_URL": database_url.render_as_string(hide_password=False)}
    runs = [
        subprocess.run(python_module("bridge.seed"), cwd=BACKEND, env=env, capture_output=True, text=True, check=False)
        for _ in range(2)
    ]
    assert [r.returncode for r in runs] == [0, 0], runs[0].stderr + runs[1].stderr
    assert runs[0].stdout == runs[1].stdout
    assert "seed: regions = 48 rows" in runs[0].stdout
    assert "seed: legal_templates = " in runs[0].stdout
    assert "seed: nda_templates = " in runs[0].stdout
