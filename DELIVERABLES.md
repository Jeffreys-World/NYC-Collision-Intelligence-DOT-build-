# DELIVERABLES — outstanding work

Updated 2026-08-17 (the bake landed). Branch `build/day-2-eb-and-bake`. 222 tests
pass. See `NEXT-SESSION.md` for the full handoff and the rebuild commands.

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

- [ ] **Re-run the audit's refutation pass** before trusting anything under
  "What the EB audit established" in `NEXT-SESSION.md` beyond the footprint fix.
- [ ] **Decide the ranking unit: cell, or corridor.** The evidence says cell —
  corridor top-decile persistence is 1.007, i.e. no regression to the mean left
  to correct, because independent cell noise cancels when ~66 cells are summed.
  The cell is already §2.1's map unit. This changes §2.7 and `DESIGN.md`, so it
  is a decision, not a refactor. Still undecided.
- [ ] **`data/countermeasures.csv` (§3.2)** — the last blocker on the estimator.
  Costs, CMFs, star ratings, measured setting and a source URL per treatment,
  from the FHWA CMF Clearinghouse. §0.3 #4 forbids inventing a CMF. The seven
  treatments are already named in `app/road_class.py`.
- [ ] **Wire `app/live.py` into the UI** — the module and its 26 offline tests are
  done, but nothing renders it. `st.popover` on the freshness line (§5).

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
