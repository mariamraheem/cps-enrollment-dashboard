#!/usr/bin/env python3
"""
Download CPS's own school-profile roster (long/official school names,
governance, ESB sub-district + representative, grades served) from
www.cps.edu's public school-profile API and save a compact extract to
data/raw/school_profiles_raw.json. build_school_names.py then turns this
into docs/data/school_names.json for the dashboard.

Run this only where www.cps.edu is reachable (e.g. in the GitHub Actions
runner) -- like fetch_budget.py, it is NOT reachable from some sandboxed
dev environments.
"""
import json
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "raw" / "school_profiles_raw.json"

API_URL = "https://www.cps.edu/api/schoolprofile/allschoolprofiles"

# Only the fields the dashboard actually uses -- the full API response
# carries 150+ fields per school (test scores, admissions contacts, etc.)
# that have nothing to do with enrollment.
FIELD_MAP = {
    "schoolID": "id",
    "schoolShortName": "short",
    "schoolLongName": "long",
    "schoolType": "type",
    "governance": "gov",
    "network": "net",
    "geographicNetwork": "geoNet",
    "primaryCategory": "cat",
    "neighborhood": "hood",
    "ersbDistrict": "esbDist",
    "ersbRepresentative": "esbRep",
    "gradesOfferedReadable": "grades",
}


def main():
    resp = requests.get(API_URL, headers={"Accept": "application/json"}, timeout=60)
    resp.raise_for_status()
    records = resp.json()

    compact = [
        {short: rec.get(long) for long, short in FIELD_MAP.items()}
        for rec in records
    ]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(compact, f)

    print(f"school_profiles_raw.json: {len(compact)} schools -> {OUT_PATH}")


if __name__ == "__main__":
    main()
