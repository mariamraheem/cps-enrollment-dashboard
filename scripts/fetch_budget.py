#!/usr/bin/env python3
"""
Download the FY2027 CPS school budget overview workbooks used by the
dashboard's budget tab and save them, untouched, to data/raw/budget/.
build_budget.py then parses and joins these into docs/data/budget.json.

Run this only where www.cps.edu is reachable (e.g. in the GitHub Actions
runner) -- it is NOT reachable from some sandboxed dev environments.
"""
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "raw" / "budget"

# CPS re-publishes these at the same URLs each budget cycle; the filenames
# encode the fiscal year, so this will need bumping to fy2028_* etc. next
# year (see https://www.cps.edu/about/finance/budget/ for the current link).
FILES = {
    "fy2027_district_managed.xlsx": "https://www.cps.edu/globalassets/cps-pages/about-cps/finance/budget/budget-2027/docs/fy2027_budget_overview_district_managed_schools.xlsx",
    "fy2027_charter_contract_alop.xlsx": "https://www.cps.edu/globalassets/cps-pages/about-cps/finance/budget/budget-2027/docs/fy2027-budget-overview-charter-contract-alop-schools.xlsx",
}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        out_path = OUT_DIR / name
        with open(out_path, "wb") as f:
            f.write(resp.content)
        print(f"{name}: {len(resp.content)} bytes -> {out_path}")


if __name__ == "__main__":
    main()
