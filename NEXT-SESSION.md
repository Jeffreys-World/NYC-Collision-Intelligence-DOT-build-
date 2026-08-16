# NEXT SESSION — pick up here

Written 2026-08-16 at the end of a session that ran out of budget mid-task.
Branch: `build/day-1-street-normalisation`. 85 tests pass. Working tree clean
except `data/eb_corridors.csv`, which is **known-bad output — delete it**.

---

## The one decision that reshaped the project

The owner changed the architecture mid-session. Spec §1.2 said *"There is no
runtime API path in the deployed app."* That is **no longer true** — the owner
chose **option C**, a hybrid:

1. The committed Parquet is extended **offline** to cover through 2026-06-11.
2. The deployed app gains a **real runtime Socrata call**: a user-triggered
   "check for newer records" action that hits the API, shows what came back, and
   reports honestly.

**§1.2 of `CLAUDE_CODE_PROMPT.md` still contradicts this and has not been
updated.** Fix that early or the spec will mislead you.

### What did NOT change

The feed still lags. Measured live on 2026-08-16, anonymously, no token:

| Query | Result |
|---|---|
| Newest crash on the API | **2026-06-11** |
| Crashes in the last 30 days | **0** |
| Anonymous access | HTTP 200 in 0.3–1.2s, no 429 |

So a live *query* is not live *data*. Every §0.1 rule stands: the banned words,
and no elapsed-days figure anywhere.

---

## Done and committed

| Commit | What |
|---|---|
| `239338f` | Day 1 — street normalisation, alias table, tests |
| `15d6e78` | Borough recovery passing all three gates + two pull-path bug fixes |
| `b4a5968` | Two silent normalisation defects + the EB granularity finding |

**Data pipeline state** (all in gitignored `data/raw/`, none of it committed):

```
crashes_raw.csv           848,742 rows   2019-01-01 .. 2026-06-11, all columns
crashes_cleaned.csv       848,739 rows
crashes_recovered.parquet 848,739 rows   + borough_recovered, borough_source
corridor_features.parquet   8,931 corridors, LION attrs joined by canonical name
boroughs_water-included.geojson          verified 468.3 sq mi vs clipped 302.1
```

Borough recovery result: **578,930 reported · 221,640 recovered · 48,169
unrecoverable**. All three §6 gates pass — agreement 99.87%, highway recovery
100.00% on coordinate-carrying rows, Belt Pkwy 11,482 of 11,482.

---

## TODO, in order

### 1. Finish the EB model — `scripts/fit_eb.py` is UNFINISHED

It runs and writes `data/eb_corridors.csv`, but **that output is unusable**: it
is raw observed harm wearing an EB label, which §2.7 forbids.

Measured: fitting at whole-corridor level gives EB equal to observed to four
significant figures (Belt Pkwy observed 5,936, EB 5,935.4) and **+0.00pp lift**.
Correct statistics, wrong granularity — a corridor with thousands of casualties
already has a reliable observed count, so the shrinkage weight collapses to
0.0002.

**The fix, already written into the file's docstring:** the unit becomes one
canonical street within one ~110m cell, `(canonical, round(lat,3), round(lon,3))`
— the same grid §2.1 bins the map on. Most cells carry 0–5 casualties, which is
the regime EB is for. A corridor's estimate is the **sum of its cells'** shrunken
estimates. Needs no LION geometry and no spatial join.

Concretely: rewrite `load()` to group by that key, drop the log-length offset
(cells are equal-size), fit, then sum back to corridor. Print capture at **both**
cell and corridor level.

**The label is ALL-MODE casualties**, not pedestrian — this is why we are
refitting at all. The sibling repo's published **+18.4pp, CI +17.5 to +19.3**
belongs to its pedestrian label and **must not be quoted** for this model.
Compute our own or quote none.

`nyc-crash-risk-forecast` is **read-only**. The owner was asked and did not
authorise modifying it. Read its `data/cache/units-*.parquet` for LION road
attributes; change nothing there.

### 2. Recover the live-path workflow output

A multi-agent workflow (`wf_a2f27d72-f3f`) was designing and implementing
`app/live.py` when the session ended. **It had not yet written files to the
repo.** Its journal is at:

```
~/.claude/projects/d--GitHub-Projects-NYC-Collision-Intelligence--DOT-build-/
  d57fcee3-1857-4033-80de-ad82513eb1c1/subagents/workflows/wf_a2f27d72-f3f/journal.jsonl
```

Read that first — the synthesized contract in there is good and worth keeping.
Highlights it had already landed on: inject the HTTP getter so tests run offline;
`app/live.py` must not import duckdb or touch the `Source` seam; a copy test that
greps every user-visible string for banned words; and the rule that a failed
call must never look like a successful call that found nothing. Re-run or
re-implement from that contract rather than starting cold.

### 3. Build `data/limited_access.csv` (§3.1)

Needed for the estimator's highway/surface branch. **Do not gate on "≥90%
unlabeled"** — the spec measured that failing. Note the sibling repo's
`is_highway` flag is *not* a limited-access flag: it marks ALLEY, PEDESTRIAN
PATH, DRIVEWAY and GREENWAY as highways. Useful as a cross-check, not a source.

### 4. THE BAKE — this is the owner's review checkpoint

**Stop and show them before committing it.** §6 step 2: bake exactly once,
carrying `borough_recovered`, `borough_source`, canonical street name and the EB
key together. Every re-bake is another permanent ~35MB blob in git history.

### 5. Update every published figure — they are all stale

Extending coverage to 2026-06-11 invalidated all 18 verified figures. Recomputed
2026-08-16 on 848,739 rows:

| Figure | Old (2019–2025) | New (2019–2026-06-11) |
|---|---|---|
| Rows | 812,315 | **848,739** |
| Rows with casualties | 275,066 (33.9%) | **290,352 (34.2%)** |
| Rows with no coordinates | 65,272 | **66,420** |
| Crashes with no borough | 261,117 (32.1%) | **269,809 (31.8%)** |
| Total deaths | 1,877 | **1,945** |
| Deaths in borough-less rows | 830 (44.2%) | **861 (44.3%)** |
| Fatality rate unlabeled vs labeled | 3.179 / 1.899 (1.67×) | **3.191 / 1.872 (1.70×)** |
| Unlabeled carrying coordinates | 213,246 (81.7%) | **221,657 (82.2%)** |
| Distinct `vehicle_type_code1` | 1,380 | **1,430** |

The §2.6 central claim **survives and strengthens**: 44.3%, and the fatality
ratio rises to 1.70×.

Must be updated together, in the same commit as the bake:
`CLAUDE_CODE_PROMPT.md` §0.2, `README.md`, and
**`.github/workflows/tests.yml`, which still asserts exactly 812,315 rows and
will fail the moment the new Parquet lands.**

### 6. Then resume the spec's build order

Days 2–7: map, telemetry drawer, estimator, PDF export, theme pass, deploy.
`requirements.txt` will need an HTTP client for the live path, and its comment
block currently argues the opposite — rewrite it or the file contradicts itself.

---

## Environment gotchas that cost time today

- **Python is `.venv/Scripts/python`.** `py` works on this machine; never write
  it in a script or workflow — ubuntu runners have no `py` launcher.
- **This network intercepts TLS.** `requests` carries its own certifi bundle and
  fails with `CERTIFICATE_VERIFY_FAILED`; `urllib` uses the Windows store and
  works. `truststore` is installed now and `scripts/pull_data.py` announces it if
  it goes missing again.
- **The app token env var** is read as either `SOCRATA_APP_TOKEN` or
  `NYC_OPEN_DATA_APP_TOKEN` now. There is still **no `.env`** — the owner never
  added a token, and everything so far ran fine anonymously.
- Deps added to `.venv` this session and **not yet in any requirements file**:
  `truststore`, `geopandas`, `shapely`, `pyproj`, `pyogrio`, `statsmodels`,
  `scipy`. The geo and stats stacks are dev-only and belong in
  `requirements-dev.txt`, never in `requirements.txt`.
