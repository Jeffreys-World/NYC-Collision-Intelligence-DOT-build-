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

## What the EB audit established, so it is not re-litigated

A multi-agent audit ran against the new cell-level fit. **READ THIS CAVEAT
BEFORE USING ANY NUMBER BELOW.** The run did not finish: two of four
investigation lenses returned, and **the adversarial refutation pass never
reported** — the workflow died when the session ended. It was designed so that
no claim would be trusted until a skeptic had tried to kill it, and that step did
not happen.

So the status of the findings is:

- **The footprint defect is solid.** Both completed lenses found it
  independently, and it was then re-measured by hand — see above.
- **Everything else below is single-source and unrefuted.** Treat it as a strong
  lead, not as established fact. Re-check before acting, especially anything
  that would change a published figure.

The journal and all ten agent transcripts are on THIS machine, including the
eight that never reported:

```
~/.claude/projects/-Users-flextop-NYC-Collision-Intelligence-DOT-build-/
  c3536101-fdd3-459e-bf13-95e429bc88f1/subagents/workflows/wf_21b6e422-0df/
```

`journal.jsonl` holds the two completed lens results; the mid-flight agents'
partial work is in the `agent-*.jsonl` files.

### Audited correct — do not re-check
`k = 1/alpha` confirmed against simulated NB draws; the EB identity matches
`mu*(k+y)/(k+mu)` to 2.8e-14; no date leak, no double-count, no label leakage.

### The granularity fix worked, but the rollup undoes it
EB weight is now **0.211** (0.0002 at whole-corridor level), so shrinkage is
real at the cell. But corridor top-decile persistence is **1.007** — no
regression to the mean left at all, because a top-decile corridor averages 66
cells and independent cell noise cancels in the sum. **FIT 1's diagnosis
reappearing one level up.** The cell is already §2.1's map unit; make it the
unit the product ranks and colours, and present the corridor number as a
descriptive rollup rather than as an EB correction.

### EB does win — where theory says it should
Lift by training count, cell level: **+12.6pp at observed==0**, +3.7pp at 1–2,
+1.9pp at 3–5, +2.0pp at 6–10, +1.0pp at 11–25, **+0.2pp at 26+**.

The 39.8% of cells with zero training casualties carry 9.7% of holdout harm and
**raw ranking cannot order them at all**; EB's top decile of them captures
20.24% against 10.02% for random.

**The global top-N metric is structurally incapable of seeing this** — every
cell in the top-5000-by-EB list has ≥10 training casualties (median 16). The
reported ~0pp lift measures EB in the head only, which is the one regime where
theory predicts no effect.

### The test that measures what EB is actually for was never run
Rate-adjusted predicted-vs-actual holdout harm (R = 0.48905):

| | raw | EB |
|---|---|---|
| Cell RMSE | 2.2837 | **2.1855** (−4.30%, CI [3.83, 4.76]) |
| Corridor RMSE | 15.420 | **14.505** (−5.70%) |
| Head over-prediction | +29.0% | **+17.9%** |

Use RMSE, not MAE: MAE is minimised by the conditional median, which for a
sub-1 mean count is exactly 0, so it structurally rewards predicting zero.

### Every quoted lift is inside its own CI on zero
2,000-draw bootstrap: cell top-500 −0.01pp CI [−0.19, +0.18]; top-5000 +0.19pp
CI [−0.04, +0.42]; corridor top-50 +0.03pp CI [−1.66, +1.84]. **The two-decimal
lift table must not be quoted without an interval** — it implies precision an
order of magnitude finer than the data supports.

### The SPF cannot correct within a street
Every covariate is street-level, so mu and w are constant along a street and EB
is provably an order-preserving affine map of `observed` within it — verified
for all 5,091 streets. It can only reorder streets against each other. For a
within-street correction the SPF needs a within-street covariate; **intersection
vs midblock** is the obvious one, and whether it leaks needs deciding on the
record.

### Two smaller ones
- The docstring's "~110m on a side" is wrong: cells are **111m × 84m, ~0.94 ha**.
  The no-offset decision still stands — area varies only 0.62% citywide — but
  the stated reason should be the correct one.
- 10,036 holdout-first cells on already-scored corridors are dropped entirely,
  carrying 6,553 holdout casualties. Scoring them at observed=0 would add the
  pure `w*mu` prior, which is what an SPF is for.

### What may be claimed
Not a top-N lift. The defensible, self-computed claims are: **−4.30% cell RMSE**,
**+12.7pp capture among the tiles raw cannot rank**, and **head over-prediction
cut from +29.0% to +17.9%**. None resembles or borrows the sibling repo's
pedestrian **+18.4pp**, which still must never be quoted here.

---

## TODO, in order

1. **Fix the footprint defect above**, retract the negative corridor lift, and
   add a rate-adjusted RMSE + bootstrap CI to `validate()`.
2. **Re-run the audit's refutation pass**, which never reported. The two lenses
   that did not return were SPF-improvement and the final adjudication. Nothing
   in the "audit established" section except the footprint defect has survived a
   skeptic yet, so verify before acting on it.
3. **Decide the ranking unit.** The evidence says cell, with corridor as a
   descriptive rollup. This changes §2.7 and DESIGN.md, so it is a real decision,
   not a refactor.
4. **THE BAKE — the owner's review checkpoint. STOP AND SHOW THEM.** §6 step 2:
   bake exactly once, carrying `borough_recovered`, `borough_source`, the
   canonical street name and the EB key together. Every re-bake is another
   permanent ~35MB blob in git history. **Do not bake until item 1 is fixed** —
   the EB key is part of the frozen schema.
5. **Update every published figure IN THE SAME COMMIT as the bake.**
   `scripts/verify_figures.py` prints the §0.2 table paste-ready and diffs
   against what the docs claim; it currently passes against
   `crashes_recovered.parquet`. Update together: `CLAUDE_CODE_PROMPT.md` §0.2,
   `README.md`, the `PUBLISHED` dict in that script, and
   **`.github/workflows/tests.yml`, which still asserts exactly 812,315 rows and
   will fail the moment the new Parquet lands.**
6. **`data/countermeasures.csv` (§3.2)** — the last blocker on the estimator.
   One row per treatment with unit cost, CMF, star rating, measured setting and
   a source URL, looked up in the FHWA CMF Clearinghouse. §0.3 #4 forbids
   inventing a CMF, and §3.1's seven treatments are already named in
   `app/road_class.py`. Split road diet from refuge island; daylighting and LPI
   are an order of magnitude cheaper than a road diet.
7. **Wire `app/live.py` into the UI** — the module and its 26 offline tests are
   done; nothing renders it yet. `st.popover` on the freshness line (§5).
8. **Then Days 2–7**: map, telemetry drawer, estimator, PDF export, theme pass,
   deploy.

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
