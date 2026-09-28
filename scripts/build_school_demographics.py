#!/usr/bin/env python3
"""
Parse the per-school "Schools" sheet of the latest RACE_*.xlsx and
EL_IEP_*.xlsx demographic reports into docs/data/school_demographics.json --
a race/ethnicity, English learner, IEP, and low-income breakdown for every
school, for the dashboard's School Profiles "Student mix" section.

CPS's per-school breakdown reports only started including a "Schools" sheet
in 2016-2017 (earlier years only have district/network-level rollups), so
this always uses the single latest year available rather than building a
time series -- the school-level Enrollment Trends chart already covers years
back to 2016-2017 for the total-enrollment figure alone.

This never talks to the network -- the RACE_*/EL_IEP_* files are fetched by
scrape_cps.py as part of the normal weekly update.
"""
import json
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_JSON = REPO_ROOT / "docs" / "data" / "school_demographics.json"

# Canonical race/ethnicity categories, in the fixed display order the
# frontend uses. CPS renamed and split a few of these between the pre-2022
# and current report layout (e.g. "African American" -> "Black/African
# American", "Asian/Pacific Islander (Retired)" split into "Asian" +
# "Hawaiian/Pacific Islander" + "Middle Eastern/Northern African") -- this
# only reads the latest year, but the map is kept broad so it degrades
# gracefully if CPS renames a category again next year.
RACE_NAME_MAP = {
    "white": "White",
    "black/african american": "Black",
    "african american": "Black",
    "black": "Black",
    "latinx": "Hispanic",
    "hispanic": "Hispanic",
    "hispanic/latino": "Hispanic",
    "asian": "Asian",
    "asian/pacific islander (retired)": "Asian",
    "multi-racial": "Multiracial",
    "multiracial": "Multiracial",
    "mulit-racial": "Multiracial",  # CPS's own typo in some older workbooks
    "native american/alaskan": "NativeAmerican",
    "native american": "NativeAmerican",
    "hawaiian/pacific islander": "HawaiianPacificIslander",
    "middle eastern/northern african": "MENA",
    "not available": "NotAvailable",
}
RACE_CATEGORY_ORDER = [
    "White", "Black", "Hispanic", "Asian", "Multiracial",
    "NativeAmerican", "HawaiianPacificIslander", "MENA", "NotAvailable",
]
RACE_CATEGORY_LABELS = {
    "White": "White", "Black": "Black/African American", "Hispanic": "Hispanic/Latino",
    "Asian": "Asian", "Multiracial": "Multiracial", "NativeAmerican": "Native American/Alaskan",
    "HawaiianPacificIslander": "Hawaiian/Pacific Islander", "MENA": "Middle Eastern/Northern African",
    "NotAvailable": "Not available",
}

EL_IEP_NAME_MAP = {
    "bilingual": "el", "state english learners": "el",
    "sped": "iep", "students with ieps": "iep",
    "free/reduced lunch": "low_income", "low income": "low_income",
}

INFO_LABELS = {"School ID", "School Name", "Network", "Governance", "School Type", "Community Area", "Total"}


def year_from_filename(path: Path) -> str | None:
    m = re.search(r"(\d{4})-(\d{4})", path.stem)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def norm_label(s) -> str:
    """Collapses whitespace (CPS's workbooks wrap some category headers with
    an embedded newline, e.g. "Native American/\\n Alaskan") and the space
    that leaves next to a slash, so lookups match regardless of wrapping."""
    s = re.sub(r"\s+", " ", str(s or "")).strip().lower()
    return re.sub(r"\s*/\s*", "/", s)


def latest_file(prefix: str) -> Path | None:
    candidates = []
    for path in RAW_DIR.glob(f"{prefix}_*.xls*"):
        year = year_from_filename(path)
        if year:
            candidates.append((year, path))
    if not candidates:
        return None
    return max(candidates, key=lambda t: t[0])[1]


def find_header_cols(df: pd.DataFrame):
    """Two-row merged header: row 0 has category names spanning a (No,
    Pct)-style column pair, row 1 has the actual per-column sub-labels
    (School ID / School Name / ... / No / Pct or N / %). Returns
    (info_cols: {label: col_idx}, metric_cols: [(category_label, no_idx, pct_idx)]).
    Reads labels rather than hardcoded positions so it survives CPS
    reordering or adding a column."""
    row0 = [str(v).strip() if pd.notna(v) else "" for v in df.iloc[0].tolist()]
    row1 = [str(v).strip() if pd.notna(v) else "" for v in df.iloc[1].tolist()]

    info_cols = {}
    metric_cols = []
    i, n = 0, len(row1)
    while i < n:
        if row1[i] in INFO_LABELS:
            info_cols[row1[i]] = i
            i += 1
            continue
        cat = row0[i]
        if cat:
            no_idx = i
            pct_idx = i + 1 if i + 1 < n else None
            metric_cols.append((cat, no_idx, pct_idx))
            i += 2
            continue
        i += 1
    return info_cols, metric_cols


def parse_race(path: Path):
    xl = pd.ExcelFile(path)
    df = xl.parse("Schools", header=None)
    info_cols, metric_cols = find_header_cols(df)
    sid_col, name_col, total_col = info_cols.get("School ID"), info_cols.get("School Name"), info_cols.get("Total")
    if sid_col is None or name_col is None:
        return {}

    # Map each metric column to a canonical race key, skipping any we don't recognize.
    resolved = []
    for cat, no_idx, pct_idx in metric_cols:
        key = RACE_NAME_MAP.get(norm_label(cat))
        if key:
            resolved.append((key, no_idx, pct_idx))

    out = {}
    for r in range(2, len(df)):
        sid = df.iat[r, sid_col]
        if pd.isna(sid):
            continue  # e.g. the "District Total" rollup row
        try:
            sid = str(int(sid))
        except (TypeError, ValueError):
            continue
        total = df.iat[r, total_col] if total_col is not None else None
        race = {}
        for key, no_idx, pct_idx in resolved:
            n = df.iat[r, no_idx] if no_idx < df.shape[1] else None
            pct = df.iat[r, pct_idx] if (pct_idx is not None and pct_idx < df.shape[1]) else None
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            try:
                pct = round(float(pct), 4)
            except (TypeError, ValueError):
                pct = None
            if n:
                race[key] = {"n": n, "pct": pct}
        out[sid] = {"total": int(total) if pd.notna(total) else None, "race": race}
    return out


def parse_el_iep(path: Path):
    xl = pd.ExcelFile(path)
    df = xl.parse("Schools", header=None)
    info_cols, metric_cols = find_header_cols(df)
    sid_col, total_col = info_cols.get("School ID"), info_cols.get("Total")
    if sid_col is None:
        return {}

    resolved = []
    for cat, no_idx, pct_idx in metric_cols:
        key = EL_IEP_NAME_MAP.get(norm_label(cat))
        if key:
            resolved.append((key, no_idx, pct_idx))

    out = {}
    for r in range(2, len(df)):
        sid = df.iat[r, sid_col]
        if pd.isna(sid):
            continue
        try:
            sid = str(int(sid))
        except (TypeError, ValueError):
            continue
        rec = {}
        total = df.iat[r, total_col] if total_col is not None else None
        for key, no_idx, pct_idx in resolved:
            n = df.iat[r, no_idx] if no_idx < df.shape[1] else None
            pct = df.iat[r, pct_idx] if (pct_idx is not None and pct_idx < df.shape[1]) else None
            try:
                rec[f"{key}_n"] = int(n)
            except (TypeError, ValueError):
                continue
            try:
                rec[f"{key}_pct"] = round(float(pct), 4)
            except (TypeError, ValueError):
                pass
        if rec:
            rec["total"] = int(total) if pd.notna(total) else None
            out[sid] = rec
    return out


def main():
    race_path = latest_file("RACE")
    el_iep_path = latest_file("EL_IEP")
    if not race_path or not el_iep_path:
        print("Missing RACE_*.xlsx or EL_IEP_*.xlsx in data/raw/ -- nothing to do.")
        return

    race_year = year_from_filename(race_path)
    el_iep_year = year_from_filename(el_iep_path)
    race_by_id = parse_race(race_path)
    el_iep_by_id = parse_el_iep(el_iep_path)

    all_ids = set(race_by_id) | set(el_iep_by_id)
    schools = {}
    for sid in all_ids:
        rec = {}
        r = race_by_id.get(sid)
        if r and r["race"]:
            rec["total"] = r["total"]
            rec["race"] = r["race"]
        e = el_iep_by_id.get(sid)
        if e:
            rec.setdefault("total", e.get("total"))
            for k in ("el_n", "el_pct", "iep_n", "iep_pct", "low_income_n", "low_income_pct"):
                if k in e:
                    rec[k] = e[k]
        if rec:
            schools[sid] = rec

    out = {
        "race_year": race_year,
        "el_iep_year": el_iep_year,
        "race_categories": RACE_CATEGORY_ORDER,
        "race_category_labels": RACE_CATEGORY_LABELS,
        "schools": schools,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(out, f)

    print(f"school_demographics.json: {len(schools)} schools "
          f"(race from {race_path.name}, EL/IEP/low-income from {el_iep_path.name})")


if __name__ == "__main__":
    main()
