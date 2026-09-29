#!/usr/bin/env python3
"""
Turn data/raw/school_profiles_raw.json (from fetch_school_names.py) into
docs/data/school_names.json -- a school_id -> official/long name (plus a
few other CPS-profile fields) lookup for the dashboard's School Profile
and search, which otherwise only have CPS's short/abbreviated names.

Skipped entirely if the raw file isn't present (e.g. fetch_school_names.py
couldn't reach www.cps.edu this run) so it never wipes out a previously
built file.
"""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = REPO_ROOT / "data" / "raw" / "school_profiles_raw.json"
OUT_PATH = REPO_ROOT / "docs" / "data" / "school_names.json"


def main():
    if not RAW_PATH.exists():
        print(f"{RAW_PATH} not found -- skipping (leaving school_names.json as-is).")
        return

    with open(RAW_PATH) as f:
        records = json.load(f)

    out = {}
    for rec in records:
        sid = rec.get("id")
        if sid is None:
            continue
        sid = str(int(sid))
        long_name = (rec.get("long") or "").strip()
        if not long_name:
            continue
        out[sid] = {
            "long_name": long_name,
            "short_name": (rec.get("short") or "").strip() or None,
            "governance": rec.get("gov") or None,
            "primary_category": rec.get("cat") or None,
            "grades": rec.get("grades") or None,
            "esb_district": (rec.get("esbDist") or "").strip().upper() or None,
            "esb_representative": rec.get("esbRep") or None,
        }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(out, f)

    print(f"school_names.json: {len(out)} schools with a long name (source: cps.edu school-profile API)")


if __name__ == "__main__":
    main()
