#!/usr/bin/env python3
"""
Check CPS's demographics page for report files (GENERAL / RACE / EL_IEP)
and download any that aren't already in data/raw/.

Adapted from the K1C CPS Demographic project's original scraper notebook.
Run on a schedule by .github/workflows/update-data.yml; also safe to run
by hand (`python3 scripts/scrape_cps.py`).
"""
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CPS_DEMOGRAPHICS_URL = "https://www.cps.edu/about/district-data/demographics/"
REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"


def extract_school_year(filename: str) -> str | None:
    fn = filename.lower()

    m = re.search(r"(20\d{2})\s*[-_]\s*(20\d{2})(?!\d)", fn)
    if m:
        y1, y2 = int(m.group(1)), int(m.group(2))
        start, end = (y1, y2) if y1 <= y2 else (y2, y1)
        return f"{start}-{end}"

    m = re.search(r"(20\d{2})\s*[-_]\s*(\d{2})(?!\d)", fn)
    if m:
        start = int(m.group(1))
        end = 2000 + int(m.group(2))
        if end <= start:
            end = start + 1
        return f"{start}-{end}"

    m = re.search(r"sy(20\d{2})", fn)
    if m:
        end = int(m.group(1))
        return f"{end - 1}-{end}"

    match = re.search(r"fy(\d{2})", fn)
    if match:
        yr = int(match.group(1))
        if yr <= 30:
            return f"{2000 + yr - 1}-{2000 + yr}"

    years = re.findall(r"(20\d{2})", fn)
    if years:
        candidates = [int(y) for y in years if 2000 <= int(y) <= 2035]
        if candidates:
            end = max(candidates)
            return f"{end - 1}-{end}"
    return None


def get_cps_reports(base_url: str = CPS_DEMOGRAPHICS_URL) -> dict[str, str]:
    resp = requests.get(base_url, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    reports = {}
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.endswith((".xls", ".xlsx")):
            continue
        file_url = urljoin(base_url, href)
        filename = Path(href).name
        year_label = extract_school_year(filename)

        fn_lower = filename.lower()
        category = "GENERAL"
        if any(w in fn_lower for w in ["lep", "elp", "iep", "sped"]):
            category = "EL_IEP"
        elif any(w in fn_lower for w in ["racial", "ethnic", "race"]):
            category = "RACE"

        key = f"{category}_{year_label}" if year_label else f"{category}_{filename}"
        reports[key] = file_url
    return reports


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    reports = get_cps_reports()

    new_files = []
    for key, url in reports.items():
        ext = Path(url).suffix
        file_name = f"{key}{ext}"
        file_path = RAW_DIR / file_name

        # If a differently-extensioned copy already exists for this key (e.g.
        # CPS re-published .xls as .xlsx), don't re-download.
        existing = list(RAW_DIR.glob(f"{key}.xls*"))
        if existing:
            continue

        print(f"Downloading {file_name} ...")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        file_path.write_bytes(resp.content)
        new_files.append(file_name)

    if new_files:
        print(f"\n{len(new_files)} new file(s): {', '.join(new_files)}")
    else:
        print("\nNo new files -- data/raw/ already up to date.")

    return new_files


if __name__ == "__main__":
    files = main()
    sys.exit(0)
