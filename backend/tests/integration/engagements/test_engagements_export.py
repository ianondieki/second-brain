"""REQ-ENG-17 (P28 track D, AT-D-2): the organisation's engagements as CSV.

- Without the plan's ``csv_export`` (the free plan): the paywall's 402 ``plan_limit``, its upgrade naming Growth (the
  first plan that has it); nothing is audited.
- With it (Growth): any member downloads a UTF-8 file with a byte-order mark, one header row and CRLF line ends, as an
  attachment named by the Nairobi date, ``no-store``: one row per engagement of this organisation only (another
  organisation's, read under Row-Level Security, never appears), each as the organisation's list shows it (the stage's
  label, the Nairobi dates, the developer's handle while unrevealed, the assignee); a cell a spreadsheet would read as
  a formula (here an assignee's display name) is neutralised with ``'``. Audited as an export (the row count only).
- A member of another organisation gets 404.
"""

from __future__ import annotations

import csv
import io
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from bridge.engagements import export
from bridge.engagements import state_machine as sm
from bridge.engagements.export import COLUMNS
from bridge.models.enums import EngagementState
from tests.integration.engagements.api_world import build, clients, db_today, deals_on, open_engagement
from tests.integration.matching.scout_world import ScoutWorld, publish, subscribe
from tests.integration.matching.scout_world import build as scout_build
from tests.integration.tenancy.team_helpers import audit_actions, code
from tests.integration.test_migration_0015 import decide_and_move, route_scene

SETTINGS = deals_on()
FORMULA = '=HYPERLINK("https://evil.test","Click")'


def parse(response: httpx.Response) -> list[list[str]]:
    assert response.content.startswith(b"\xef\xbb\xbf")
    body = response.content.decode("utf-8").removeprefix("\ufeff")
    assert body.count("\r\n") == body.count("\n")  # every line ends CRLF
    return list(csv.reader(io.StringIO(body, newline="")))


async def test_the_export_needs_csv_export_and_holds_the_organisation_s_rows_only(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    other = await build(owner_engine)
    mine = await open_engagement(app_engine, world)
    theirs = await open_engagement(app_engine, other)
    async with owner_engine.begin() as conn:  # a display name a person chose, shaped like a formula
        named = {"n": FORMULA, "u": world.reviewer}
        await conn.execute(text("UPDATE users SET display_name = :n WHERE id = :u"), named)
    path = f"/api/orgs/{world.org}/engagements.csv"
    async with clients(app_engine, SETTINGS, world.owner, world.viewer, other.owner) as (owner, viewer, outsider):
        refused = await viewer.get(path)
        assert code(refused) == (402, "plan_limit")
        detail = refused.json()["detail"]
        assert (detail["plan"], detail["limit_key"]) == ("org_claimed", "csv_export")
        assert detail["upgrade"] == {"plan": "org_growth", "url": "/billing/upgrade?plan=org_growth"}
        assert await audit_actions(owner_engine, world.org, "org.engagements_exported") == []

        await subscribe(owner_engine, world.org, "org_growth")
        await subscribe(owner_engine, other.org, "org_growth")
        assigned = await owner.put(
            f"/api/orgs/{world.org}/engagements/{mine}/assignee", json={"user_id": str(world.reviewer)}
        )
        assert assigned.status_code == 200, assigned.text
        exported = await viewer.get(path)  # any member, the viewer included
        assert exported.status_code == 200, exported.text
        today = await db_today(owner_engine)
        assert exported.headers["content-type"] == "text/csv; charset=utf-8"
        assert exported.headers["content-disposition"] == f'attachment; filename="engagements-{today.isoformat()}.csv"'
        assert exported.headers["cache-control"] == "no-store"
        header, *found = parse(exported)
        assert header == list(COLUMNS)
        [listed] = (await viewer.get(f"/api/orgs/{world.org}/engagements")).json()["items"]
        assert found == [
            [
                str(mine),
                listed["proposal_title"],
                listed["stage_label"],
                today.isoformat(),
                listed["due"]["due_on"],
                listed["developer_name"],
                "'" + FORMULA,
                "",
            ]
        ]
        assert listed["developer_named"] is False  # the handle, as the list shows it
        assert str(theirs) not in exported.text
        assert code(await outsider.get(path)) == (404, "not_found")
        theirs_file = parse(await outsider.get(f"/api/orgs/{other.org}/engagements.csv"))
        assert [row[0] for row in theirs_file[1:]] == [str(theirs)]
    [event] = await audit_actions(owner_engine, world.org, "org.engagements_exported")
    assert (event.actor_user_id, event.subject_id) == (world.viewer, world.org)
    assert event.payload == {"format": "csv", "rows": 1, "truncated": False}


async def test_an_organisation_without_engagements_gets_the_header_row(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    world = await build(owner_engine)
    await subscribe(owner_engine, world.org, "org_enterprise")
    async with clients(app_engine, SETTINGS, world.finance) as (finance,):
        exported = await finance.get(f"/api/orgs/{world.org}/engagements.csv")
    assert exported.status_code == 200, exported.text
    assert parse(exported) == [list(COLUMNS)]


async def interested(owner_engine: AsyncEngine, app_engine: AsyncEngine, count: int) -> tuple[ScoutWorld, list[str]]:
    """An organisation on Growth with ``count`` ORG_INTEREST engagements its signatory opened, one after another."""
    world = await scout_build(owner_engine)
    await subscribe(owner_engine, world.org.id, "org_growth")
    today = await db_today(owner_engine)
    ids = []
    async with clients(app_engine, SETTINGS, world.org.signatory) as (signatory,):
        for n in range(count):
            proposal = (await publish(owner_engine, world, f"p{n}"))[0]
            body = {
                "proposal_id": str(proposal),
                "origin": "org_browse",
                "match_id": None,
                "contact_user_id": str(world.org.owner),
                "channel": "video_call",
                "contact_by": str(today + timedelta(days=1)),
            }
            created = await signatory.post(f"/api/orgs/{world.org.id}/interest", json=body)
            assert created.status_code == 201, created.text
            ids.append(created.json()["id"])
    return world, ids


async def test_rows_are_newest_first_and_a_cut_file_says_so(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, ids = await interested(owner_engine, app_engine, 3)
    path = f"/api/orgs/{world.org.id}/engagements.csv"
    async with clients(app_engine, SETTINGS, world.org.finance) as (finance,):
        listed = [item["id"] for item in (await finance.get(f"/api/orgs/{world.org.id}/engagements")).json()["items"]]
        assert listed == ids[::-1]  # the list: newest first
        whole = await finance.get(path)
        assert [row[0] for row in parse(whole)[1:]] == listed
        assert export.TRUNCATED_HEADER.lower() not in whole.headers
        monkeypatch.setattr(export, "EXPORT_CAP", 2)
        cut = await finance.get(path)
        assert [row[0] for row in parse(cut)[1:]] == listed[:2]
        assert cut.headers[export.TRUNCATED_HEADER] == "true"
    [*_, last] = await audit_actions(owner_engine, world.org.id, "org.engagements_exported")
    assert last.payload == {"format": "csv", "rows": 2, "truncated": True}


async def test_a_member_exports_a_bounded_number_of_times_an_hour(
    owner_engine: AsyncEngine, app_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(export, "EXPORTS_PER_HOUR", 2)
    world = await build(owner_engine)
    await subscribe(owner_engine, world.org, "org_growth")
    path = f"/api/orgs/{world.org}/engagements.csv"
    async with clients(app_engine, SETTINGS, world.viewer, world.finance) as (viewer, finance):
        for _ in range(2):
            assert (await viewer.get(path)).status_code == 200
        refused = await viewer.get(path)
        assert code(refused) == (429, "rate_limited")
        assert int(refused.headers["retry-after"]) > 0
        assert (await finance.get(path)).status_code == 200  # per member
    assert len(await audit_actions(owner_engine, world.org, "org.engagements_exported")) == 3


async def test_a_decided_procurement_route_is_exported_by_its_label(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:  # a public entity's engagement through 3b, its route decided
        p, engagement = await route_scene(conn)
        await decide_and_move(conn, p, engagement, "rfq_tender")
    await subscribe(owner_engine, p.org, "org_growth")
    async with clients(app_engine, SETTINGS, p.finance) as (finance,):
        [header, row] = parse(await finance.get(f"/api/orgs/{p.org}/engagements.csv"))
    exported = dict(zip(header, row, strict=True))
    assert exported["reference"] == str(engagement)
    assert exported["procurement_route"] == "Request for quotation or tender"
    assert exported["stage"] == sm.STAGE_LABELS[EngagementState.INTEREST_CONFIRMED]
