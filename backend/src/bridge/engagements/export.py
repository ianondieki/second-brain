"""The organisation's engagements as a spreadsheet (REQ-ENG-17; docs/platform/tasks/P28.md track D; docs/spec/05
``csv_export``).

``GET /api/orgs/{org_id}/engagements.csv`` (any active member; 404 for anyone else): the organisation's plan must have
``csv_export`` (403 ``entitlement_required`` naming the plan that has it: ``bridge.billing.entitlements``). One row per
engagement of the organisation (its own, read under the member's Row-Level Security; at most ``EXPORT_CAP``, oldest
first), exactly as the organisation's Engagements list shows it (``history.summaries`` and the team's facts, the same
code): the columns ``COLUMNS``, the stage by its label, the dates as Nairobi dates (ISO 8601), the developer as the list
names them at that stage (their handle until the engagement reveals them, never more), the assignee as the team sees
them, and the procurement route by its label (empty when none).

The file is UTF-8 with a byte-order mark (spreadsheet apps then read it as UTF-8), one header row and CRLF line ends
(RFC 4180), sent as an attachment named ``engagements-YYYY-MM-DD.csv`` (the Nairobi date) with ``Cache-Control:
no-store``. Formula injection (OWASP "CSV Injection"): a cell whose first character, or first after leading spaces,
is ``=``, ``+``, ``-``, ``@`` (or their full-width forms), a tab, a carriage return or a line feed is prefixed with
``'``, so a spreadsheet shows it as text and runs nothing. Each export is audited (``org.engagements_exported``: the
row count only).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any, Final

from fastapi import APIRouter, Response
from sqlalchemy import select

from bridge.audit.service import record as audit
from bridge.auth.deps import Db, SettingsDep
from bridge.billing import entitlements
from bridge.engagements import history, team
from bridge.engagements.calendar import local_date
from bridge.engagements.models import Engagement
from bridge.engagements.schemas import OrgEngagementSummary
from bridge.engagements.service import app_now
from bridge.errors import json_errors
from bridge.models.enums import ProcurementRoute
from bridge.tenancy.deps import OrgMember

router = APIRouter(tags=["engagements"])
CSV_EXPORT: Final = "csv_export"  # the plan's entitlement (plans.yaml)
EXPORT_CAP: Final = 10_000  # rows per file
MEDIA_TYPE: Final = "text/csv; charset=utf-8"
BOM: Final = "\ufeff"
COLUMNS: Final = (
    "reference",
    "title",
    "stage",
    "stage_entered_on",
    "due_on",
    "other_party",
    "assignee",
    "procurement_route",
)
# Characters a spreadsheet may read as the start of a formula, or that break a cell's first line.
UNSAFE_FIRST: Final = frozenset("=+-@\t\r\n＝＋－＠")  # noqa: RUF001 (the full-width forms, on purpose)
# [[COPY-REVIEW]] the procurement routes as the export names them (docs/spec/06 6.9 stage 3b).
ROUTE_LABELS: Final[dict[ProcurementRoute, str]] = {
    ProcurementRoute.DIRECT: "Direct procurement",
    ProcurementRoute.RFQ_TENDER: "Request for quotation or tender",
    ProcurementRoute.PPP_PIP: "Privately-initiated PPP proposal",
    ProcurementRoute.INNOVATION_CHALLENGE: "Innovation challenge or grant",
    ProcurementRoute.PILOT_MOU: "Pilot under an MOU",
}
CSV_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    200: {"content": {"text/csv": {}}, "description": "One row per engagement (UTF-8 with a byte-order mark, CRLF)"},
    **json_errors(401, 403, 404),
}


def neutralise(cell: str) -> str:
    """``cell`` prefixed with ``'`` when a spreadsheet could read it as a formula (see the module docstring)."""
    if cell[:1] in UNSAFE_FIRST or cell.lstrip(" ")[:1] in UNSAFE_FIRST:
        return "'" + cell
    return cell


def render(rows: Iterable[Sequence[str]]) -> bytes:
    """The CSV file: the byte-order mark, the header row, then ``rows`` (each cell neutralised), CRLF line ends."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(COLUMNS)
    for row in rows:
        writer.writerow([neutralise(cell) for cell in row])
    return (BOM + buffer.getvalue()).encode("utf-8")


def _day(value: date | None) -> str:
    return "" if value is None else value.isoformat()


def row_of(item: OrgEngagementSummary, route: ProcurementRoute | None) -> list[str]:
    """One engagement's cells, as the organisation's list shows it."""
    assignee = item.team.assignee if item.team is not None else None
    return [
        str(item.id),
        item.proposal_title,
        item.stage_label,
        _day(local_date(item.stage_entered_at)),
        _day(item.due.due_on if item.due is not None else None),
        item.developer_name,
        assignee.display_name if assignee is not None else "",
        ROUTE_LABELS.get(route, route.value) if route is not None else "",
    ]


def filename(today: date) -> str:
    return f"engagements-{today.isoformat()}.csv"


@router.get("/api/orgs/{org_id}/engagements.csv", response_class=Response, responses=CSV_RESPONSES)
async def export_engagements(org: OrgMember, db: Db, settings: SettingsDep) -> Response:
    """Download the organisation's engagements as CSV (the plan's ``csv_export``): one row per engagement, as the
    Engagements list shows it."""
    plan = await entitlements.for_subject(db, settings, org_id=org.org_id)
    entitlements.require_entitlement(settings, plan, CSV_EXPORT)
    found = list(
        (
            await db.scalars(
                select(Engagement)
                .where(Engagement.org_id == org.org_id)
                .order_by(Engagement.created_at, Engagement.id)
                .limit(EXPORT_CAP + 1)
            )
        ).all()
    )
    truncated = len(found) > EXPORT_CAP
    found = found[:EXPORT_CAP]
    summaries = await history.summaries(db, found, deals_enabled=settings.feature_deals_enabled, developer_caller=False)
    items = await team.with_team(db, org.org_id, org.live.user.id, summaries)
    routes = {engagement.id: engagement.procurement_route for engagement in found}
    body = render(row_of(item, routes.get(item.id)) for item in items)
    today = local_date(await app_now(db))
    await audit(
        db,
        "org.engagements_exported",
        actor_user_id=org.live.user.id,
        org_id=org.org_id,
        subject_type="organization",
        subject_id=org.org_id,
        payload={"format": "csv", "rows": len(items), "truncated": truncated},
    )
    await db.commit()
    return Response(
        content=body,
        media_type=MEDIA_TYPE,
        headers={
            "Content-Disposition": f'attachment; filename="{filename(today)}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
