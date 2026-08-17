# DELIVERABLES — outstanding work

Updated 2026-08-16 (end of the macOS migration session). Branch
`build/day-2-eb-and-bake`. 217 tests pass. See `NEXT-SESSION.md` for the full
handoff and the rebuild commands.

## One honest caveat, and one retraction

- [ ] **The EB model has a real defect, and it is the top of the list.** A
  corridor's `eb_estimate` is summed over geocoded cells only, but is compared
  against an `observed` count that includes the 7.8% of crashes carrying a street
  and no coordinate. 18,499 of 248,856 training casualties (7.4%) are invisible
  to EB, concentrated on limited-access roads (17.5% against 5.5% for surface).
  `eb_estimate` sums to *exactly* `observed_in_cells`, which proves net citywide
  shrinkage is ~0 and the whole gap is coverage. On Belt Pkwy the split is 686
  casualties of coverage loss against 26 of real shrinkage — 96% of the apparent
  correction is missing coordinates wearing an EB label, which is the §2.7
  failure arriving by a new route.

- [ ] **Retract the negative corridor lift.** The −0.27pp / −0.60pp figures in
  the project record are the footprint handicap, not a property of Empirical
  Bayes. On a coverage-fair baseline they are −0.00pp / +0.04pp / −0.00pp. The
  honest corridor claim is "no measurable difference", which is a different
  statement from "EB is worse".

- [ ] **The EB audit never finished.** The refutation pass did not report, so
  every finding except the footprint defect is single-source and unverified. The
  journal and all ten agent transcripts survive on this machine —
  `NEXT-SESSION.md` has the path.

## Top of the list, in order

- [ ] **Fix the footprint defect** — add `observed_in_cells` / `holdout_in_cells`,
  rank and validate on them, and label coverage in the product so a corridor
  estimate never silently omits 17% of its harm (§4.2).
- [ ] **Add the validation that measures what EB is for** — rate-adjusted RMSE
  and a bootstrap CI. Every lift currently quoted to two decimals sits inside its
  own confidence interval on zero. Use RMSE, not MAE: MAE is minimised by the
  conditional median, which is 0 for a sub-1 mean count, so it rewards predicting
  zero.
- [ ] **Decide the ranking unit: cell, or corridor.** The evidence says cell —
  corridor top-decile persistence is 1.007, i.e. no regression to the mean left
  to correct, because independent cell noise cancels when ~66 cells are summed.
  The cell is already §2.1's map unit. This changes §2.7 and `DESIGN.md`, so it
  is a decision, not a refactor.
- [ ] **THE BAKE — the owner's review checkpoint. Stop and show them.** §6 step 2:
  bake exactly once, carrying `borough_recovered`, `borough_source`, canonical
  street name and the EB key together. **Blocked on the defect above**, because
  the EB key is part of the schema being frozen.
- [ ] **Update all 18 figures + the CI gate in the same commit as the bake.**
  `scripts/verify_figures.py` prints the §0.2 table paste-ready and diffs it
  against the docs. `.github/workflows/tests.yml` still asserts exactly 812,315
  rows and will fail the moment the new Parquet lands.
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
