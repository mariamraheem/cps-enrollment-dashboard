# CPS Enrollment Dashboard

An auto-updating dashboard of Chicago Public Schools' district-wide and
school-level enrollment, built from CPS's public [20th-day demographic
reports](https://www.cps.edu/about/district-data/demographics/) (total
enrollment, race/ethnicity, English learners, students with disabilities,
and low income).

**Live dashboard:** https://mariamraheem.github.io/cps-enrollment-dashboard/

The dashboard has four tabs: **Overall Enrollment** (total + grade-band
trends, year-over-year comparison, data table), **Race / Ethnicity**
(composition over time, per-group trend, year-over-year comparison, data
table), **EL / IEP / Low Income** (share-of-enrollment trends, year-over-year
comparison, data table), and **School-Level Declines** (pick any two years
and a top-N size to see the schools with the largest enrollment changes,
then drill into a single school's full trend).

## How it works

A GitHub Action runs weekly (Mondays, and any time from the *Actions* tab via
"Run workflow"):

1. `scripts/scrape_cps.py` checks CPS's demographics page for report files
   (`GENERAL_*`, `RACE_*`, `EL_IEP_*`) and downloads any school year that
   isn't already in `data/raw/`.
2. `scripts/build_summary.py` reads every file in `data/raw/`, pulls each
   year's district-wide totals (overall, by grade band, by race/ethnicity,
   and EL/IEP/low-income), and writes `docs/data/summary.json` (and a `.csv`
   copy).
3. `scripts/build_schools.py` reads every `GENERAL_*` file and writes
   `docs/data/schools.json`, a per-school enrollment time series used by the
   School-Level Declines tab.
4. If anything changed, the workflow commits the new raw file(s) and the
   rebuilt data files, then redeploys `docs/` to GitHub Pages.

No step here needs secrets or credentials &mdash; CPS's report page is public.

## Data coverage

CPS has changed these report layouts several times over 25+ years.
`build_summary.py` recognizes:

- **Total enrollment** &mdash; 2005&ndash;2006 onward (gap: 2008&ndash;2009, which used a
  one-off per-school layout with no district-total row)
- **Grade-band breakdown** (Pre-K / Kindergarten / Elementary / Middle /
  High) &mdash; 2016&ndash;2017 onward
- **Race/ethnicity breakdown** &mdash; 2010&ndash;2011 onward (1999&ndash;2010 used several
  different layouts; not yet automated)
- **English learner / IEP / low-income breakdown** &mdash; 2013&ndash;2014 onward

`build_schools.py` recognizes the per-school layout from **2016&ndash;2017
onward**.

Skipped years aren't guessed at or estimated &mdash; they just don't appear in
the data files, which shows up as a gap in the dashboard's line charts rather
than a silently wrong number. Extending a parser to an older layout means
adding a case to the relevant function in `scripts/build_summary.py` or
`scripts/build_schools.py` and re-running it against the files already in
`data/raw/`.

**Known upstream data issue:** CPS's own `EL_IEP_2019-2020.xls` file is a
duplicate of the 2016&ndash;2017 report (its internal header literally reads
"20th Day 2016-2017", and every value matches that year exactly). This
dashboard reproduces CPS's published number rather than guessing at a
correction &mdash; if CPS republishes a corrected 2019&ndash;2020 file, re-run
`scrape_cps.py` after deleting the stale file from `data/raw/`.

## Repo layout

```
data/raw/             Original CPS report files (.xls/.xlsx), one per year per report
docs/                 Published to GitHub Pages
  index.html          The dashboard (loads docs/data/*.json client-side)
  data/summary.json   Generated -- don't hand-edit
  data/schools.json   Generated -- don't hand-edit
scripts/
  scrape_cps.py        Downloads new report files from cps.edu
  build_summary.py     Parses data/raw/ into docs/data/summary.json (+ .csv)
  build_schools.py     Parses data/raw/GENERAL_*.xlsx into docs/data/schools.json
.github/workflows/
  update-data.yml      The weekly scrape -> build -> commit -> deploy job
```

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python3 scripts/scrape_cps.py     # fetch any new report files
python3 scripts/build_summary.py  # rebuild docs/data/summary.json
python3 scripts/build_schools.py  # rebuild docs/data/schools.json

python3 -m http.server 8000 --directory docs   # preview the dashboard
```

## Background

This project automates part of the CPS Demographic data pipeline originally
built and maintained by hand at Kids First Chicago (K1C), including the
`enrollment_trends_app.py` and `enrollment_decline_app.py` Streamlit apps
this dashboard's Overall Enrollment and School-Level Declines tabs are
modeled on &mdash; see that project's `raw data`, `clean data`, and `script`
folders for the fuller, hand-maintained cleaning work this dashboard's
automated pipeline doesn't replace.
