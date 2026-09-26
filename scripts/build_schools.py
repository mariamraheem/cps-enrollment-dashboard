#!/usr/bin/env python3
"""
Build a per-school enrollment time series (School ID, School Name, Year,
Total) from every GENERAL_*.xlsx/.xls file in data/raw/, for the dashboard's
school-level decline-analysis view.

Only covers years whose sheet matches the modern header-row layout (the
same one build_summary.py's parse_general looks for) -- older years are
skipped the same way, and don't appear in the output.
"""
import json
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_JSON = REPO_ROOT / "docs" / "data" / "schools.json"


def year_from_filename(path: Path) -> str | None:
    m = re.search(r"(\d{4})-(\d{4})", path.stem)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _header_row(df: pd.DataFrame) -> int | None:
    for r in range(min(5, len(df))):
        vals = set(str(v).strip() for v in df.iloc[r].tolist())
        if "Total" in vals and "School Name" in vals:
            return r
    return None


def extract_schools(path: Path, year: str) -> list[dict]:
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return []

    for sheet in xl.sheet_names:
        try:
            df = xl.parse(sheet, header=None)
        except Exception:
            continue
        header_row = _header_row(df)
        if header_row is None:
            continue

        headers = [str(v).strip() for v in df.iloc[header_row].tolist()]
        try:
            id_col = headers.index("School ID")
            name_col = headers.index("School Name")
            total_col = headers.index("Total")
        except ValueError:
            continue

        rows = []
        for r in range(header_row + 1, len(df)):
            name = df.iat[r, name_col]
            if pd.isna(name) or "district total" in str(name).lower():
                continue
            sid = df.iat[r, id_col]
            total = df.iat[r, total_col]
            try:
                total = float(total)
            except (TypeError, ValueError):
                continue
            if total <= 0:
                continue
            try:
                sid = int(sid)
            except (TypeError, ValueError):
                sid = str(sid)
            rows.append({"school_id": sid, "school_name": str(name).strip(), "year": year, "total": int(total)})
        if rows:
            return rows
    return []


def main():
    all_rows = []
    skipped = []
    for path in sorted(RAW_DIR.glob("GENERAL_*.xls*")):
        year = year_from_filename(path)
        if year is None:
            continue
        rows = extract_schools(path, year)
        if rows:
            all_rows.extend(rows)
        else:
            skipped.append(path.name)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    years_covered = sorted(set(r["year"] for r in all_rows))
    with open(OUT_JSON, "w") as f:
        json.dump({"years": years_covered, "schools": all_rows}, f)

    print(f"Wrote {len(all_rows)} school-year rows across {len(years_covered)} years to {OUT_JSON}")
    if skipped:
        print(f"Skipped (older layout): {', '.join(skipped)}")


if __name__ == "__main__":
    main()
