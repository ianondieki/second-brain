#!/usr/bin/env python3
"""Phase 0 exit checks for docs/platform/REQUIREMENTS.md and docs/platform/PLAN.md.

Verifies:
  1. Every R01-R53 and R-HYG-01..06 maps to >=1 REQ-ID and >=1 AC that exist, and links are
     bidirectional (R-id row <-> REQ row <-> AC row).
  2. Release-1 REQ-IDs have >=1 AC (owned, or re-run via "AC-X (re-run)"); deferred rows cite an ADR.
  3. No AC is built before the REQ-IDs it depends on.
  4. No phase exit depends on a later phase: every AC (or clause) listed in the PLAN.md phase exit
     map is built at or before that phase, every built AC is listed at its own phase, and the spec's
     own per-phase AC lists (docs/spec/11-delivery-phases.md) are never asserted later than the spec
     demands (earlier is allowed and reported as a warning).
  5. The AC universe is complete: the ids in the spec tables (docs/spec/05, 06, 07, 10, read at run
     time) equal the hard-coded snapshot below and every one has a row in REQUIREMENTS.md.

Usage: python docs/platform/checks/check_traceability.py   (exit code 0 = PASS)
Standard library only; Python 3.12+.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = ROOT / "docs" / "platform" / "REQUIREMENTS.md"
PLAN = ROOT / "docs" / "platform" / "PLAN.md"
SPEC_AC_FILES = [
    ROOT / "docs" / "spec" / "05-subscriptions-billing.md",
    ROOT / "docs" / "spec" / "06-feature-modules.md",
    ROOT / "docs" / "spec" / "07-ux-information-architecture.md",
    ROOT / "docs" / "spec" / "10-security-privacy-compliance.md",
]
EXIT_MAP_AC_COLUMN = "Acceptance tests asserted at exit"

R_ID = re.compile(r"\bR(?:-HYG-)?\d{2}\b")
REQ_ID = re.compile(r"\bREQ-[A-Z0-9]+-\d{2}\b")
AC_ID = re.compile(r"\bAC-[A-Z]+-\d{1,2}(?:/[ab])?\b")
# In a REQ row's ACs column, "AC-X (re-run)" means the REQ is verified by re-running an AC owned by
# an earlier REQ (hardening, launch readiness); such links are exempt from the phase-order check.
AC_LINK = re.compile(r"(AC-[A-Z]+-\d{1,2}(?:/[ab])?)(\s*\(re-run\))?")
ADR_REF = re.compile(r"\bADR-00[1-8]\b")
# Loose shapes that look like ids but do not parse strictly (typos such as R1, REQ-FND-1, AC-IP-3/A).
LOOSE_R = re.compile(r"\bR(?:-HYG-)?-?\d{1,2}\b")
LOOSE_REQ = re.compile(r"\bREQ-[A-Za-z0-9-]+\b")
LOOSE_AC = re.compile(r"\bAC-[A-Za-z]+-\d+(?:/[A-Za-z])?\b")
SEPARATOR_CELL = re.compile(r"^:?-{3,}:?$")

EXPECTED_R = [f"R{i:02d}" for i in range(1, 54)] + [f"R-HYG-{i:02d}" for i in range(1, 7)]
R1_STATUSES = {"TODO", "IN-PROGRESS", "DONE", "NEEDS-HUMAN"}

# AC universe snapshot: the spec tables (docs/spec/05, 06, 07, 10) plus the derived AC-HYG set.
# check_spec_universe() re-reads those spec files and fails if this snapshot drifts from them.
SPEC_ACS: set[str] = set()
SPEC_ACS.update(f"AC-HYG-{i:02d}" for i in range(1, 7))
SPEC_ACS.update(f"AC-SUB-{i}" for i in range(1, 8))
SPEC_ACS.update(f"AC-REPO-{i}" for i in range(1, 7))
SPEC_ACS.update(f"AC-DIR-{i}" for i in range(1, 8))
SPEC_ACS.update(f"AC-PROP-{i}" for i in range(1, 8))
SPEC_ACS.update(f"AC-IP-{i}" for i in range(1, 10))
SPEC_ACS.update(f"AC-RES-{i}" for i in range(1, 5))
SPEC_ACS.update(f"AC-TREND-{i}" for i in range(1, 4))
SPEC_ACS.update(f"AC-PERS-{i}" for i in range(1, 8))
SPEC_ACS.update(f"AC-SCOUT-{i}" for i in range(1, 9))
SPEC_ACS.update(f"AC-TRACK-{i}" for i in range(1, 11))
SPEC_ACS.update(f"AC-MAIL-{i}" for i in range(1, 6))
SPEC_ACS.update(f"AC-REM-{i}" for i in range(1, 5))
SPEC_ACS.update(f"AC-ADM-{i}" for i in range(1, 5))
SPEC_ACS.update(f"AC-UX-{i}" for i in range(1, 6))
SPEC_ACS.update(f"AC-SEC-{i}" for i in range(1, 8))

# Spec exit lists hand-copied from docs/spec/11-delivery-phases.md (verified against commit 7e5ec59 of
# that file; re-verify when it changes). Value = the phase the spec asserts the AC at. Clause-specific
# deferrals in the spec ("X -> Phase N") are encoded on the clause id. Release-2 clauses have no spec
# phase: AC-MAIL-4, AC-IP-3/b.
SPEC_PHASE: dict[str, int] = {}
SPEC_PHASE.update({f"AC-HYG-{i:02d}": 1 for i in range(1, 7)})
SPEC_PHASE.update({"AC-SEC-1/a": 1, "AC-REM-4/a": 1})
SPEC_PHASE.update({"AC-SEC-1/b": 2})
SPEC_PHASE.update({f"AC-REPO-{i}": 2 for i in (1, 2, 3, 5)})
SPEC_PHASE.update({"AC-REPO-4/a": 2, "AC-REPO-4/b": 4, "AC-REPO-6/a": 2, "AC-REPO-6/b": 5})
SPEC_PHASE.update({f"AC-DIR-{i}": 2 for i in (1, 2, 3, 4, 6, 7)})
SPEC_PHASE.update({"AC-DIR-5/a": 2, "AC-DIR-5/b": 4})
SPEC_PHASE.update({f"AC-PROP-{i}": 2 for i in (2, 4, 5, 6, 7)})
SPEC_PHASE.update({"AC-PROP-1/a": 2, "AC-PROP-1/b": 3, "AC-PROP-3": 3})
SPEC_PHASE.update({f"AC-IP-{i}": 2 for i in (1, 2, 4, 5, 6, 9)})
SPEC_PHASE.update({"AC-IP-3/a": 3, "AC-IP-8": 3, "AC-IP-7": 8})
SPEC_PHASE.update({f"AC-TRACK-{i}": 3 for i in (1, 2, 3, 4, 5, 6, 7, 9, 10)})
SPEC_PHASE.update({"AC-TRACK-8/a": 3, "AC-TRACK-8/b": 4})
SPEC_PHASE.update({f"AC-MAIL-{i}": 3 for i in (1, 2, 3, 5)})
SPEC_PHASE.update({f"AC-REM-{i}": 3 for i in (1, 2, 3)})
SPEC_PHASE.update({"AC-REM-4/b": 3, "AC-SEC-6": 3, "AC-SEC-7": 3})
SPEC_PHASE.update({f"AC-SCOUT-{i}": 4 for i in range(1, 9)})
SPEC_PHASE.update({f"AC-RES-{i}": 5 for i in range(1, 5)})
SPEC_PHASE.update({f"AC-TREND-{i}": 5 for i in range(1, 4)})
SPEC_PHASE.update({f"AC-PERS-{i}": 5 for i in range(1, 8)})
SPEC_PHASE.update({f"AC-SUB-{i}": 6 for i in range(1, 8)})
SPEC_PHASE.update({f"AC-UX-{i}": 7 for i in range(1, 6)})
SPEC_PHASE.update({f"AC-SEC-{i}": 8 for i in (2, 3, 4, 5)})
SPEC_PHASE.update({f"AC-ADM-{i}": 8 for i in range(1, 5)})

Table = tuple[list[str], list[list[str]]]
Phase = int | str


class ReqRow(TypedDict):
    r: set[str]
    ac: set[str]
    rerun: set[str]
    phase: Phase
    release: str
    status: str


class AcRow(TypedDict):
    req: set[str]
    phase: Phase
    release: str
    status: str
    gwt: tuple[str, str, str]


class RRow(TypedDict):
    req: set[str]
    ac: set[str]
    phase: Phase


class Report:
    """Collects errors and warnings; errors make the run fail."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def finish(self) -> int:
        for w in self.warnings:
            print(f"WARN  {w}")
        for e in self.errors:
            print(f"ERROR {e}")
        if self.errors:
            print(f"FAIL: {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
            return 1
        print(f"PASS: 0 errors, {len(self.warnings)} warning(s)")
        return 0


# ---------------------------------------------------------------------------- parsing helpers


def read_text(path: Path, rep: Report) -> str | None:
    """Read a UTF-8 file; report a clean error instead of a traceback when it is missing or not UTF-8."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        rep.error(f"{path.relative_to(ROOT)}: file not found")
    except UnicodeDecodeError as exc:
        rep.error(f"{path.relative_to(ROOT)}: not valid UTF-8 ({exc.reason} at byte {exc.start})")
    return None


def split_row(line: str) -> list[str]:
    """Split one `| a | b |` line into cells, keeping escaped pipes (`\\|`) inside a cell."""
    inner = line.strip().strip("|")
    cells: list[str] = []
    cur: list[str] = []
    esc = False
    for ch in inner:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            cur.append(ch)
            esc = True
        elif ch == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur).strip())
    return cells


def is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(SEPARATOR_CELL.match(c.strip()) for c in cells)


def parse_tables(text: str, label: str, rep: Report) -> list[Table]:
    """Return (header, rows) for every markdown table; report blocks that are not well-formed tables.

    A well-formed table is a run of consecutive `|` lines whose second line is the `|---|` separator.
    A run that lacks the separator (for example the tail of a table cut in two by a blank line) is
    reported instead of being silently dropped.
    """
    tables: list[Table] = []
    block: list[tuple[int, str]] = []

    def flush() -> None:
        if not block:
            return
        rows = [split_row(line) for _, line in block]
        first_line = block[0][0]
        if len(rows) >= 2 and is_separator(rows[1]):
            tables.append((rows[0], rows[2:]))
        else:
            rep.error(f"{label}:{first_line}: malformed table block (no `|---|` separator on its second line; "
                      "a blank line inside a table splits it)")
        block.clear()

    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("|"):
            block.append((number, line))
        else:
            flush()
    flush()
    return tables


def find_table(tables: list[Table], first_header: str) -> Table | None:
    """Return the table whose first header cell equals first_header."""
    for header, rows in tables:
        if header and header[0].strip("*` ") == first_header:
            return header, rows
    return None


def phase_of(cell: str) -> Phase:
    """Parse a Phase cell: build phase (int 1-8) or a release label such as 'R2'."""
    cell = cell.strip()
    return int(cell) if cell.isascii() and cell.isdecimal() else cell


def base(ac: str) -> str:
    """Strip a clause suffix: AC-PROP-1/a -> AC-PROP-1."""
    return ac.split("/")[0]


def warn_loose_ids(cell: str, strict: re.Pattern[str], loose: re.Pattern[str], where: str, rep: Report) -> None:
    """Warn about tokens that look like ids but do not match the strict pattern (likely typos)."""
    strict_ids = set(strict.findall(cell))
    for token in loose.findall(cell):
        if token not in strict_ids and not any(token == s or token.startswith(s) for s in strict_ids):
            rep.warn(f"{where}: '{token}' looks like an id but does not parse; ignored")


# ---------------------------------------------------------------------------- table loaders


def column_index(header: list[str], names: list[str], label: str, rep: Report) -> dict[str, int] | None:
    index = {h: i for i, h in enumerate(header)}
    missing = [n for n in names if n not in index]
    if missing:
        rep.error(f"{label}: table is missing column(s) {missing}")
        return None
    return index


def load_reqs(table: Table, rep: Report) -> tuple[dict[str, ReqRow], list[tuple[str, ReqRow]]]:
    """Parse the REQ table. Duplicated ids are reported; every copy is returned for content checks."""
    header, rows = table
    ci = column_index(header, ["REQ-ID", "R-ids", "ACs", "Phase", "Release", "Status"], "REQ table", rep)
    reqs: dict[str, ReqRow] = {}
    duplicates: list[tuple[str, ReqRow]] = []
    if ci is None:
        return reqs, duplicates
    for row in rows:
        if len(row) < len(header):
            rep.error(f"REQ row too short ({len(row)} of {len(header)} cells): {row[:1]}")
            continue
        rid = row[ci["REQ-ID"]].strip("` ")
        if not REQ_ID.fullmatch(rid):
            rep.error(f"bad REQ-ID cell: {rid!r}")
            continue
        warn_loose_ids(row[ci["R-ids"]], R_ID, LOOSE_R, f"{rid} R-ids", rep)
        warn_loose_ids(row[ci["ACs"]], AC_ID, LOOSE_AC, f"{rid} ACs", rep)
        entry: ReqRow = {
            "r": set(R_ID.findall(row[ci["R-ids"]])),
            "ac": {m.group(1) for m in AC_LINK.finditer(row[ci["ACs"]]) if not m.group(2)},
            "rerun": {m.group(1) for m in AC_LINK.finditer(row[ci["ACs"]]) if m.group(2)},
            "phase": phase_of(row[ci["Phase"]]),
            "release": row[ci["Release"]].strip(),
            "status": row[ci["Status"]].strip(),
        }
        if rid in reqs:
            rep.error(f"duplicate REQ-ID row {rid} (both copies are checked)")
            duplicates.append((rid, entry))
        else:
            reqs[rid] = entry
    return reqs, duplicates


def load_acs(table: Table, rep: Report) -> tuple[dict[str, AcRow], list[tuple[str, AcRow]]]:
    """Parse the AC table. Duplicated ids are reported; every copy is returned for content checks."""
    header, rows = table
    ci = column_index(header, ["AC", "REQ-IDs", "Given", "When", "Then", "Phase", "Release", "Status"], "AC table", rep)
    acs: dict[str, AcRow] = {}
    duplicates: list[tuple[str, AcRow]] = []
    if ci is None:
        return acs, duplicates
    for row in rows:
        if len(row) < len(header):
            rep.error(f"AC row too short ({len(row)} of {len(header)} cells): {row[:1]}")
            continue
        aid = row[ci["AC"]].strip("` ")
        if not AC_ID.fullmatch(aid):
            rep.error(f"bad AC cell: {aid!r}")
            continue
        warn_loose_ids(row[ci["REQ-IDs"]], REQ_ID, LOOSE_REQ, f"{aid} REQ-IDs", rep)
        entry: AcRow = {
            "req": set(REQ_ID.findall(row[ci["REQ-IDs"]])),
            "phase": phase_of(row[ci["Phase"]]),
            "release": row[ci["Release"]].strip(),
            "status": row[ci["Status"]].strip(),
            "gwt": (row[ci["Given"]], row[ci["When"]], row[ci["Then"]]),
        }
        if aid in acs:
            rep.error(f"duplicate AC row {aid} (both copies are checked)")
            duplicates.append((aid, entry))
        else:
            acs[aid] = entry
    return acs, duplicates


def load_r_rows(table: Table, rep: Report) -> dict[str, RRow]:
    """Parse the R-id index table."""
    header, rows = table
    ci = column_index(header, ["R-id", "REQ-IDs", "ACs", "Phase"], "R-id table", rep)
    seen: dict[str, RRow] = {}
    if ci is None:
        return seen
    for row in rows:
        if len(row) < len(header):
            rep.error(f"R row too short ({len(row)} of {len(header)} cells): {row[:1]}")
            continue
        rid = row[ci["R-id"]].strip("` ")
        if not R_ID.fullmatch(rid):
            rep.error(f"bad R-id cell: {rid!r}")
            continue
        warn_loose_ids(row[ci["REQ-IDs"]], REQ_ID, LOOSE_REQ, f"{rid} REQ-IDs", rep)
        warn_loose_ids(row[ci["ACs"]], AC_ID, LOOSE_AC, f"{rid} ACs", rep)
        if rid in seen:
            rep.error(f"duplicate R-id row {rid} (first copy kept)")
            continue
        seen[rid] = {
            "req": set(REQ_ID.findall(row[ci["REQ-IDs"]])),
            "ac": set(AC_ID.findall(row[ci["ACs"]])),
            "phase": phase_of(row[ci["Phase"]]),
        }
    return seen


def expected_r_phase(entry: RRow, reqs: dict[str, ReqRow], acs: dict[str, AcRow]) -> int | None:
    """Latest build phase among the R-id's Release-1 REQ-IDs and the clauses of its ACs (None if nothing is built)."""
    phases: list[int] = []
    for q in entry["req"]:
        if q in reqs and isinstance(reqs[q]["phase"], int):
            phases.append(reqs[q]["phase"])
    for a in entry["ac"]:
        for aid, row in acs.items():
            if base(aid) == base(a) and isinstance(row["phase"], int):
                phases.append(row["phase"])
    return max(phases) if phases else None


def load_exit_map(table: Table, rep: Report) -> dict[int, set[str]]:
    """Parse PLAN.md's phase exit map: phase number -> AC ids listed at that exit."""
    header, rows = table
    ci = column_index(header, ["Phase", EXIT_MAP_AC_COLUMN], "phase exit map", rep)
    exit_map: dict[int, set[str]] = {}
    if ci is None:
        return exit_map
    for row in rows:
        if len(row) < len(header):
            rep.error(f"phase exit map row too short ({len(row)} of {len(header)} cells): {row[:1]}")
            continue
        cell = row[ci["Phase"]].strip()
        if not (cell.isascii() and cell.isdecimal()):
            continue
        phase = int(cell)
        if phase in exit_map:
            rep.error(f"phase exit map lists phase {phase} twice")
        warn_loose_ids(row[ci[EXIT_MAP_AC_COLUMN]], AC_ID, LOOSE_AC, f"phase {phase} exit", rep)
        exit_map[phase] = set(AC_ID.findall(row[ci[EXIT_MAP_AC_COLUMN]]))
    return exit_map


# ---------------------------------------------------------------------------- checks


def check_r_rows(seen_r: dict[str, RRow], reqs: dict[str, ReqRow], acs: dict[str, AcRow], rep: Report) -> None:
    """Check 1: every expected R-id maps to >=1 existing REQ-ID and >=1 existing AC, links go both ways."""
    ac_bases = {base(a) for a in acs}
    for rid in EXPECTED_R:
        if rid not in seen_r:
            rep.error(f"{rid}: missing from the R-id table")
            continue
        entry = seen_r[rid]
        if not entry["req"]:
            rep.error(f"{rid}: no REQ-ID")
        for q in entry["req"]:
            if q not in reqs:
                rep.error(f"{rid}: REQ-ID {q} does not exist in the REQ table")
        if not entry["ac"]:
            rep.error(f"{rid}: no AC")
        for a in entry["ac"]:
            if base(a) not in ac_bases:
                rep.error(f"{rid}: AC {a} does not exist in the AC table")
        for q in entry["req"]:
            if q in reqs and rid not in reqs[q]["r"]:
                rep.error(f"{rid}: lists {q} but {q}'s R-ids column does not list {rid}")
        reachable: set[str] = set()
        for q in entry["req"]:
            if q in reqs:
                reachable |= {base(a) for a in reqs[q]["ac"] | reqs[q]["rerun"]}
        for a in entry["ac"]:
            if base(a) in ac_bases and base(a) not in reachable:
                rep.warn(f"{rid}: AC {a} is not linked from any of {rid}'s REQ-IDs (indirect trace)")
        want = expected_r_phase(entry, reqs, acs)
        if want is not None and entry["phase"] != want:
            rep.error(f"{rid}: Phase is {entry['phase']!r} but its latest Release-1 REQ-ID/AC clause is built in phase {want}")
    for rid in seen_r:
        if rid not in EXPECTED_R:
            rep.error(f"unexpected R-id {rid} in the R-id table")


def check_req_content(q: str, e: ReqRow, rep: Report) -> None:
    """Row-level rules for one REQ row (applied to duplicates too)."""
    if not e["r"]:
        rep.error(f"{q}: no R-id")
    for rid in e["r"]:
        if rid not in EXPECTED_R:
            rep.error(f"{q}: unknown R-id {rid}")
    if e["release"] == "R1":
        if not (e["ac"] or e["rerun"]):
            rep.error(f"{q}: Release 1 REQ without an AC")
        if not isinstance(e["phase"], int) or not 1 <= e["phase"] <= 8:
            rep.error(f"{q}: Release 1 REQ needs a build phase 1-8, got {e['phase']!r}")
        if e["status"] not in R1_STATUSES:
            rep.error(f"{q}: Release 1 status must be one of {sorted(R1_STATUSES)}, got {e['status']!r}")
    else:
        if not e["status"].startswith("DEFERRED"):
            rep.error(f"{q}: Release {e['release']} row must be DEFERRED")
        if not ADR_REF.search(e["status"]):
            rep.error(f"{q}: DEFERRED row must cite an ADR number")
        if e["phase"] not in ("R2", "R3"):
            rep.error(f"{q}: deferred row phase must be R2/R3, got {e['phase']!r}")


def check_req_links(reqs: dict[str, ReqRow], seen_r: dict[str, RRow], acs: dict[str, AcRow], rep: Report) -> None:
    """Check 2: REQ <-> R-id and REQ <-> AC links are consistent."""
    for q, e in reqs.items():
        for rid in e["r"]:
            if rid in seen_r and q not in seen_r[rid]["req"]:
                rep.error(f"{q}: lists {rid} but {rid}'s row does not list {q}")
        for a in e["ac"] | e["rerun"]:
            if a not in acs:
                rep.error(f"{q}: AC {a} not found as an AC row (clause ids must match exactly)")
        for a in e["ac"]:
            if a in acs and q not in acs[a]["req"]:
                rep.error(f"{q}: owns {a} but {a}'s REQ-IDs column does not list {q} (use '(re-run)' if it only re-runs it)")
        for a in e["rerun"]:
            if a in acs and q in acs[a]["req"]:
                rep.error(f"{q}: marks {a} as re-run but {a} lists {q} as an owner")


def check_ac_content(a: str, e: AcRow, rep: Report) -> None:
    """Row-level rules for one AC row (applied to duplicates too)."""
    if base(a) not in SPEC_ACS:
        rep.error(f"{a}: not an AC from the spec tables (invented id?)")
    if not e["req"]:
        rep.error(f"{a}: no REQ-ID")
    if not all(part.strip() for part in e["gwt"]):
        rep.error(f"{a}: empty Given/When/Then cell")
    if isinstance(e["phase"], int):
        if not 1 <= e["phase"] <= 8:
            rep.error(f"{a}: build phase must be 1-8, got {e['phase']}")
        if e["release"] != "R1":
            rep.error(f"{a}: built in phase {e['phase']} but release {e['release']}")
        if e["status"].startswith("DEFERRED"):
            rep.error(f"{a}: built in phase {e['phase']} but status DEFERRED")
    elif not e["status"].startswith("DEFERRED") or not ADR_REF.search(e["status"]):
        rep.error(f"{a}: deferred AC must be 'DEFERRED (ADR-nnn)'")


def check_ac_links(acs: dict[str, AcRow], reqs: dict[str, ReqRow], rep: Report) -> None:
    """Check 3: AC -> REQ links exist, are mutual, and no AC is built before its REQs; clause pairs are complete."""
    for a, e in acs.items():
        for q in e["req"]:
            if q not in reqs:
                rep.error(f"{a}: REQ-ID {q} does not exist")
                continue
            if a not in reqs[q]["ac"]:
                rep.error(f"{a}: lists {q} but {q}'s ACs column does not list {a}")
            qp = reqs[q]["phase"]
            if isinstance(e["phase"], int):
                if not isinstance(qp, int):
                    rep.error(f"{a} (phase {e['phase']}): depends on deferred {q} ({qp})")
                elif qp > e["phase"]:
                    rep.error(f"{a} (phase {e['phase']}): depends on {q} built in later phase {qp}")
        if "/" in a:
            b = base(a)
            if b in acs:
                rep.error(f"{a}: clause row and plain row {b} both exist")
            if not (f"{b}/a" in acs and f"{b}/b" in acs):
                rep.error(f"{a}: split AC needs both /a and /b rows")
    ac_bases = {base(a) for a in acs}
    for spec_ac in sorted(SPEC_ACS):
        if spec_ac not in ac_bases:
            rep.error(f"{spec_ac}: AC from the spec is missing from the AC table")


def check_exit_map(exit_map: dict[int, set[str]], acs: dict[str, AcRow], rep: Report) -> None:
    """Check 4a: no phase exit depends on a later phase; every built AC is listed at its own phase."""
    if set(exit_map) != set(range(1, 9)):
        rep.error(f"phase exit map must cover phases 1-8 exactly once, got {sorted(exit_map)}")
    listed: dict[str, list[int]] = {}
    for p, ids in exit_map.items():
        for a in ids:
            if a not in acs:
                rep.error(f"phase {p} exit lists {a}, which has no AC row (clause id mismatch?)")
                continue
            listed.setdefault(a, []).append(p)
            ap = acs[a]["phase"]
            if not isinstance(ap, int):
                rep.error(f"phase {p} exit lists deferred AC {a}")
            elif ap > p:
                rep.error(f"phase {p} exit depends on {a}, which is built in later phase {ap}")
    for a, e in acs.items():
        if isinstance(e["phase"], int):
            if a not in listed:
                rep.error(f"{a}: built in phase {e['phase']} but listed at no phase exit")
            elif e["phase"] not in listed[a]:
                rep.error(f"{a}: built in phase {e['phase']} but listed only at phases {listed[a]}")


def check_spec_alignment(acs: dict[str, AcRow], rep: Report) -> None:
    """Check 4b: never assert an AC later than the phase docs/spec/11 lists it at (earlier is a warning)."""
    for a, sp in SPEC_PHASE.items():
        if a not in acs:
            rep.error(f"spec lists {a} at phase {sp} but the AC table has no such row")
            continue
        ap = acs[a]["phase"]
        if not isinstance(ap, int):
            rep.error(f"{a}: spec asserts it at phase {sp} but it is deferred")
        elif ap > sp:
            rep.error(f"{a}: asserted at phase {ap}, later than the spec's phase {sp}")
        elif ap < sp:
            rep.warn(f"{a}: asserted at phase {ap}, earlier than the spec's phase {sp} (allowed)")


def check_spec_universe(rep: Report) -> None:
    """Check 5: the SPEC_ACS snapshot equals the AC ids found in the spec tables read at run time."""
    found: set[str] = set()
    for path in SPEC_AC_FILES:
        text = read_text(path, rep)
        if text is None:
            continue
        for line in text.splitlines():
            if line.startswith("| AC-"):
                cells = split_row(line)
                if cells and AC_ID.fullmatch(cells[0].strip("` ")):
                    found.add(cells[0].strip("` "))
    expected = {a for a in SPEC_ACS if not a.startswith("AC-HYG-")}  # AC-HYG is derived, not in the spec tables
    for a in sorted(found - expected):
        rep.error(f"{a}: present in the spec tables but missing from the SPEC_ACS snapshot in this script")
    for a in sorted(expected - found):
        rep.error(f"{a}: in the SPEC_ACS snapshot but no longer in the spec tables")


# ---------------------------------------------------------------------------- entry point


def main() -> int:
    """Load both documents, run every check, print the summary and return the exit code."""
    rep = Report()
    req_text = read_text(REQUIREMENTS, rep)
    plan_text = read_text(PLAN, rep)
    if req_text is None or plan_text is None:
        return rep.finish()
    req_tables = parse_tables(req_text, "REQUIREMENTS.md", rep)
    plan_tables = parse_tables(plan_text, "PLAN.md", rep)

    r_table = find_table(req_tables, "R-id")
    q_table = find_table(req_tables, "REQ-ID")
    a_table = find_table(req_tables, "AC")
    x_table = find_table(plan_tables, "Phase")
    for name, tbl in (("R-id", r_table), ("REQ-ID", q_table), ("AC", a_table), ("Phase", x_table)):
        if tbl is None:
            rep.error(f"table whose first header is '{name}' not found")
    if r_table is None or q_table is None or a_table is None or x_table is None:
        return rep.finish()

    reqs, req_dups = load_reqs(q_table, rep)
    acs, ac_dups = load_acs(a_table, rep)
    seen_r = load_r_rows(r_table, rep)
    exit_map = load_exit_map(x_table, rep)

    check_r_rows(seen_r, reqs, acs, rep)
    for q, req_row in list(reqs.items()) + req_dups:
        check_req_content(q, req_row, rep)
    check_req_links(reqs, seen_r, acs, rep)
    for a, ac_row in list(acs.items()) + ac_dups:
        check_ac_content(a, ac_row, rep)
    check_ac_links(acs, reqs, rep)
    check_exit_map(exit_map, acs, rep)
    check_spec_alignment(acs, rep)
    check_spec_universe(rep)

    r1_req = sum(1 for e in reqs.values() if e["release"] == "R1")
    r1_ac = sum(1 for e in acs.values() if e["release"] == "R1")
    print(f"R-ids: {len(EXPECTED_R)} expected, {len(seen_r)} found")
    print(f"REQ rows: {len(reqs)} ({r1_req} R1); AC rows incl. clauses: {len(acs)} ({r1_ac} R1)")
    print("Phase exit map: " + ", ".join(f"P{p}={len(exit_map[p])}" for p in sorted(exit_map)))
    return rep.finish()


if __name__ == "__main__":
    sys.exit(main())
