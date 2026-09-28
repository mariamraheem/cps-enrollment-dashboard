#!/usr/bin/env python3
"""
Parse the FY2027 CPS school budget overview workbooks (data/raw/budget/*.xlsx)
into docs/data/budget.json -- a per-school per-pupil funding figure next to
that school's own 2025-2026 and 2026-2027 enrollment, so the dashboard can
show how enrollment has moved since the FY2027 budget was built.

Enrollment for both years comes from docs/data/schools.json (the same
demographic-report pipeline every other number on the dashboard uses) rather
than from the budget workbooks' own enrollment columns, so a school's count
here always matches what's shown elsewhere on the site. The workbook's own
enrollment column is used only as a fallback for a school schools.json has no
2025-2026 row for.

This never talks to the network -- run fetch_budget.py first to populate
data/raw/budget/.

Sources (published by CPS, linked from
https://www.cps.edu/about/finance/budget/budget-2027/more-information-2027/):
  - FY27 School Budget Overview - District Managed Schools (Traditional +
    Alt-Spec tabs): mostly FTE staffing allocations, plus two per-pupil
    dollar rates (Need-Based Flexible Funding, Title I).
  - FY27 School Budget Overview - Charter, Contract, ALOP Schools: actual
    per-school dollar totals (tuition / core instructional / non-instructional
    / special ed / facilities), which this script divides by enrollment to
    get a comparable per-pupil rate.

Because the two funding methodologies aren't apples-to-apples, each record
carries a `funding_basis` field the frontend uses to label the number
honestly rather than implying one "total budget" figure across all schools.

School matching: the workbooks identify schools by name, not School ID, and
spelling sometimes drifts from the name used in the demographic-report-based
schools.json (e.g. "CICS Northtown" vs "CICS - NORTHTOWN HS"). NAME_ALIASES
below is a short, manually-verified list of known drift; anything left over
after normalization + aliasing is reported in the `unmatched` list rather
than silently dropped.
"""
import json
import re
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw" / "budget"
DATA_DIR = REPO_ROOT / "docs" / "data"
OUT_JSON = DATA_DIR / "budget.json"

FISCAL_YEAR = "FY2027"
BUDGET_ENROLLMENT_YEAR = "2025-2026"   # Fall 2025 counts the FY27 budget was built on
ACTUAL_ENROLLMENT_YEAR = "2026-2027"   # latest actual year in schools.json, for comparison

# Manually-verified name corrections for workbook spellings that don't survive
# normalization (hyphen/whitespace collapsing) -- found by diffing workbook
# names against schools.json's latest-year names.
NAME_ALIASES = {
    "CICS AVALON": "CICS AVALON/SOUTH SHORE",
    "CICS LLOYD BOND": "CICS BOND",
    "CICS NORTHTOWN": "CICS NORTHTOWN HS",
    "CICS RALPH ELLISON": "CICS ELLISON HS",
    "AHS PASSAGES": "PASSAGES",
    "INSTITUTO JUSTICE AND LEADERSHIP ACADEMY": "INSTITUTO JUSTICE HS",
    "URBAN PREP ENGLEWOOD HS": "URBAN PREP HS",
    "NORTH LAWNDALE CHRISTIANA HS": "NLCP CHRISTIANA HS",
    "NORTH LAWNDALE COLLINS HS": "NLCP COLLINS HS",
    "CAMELOT CHICAGO EXCEL ACADEMY": "CHICAGO EXCEL HS",
    "CAMELOT EXCEL ACADEMY OF ENGLEWOOD": "EXCEL ENGLEWOOD HS",
    "CAMELOT EXCEL ACADEMY OF SOUTHSHORE": "EXCEL SOUTH SHORE HS",
    "CAMELOT EXCEL SOUTHWEST HS": "EXCEL SOUTHWEST HS",
    "SAFE ACHIEVE WEST *": "SAFE ACHIEVE WEST HS",
}

# Rows that are notes/footnotes/rollups rather than individual schools --
# skipped outright rather than reported as unmatched.
SKIP_ROWS = {
    "PROJECTED ADDITIONAL RESOURCES BUDGETED CITYWIDE",
    "YCCS",
    "SAFE ACHIEVE SOUTH *",
}


def norm(s):
    s = str(s or "").strip().upper()
    s = re.sub(r"\s*-\s*", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def load_school_index():
    with open(DATA_DIR / "schools.json") as f:
        schools = json.load(f)
    latest = schools["years"][-1]
    assert latest == ACTUAL_ENROLLMENT_YEAR, f"schools.json latest year is {latest}, expected {ACTUAL_ENROLLMENT_YEAR}"
    by_norm = {}
    actual_enrollment = {}
    budget_year_enrollment = {}
    for r in schools["schools"]:
        if r["year"] == latest:
            by_norm[norm(r["school_name"])] = r["school_id"]
            actual_enrollment[r["school_id"]] = r["total"]
        if r["year"] == BUDGET_ENROLLMENT_YEAR:
            budget_year_enrollment[r["school_id"]] = r["total"]
    with open(DATA_DIR / "school_groups.json") as f:
        groups = json.load(f)
    return by_norm, actual_enrollment, budget_year_enrollment, groups


def match_school_id(raw_name, by_norm):
    key = norm(raw_name)
    if key in SKIP_ROWS:
        return "skip"
    if key in by_norm:
        return by_norm[key]
    alias_key = norm(NAME_ALIASES.get(key, ""))
    if alias_key and alias_key in by_norm:
        return by_norm[alias_key]
    return None


def col_index(header_row, label):
    for i, v in enumerate(header_row):
        if v and str(v).strip() == label:
            return i
    return None


def build_district_managed(by_norm, actual_enrollment, budget_year_enrollment, groups):
    path = RAW_DIR / "fy2027_district_managed.xlsx"
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Traditional"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    header = rows[1]  # row 2 has the actual column labels (row 1 is merged section headers)
    data_rows = rows[2:]

    idx = {
        "name": 0, "type": col_index(header, "School Type"), "network": col_index(header, "Network"),
        "community_area": col_index(header, "Community Area"), "opportunity_index": col_index(header, "Opportunity Index"),
        "fall25_total": col_index(header, "Fall 2025 Total Enrollment"),
        "per_pupil_flex": col_index(header, "Per-Pupil Total For Need-Based Flexible Funding \n(Unadjusted for Floor)"),
        "per_pupil_title1": col_index(header, "Per-Pupil Total For Title I Funding"),
    }

    records, unmatched = [], []
    for r in data_rows:
        name = r[idx["name"]]
        if not name:
            continue
        sid = match_school_id(name, by_norm)
        if sid == "skip":
            continue
        budgeted_enrollment = budget_year_enrollment.get(sid) if sid else None
        if budgeted_enrollment is None:
            budgeted_enrollment = r[idx["fall25_total"]]  # fallback: no 2025-2026 row in schools.json
        per_pupil_flex = r[idx["per_pupil_flex"]] or 0
        per_pupil_title1 = r[idx["per_pupil_title1"]] or 0
        rec = {
            "school_name": str(name).strip(),
            "school_id": sid,
            "school_type": r[idx["type"]],
            "network": r[idx["network"]],
            "community_area": r[idx["community_area"]],
            "opportunity_index": r[idx["opportunity_index"]],
            "budgeted_enrollment": budgeted_enrollment,
            "actual_enrollment": actual_enrollment.get(sid),
            "per_pupil_flex_funding": round(per_pupil_flex, 2) if per_pupil_flex else None,
            "per_pupil_title1_funding": round(per_pupil_title1, 2) if per_pupil_title1 else None,
            "per_pupil_funding": round(per_pupil_flex + per_pupil_title1, 2) if (per_pupil_flex or per_pupil_title1) else None,
            "funding_basis": "district_flex_title1",
        }
        if sid is None:
            unmatched.append(str(name).strip())
        else:
            records.append(rec)
    return records, unmatched


def build_altspec(by_norm, actual_enrollment, budget_year_enrollment):
    path = RAW_DIR / "fy2027_district_managed.xlsx"
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Alt-Spec"]
    rows = list(ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=True))
    header = rows[1]
    data_rows = rows[2:]

    idx = {
        "name": 0, "community_area": col_index(header, "Community Area"), "type": col_index(header, "School Type"),
        "network": col_index(header, "Network"), "fall25_total": col_index(header, "Fall 2025 Total Enrollment"),
        "per_pupil_title1": col_index(header, "Per-Pupil Total For Title I Funding"),
    }
    records, unmatched = [], []
    for r in data_rows:
        name = r[idx["name"]]
        if not name:
            continue
        sid = match_school_id(name, by_norm)
        if sid == "skip":
            continue
        budgeted_enrollment = budget_year_enrollment.get(sid) if sid else None
        if budgeted_enrollment is None:
            budgeted_enrollment = r[idx["fall25_total"]]  # fallback: no 2025-2026 row in schools.json
        per_pupil_title1 = r[idx["per_pupil_title1"]] or 0
        rec = {
            "school_name": str(name).strip(),
            "school_id": sid,
            "school_type": r[idx["type"]],
            "network": r[idx["network"]],
            "community_area": r[idx["community_area"]],
            "budgeted_enrollment": budgeted_enrollment,
            "actual_enrollment": actual_enrollment.get(sid),
            "per_pupil_title1_funding": round(per_pupil_title1, 2) if per_pupil_title1 else None,
            "per_pupil_funding": round(per_pupil_title1, 2) if per_pupil_title1 else None,
            "funding_basis": "district_altspec_title1",
        }
        if sid is None:
            unmatched.append(str(name).strip())
        else:
            records.append(rec)
    return records, unmatched


def build_nondistrict(by_norm, actual_enrollment, budget_year_enrollment, groups):
    path = RAW_DIR / "fy2027_charter_contract_alop.xlsx"
    wb = openpyxl.load_workbook(path, data_only=True)
    records, unmatched = [], []

    def sum_cols(row, idxs):
        return sum((row[i] or 0) for i in idxs if i is not None)

    # -- Charter schools: single dollar total ("Estimated Per Capita Tuition Charge") --
    ws = wb["FY27 Charter Schools"]
    header = [c.value for c in ws[2]]
    idx_name = 0
    idx_network = col_index(header, "Network ") or col_index(header, "Network")
    idx_enr = col_index(header, "FY26 20th Day Enrollment - Semester 1")
    idx_tuition = col_index(header, "Estimated Per Capita Tuition Charge ") or col_index(header, "Estimated Per Capita Tuition Charge")
    for row in ws.iter_rows(min_row=3, values_only=True):
        name = row[idx_name]
        if not name:
            continue
        sid = match_school_id(name, by_norm)
        if sid == "skip":
            continue
        enr = budget_year_enrollment.get(sid) if sid else None
        if enr is None:
            enr = row[idx_enr]  # fallback: no 2025-2026 row in schools.json
        tuition = row[idx_tuition]
        per_pupil = round(tuition / enr, 2) if (tuition and enr) else None
        rec = {
            "school_name": str(name).strip(),
            "school_id": sid,
            "school_type": "Charter",
            "network": row[idx_network],
            "community_area": (groups.get(str(sid)) or {}).get("community_area") if sid else None,
            "budgeted_enrollment": enr,
            "actual_enrollment": actual_enrollment.get(sid),
            "total_funding": round(tuition, 2) if tuition else None,
            "per_pupil_funding": per_pupil,
            "funding_basis": "charter_per_capita_tuition",
        }
        if sid is None:
            unmatched.append(str(name).strip())
        else:
            records.append(rec)

    # -- Contract / ALOP / SAFE: sum of four dollar components --
    ws = wb["FY27 Contract, ALOP, SAFE"]
    header = [c.value for c in ws[2]]
    idx_name = 0
    idx_network = col_index(header, "Network ") or col_index(header, "Network")
    idx_enr = col_index(header, "FY26 20th Day Enrollment - Semester 1")
    comp_idxs = [
        col_index(header, "Core Instructional Funding"),
        col_index(header, "Non-Instructional"),
        col_index(header, "Special Education^") or col_index(header, "Special Education"),
        col_index(header, "Facilities Supplement"),
    ]
    for row in ws.iter_rows(min_row=3, values_only=True):
        name = row[idx_name]
        if not name or not isinstance(row[idx_enr], (int, float)):
            continue  # skip footnote/text rows
        sid = match_school_id(name, by_norm)
        if sid == "skip":
            continue
        enr = budget_year_enrollment.get(sid) if sid else None
        if enr is None:
            enr = row[idx_enr]  # fallback: no 2025-2026 row in schools.json
        total = sum_cols(row, comp_idxs)
        per_pupil = round(total / enr, 2) if (total and enr) else None
        rec = {
            "school_name": str(name).strip(),
            "school_id": sid,
            "school_type": "Contract/ALOP/SAFE",
            "network": row[idx_network],
            "community_area": (groups.get(str(sid)) or {}).get("community_area") if sid else None,
            "budgeted_enrollment": enr,
            "actual_enrollment": actual_enrollment.get(sid),
            "total_funding": round(total, 2) if total else None,
            "per_pupil_funding": per_pupil,
            "funding_basis": "contract_component_sum",
        }
        if sid is None:
            unmatched.append(str(name).strip())
        else:
            records.append(rec)

    return records, unmatched


def main():
    by_norm, actual_enrollment, budget_year_enrollment, groups = load_school_index()
    district_records, district_unmatched = build_district_managed(by_norm, actual_enrollment, budget_year_enrollment, groups)
    altspec_records, altspec_unmatched = build_altspec(by_norm, actual_enrollment, budget_year_enrollment)
    nondistrict_records, nondistrict_unmatched = build_nondistrict(by_norm, actual_enrollment, budget_year_enrollment, groups)

    all_records = district_records + altspec_records + nondistrict_records
    all_records.sort(key=lambda r: r["school_name"])

    out = {
        "fiscal_year": FISCAL_YEAR,
        "budget_enrollment_year": BUDGET_ENROLLMENT_YEAR,
        "actual_enrollment_year": ACTUAL_ENROLLMENT_YEAR,
        "source": "https://www.cps.edu/about/finance/budget/budget-2027/more-information-2027/",
        "schools": all_records,
        "unmatched": sorted(set(district_unmatched + altspec_unmatched + nondistrict_unmatched)),
    }
    with open(OUT_JSON, "w") as f:
        json.dump(out, f)

    print(f"budget.json: {len(all_records)} schools matched "
          f"({len(district_records)} district-managed, {len(altspec_records)} alt-spec, "
          f"{len(nondistrict_records)} charter/contract/ALOP), {len(out['unmatched'])} unmatched")


if __name__ == "__main__":
    main()
