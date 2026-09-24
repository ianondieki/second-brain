#!/usr/bin/env python3
"""Phase 0 exit checks for docs/platform/REQUIREMENTS.md and docs/platform/PLAN.md.

Verifies:
  1. Every R01-R53 and R-HYG-01..06 maps to >=1 REQ-ID and >=1 AC that exist.
  2. Every REQ-ID has >=1 R-id; Release-1 REQ-IDs have >=1 AC; deferred rows cite an ADR.
  3. Every AC has >=1 REQ-ID and is not built before the REQ-IDs it depends on.
  4. No phase exit depends on a later phase: every AC (or clause) listed in the PLAN.md phase
     exit map is built at or before that phase, every built AC is listed at its own phase, and the
     spec's own per-phase AC lists (docs/spec/11-delivery-phases.md) are never asserted later than
     the spec demands.
  5. The AC universe from the spec tables is complete (no AC missing, none invented).

Usage: python docs/platform/checks/check_traceability.py   (exit code 0 = PASS)
Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REQUIREMENTS = ROOT / "docs" / "platform" / "REQUIREMENTS.md"
PLAN = ROOT / "docs" / "platform" / "PLAN.md"

R_ID = re.compile(r"\bR(?:-HYG-)?\d{2}\b")
REQ_ID = re.compile(r"\bREQ-[A-Z0-9]+-\d{2}\b")
AC_ID = re.compile(r"\bAC-[A-Z]+-\d{1,2}(?:/[ab])?\b")
# In a REQ row's ACs column, "AC-X (re-run)" means the REQ is verified by re-running an AC owned by
# an earlier REQ (hardening, launch readiness); such links are exempt from the phase-order check.
AC_LINK = re.compile(r"(AC-[A-Z]+-\d{1,2}(?:/[ab])?)(\s*\(re-run\))?")
ADR_REF = re.compile(r"\bADR-00[1-8]\b")

EXPECTED_R = [f"R{i:02d}" for i in range(1, 54)] + [f"R-HYG-{i:02d}" for i in range(1, 7)]

# AC universe copied from the spec tables (docs/spec/05, 06, 07, 10) plus the derived AC-HYG set.
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

# Spec exit lists from docs/spec/11-delivery-phases.md. Value = phase the spec asserts the AC at.
# Clause-specific deferrals in the spec ("X -> Phase N") are encoded on the clause id.
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
# Release-2 clauses have no spec phase: AC-MAIL-4, AC-IP-3/b.


def split_row(line: str) -> list[str]:
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


def parse_tables(text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return (header, rows) for every markdown table in the text."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    block: list[str] = []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            block.append(line)
            continue
        if block:
            rows = [split_row(line_) for line_ in block]
            if len(rows) >= 2:
                tables.append((rows[0], rows[2:]))
            block = []
    return tables


def find_table(tables, first_header: str):
    for header, rows in tables:
        if header and header[0].strip("*` ") == first_header:
            return header, rows
    return None, None


def phase_of(cell: str) -> int | str:
    cell = cell.strip()
    return int(cell) if cell.isdigit() else cell  # 'R2' / 'R3'


def base(ac: str) -> str:
    return ac.split("/")[0]


def report(errors: list[str], warnings: list[str]) -> int:
    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        print(f"FAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"PASS: 0 errors, {len(warnings)} warning(s)")
    return 0


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    req_tables = parse_tables(REQUIREMENTS.read_text(encoding="utf-8"))
    plan_tables = parse_tables(PLAN.read_text(encoding="utf-8"))

    r_header, r_rows = find_table(req_tables, "R-id")
    q_header, q_rows = find_table(req_tables, "REQ-ID")
    a_header, a_rows = find_table(req_tables, "AC")
    x_header, x_rows = find_table(plan_tables, "Phase")
    for name, tbl in (("R-id", r_rows), ("REQ-ID", q_rows), ("AC", a_rows), ("Phase", x_rows)):
        if tbl is None:
            errors.append(f"table whose first header is '{name}' not found")
    if errors:
        return report(errors, warnings)

    # ---- REQ table --------------------------------------------------------------------------
    qi = {h: i for i, h in enumerate(q_header)}
    reqs: dict[str, dict] = {}
    for row in q_rows:
        if len(row) < len(q_header):
            errors.append(f"REQ row too short: {row[:2]}")
            continue
        rid = row[qi["REQ-ID"]].strip("` ")
        if not REQ_ID.fullmatch(rid):
            errors.append(f"bad REQ-ID cell: {rid!r}")
            continue
        if rid in reqs:
            errors.append(f"duplicate REQ-ID {rid}")
        owned = {m.group(1) for m in AC_LINK.finditer(row[qi["ACs"]]) if not m.group(2)}
        rerun = {m.group(1) for m in AC_LINK.finditer(row[qi["ACs"]]) if m.group(2)}
        reqs[rid] = {
            "r": set(R_ID.findall(row[qi["R-ids"]])),
            "ac": owned,
            "rerun": rerun,
            "phase": phase_of(row[qi["Phase"]]),
            "release": row[qi["Release"]].strip(),
            "status": row[qi["Status"]].strip(),
        }

    # ---- AC table ---------------------------------------------------------------------------
    ai = {h: i for i, h in enumerate(a_header)}
    acs: dict[str, dict] = {}
    for row in a_rows:
        if len(row) < len(a_header):
            errors.append(f"AC row too short: {row[:2]}")
            continue
        aid = row[ai["AC"]].strip("` ")
        if not AC_ID.fullmatch(aid):
            errors.append(f"bad AC cell: {aid!r}")
            continue
        if aid in acs:
            errors.append(f"duplicate AC row {aid}")
        acs[aid] = {
            "req": set(REQ_ID.findall(row[ai["REQ-IDs"]])),
            "phase": phase_of(row[ai["Phase"]]),
            "release": row[ai["Release"]].strip(),
            "status": row[ai["Status"]].strip(),
            "gwt": (row[ai["Given"]], row[ai["When"]], row[ai["Then"]]),
        }
    ac_bases = {base(a) for a in acs}

    # ---- R-id table -------------------------------------------------------------------------
    ri = {h: i for i, h in enumerate(r_header)}
    seen_r: dict[str, dict] = {}
    for row in r_rows:
        if len(row) < len(r_header):
            errors.append(f"R row too short: {row[:2]}")
            continue
        rid = row[ri["R-id"]].strip("` ")
        if rid in seen_r:
            errors.append(f"duplicate R-id row {rid}")
        seen_r[rid] = {
            "req": set(REQ_ID.findall(row[ri["REQ-IDs"]])),
            "ac": set(AC_ID.findall(row[ri["ACs"]])),
        }

    # Check 1: every R-id present with >=1 existing REQ and >=1 existing AC.
    for rid in EXPECTED_R:
        if rid not in seen_r:
            errors.append(f"{rid}: missing from the R-id table")
            continue
        entry = seen_r[rid]
        if not entry["req"]:
            errors.append(f"{rid}: no REQ-ID")
        for q in entry["req"]:
            if q not in reqs:
                errors.append(f"{rid}: REQ-ID {q} does not exist in the REQ table")
        if not entry["ac"]:
            errors.append(f"{rid}: no AC")
        for a in entry["ac"]:
            if base(a) not in ac_bases:
                errors.append(f"{rid}: AC {a} does not exist in the AC table")
        if not any(rid in reqs[q]["r"] for q in entry["req"] if q in reqs):
            errors.append(f"{rid}: none of its REQ-IDs lists {rid} in its R-ids column")
        reachable = set()
        for q in entry["req"]:
            if q in reqs:
                reachable |= {base(a) for a in reqs[q]["ac"] | reqs[q]["rerun"]}
        for a in entry["ac"]:
            if base(a) in ac_bases and base(a) not in reachable:
                warnings.append(f"{rid}: AC {a} is not linked from any of {rid}'s REQ-IDs (indirect trace)")
    for rid in seen_r:
        if rid not in EXPECTED_R:
            errors.append(f"unexpected R-id {rid} in the R-id table")

    # Check 2: REQ rows.
    for q, e in reqs.items():
        if not e["r"]:
            errors.append(f"{q}: no R-id")
        for rid in e["r"]:
            if rid not in EXPECTED_R:
                errors.append(f"{q}: unknown R-id {rid}")
            elif q not in seen_r.get(rid, {"req": set()})["req"]:
                errors.append(f"{q}: lists {rid} but {rid}'s row does not list {q}")
        for a in e["ac"] | e["rerun"]:
            if a not in acs:
                errors.append(f"{q}: AC {a} not found as an AC row (clause ids must match exactly)")
        for a in e["ac"]:
            if a in acs and q not in acs[a]["req"]:
                errors.append(f"{q}: owns {a} but {a}'s REQ-IDs column does not list {q} (use '(re-run)' if it only re-runs it)")
        for a in e["rerun"]:
            if a in acs and q in acs[a]["req"]:
                errors.append(f"{q}: marks {a} as re-run but {a} lists {q} as an owner")
        if e["release"] == "R1":
            if not (e["ac"] or e["rerun"]):
                errors.append(f"{q}: Release 1 REQ without an AC")
            if not isinstance(e["phase"], int) or not 1 <= e["phase"] <= 8:
                errors.append(f"{q}: Release 1 REQ needs a build phase 1-8, got {e['phase']!r}")
            if e["status"] not in {"TODO", "IN-PROGRESS", "DONE", "NEEDS-HUMAN"}:
                errors.append(f"{q}: Release 1 status must be TODO/IN-PROGRESS/DONE/NEEDS-HUMAN, got {e['status']!r}")
        else:
            if not e["status"].startswith("DEFERRED"):
                errors.append(f"{q}: Release {e['release']} row must be DEFERRED")
            if not ADR_REF.search(e["status"]):
                errors.append(f"{q}: DEFERRED row must cite an ADR number")
            if e["phase"] not in ("R2", "R3"):
                errors.append(f"{q}: deferred row phase must be R2/R3, got {e['phase']!r}")

    # Check 3: AC rows.
    for a, e in acs.items():
        if base(a) not in SPEC_ACS:
            errors.append(f"{a}: not an AC from the spec tables (invented id?)")
        if not e["req"]:
            errors.append(f"{a}: no REQ-ID")
        if not all(part.strip() for part in e["gwt"]):
            errors.append(f"{a}: empty Given/When/Then cell")
        for q in e["req"]:
            if q not in reqs:
                errors.append(f"{a}: REQ-ID {q} does not exist")
                continue
            if a not in reqs[q]["ac"]:
                errors.append(f"{a}: lists {q} but {q}'s ACs column does not list {a}")
            qp = reqs[q]["phase"]
            if isinstance(e["phase"], int):
                if not isinstance(qp, int):
                    errors.append(f"{a} (phase {e['phase']}): depends on deferred {q} ({qp})")
                elif qp > e["phase"]:
                    errors.append(f"{a} (phase {e['phase']}): depends on {q} built in later phase {qp}")
        if isinstance(e["phase"], int):
            if e["release"] != "R1":
                errors.append(f"{a}: built in phase {e['phase']} but release {e['release']}")
            if e["status"].startswith("DEFERRED"):
                errors.append(f"{a}: built in phase {e['phase']} but status DEFERRED")
        else:
            if not e["status"].startswith("DEFERRED") or not ADR_REF.search(e["status"]):
                errors.append(f"{a}: deferred AC must be 'DEFERRED (ADR-nnn)'")
    for spec_ac in sorted(SPEC_ACS):
        if spec_ac not in ac_bases:
            errors.append(f"{spec_ac}: AC from the spec is missing from the AC table")
    for a in acs:
        if "/" in a:
            b = base(a)
            if b in acs:
                errors.append(f"{a}: clause row and plain row {b} both exist")
            if not (f"{b}/a" in acs and f"{b}/b" in acs):
                errors.append(f"{a}: split AC needs both /a and /b rows")

    # Check 4: phase exit map.
    xi = {h: i for i, h in enumerate(x_header)}
    exit_map: dict[int, set[str]] = {}
    for row in x_rows:
        cell = row[xi["Phase"]].strip()
        if not cell.isdigit():
            continue
        exit_map[int(cell)] = set(AC_ID.findall(row[1]))
    if set(exit_map) != set(range(1, 9)):
        errors.append(f"phase exit map must cover phases 1-8, got {sorted(exit_map)}")
    listed: dict[str, list[int]] = {}
    for p, ids in exit_map.items():
        for a in ids:
            if a not in acs:
                errors.append(f"phase {p} exit lists {a}, which has no AC row (clause id mismatch?)")
                continue
            listed.setdefault(a, []).append(p)
            ap = acs[a]["phase"]
            if not isinstance(ap, int):
                errors.append(f"phase {p} exit lists deferred AC {a}")
            elif ap > p:
                errors.append(f"phase {p} exit depends on {a}, which is built in later phase {ap}")
    for a, e in acs.items():
        if isinstance(e["phase"], int):
            if a not in listed:
                errors.append(f"{a}: built in phase {e['phase']} but listed at no phase exit")
            elif e["phase"] not in listed[a]:
                errors.append(f"{a}: built in phase {e['phase']} but listed only at phases {listed[a]}")

    # Spec cross-check: never assert later than the spec's phase.
    for a, sp in SPEC_PHASE.items():
        if a not in acs:
            errors.append(f"spec lists {a} at phase {sp} but the AC table has no such row")
            continue
        ap = acs[a]["phase"]
        if not isinstance(ap, int):
            errors.append(f"{a}: spec asserts it at phase {sp} but it is deferred")
        elif ap > sp:
            errors.append(f"{a}: asserted at phase {ap}, later than the spec's phase {sp}")
        elif ap < sp:
            warnings.append(f"{a}: asserted at phase {ap}, earlier than the spec's phase {sp} (allowed)")

    r1_req = sum(1 for e in reqs.values() if e["release"] == "R1")
    r1_ac = sum(1 for e in acs.values() if e["release"] == "R1")
    print(f"R-ids: {len(EXPECTED_R)} expected, {len(seen_r)} found")
    print(f"REQ rows: {len(reqs)} ({r1_req} R1); AC rows incl. clauses: {len(acs)} ({r1_ac} R1)")
    print("Phase exit map: " + ", ".join(f"P{p}={len(exit_map[p])}" for p in sorted(exit_map)))
    return report(errors, warnings)


if __name__ == "__main__":
    sys.exit(main())
