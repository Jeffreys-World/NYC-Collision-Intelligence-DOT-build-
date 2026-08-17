# NEXT SESSION — pick up here

Written 2026-08-16, end of the session that moved the project to macOS.
Branch: `build/day-2-eb-and-bake`, pushed. **217 tests pass. Working tree clean.**

---

## Read this first: the machine changed, and it cost the whole data layer

The project developed on Windows through 2026-08-16 and now lives on macOS at
`/Users/flextop/NYC-Collision-Intelligence-DOT-build-`. Everything in gitignored
`data/raw/` was gone — the raw pull, the cleaned CSV, the recovered Parquet, the
borough boundaries and the corridor features. The crash pull came back because
`scripts/pull_data.py` existed. The other two did not, because those steps had
only ever happened in somebody's shell.

**That is fixed and must stay fixed.** Every pipeline step is now a committed
script, and the whole chain rebuilds from a bare clone:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt -r requirements-dev.txt

.venv/bin/python scripts/pull_data.py --start-year 2019 --end-year 2026 \
    --out data/raw/crashes_raw.csv                       # 848,742 rows, ~2 min
.venv/bin/python scripts/clean_crash_data.py \
    data/raw/crashes_raw.csv data/raw/crashes_cleaned    # 848,739 rows
.venv/bin/python scripts/fetch_boundaries.py \
    --out data/raw/boroughs_water-included.geojson       # verifies 468.3 sq mi
.venv/bin/python scripts/recover_borough.py \
    --crashes data/raw/crashes_cleaned.csv \
    --boundaries data/raw/boroughs_water-included.geojson \
    --out data/raw/crashes_recovered.parquet             # all 3 gates must pass
.venv/bin/python scripts/build_corridor_features.py \
    --units "/Users/flextop/Downloads/jeffrey-portfolio/nyc-crash-risk-forecast/data/cache/units-*.parquet" \
    --out data/raw/corridor_features.parquet
.venv/bin/python scripts/fit_eb.py
.venv/bin/python scripts/verify_figures.py --source data/raw/crashes_recovered.parquet
```

**The interpreter is `.venv/bin/python`.** Any surviving `.venv/Scripts/python`
or `py` is a Windows leftover — fix it, don't work around it. Never write `py`
in a script or workflow; ubuntu runners have no `py` launcher.

**The sibling repo `nyc-crash-risk-forecast` is at
`~/Downloads/jeffrey-portfolio/nyc-crash-risk-forecast`** and is STRICTLY
READ-ONLY — the copy at `~/nyc-crash-risk-forecast` is an empty stub, don't use
it. Read its `data/cache/units-*.parquet` for LION attributes; change nothing.

Reproduced on macOS, matching the Windows run: 848,742 pulled, 848,739 cleaned,
agreement 99.87%, highway recovery 100.00%, Belt Pkwy 11,482 of 11,482, and
468.3 sq mi of water-included boundary measured independently.

---

## THE ONE THING TO DO FIRST — a real defect, found by two auditors independently

**`scripts/fit_eb.py` computes a corridor's EB estimate on a different footprint
from the observed count it is compared against.** `eb_estimate` sums only cells,
and a cell needs coordinates; `observed` and `holdout` are full-corridor totals
including the 65,965 crashes (7.8%) that carry a street but no coordinate.

Re-measured directly rather than taken on trust — every figure below reproduced:

```
corridor observed            248,856
corridor observed_in_cells   230,357
FOOTPRINT GAP                 18,499   (7.4%)
eb_estimate sum              230,357   <-- identical to observed_in_cells
  limited-access  n=  37   obs  40,949   gap 7,149  = 17.5%
  surface         n=5054   obs 207,907   gap 11,350 =  5.5%
```

`eb_estimate` summing to **exactly** `observed_in_cells` is the proof: citywide,
net real shrinkage is ~0 and the entire observed-to-estimate gap is missing
coordinates. And the loss is concentrated on exactly the roads §2.6 is about —
17.5% of limited-access corridors' training harm against 5.5% for surface.

**On Belt Pkwy, coverage loss is 686 casualties and real shrinkage is 26** — 96%
of the apparent "EB correction" on the city's worst corridor is missing
coordinates wearing an EB label. That is precisely the failure §2.7 forbids,
arriving by a new route.

It also fully explains the negative corridor lift now in the project record.
Holding the estimator fixed and changing only the baseline's footprint:

| top-N | as reported | with a coverage-fair baseline |
|---|---|---|
| 100 | −0.09pp | −0.00pp |
| 250 | −0.27pp | **+0.04pp** |
| 500 | −0.60pp | −0.00pp |

**Retract the negative corridor figure — it was never a property of EB.** The
honest corridor result is ~0.00pp, which is a different claim.

Fix: add `observed_in_cells` / `holdout_in_cells` and rank and validate on
those, so the benchmark covers the same crashes the estimate does. Separately,
the product must not present a corridor estimate that silently omits 17% of its
harm — label the coverage, per §4.2.

---

## What the EB audit established — UPDATED 2026-08-17, most of this is now
## verified against the shipped pipeline, not single-source audit hearsay

The original multi-agent audit (2026-08-16) never finished — its adversarial
refutation pass died when the session ended. Rather than re-run that exact
workflow, the footprint fix (`c44ddc5`) rewrote `scripts/fit_eb.py` to compute
several of the audit's findings directly and print them on every run —
bootstrap CIs, rate-adjusted RMSE, the SPF-only comparison, and a live
low-coverage warning list. That makes them reproducible by anyone who runs
the script, which is a stronger form of verification than a single audit
agent's claim. Today (2026-08-17) the script was re-run and several of the
remaining claims were independently re-checked directly against the current
data. Status per finding:

- **The footprint defect: FIXED**, not just diagnosed. See the fix section
  above.
- **Confirmed by direct re-measurement today, 2026-08-17** (see below): the
  EB-weight-vs-rollup finding, the low-count SPF-ordering guard, the
  rate-adjusted RMSE win, the bootstrap CIs, and the within-street
  order-preserving-affine-map claim (checked against all 4,221 multi-cell
  streets in the current data — zero exceptions).
- **Still genuinely open, not re-run**: the SPF-improvement investigation
  (whether an intersection-vs-midblock covariate would fix the within-street
  limitation) and a full independent adjudication pass. These were the two
  lenses the original audit's workflow never reached, and nothing below
  substitutes for them.

The original journal and all ten agent transcripts still survive on this
machine if the full original findings text is wanted:

```
~/.claude/projects/-Users-flextop-NYC-Collision-Intelligence-DOT-build-/
  c3536101-fdd3-459e-bf13-95e429bc88f1/subagents/workflows/wf_21b6e422-0df/
```

### Audited correct — do not re-check
`k = 1/alpha` confirmed against simulated NB draws; the EB identity matches
`mu*(k+y)/(k+mu)` to 2.8e-14; no date leak, no double-count, no label leakage.

### RANKING UNIT DECIDED 2026-08-17: cell, not corridor
EB weight is **0.211** at the cell (0.0002 at whole-corridor level before the
fix), so shrinkage is real at the cell but the rollup used to erase it —
independent cell noise cancels when a corridor's ~66 cells are summed. The
cell is already §2.1's map unit, so `CLAUDE_CODE_PROMPT.md` §2.7 and this
decision now say: rank and colour by the cell, present the corridor number as
a descriptive rollup. Not a refactor — a decision that's been made and
written down.

### EB does win — where theory says it should (re-run 2026-08-17, numbers moved)
Lift by training count, cell level, current data: **+14.61pp at observed==0**,
+4.15pp at 1–2, +1.88pp at 3–5, +2.81pp at 6–10, +1.18pp at 11–25, **+0.20pp at
26+**. (Was +12.6/+3.7/... on the pre-footprint-fix data — direction and shape
unchanged, magnitudes shifted because the training/holdout population moved
with the fix and the extended pull.)

39.8% of cells carry zero training casualties (unchanged) and raw ranking
cannot order them at all. `scripts/fit_eb.py`'s "vs mu" column at that stratum
reads **+0.00** — the printed, live confirmation of the guard: at
`observed == 0`, `eb_estimate = mu/(1+mu/k)` is strictly increasing in `mu`, so
EB's ordering there is identical to the SPF's. The low-count lift is real but
belongs to the SPF, not to EB specifically.

### The RMSE test — shipped, not just proposed. Current numbers, re-run 2026-08-17
Rate-adjusted predicted-vs-actual holdout harm (R = 0.48905):

| | raw | SPF alone | EB |
|---|---|---|---|
| Cell RMSE | 2.2837 | 3.0023 | **2.1855** |
| Corridor RMSE (coverage-fair) | 15.3353 | 35.2974 | **13.3907** |

SPF alone is worse than raw at both levels — the EB gain is not just the SPF
term. `validate()` also prints MAE, which EB loses on exactly as predicted
(minimised by the conditional median, which is 0 for a sub-1 mean count).

### Every quoted lift ships with its own CI now — re-run 2026-08-17
`scripts/fit_eb.py` prints a 95%-CI bootstrap column on every top-N row.
Current numbers: cell top-500 −0.01pp CI[−0.10,+0.16] (straddles 0); cell
top-5000 **+0.19pp CI[+0.02,+0.37]** (does not straddle 0 — the one lift that's
statistically distinguishable from zero); every corridor-level top-N (50/100/
250/500) straddles zero. The retraction stands: no corridor-level lift is
established. The cell-level top-5000 result is the one number in this whole
document with a CI that clears zero.

### The SPF cannot correct within a street — CONFIRMED 2026-08-17 against current data
Checked directly: of 4,221 streets with more than one scored cell, **zero**
have a non-constant `spf_prediction` or `eb_weight` across their cells. mu and
w are provably constant per street, so EB is an order-preserving affine map of
`observed` within it — it can only reorder streets against each other, never
correct within one. For a within-street correction the SPF needs a
within-street covariate; **intersection vs midblock** is the obvious one, and
whether it leaks still needs deciding on the record. **This specific
investigation — whether adding that covariate helps — is the one piece of the
original audit that is still genuinely undone.**

### One number changed, one is still open
- Cell size (111m × 84m, ~0.94 ha) was already fixed in the footprint-fix
  commit's docstrings.
- Holdout-first cells dropped: **13,308** cells first seen in holdout on the
  current (extended, footprint-fixed) data — was 10,036 on the older pull.
  Same phenomenon, still not fixed: these cells are dropped entirely rather
  than scored at `observed=0` with the pure `w*mu` prior, which is what an SPF
  is for. Still on the TODO list.

### Bridge-shaped hole — now labelled in the product, not just documented
`scripts/fit_eb.py` prints a live low-coverage warning list on every run (75
corridors currently under 50% coordinate coverage — Brooklyn Bridge 0.05,
Willis Ave Bridge 0.02, Manhattan Bridge 0.11, several bridges/tunnels/short
service roads). As of the 2026-08-17 UI work this is now surfaced in
`app/streamlit_app.py`'s drawer and ranked table, not just in this file — see
`tests/test_corridor_table.py`, which also pins a real bug the first cut of
that label had (it double-counted ~1,131 never-matched minor streets that
happen to carry a coverage ratio; fixed same day).

### What may be claimed
Not a corridor-level top-N lift. The defensible, self-computed claims,
re-verified 2026-08-17: **−4.30% cell RMSE**, **+12.7pp capture among the
cells raw cannot rank** (39.8% zero-training-count cells, now measured as
+14.61pp head-of-stratum lift), and **head over-prediction cut from +29.0% to
+17.9%**, plus the one statistically-clear cell-level lift: **+0.19pp at
top-5000, CI[+0.02,+0.37]**. None resembles or borrows the sibling repo's
pedestrian **+18.4pp**, which still must never be quoted here.

---

## TODO, in order — UPDATED 2026-08-17

Items 1–7 below are **done**. What's left:

1. **The SPF-improvement investigation** — the one piece of the original audit
   never re-run. Whether an intersection-vs-midblock covariate fixes the
   within-street limitation (§ above), and whether it leaks, needs deciding on
   the record.
2. **IBM Plex self-hosting (DESIGN.md §2)** — woff2 files not committed;
   `.streamlit/config.toml`'s `fontFaces` block is deliberately still commented
   out rather than pointed at files that don't exist.
3. **10,036→13,308 holdout-first cells still dropped**, not scored at
   `observed=0` with the pure SPF prior. Still open, not yet fixed in
   `scripts/fit_eb.py`.
4. **Deploy to Streamlit Community Cloud**, then re-run the WCAG 2.2 AA pass
   against the live URL (`TODOS.md` — the audit needs the deployed app, not
   localhost).
5. **Radius selection, victim-type breakdown, XLSX export** — deferred by
   design, see `TODOS.md`.

<details>
<summary>Done — 2026-08-17</summary>

1. ~~Fix the footprint defect~~ — done, `c44ddc5`.
2. ~~Re-run the audit's refutation pass~~ — most claims independently
   re-verified against the shipped, re-run pipeline (see above); the
   SPF-improvement lens specifically is carried forward as open item 1 above.
3. ~~Decide the ranking unit~~ — done: cell, corridor is a rollup. §2.7
   rewritten.
4. ~~THE BAKE~~ — done, `c64b747` (dry-run) + `ba8faa5` (`--commit`).
5. ~~Update every published figure in the same commit as the bake~~ — done,
   `ba8faa5`.
6. ~~`data/countermeasures.csv`~~ — done, `90c129f`. Every CMF real and
   FHWA-sourced; daylighting's missing-CMF gap left honest (CMF 1.00, no
   rating) rather than guessed.
7. ~~Wire `app/live.py` into the UI~~ — done, `90c129f`, `st.popover` on the
   freshness line.
8. Days 2–7 (map, drawer, estimator, PDF export) — first working version done,
   `90c129f`. Theme pass partial (tokens applied, fonts not self-hosted yet).
   Deploy still open, see item 4 above.

</details>

---

## Done this session

| What | Where |
|---|---|
| Whole data layer rebuilt on macOS, all gates passing | `data/raw/` |
| Boundary fetch, verified by area not by dataset id | `scripts/fetch_boundaries.py` |
| LION corridor features, reproducible | `scripts/build_corridor_features.py` |
| §3.1 curated list, loader, 63 roads, 40 tests | `data/limited_access.csv`, `app/road_class.py` |
| §1.2 runtime feed check, 4 outcomes, 0 new deps | `app/live.py` |
| Figure verification, catches drift | `scripts/verify_figures.py` |
| EB refit at cell granularity (weight 0.211 vs 0.0002) | `scripts/fit_eb.py` |
| §1.2 rewritten for the owner's hybrid; TODOS entry reversed | spec, `TODOS.md` |
| `statsmodels`, `scipy`, `pyogrio` finally recorded | `requirements-dev.txt` |

Two findings worth keeping from the supporting work:

- **The sibling repo's `is_highway` is exactly `rw_type != 1`** — it marks 3,861
  alleys, 723 pedestrian paths and 708 driveways as highways. Never use it as a
  limited-access flag. LION types 2/3/4/9 separate the populations properly.
- **Counting ramps was not optional.** With ramps excluded from the numerator
  but their length left in the denominator, Van Wyck Expy scored 0.494 and a
  majority rule called the Van Wyck a surface street — §3.1's named failure,
  produced by the classifier built to prevent it.

---

## Environment notes

- **The TLS interception is gone** with the Windows machine. `requests` works
  normally; `truststore` is still installed and still harmless.
- **No app token, and none needed.** 848,742 rows pulled anonymously in 2.2 min
  at ~6,500 rows/s with no 429. There is still no `.env`.
- **`uv` is the toolchain** (`uv venv`, `uv pip install`), not bare pip.
- The feed has not moved: newest crash **2026-06-11**, re-verified live today at
  HTTP 200 in 0.72s. Every §0.1 rule stands — the banned words, and no
  elapsed-days figure anywhere.
