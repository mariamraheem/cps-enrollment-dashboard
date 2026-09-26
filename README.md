# CPS Enrollment Dashboard

An auto-updating dashboard of Chicago Public Schools' district-wide enrollment,
built from CPS's public [20th-day demographic reports](https://www.cps.edu/about/district-data/demographics/)
(total enrollment, race/ethnicity, English learners, students with disabilities,
and low income).

**Live dashboard:** `https://<your-username>.github.io/<repo-name>/` (set up
GitHub Pages once, per the setup steps below, and this URL goes live).

## How it works

A GitHub Action runs weekly (Mondays, and any time from the *Actions* tab via
"Run workflow"):

1. `scripts/scrape_cps.py` checks CPS's demographics page for report files
   (`GENERAL_*`, `RACE_*`, `EL_IEP_*`) and downloads any school year that
   isn't already in `data/raw/`.
2. `scripts/build_summary.py` reads every file in `data/raw/`, pulls each
   year's district-wide totals, and writes `docs/data/summary.json` (and a
   `.csv` copy) &mdash; the tidy time series the dashboard reads.
3. If anything changed, the workflow commits the new raw file(s) and the
   rebuilt summary, then redeploys `docs/` to GitHub Pages.

No step here needs secrets or credentials &mdash; CPS's report page is public.

## Data coverage

CPS has changed these report layouts several times over 25+ years.
`build_summary.py` recognizes:

- **Total enrollment** &mdash; 2005&ndash;2006 onward (gap: 2008&ndash;2009, which used a
  one-off per-school layout with no district-total row)
- **Race/ethnicity breakdown** &mdash; 2010&ndash;2011 onward (1999&ndash;2010 used several
  different layouts; not yet automated)
- **English learner / IEP / low-income breakdown** &mdash; 2013&ndash;2014 onward

Skipped years aren't guessed at or estimated &mdash; they just don't appear in
`summary.json`, which shows up as a gap in the dashboard's line charts rather
than a silently wrong number. Extending the parser to an older layout means
adding a case to the relevant `parse_*()` function in `scripts/build_summary.py`
and re-running it against the files already in `data/raw/`.

## Repo layout

```
data/raw/            Original CPS report files (.xls/.xlsx), one per year per report
docs/                Published to GitHub Pages
  index.html         The dashboard (loads data/summary.json client-side)
  data/summary.json  Generated -- don't hand-edit
scripts/
  scrape_cps.py       Downloads new report files from cps.edu
  build_summary.py    Parses data/raw/ into docs/data/summary.json
.github/workflows/
  update-data.yml     The weekly scrape -> build -> commit -> deploy job
```

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 scripts/scrape_cps.py     # fetch any new report files
python3 scripts/build_summary.py  # rebuild docs/data/summary.json

python3 -m http.server 8000 --directory docs   # preview the dashboard
```

## One-time GitHub setup

1. **Enable Pages:** repo Settings -> Pages -> Build and deployment -> Source:
   **GitHub Actions**. (The included workflow deploys `docs/` automatically
   from then on.)
2. That's it &mdash; the first scheduled run (or a manual "Run workflow" from the
   Actions tab) will build and publish the dashboard.

## Background

This project automates part of the CPS Demographic data pipeline originally
built and maintained by hand at Kids First Chicago (K1C) &mdash; see that
project's `raw data`, `clean data`, and `script` folders for the fuller,
school-level cleaning work (grade-level detail, network aggregates, etc.)
that this dashboard's district-level summary doesn't replace.
