"""REQ-ENG-17 (P28 track D, AT-D-2's file half): the engagements export's CSV.

UTF-8 with a byte-order mark, one header row, CRLF line ends, RFC 4180 quoting; a cell a spreadsheet could read as a
formula (OWASP "CSV Injection": ``= + - @``, their full-width forms, a tab, CR or LF first, or first after spaces) is
prefixed with ``'``; every procurement route has a label; the file is named by the Nairobi date.
"""

from __future__ import annotations

import csv
import io
from datetime import date

import pytest

from bridge.engagements.export import COLUMNS, ROUTE_LABELS, filename, neutralise, render
from bridge.models.enums import ProcurementRoute


@pytest.mark.parametrize(
    "cell",
    [
        '=HYPERLINK("https://evil.test","Click")',
        "+254700000000",
        "-1+1",
        "@SUM(A1:A2)",
        "\t=1+1",
        "\r=1+1",
        "\n=1+1",
        "  =1+1",
        "＝1+1",  # noqa: RUF001 (a full-width equals sign)
        "＠SUM(1)",  # noqa: RUF001
    ],
)
def test_a_formula_like_cell_is_neutralised(cell: str) -> None:
    assert neutralise(cell) == "'" + cell


@pytest.mark.parametrize("cell", ["", "Cold-chain alerts", "Telco A (fixture)", "2026-10-13", "a=b", "x-y", "'quoted"])
def test_an_ordinary_cell_is_left_as_it_is(cell: str) -> None:
    assert neutralise(cell) == cell


def test_the_file_is_utf8_with_a_bom_a_header_row_and_crlf() -> None:
    body = render([["id-1", 'Maji, "safi"\nna salama', "Proposal submitted", "2026-10-13", "", "@dev", "", ""]])
    assert body.startswith(b"\xef\xbb\xbf")
    text = body.decode("utf-8")
    header = "reference,title,stage,stage_entered_on,due_on,other_party,assignee,procurement_route"
    assert text.startswith(f"\ufeff{header}\r\n")
    assert text.endswith("\r\n")
    rows = list(csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline="")))
    assert rows[0] == list(COLUMNS)
    assert rows[1] == ["id-1", 'Maji, "safi"\nna salama', "Proposal submitted", "2026-10-13", "", "'@dev", "", ""]


def test_an_empty_export_is_the_header_row_alone() -> None:
    assert render([]).decode("utf-8") == "\ufeff" + ",".join(COLUMNS) + "\r\n"


def test_every_procurement_route_has_a_label() -> None:
    assert set(ROUTE_LABELS) == set(ProcurementRoute)
    assert all(label and label[0] not in "=+-@" for label in ROUTE_LABELS.values())


def test_the_file_is_named_by_the_nairobi_date() -> None:
    assert filename(date(2026, 10, 13)) == "engagements-2026-10-13.csv"
