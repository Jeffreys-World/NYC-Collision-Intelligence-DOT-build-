# DELIVERABLES — outstanding work

Updated 2026-08-17 (first working UI landed). Branch `build/day-2-eb-and-bake`.
234 tests pass. See `NEXT-SESSION.md` for the full handoff and the rebuild
commands.

## Closed today, after the bake

- [x] **Ranking unit decided: cell, not corridor.** CLAUDE_CODE_PROMPT.md §2.7
  rewritten — cell-level EB is the ranking/colour unit, corridor is a
  descriptive rollup. Only the audited claims are quoted (−4.30% cell RMSE,
  +12.7pp capture where raw can't rank, head over-prediction 29.0%→17.9%);
  the sibling repo's +18.4pp is explicitly barred from this doc now.
- [x] **`data/countermeasures.csv` (§3.2) — no invented CMFs.** All 7
  treatments in `app/road_class.py` have a row, each CMF sourced from the FHWA
  CMF Clearinghouse (facid + star rating + source URL) or left honestly
  unrated. Daylighting has **no dedicated CMF anywhere in the Clearinghouse**
  — held at CMF 1.00 rather than borrowing a proxy, with NYC DOT's own report
  quoted saying so. `tests/test_estimator.py` asserts every non-1.0 CMF
  carries a rating and a source.
- [x] **First working UI** — `app/streamlit_app.py`: freshness line +
  `st.popover` wired to `app/live.py`, sticky control bar, map (pydeck
  ColumnLayer, cell-level EB colour/height), drawer with a correctable
  road-class control, ranked corridor table (the accessibility equivalent),
  countermeasure estimator (branches highway vs. surface, editable CMF/cost,
  §3.3 caveat block), PDF export (`app/pdf_export.py`, reportlab). Verified
  live in a browser: Belt Pkwy → highway branch (guardrail/HFST only),
  Atlantic Ave → surface branch (5 treatments), both drawers reproduce the
  §2.3 fixture exactly. `app/theme.py` carries the DESIGN.md §1 tokens; IBM
  Plex self-hosting is still not done (no woff2 files committed).
- [x] **Known gap, not a bug:** headless test browsers without a GPU can't
  create a WebGL context, so the map can't be screenshotted in this sandbox.
  Real browsers (including Streamlit Community Cloud's client-side render)
  have working WebGL — confirmed the map's data layer is correct via the
  ranked table and drawer, which pull from the same query.

## Closed since the last update

- [x] **The EB footprint defect is fixed.** Corridor rows now carry
  `observed_in_cells` / `holdout_in_cells` / `coverage`, and validation compares
  like with like. The negative corridor lift is retracted — on a coverage-fair
  baseline every corridor lift straddles zero (top-250 −0.27pp → +0.04pp,
  top-500 −0.60pp → −0.02pp).
- [x] **Rate-adjusted RMSE + bootstrap CI added to `validate()`.** EB wins the
  error test raw ranking cannot: cell RMSE 2.1855 vs raw 2.2837, corridor 13.3907
  vs 15.3353. Every lift is now printed with its bootstrap interval.
- [x] **THE BAKE.** `scripts/bake.py --commit` ran 2026-08-17.
  `data/processed/crashes.parquet` is now 848,739 rows / 36 columns / 2019-01-01
  to 2026-06-11, carrying `borough_recovered`, `borough_source`, `canonical`,
  `canonical_source`, `lat_c`, `lon_c`. The §2.3 corridor fixture is pinned in
  `tests/test_corridor_fixture.py` and its 5 previously-skipped tests now run.
- [x] **All figures + the CI gate updated in the same commit as the bake.**
  §0.2 in `CLAUDE_CODE_PROMPT.md`, `README.md`, and
  `.github/workflows/tests.yml` (812,315 → 848,739) all moved together;
  `scripts/verify_figures.py`'s `PUBLISHED` dict already matched the new figures.
  All 18 reproduce exactly.

## One thing still open from the audit

- [ ] **The EB audit never finished.** The refutation pass did not report, so
  every finding except the footprint defect (now fixed above) is single-source
  and unverified. The journal and all ten agent transcripts survive on this
  machine — `NEXT-SESSION.md` has the path.

## Top of the list, in order

- [x] **Re-run the audit's refutation pass** — mostly done differently than
  planned: rather than re-running the exact multi-agent workflow, the
  footprint fix made several claims directly reproducible from
  `scripts/fit_eb.py`'s own output, and the rest were independently
  re-checked against current data on 2026-08-17 (within-street
  order-preservation confirmed on all 4,221 multi-cell streets; RMSE,
  bootstrap CIs and the low-count SPF-ordering guard all re-run with current
  numbers). See `NEXT-SESSION.md`. **One piece is still genuinely open**: the
  SPF-improvement investigation (would an intersection-vs-midblock covariate
  fix the within-street limitation?) — that lens of the original audit never
  ran and nothing above substitutes for it.
- [ ] **IBM Plex self-hosting (DESIGN.md §2)** — woff2 files not committed yet;
  `.streamlit/config.toml`'s `fontFaces` block stays commented out until they
  land, on purpose (a broken font path silently falls back to the system
  stack, which is the exact failure self-hosting exists to prevent).
- [ ] **Radius selection, victim-type breakdown, XLSX export** — all
  deliberately deferred, see `TODOS.md`.
- [ ] **Deploy to Streamlit Community Cloud** and re-verify the WCAG 2.2 AA
  pass against the live URL (`TODOS.md`) — the accessibility audit needs the
  deployed app, not localhost.
- [ ] **Bridge/tunnel coverage gap is labelled in code comments but not yet in
  the UI** — the map will read the Brooklyn Bridge (coordinate coverage 0.05)
  as near-harmless unless this is surfaced. §4.2 territory.

## Closed this session

- [x] **The data layer rebuilds from a bare clone.** Every step is a committed
  script now; `scripts/fetch_boundaries.py` and
  `scripts/build_corridor_features.py` replace two steps that had only ever
  existed in a shell and did not survive the move to macOS.
- [x] **`data/limited_access.csv` (§3.1)** — 63 roads, a loader returning a frozen
  `RoadClass`, and 40 tests. Checked against a signal not used to build it: the
  listed roads average 0.948 unlabeled share against 0.221 for surface.
- [x] **The EB refit at cell granularity.** Shrinkage is real now — weight 0.211
  against 0.0002 at whole-corridor level. The model is not finished, but the
  granularity question is settled and the arithmetic is audited correct
  (`k = 1/alpha` confirmed against simulated draws; the EB identity matches to
  2.8e-14; no date leak, no double-count, no label leakage).
- [x] **`app/live.py` (§1.2)** — the runtime feed check, four outcomes so a
  failure can never read as an empty success, zero new runtime dependencies, and
  §0.1's banned words enforced by a CI copy test.
- [x] **Spec §1.2 rewritten** for the owner's hybrid decision; the matching
  `TODOS.md` entry was reversed with its history rather than deleted.
- [x] **`scripts/verify_figures.py`** — recomputes all 18 figures and diffs them
  against what the docs claim. It caught two that had already drifted between two
  pulls taken on the same day, because NYPD amends published records.

## Two things flagged but deliberately left undone

- [ ] **Decide on `nyc-crash-risk-forecast`** — still untouched and still
  read-only. Changing its label would change its published headline; owner's call.
  Its `is_highway` column is exactly `rw_type != 1` and must never be used as a
  limited-access flag.
- [ ] **Exposure / AADT normalisation** — a genuine data gap, not a shortcut. See
  `TODOS.md`. The §3.3 caveat stays mandatory wherever the tool ranks or
  recommends spending.
