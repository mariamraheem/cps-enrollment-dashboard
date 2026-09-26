#!/usr/bin/env python3
"""
Build a citywide (district-level) enrollment summary time series from CPS's
annual demographic reports (GENERAL / RACE / EL_IEP files).

Reads every file in data/raw/, pulls the district-level totals for that
file's own school year, and writes a single tidy summary to
data/summary.json (used by the dashboard) and data/summary.csv.

CPS has changed these report layouts many times over 25+ years. This
parser handles the layouts CPS has used since roughly 2005 for total
enrollment, since roughly 2010 for the race/ethnicity breakdown, and
since roughly 2013 for the English-learner / IEP / low-income breakdown.
A handful of individual years use older, one-off layouts this script
doesn't recognize -- those are skipped (and logged) rather than guessed
at, which shows up as a small gap in the dashboard's chart rather than a
silently wrong number. See README.md for the exact years affected.
"""
import json
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
# Written straight into docs/ so the GitHub Pages dashboard (docs/index.html)
# can fetch it with a plain relative path.
OUT_JSON = REPO_ROOT / "docs" / "data" / "summary.json"
OUT_CSV = REPO_ROOT / "docs" / "data" / "summary.csv"

RACE_NAME_MAP = {
    "black/african american": "Black",
    "african american": "Black",
    "black": "Black",
    "white": "White",
    "latinx": "Hispanic",
    "hispanic": "Hispanic",
    "hispanic/latino": "Hispanic",
    "asian": "Asian",
    "asian/pacific islander (retired)": "Asian",
    "multi-racial": "Multiracial",
    "multiracial": "Multiracial",
    "native american/alaskan": "NativeAmerican",
    "native american": "NativeAmerican",
    "hawaiian/pacific islander": "HawaiianPacificIslander",
    "middle eastern/northern african": "MENA",
    "not available": "NotAvailable",
}


def year_from_filename(path: Path) -> str | None:
    m = re.search(r"(\d{4})-(\d{4})", path.stem)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def _find_total_after_label(df: pd.DataFrame, label: str = "District Total") -> int | None:
    """Search every cell for `label`; return the first plausible district
    total (a number > 1000) found in that same row."""
    for r in range(len(df)):
        row = df.iloc[r]
        if row.astype(str).str.contains(label, case=False, na=False).any():
            for val in row.tolist():
                try:
                    n = float(val)
                except (TypeError, ValueError):
                    continue
                if n > 100_000:  # CPS district enrollment has stayed in the 300-450k range
                    return int(n)
    return None


def parse_general(path: Path) -> dict | None:
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return None
    for sheet in xl.sheet_names:
        try:
            df = xl.parse(sheet, header=None)
        except Exception:
            continue
        total = _find_total_after_label(df, "District Total")
        if total:
            return {"total_enrollment": total}
    return None


def parse_el_iep(path: Path) -> dict | None:
    try:
        xl = pd.ExcelFile(path)
    except Exception:
        return None
    for sheet in xl.sheet_names:
        if sheet.lower() not in ("district", "citywide"):
            continue
        try:
            df = xl.parse(sheet, header=None)
        except Exception:
            continue
        for r in range(len(df)):
            row = df.iloc[r]
            if not row.astype(str).str.contains("District Total", case=False, na=False).any():
                continue
            nums = []
            for v in row.tolist():
                try:
                    nums.append(float(v))
                except (TypeError, ValueError):
                    pass
            # Expect: [total, el_n, el_pct, swd_n, swd_pct, li_n, li_pct, ...]
            if len(nums) >= 7:
                total, el_n, el_pct, swd_n, swd_pct, li_n, li_pct = nums[:7]
                if el_pct <= 1 and swd_pct <= 1 and li_pct <= 1:  # sanity check: these are fractions
                    return {
                        "el_n": int(el_n),
                        "el_pct": round(el_pct, 4),
                        "swd_n": int(swd_n),
                        "swd_pct": round(swd_pct, 4),
                        "low_income_n": int(li_n),
                        "low_income_pct": round(li_pct, 4),
                    }
    return None


def parse_race(path: Path) -> dict | None:
    """Only handles the modern 'Comparison' sheet layout: two side-by-side
    (Name, blank, N, %) blocks, each headed by a date. Returns None (rather
    than guessing) for older layouts."""
    try:
        df = pd.read_excel(path, sheet_name="Comparison", header=None)
    except Exception:
        return None

    # Find every cell that parses as a date, anywhere in the top ~5 rows.
    date_cells = []  # (row, col, parsed_date)
    for r in range(min(5, len(df))):
        for c in range(df.shape[1]):
            v = df.iat[r, c]
            if pd.isna(v):
                continue
            try:
                d = pd.to_datetime(v)
                date_cells.append((r, c, d))
            except Exception:
                continue
    if not date_cells:
        return None

    date_row, best_col, _ = max(date_cells, key=lambda t: t[2])

    races = {}
    total = None
    for r in range(date_row + 1, len(df)):
        name_col = best_col - 2
        if name_col < 0:
            break
        name = df.iat[r, name_col] if name_col < df.shape[1] else None
        count = df.iat[r, best_col] if best_col < df.shape[1] else None
        if pd.isna(name) and pd.notna(count):
            try:
                c = float(count)
                if c > 1000:
                    total = c
            except (TypeError, ValueError):
                pass
            continue
        if pd.isna(name) or pd.isna(count):
            continue
        name_str = str(name).strip()
        if name_str.lower() not in RACE_NAME_MAP:
            continue  # not a recognized race label -> likely off the modern layout
        key = RACE_NAME_MAP[name_str.lower()]
        try:
            races[key] = races.get(key, 0) + float(count)
        except (TypeError, ValueError):
            continue

    if len(races) < 4:  # too few recognized rows -> probably an older/irregular layout
        return None
    result = {f"race_{k}_n": int(v) for k, v in races.items()}
    if total:
        result["race_total_n"] = int(total)
    return result


PARSERS = {"GENERAL": parse_general, "RACE": parse_race, "EL_IEP": parse_el_iep}


def main():
    years: dict[str, dict] = {}
    skipped = []

    for path in sorted(RAW_DIR.glob("*.xls*")):
        prefix = next((p for p in PARSERS if path.stem.startswith(p + "_")), None)
        parser = PARSERS.get(prefix)
        if parser is None:
            continue
        year = year_from_filename(path)
        if year is None:
            skipped.append((path.name, "no year in filename"))
            continue
        try:
            result = parser(path)
        except Exception as e:
            skipped.append((path.name, f"error: {e}"))
            continue
        if result is None:
            skipped.append((path.name, "layout not recognized (pre-modern report format)"))
            continue
        years.setdefault(year, {"school_year": year})
        years[year].update(result)

    complete_years = {y: d for y, d in years.items() if "total_enrollment" in d}
    ordered = sorted(complete_years.values(), key=lambda d: d["school_year"])

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w") as f:
        json.dump(
            {"last_built": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"), "years": ordered},
            f,
            indent=2,
        )
    if ordered:
        pd.DataFrame(ordered).to_csv(OUT_CSV, index=False)

    print(f"Parsed {len(ordered)} school years into {OUT_JSON}")
    if skipped:
        print(f"\nSkipped {len(skipped)} files (older report layout not recognized -- shows as a gap, not a wrong number):")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")
    return ordered, skipped


if __name__ == "__main__":
    main()
