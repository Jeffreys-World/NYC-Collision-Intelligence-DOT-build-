# NYC Collision Intelligence (DOT build)

A chronic-risk prioritisation tool for NYC DOT transit and safety engineers, built on
the NYPD Motor Vehicle Collisions dataset. Not an incident-response dashboard — the
feed lags reporting by weeks, and the product is framed around multi-year patterns
that the lag does not weaken.

**Status:** Day 0. Data layer seeded and verified; no UI yet.

## What it does that other NYC crash maps do not

Every standard borough view silently drops the 261,117 crashes with no recorded
borough — and those rows carry 830 of the city's 1,877 traffic deaths, **44.2%**.
This tool includes them, recovers a borough for the 213,246 that carry coordinates,
and shows the share on every corridor. On highways that share runs 92–98%.

It also ranks by Empirical Bayes expected harm rather than raw observed counts, so
the ranking is not distorted by regression to the mean. Observed figures stay
labelled observed; anything predictive is labelled expected.

## Data

`data/processed/crashes.parquet` — 812,315 rows, 2019-01-01 to 2025-12-31, committed
so the deployed app has no runtime data dependency.

| Measure | Value |
|---|---|
| Rows | 812,315 |
| Rows with casualties | 275,066 (33.9%) |
| Total deaths | 1,877 |
| Crashes with no borough | 261,117 (32.1%) |
| Deaths in rows with no borough | 830 (44.2%) |
| Fatality rate, unlabeled vs labeled | 3.179 vs 1.899 per 1,000 (1.67×) |

Every figure re-verified against the Parquet on 2026-08-15. The pipeline emits
corridor-level figures to `data/processed/corridor_fixture.csv`; they are
deliberately not written into prose, because the previous version of the spec
carried twelve hand-copied corridor counts and none of them reproduced.

## Setup

Python 3.12. On this machine it is reachable as `py`, not `python` — the `python`
on PATH is the Microsoft Store stub. Never write `py` in a script or workflow;
ubuntu runners have no `py` launcher.

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -r requirements-dev.txt
.venv/Scripts/python -m pytest -q
```

`requirements.txt` is runtime-only and is what Streamlit Community Cloud installs.
`requirements-dev.txt` adds geopandas and friends for the offline borough recovery,
which runs on a laptop and bakes its output into the Parquet. The geo stack is never
deployed.

## Documents

| File | What it is |
|---|---|
| `CLAUDE_CODE_PROMPT.md` | The build spec. Amended by an engineering review and a design review; carries the review report at the end. |
| `DESIGN.md` | UI source of truth. Colour semantics, typography, layout, accessibility target. |
| `TODOS.md` | Deliberately deferred work, with the reason for each cut. |

## Provenance

The data layer, SQL seam and pull/clean scripts are seeded from
[Motor-Vehicle-Collisions---Crashes-Dashboard](https://github.com/Jeffreys-World/Motor-Vehicle-Collisions---Crashes-Dashboard),
where they were QA-hardened against real bugs. Carried over rather than rewritten;
what was dropped in the port is noted at the top of `app/data.py`.
