#!/usr/bin/env python3
"""
Download the raw boundary GeoJSONs used by the dashboard's group-by map
(Community Area, Network, School attendance) from the Chicago Data Portal
and save them, untouched, to data/raw/geo/. build_geo.py then cleans and
merges these into docs/data/geo/*.

Run this only where data.cityofchicago.org is reachable (e.g. in the
GitHub Actions runner) -- it is NOT reachable from some sandboxed dev
environments.
"""
import json
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "raw" / "geo"

# name -> Socrata dataset id. "-Map" suffixed dataset ids on this portal
# reliably return empty geometry/properties (a portal-side quirk, not a
# client error) -- these are all the non-Map, working resource ids.
DATASETS = {
    "cps_geo_community_areas": "igwz-8jzy",  # Boundaries - Community Areas
    "cps_geo_networks_elementary": "pnta-kuqa",  # CPS Elementary Geographic Networks
    "cps_geo_networks_highschool": "aupu-jt2g",  # CPS High School Geographic Networks
    "cps_geo_attendance_elementary": "x72b-38qv",  # CPS Elementary School Attendance Boundaries SY2526
    "cps_geo_attendance_middle": "fyff-53xy",  # CPS Middle School Attendance Boundaries SY2526
    "cps_geo_attendance_highschool": "xg7c-d8rm",  # CPS High School Attendance Boundaries SY2526
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, dataset_id in DATASETS.items():
        url = f"https://data.cityofchicago.org/resource/{dataset_id}.geojson?$limit=5000"
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        n = len(data.get("features", []))
        if n == 0:
            raise RuntimeError(f"{name} ({dataset_id}) returned 0 features -- portal issue?")
        out_path = OUT_DIR / f"{name}.json"
        with open(out_path, "w") as f:
            json.dump(data, f)
        print(f"{name}: {n} features -> {out_path}")


if __name__ == "__main__":
    main()
