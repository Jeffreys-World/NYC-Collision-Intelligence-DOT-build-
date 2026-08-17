# System prompt for Claude Code — NYC Collision Intelligence (DOT build)

You are a principal full-stack engineer and enterprise UI/UX designer. Build a
production-ready, highly polished web application for Department of
Transportation transit and safety engineers, using the NYC Open Data NYPD Motor
Vehicle Collisions dataset. Target: a live executive demo in one week, deployed
on Streamlit Community Cloud.

---

## 0. Read this first — verified facts and hard constraints

Every figure below was measured directly against
`data/processed/crashes.parquet` on 2026-08-17, the day of the §6 step 2 bake. Do
not recompute them from memory, and do not soften them.

### 0.1 The data is NOT real-time. Never imply that it is.

The NYPD collision feed lags roughly **67 days** — the most recent crash on the
public API is 2026-06-11. The committed Parquet covers **2019-01-01 to
2026-06-11**.

This is a police-reporting pipeline, not a fixable API problem. Therefore:

- **BANNED words** anywhere in UI copy, comments or docs: "real-time", "live
  crash data", "current", "today's crashes", "up to the minute".
- **REQUIRED**: a persistent freshness line, visible on every screen. Both halves
  must be facts that cannot rot: **derive coverage from the data** via
  `date_bounds()`, and state the feed date as a fixed historical fact —
  `Complete through {max_crash_date} · NYPD feed last carried 2026-06-11, pulled 2026-08-08`.
  Never hardcode the coverage date, and never render an elapsed-days figure. "~65
  days" was true only on 2026-08-15; it grows by one every day and is wrong the
  moment the demo slips. `app/data.py:47` already carries this rule — /qa filed
  ISSUE-002 against exactly this pattern on 2026-08-09.
- Frame the product as **chronic-risk prioritisation**, not incident response.
  Multi-year patterns are stable; the lag does not weaken them. Say so.

A DOT engineer in the room will ask whether this is current. Handled well, that
question becomes a credibility moment. Handled badly, it ends the demo.

### 0.2 Verified dataset figures

| Measure | Value |
|---|---|
| Rows (2019–2026-06-11) | 848,739 |
| Rows with casualties (injured > 0 OR killed > 0) | 290,354 (**34.2%**) |
| Rows with no coordinates | 66,419 |
| Crashes with no `borough` value | 269,810 (**31.8%**) |
| Total deaths | 1,945 |
| Deaths in rows with no borough | 861 (**44.3%**) |
| Fatality rate, unlabeled vs labeled | 3.191 vs 1.872 per 1,000 (**1.70×**) |
| Unlabeled rows **carrying coordinates** | 221,658 (82.2% of unlabeled) |
| Distinct raw `vehicle_type_code1` values | 1,430 |

Every figure above reproduces exactly against the committed Parquet — run
`scripts/verify_figures.py` to check. These are the §6 step 2 bake figures
(848,739 rows, 2019-01-01 to 2026-06-11), not the earlier 812,315-row slice.

**Read the last row carefully.** 221,658 is a *has-coordinates* count, not a
*will-match-a-polygon* count. It is an upper bound on recovery, never an
acceptance criterion. See §6 step 2.

### 0.3 Non-negotiables

1. **Streamlit, not React.** Do not introduce Next.js, Vercel, TypeScript, SWR,
   React Query or React Error Boundaries.

   **This repo starts by seeding from a proven foundation.** The working Python +
   DuckDB + Parquet codebase with a passing test suite lives in a *different*
   GitHub repo — `Jeffreys-World/Motor-Vehicle-Collisions---Crashes-Dashboard`.
   Commit 1 here copies `app/data.py`, `sql/`, `scripts/`, `tests/`,
   `requirements.txt` and `data/processed/crashes.parquet` into this repo. Only
   after that does "do not rewrite it" mean anything — before it, there is
   nothing here to preserve.

   Do **not** build inside the dashboard repo: it auto-redeploys `main` to
   Streamlit Community Cloud, so pushing DOT code there replaces a live
   portfolio app.
2. **Never overwrite the `borough` column.** Recovered values go in
   `borough_recovered`, with `borough_source` ∈ {`reported`, `recovered`,
   `unrecoverable`}.
3. **Fallbacks must be loud, never seamless.** See §4.2.
4. **No fabricated figure may be rendered as fact.** See §3.2.
5. **Exposure is not available.** Crash counts are not adjusted for traffic
   volume. One visible caveat wherever the tool ranks or recommends spending.

---

## 1. Data integration

### 1.1 Primary source: the committed Parquet

Read `data/processed/crashes.parquet` via DuckDB. This is the demo path. It is
fast, offline, and cannot fail on stage.

### 1.2 Secondary source: the Socrata API — offline refresh AND a live check

**Changed by the owner on 2026-08-16. This section previously read "There is no
runtime API path in the deployed app." That is no longer true.** The owner chose
a hybrid, and both halves are required:

1. **Offline.** The committed Parquet is extended by `scripts/`, on a laptop, to
   cover 2019-01-01 through 2026-06-11 — the whole of what the feed carries.
   This remains the demo path (§1.1): fast, offline, and it cannot fail on
   stage. *(The pipeline through `crashes_recovered.parquet` covers that range
   as of 2026-08-16; the committed Parquet itself is re-baked at §6 step 2,
   which is the owner's review checkpoint and has not happened yet.)*
2. **Runtime.** The deployed app gains **one** network call: a user-triggered
   *"check for newer records"* action that queries the API, shows exactly what
   came back, and reports it honestly.

**Why a live call when the answer is almost always "nothing new".** That IS the
answer, and demonstrating it is worth more than asserting it. §0.1 says a DOT
engineer will ask whether this is current and that the answer decides the demo.
A presenter claiming the feed lags is making a claim; a button that queries the
live API in front of them and returns the same date the app already shows turns
the room's scepticism into the product's evidence. The lag stops being an excuse
and becomes a measurement.

Measured live on 2026-08-16, anonymously, with no app token:

| Query | Result |
|---|---|
| Newest crash on the API | **2026-06-11** |
| Crashes in the last 30 days | **0** |
| Anonymous access | HTTP 200 in 0.3–1.2s, no 429 |

Re-verified 2026-08-16 on macOS: HTTP 200 in 0.72s, newest still 2026-06-11.

**A live query is not live data. Every §0.1 rule still stands** — the banned
words, and no elapsed-days figure anywhere, including in whatever this action
renders.

Constraints on the runtime path, each of which is load-bearing:

- **The HTTP getter is injected**, so the whole module is testable offline. CI
  must never make a network call; a test suite whose result depends on NYC Open
  Data being up is not a test suite.
- **`app/live.py` must not import `duckdb` and must not touch the `Source`
  seam.** The live check reports on the feed; it never becomes a data source for
  anything the app renders. Keeping it structurally unable to do so is cheaper
  than a rule saying it must not.
- **A failed call must never look like a successful call that found nothing.**
  A timeout, a 429 and "the feed genuinely has nothing newer" are three
  different outcomes and must read as three different outcomes. This is §4.2's
  loud-not-seamless rule applied to the one place the app can now fail.
- **A copy test greps every user-visible string in the module for the §0.1
  banned words**, so the rule is enforced by CI rather than by memory.
- Block the §3.4 export while a live check is in its error state, same as any
  other degraded section.

The offline refresh keeps its own rules. Port `scripts/pull_data.py` from the
seeded repo rather than rewriting it — it already implements everything below.

Endpoint: `https://data.cityofnewyork.us/resource/h9gi-nx95.json`

- Send an app token in the `X-App-Token` header, read from `.env` via
  `python-dotenv` — **not** `st.secrets`. The refresh is an offline script with
  no Streamlit runtime, so `st.secrets` is unavailable to it, and the deployed
  app needs no secret at all because it never calls the API. Without a token you
  share an anonymous rate-limit pool and will see intermittent 429s.
- **Every request must carry `$order=crash_date`.** Socrata pagination without
  a stable sort repeats and drops rows. This bug already occurred in this
  project and produced a sample that was 89% one year.
- Page at `$limit=50000` with `$offset`; 50,000 is the per-page cap, not the
  dataset size.
- The API omits null keys entirely, so pages arrive with differing column sets.
  Reindex every chunk to an expected column list at the pull boundary.
- Retry 429 and 5xx with exponential backoff. Never retry 400 — that means the
  SoQL is malformed.

### 1.3 The casualty filter is a toggle, not a default

The proposed
`$where=latitude IS NOT NULL AND (number_of_persons_injured > 0 OR number_of_persons_killed > 0)`
keeps only **34.2%** of records (290,354 of 848,739).

That is a defensible lens for safety engineering, but it must be a **labelled,
user-visible toggle** defaulting to *off*, with the row count shown both ways.
Applied silently, every total in the app will contradict every published NYC
crash figure, and an engineer who knows the real numbers will notice.

### 1.4 Caching

`@st.cache_data(ttl=6*3600)` on all loaders; `@st.cache_resource` for the DuckDB
connection. Keep caching decorators in one module so analytics code stays
importable and testable without a Streamlit runtime.

---

## 2. Interactive map and hotspot workflow

### 2.1 Map

Use `pydeck` (ships with Streamlit, no Mapbox token required with the Carto
basemap). Do not add Deck.gl-via-JS, Leaflet or a Mapbox token dependency.

- **Bin in DuckDB, draw with `ColumnLayer`.** Do *not* use `HexagonLayer`: it
  performs its own GPU aggregation, so feeding it pre-binned centroids re-bins
  them and the hexagon radius — not your bin size — decides what the viewer sees.
  `ColumnLayer` draws exactly what the query returned, which means the map can be
  asserted in a unit test.
- Bin precision follows zoom. Measured on this Parquet: `round(lat/lon, 2)`
  (~1.1km) yields 914 bins ≈ 0.1 MB of JSON; `round(…, 3)` (~110m) yields 35,546
  bins ≈ 2 MB. Streamlit re-serialises the layer on every rerun on a ~1 GB
  container, so open the demo at the coarse level.
- Never let the 66,419 rows without coordinates reach the layer.
- **Colour by the Empirical Bayes estimate, not raw observed harm.** See §2.7.
  Raw `killed × 10 + injured` stays available as an *observed* figure in the
  drawer; it must not drive ranking or colour.
- Tooltip on hover; click selects.

### 2.2 Selection modes

Point-click and a **Featured corridors** dropdown for fast demoing.

Radius selection is **deferred** — see `TODOS.md`. §7 never exercises it.

### 2.3 Featured corridors — use these exact values

**Do not invent hotspots.** The originally proposed "Queens Blvd" is famous, not
frequent — it does not rank.

**This table carries inputs only. It must never carry counts.** Corridor
statistics are *outputs* of the pipeline and are computed at runtime (§7 requires
this). Any count written here becomes a second source of truth that drifts from
the code — the previous version of this table listed twelve figures, and the
engineering review on 2026-08-15 reproduced **zero of twelve** from the §2.4
rules below.

Instead: the bake emits `data/corridor_fixture.csv` with the real figures, and a
golden test pins it so a normalisation change fails loudly instead of silently
shifting every number on screen.

| Corridor | lat | lon |
|---|---|---|
| Belt Pkwy | 40.63237 | -73.88593 |
| Long Island Expy | 40.73884 | -73.83952 |
| Broadway | 40.75897 | -73.93857 |
| Brooklyn Queens Expy | 40.70525 | -73.95905 |
| Grand Central Pkwy | 40.73210 | -73.83202 |
| Atlantic Ave | 40.67949 | -73.92183 |
| FDR Drive | 40.76241 | -73.95443 |
| Major Deegan Expy | 40.85410 | -73.91810 |
| Cross Bronx Expy | 40.84353 | -73.89401 |
| Van Wyck Expy | 40.70715 | -73.81890 |
| Linden Boulevard | 40.66384 | -73.87840 |
| Flatbush Ave | 40.64269 | -73.95764 |

Include a mix of highway and surface corridors — the budget estimator (§3)
branches on that distinction, so the demo must exercise both.

Two corridors rank in the real top ten but are absent above: **3 Ave** and
**Cross Island Pkwy**. Consider adding them once the fixture exists.

### 2.4 Street names MUST be normalised before matching

Raw street names fragment badly. `FLATBUSH AVENUE` (2,873 rows) and
`FLATBUSH AVE` (424 rows) are the same street; matching one literal spelling
misses most of the corridor, on screen, in front of executives.

Normalisation rules, in this order:

1. **Strip leading house numbers — on `cross_street_name` only.** Measured
   2026-08-15: `on_street_name` has **zero** values with a padded house number,
   while `cross_street_name` has **166,443 of 217,510 (76.5%)**. The spec's own
   example, `3468<2 spaces>RICHMOND RD`, is a cross-street value.

   **Never apply this rule to `on_street_name`.** That column holds 101,041 rows
   beginning with a digit and a single space — `'3 AVENUE'`, `'5 AVENUE'` — all
   real streets. Scoping the rule by column makes collapsing them structurally
   impossible, rather than depending on a `\s{2,}` quantifier staying correct
   forever. Keep the `2+ spaces` guard as well; belt and braces.
2. Collapse repeated whitespace; uppercase.
3. Standardise suffixes: AVENUE→AVE, EXPRESSWAY/EXPWY→EXPY, PARKWAY/PKY→PKWY,
   STREET→ST, BOULEVARD→BLVD, ROAD→RD, TURNPIKE→TPKE, **DRIVE→DR, PLACE→PL**.
   (DRIVE, PLACE, BRIDGE and RAMP are all in the top-18 terminal tokens and were
   missing from this list.)
4. Strip ramp/direction noise: `'CROSS BRONX EXPWY WB ET 11'` → `CROSS BRONX EXPY`,
   `'BELT PKWY EXIT 24 A WB'` → `BELT PKWY`.
5. Prefer `on_street_name`; fall back to `cross_street_name`. This chain leaves
   only 33 rows unmatched. `off_street_name` adds nothing — it is non-null only
   when `on_street_name` already is.
6. **Then apply an explicit alias table** (`data/street_aliases.csv`). Rules
   alone provably cannot finish the job: the Brooklyn Queens Expressway still
   splits across six spellings including `'BROOKLYN QUEENS EXPY (CDR)'`, and Van
   Wyck splits 1,620 / 446 on a missing internal space. No general rule merges a
   parenthetical or a missing space without also merging roads that must stay
   separate. Beware `'GRAND CENTRAL PARKWAY SERVICE RO'` — a service road is a
   *surface* street and must not fold into the parkway.

Write a unit test for each rule using real raw values from the dataset, plus a
test asserting every featured corridor's alias set is complete, plus a regression
test that `'3 AVENUE'` survives normalisation intact.

### 2.5 Telemetry drawer

On selection, open a side panel showing, for the selected radius or corridor:
crashes, injured, killed, fatality rate per 1,000 vs the citywide rate, top
contributing factors, victim-type split (pedestrian / cyclist / motorist), and
the hour-of-week peak.

**The vehicle breakdown is omitted from v1** — see `TODOS.md`. Reason, verified
2026-08-15 and unchanged in the §6 bake: `vehicle_type_code1` has 1,430 distinct
values, and `Sedan` alone
splits across `Sedan` (372,582), `4 dr sedan` (488), `2 dr sedan` (40),
`SEDAN` (3), `sedan` (1). Never group by it raw; it needs a controlled taxonomy
built the same way as the street alias table.

### 2.6 The differentiating feature: include the dropped rows

Every other NYC crash map silently drops the 269,810 records with no borough —
and those rows carry **44.3% of the deaths**. This tool includes them.

Surface this in the drawer as a badge: `Includes N crashes other tools drop`.
On highway corridors that share is 88–98%, which makes the point vividly with no
extra explanation needed.

Report the recovery as a three-way slice where space allows — see `TODOS.md`.

### 2.7 Rank on the Empirical Bayes estimate, not raw observed harm — at the cell,
### not the corridor

Ranking by `killed × 10 + injured` is the naive approach, and §3.3 already
apologises for its central defect: high-crash sites regress toward the mean, so
a naive before-and-after over-credits any treatment. Empirical Bayes is the
Highway Safety Manual's prescribed correction. **This project fits its own EB
model** (`scripts/fit_eb.py`) on this repo's own recovered Parquet — the earlier
plan to reuse the sibling repo's `scored-units.parquet` did not survive contact
with the data and is superseded by everything below. **Never quote the sibling
repo's +18.4pp lift here; it is a different model on a different population.**

**RANKING UNIT DECIDED 2026-08-17: the cell, not the corridor.** Evidence, from
the audited cell-level fit:

- EB shrinkage weight is real at the cell (**0.211**) but the corridor rollup
  destroys it (**0.0002** at whole-corridor granularity before the fix below).
  Corridor top-decile persistence is **1.007** — no regression to the mean left
  to correct, because a top-decile corridor averages ~66 cells and independent
  cell noise cancels in the sum.
- The cell (`round(lat/lon, 3)`, ~111m × 84m) is already §2.1's map unit, so
  ranking and colouring at the cell needs no new geometry.
- **Corridor figures are a descriptive rollup of ranked cells, not an EB
  correction in their own right.** Show them in the drawer as sums/means over
  the corridor's cells, never re-rank corridors by a separate corridor-level EB
  fit.

**What can be claimed, from the rate-adjusted holdout test — use these numbers
and no others:**

| | raw | EB |
|---|---|---|
| Cell RMSE | 2.2837 | **2.1855** (−4.30%, bootstrap CI [3.83%, 4.76%]) |
| Head over-prediction (highest-count cells) | +29.0% | **+17.9%** |

Plus: **+12.7pp capture among cells raw count cannot rank at all** — the 39.8% of
cells with zero training casualties, which carry 9.7% of holdout harm.

**A guard that already fired once, keep it firing:** at `observed == 0` the EB
estimate is `mu/(1+mu/k)`, strictly increasing in `mu`, so EB's ordering of those
cells is *identical* to the SPF's ordering. The low-count lift is real but
belongs to the SPF, not to Empirical Bayes specifically — if both are quoted,
quote them separately, never combined as one EB number.

Rules:

- **Rank and colour by cell-level `eb_estimate`.** It is also the baseline the
  CMFs multiply. Never apply a CMF to a raw observed count.
- **Observed counts stay observed.** Crashes, injured and killed are facts and
  belong in the drawer as facts, labelled *observed*. Anything predictive is
  labelled *expected*. That distinction is the whole seam — keep it visible.
- **A corridor lift number, if shown at all, must carry its bootstrap CI** —
  every corridor-level lift measured so far sits inside its own CI on zero (see
  `NEXT-SESSION.md`). Do not print a bare percentage.
- **Coverage caveat is mandatory wherever a corridor rollup is shown.** Bridges
  and tunnels are not geocoded by NYPD (coordinate coverage 0.153 and 0.210
  against 0.943 for surface streets) — Brooklyn Bridge has 305 observed
  casualties and 16 visible to the cell grid. A cell-coloured map will read the
  Brooklyn Bridge as near-harmless unless this is labelled. See §4.2.
- A corridor with no matching EB cells at all is labelled unmatched, per §4.2.

This is the one axis where the target user is the expert. "Is this EB-adjusted,
and at what unit?" must have a straight answer.

---

## 3. Countermeasure and budget estimator

### 3.1 Branch on location type

Classify from a **curated list of NYC limited-access roads**
(`data/limited_access.csv`) — a small, closed, stable set, including bridges.
Anything not on the list is a surface street.

**Do not gate on "≥90% unlabeled".** That was the original rule and it fails on
real data: measured 2026-08-15, Nassau Expy sits at 85.7% and the `VANWYCK EXPY`
spelling at 83.6%, so both would be offered a road diet. Cross Bronx Expy lands
at 90.6% or 89.1% depending on an unrelated string-matching decision elsewhere in
the pipeline — meaning whether the tool proposes guardrail or a crosswalk on the
Cross Bronx flips on a coin toss. Borough-nullness is a police-paperwork artifact,
not a fact about the road.

Keep the unlabeled share as a **secondary signal only**: when the list and the
share disagree, log a warning naming the road. That is how you find a road
missing from the list.

Then offer only countermeasures valid for that type:

- Highway → guardrail & attenuator retrofit, high-friction surface treatment
- Surface → signal upgrade / smart phasing, road diet, pedestrian refuge island,
  leading pedestrian interval, daylighting

Offering a road diet on the Belt Parkway will discredit the tool instantly.

### 3.2 Costs and CMFs are editable planning defaults, never facts

**Ship `data/countermeasures.csv`: one row per treatment, carrying unit cost,
CMF, CMF star rating, the setting the CMF was measured in, and a source URL.**

§3.1 lists seven treatments. The original seed list gave four costs — bundling
road diet with refuge island, and giving leading pedestrian interval and
daylighting no cost at all — and gave **no CMF for anything**. Since the CMF is
the input the whole estimate multiplies through, that left the implementer no
choice but to invent it, which §0.3 #4 forbids. Look the values up in the FHWA
CMF Clearinghouse and cite each one.

Split road diet from pedestrian refuge island; they are different treatments at
different prices. Daylighting (paint and bollards) and an LPI (a signal timing
change) are roughly an order of magnitude cheaper than a road diet — a DOT
engineer will notice immediately if they are priced alike.

Requirements:

- Every cost is a **`st.number_input`**, editable in the UI, labelled
  *"Planning default — replace with your agency's unit cost."*
- **CMF terminology must be correct.** A CMF is a multiplier, not a percentage:
  CMF 0.75 means expected crashes fall to 75% of baseline, i.e. a 25% reduction.
  Never write "% CMF". Display both: `CMF 0.75 (25% reduction)`.
- Cite the FHWA CMF Clearinghouse as the source and state that star ratings vary
  by setting. Make the CMF a slider.
- Show cost per crash avoided and cost per unit of harm avoided, so treatments
  rank by efficiency rather than familiarity.

### 3.3 Mandatory caveat block

Render adjacent to the total, not in a footnote:

> Planning estimate, not an evaluation. Crash counts are not adjusted for
> traffic volume, so high-volume corridors rank high partly because they are
> busy. CMFs describe an average effect across many sites, not a guaranteed
> outcome at one. High-crash sites also regress toward the mean, so a naive
> before-and-after comparison will over-credit any treatment.

### 3.4 Export

Executive summary as **PDF** (`reportlab`), carrying: selection geometry, date
window, filters applied, unit costs used, CMFs used and their citations, data
completeness date, feed date, and the §3.3 caveats. An export without its
assumptions attached is a liability.

XLSX is **deferred** — see `TODOS.md`.

**Block export while any section is in its degraded error state.** A PDF that
silently omits a failed figure is worse than no PDF, because it leaves the
building.

---

## 4. Code quality and failure behaviour

### 4.1 Defensive requirements

- Python dataclasses or Pydantic models for the config and result objects; no
  free-floating dicts across module boundaries.
- Null-check every spatial operation. 66,419 rows have no coordinates and must
  never reach the map layer.
- Treat `(0, 0)` coordinates as missing — null island is absent data wearing a
  coordinate costume.
- Coerce Socrata's string numerics with `pd.to_numeric(errors="coerce")`. The
  API returns every scalar as a string.
- Wrap each page section so one failing chart degrades to an inline error
  message rather than replacing the app with a traceback.
- `pytest` for every cleaning rule, using **real raw values** from the dataset,
  not invented ones.

### 4.2 Demo safety net — loud, not seamless

Provide `data/mock_collisions.json` as a last-resort fallback, but the fallback
**must announce itself**:

- A `Source` object carrying `kind`, `label` and `trustworthy: bool`.
- When `trustworthy` is False, render a full-width red banner: *"Running on
  cached snapshot — API unreachable. Figures are illustrative."*
- Never let a number computed from mock data reach an export.

A silent fallback means presenting fabricated figures without knowing it. That
is worse than a visible error. **This pattern is already implemented** — it
arrives in this repo with the seed commit (§0.3 #1) as
`app/data.py::resolve_source`, returning a frozen `Source(kind, reader, label,
trustworthy)`. Follow it; do not rewrite it.

The same rule governs the Empirical Bayes join (§2.7): a corridor whose EB unit
does not match must be **labelled as unmatched**, never silently fall back to a
raw observed count while still being presented as an estimate.

---

## 5. UI/UX

**`DESIGN.md` in this repo is the source of truth for every UI decision.** Read it
before writing any interface code. Where this section and `DESIGN.md` disagree,
`DESIGN.md` wins. What follows is the summary and the reasoning that produced it.

Enterprise civic dashboard: dark theme, high-contrast hierarchy, crisp figure
typography. Classifier is **APP UI**, not a landing page — calm surface
hierarchy, few colours, dense but readable, minimal chrome.

**Colour is three independent channels, not one.** The palette this repo seeds
from sets `C_DEATH` and `C_UNLABELED` to the same `#B4232C`, which on this
product's screens would mean red says "people died here" and "this data is
incomplete" at once. §2.7 adds a third distinction on top. So:

- **Hue** carries severity (green → amber → orange → red), with opacity as a
  redundant channel so it survives colour-vision deficiency.
- **Fill vs outline** carries expected vs observed. Filled marks are Empirical
  Bayes estimates; outlined marks are observed-only, with no EB match. This pair
  is the most dangerous to confuse and the distinction survives greyscale.
- **Neutral plus hatch** carries data completeness. It never borrows a severity
  hue, so the "records other tools drop" badge can never read as a harm signal.
- One reserved hue for pedestrian and cyclist harm, used in the victim-split
  chart and nowhere else.
- A legend is visible wherever more than one channel is in play.

**Typography is named and self-hosted.** IBM Plex Sans Condensed for headings,
IBM Plex Mono for figures, IBM Plex Sans for body — committed as woff2 and
declared via Streamlit's theme `fontFaces`. No CDN: §1.1 chose a committed
Parquet so nothing can fail on stage, and a blocked font request is the same
class of risk. Never `system-ui` or a default stack as the display face.

**Layout.** Persistent freshness line, then a sticky control bar, then map and
drawer side by side.

- The drawer is a real `st.columns` column, never a CSS overlay — injected CSS
  re-applies with a delay on every rerun and would make the panel jump mid-demo.
- **The map never drops below 65% of content width.** §7's Belt Pkwy vs Atlantic
  Ave contrast is a map comparison; compress the map and the beat weakens.
- **Primary controls live in the sticky bar, not the sidebar.** Streamlit
  collapses the sidebar below ~768px — the width this spec previously named as a
  requirement — and the corridor dropdown must never hide (see accessibility).
- Cache the map layer on `(corridor, filters, zoom)` so estimator interactions
  never rebuild it. Streamlit reruns the whole script on every widget change, and
  §7 step 4 is someone dragging a cost slider; without the cache the map
  re-serialises on every drag.

**KPI figures are typographic rows, not cards.** Label, value, one-line
qualifier, hairline separators. Never a bare number. Cards are reserved for
countermeasure options, which are genuinely selectable — so a boxed thing on
screen always means "you can pick this."

**Road class is a labelled, correctable control** at the top of the drawer,
showing its basis. The curated limited-access list (§3.1) fails silently when a
road is missing from it; a visible control turns that into something the engineer
fixes in the room. Overrides are recorded in the export.

**The freshness line is operable, not decorative.** §0.1 says a DOT engineer will
ask whether this is current, and that the answer decides the demo. Clicking the
line opens a short panel: where the lag comes from, why multi-year chronic-risk
patterns are unaffected by it, and what the tool does not claim. Use
`st.popover` — native, no new dependency. The product answers the question, not
the presenter.

**Accessibility target: WCAG 2.2 AA.** The map is a WebGL canvas, which to
assistive technology is one opaque image — no keyboard focus, no per-bin
semantics. Visible focus styling does not help when nothing is focusable.
Therefore **the Featured corridors dropdown is the designated keyboard and
screen-reader equivalent of the map**, not a demo convenience, and everything the
map can do must be reachable through it. Ship a ranked corridor table carrying
the same figures in text. Touch targets ≥44px. Body text ≥16px, contrast ≥4.5:1,
≥3:1 for focus indicators — note `#B4232C` on `#0E1117` measures ~2.9:1 and fails
that bar, which the dashboard repo already hit and fixed with `currentColor`.
`prefers-reduced-motion: reduce` disables the drawer transition.

**Motion budget:** the drawer transition plus `:hover` / `:focus-visible`. That is
all. Streamlit's rerun model fights anything more ambitious.

**Copy** in sentence case, active voice, utility register. Errors state what
happened and what to do next. Empty states propose an action — the named ones are
in `DESIGN.md` §7, including the CMF-at-1.0 and EB-unmatched cases that would
otherwise ship as `inf` and silence.

---

## 6. Build order for one week

Ship in this sequence. Each step must leave the app running and demoable.

0. **Day 0** — Seed this repo from the dashboard repo (§0.3 #1). Stand up
   `requirements.txt`, `.streamlit/config.toml`, CI and secrets. Note Python is
   reachable as **`py`**, not `python`, on this machine — but never write `py`
   inside a script or workflow; Ubuntu runners have no `py` launcher.
1. **Day 1** — Street normalisation + alias table + tests (§2.4). Everything
   downstream depends on it.
2. **Day 1–2** — Offline point-in-polygon borough recovery. **Freeze the full
   derived schema first and bake the Parquet exactly once**, carrying
   `borough_recovered`, `borough_source`, the canonical street name, and the EB
   unit join key. Every re-bake is another permanent ~35 MB blob in git history,
   and a mid-week schema change invalidates the corridor fixture (§2.3) and the
   gate below.

   **Use water-included borough boundaries, not the shoreline-clipped variant.**
   The clipped polygons drop points over water, which is where elevated and
   waterfront highways sit.

   **The gate is stratified, not a single agreement number.** Three checks, all
   must pass:
   - overall agreement on rows having both a reported borough and coordinates —
     expect high-90s%. Below ~90% means the CRS or axis order is wrong: the DCP
     shapefile is EPSG:2263 in feet, the Open Data GeoJSON is EPSG:4326, and
     `Point` takes `(lon, lat)`.
   - **recovery rate broken out by road class.**
   - **an explicit Belt Pkwy assertion** against its 10,963 unlabeled rows that
     carry coordinates.

   Why the extra two: the agreement check measures rows that *have* a borough
   (533,797 rows, 1.80% limited-access) while recovery is applied to rows that
   *lack* one (213,246 rows, 35.39% limited-access). The populations are disjoint
   by construction and differ twentyfold in exactly the dimension that fails, so
   the agreement number alone can read 97% while tens of thousands of highway
   rows are silently lost — on Belt Pkwy, the corridor §7 opens on.

   **Publish no recovery figure until all three gates pass.**
3. **Day 2–3** — Map with binned aggregation + click and radius selection.
4. **Day 3–4** — Telemetry drawer + featured corridors dropdown.
5. **Day 4–5** — Countermeasure and budget estimator with editable inputs.
6. **Day 5** — PDF and XLSX export with assumptions attached.
7. **Day 6** — Dark theme pass, responsiveness, freshness line everywhere.
8. **Day 7** — Rehearse the demo on the deployed URL, not locally. Deploy early
   so Streamlit Cloud's cold-start behaviour is a known quantity, not a surprise.

If time runs short, cut export (§3.4) before cutting the borough recovery or the
EB ranking (§2.7). Those two are the differentiators; export is convenience.
Radius selection, XLSX, the vehicle breakdown and the runtime API path are
already out of scope — see `TODOS.md`.

---

## 7. Demo narrative the build must support

1. Open on the map. Harm concentrates visibly on highways.
2. Select Belt Pkwy from Featured corridors → drawer shows its casualty crashes,
   deaths, and the badge *"N% of these are records other tools drop."*
3. Contrast with Atlantic Ave → the estimator now offers surface-street
   countermeasures instead of guardrail.
4. Adjust a unit cost live → CAPEX and cost-per-crash-avoided recompute.
5. Export the executive summary, with assumptions and caveats attached.

Every claim in that sequence must be computed from the data at runtime. Nothing
in it may be hardcoded — **including in this document.** Deliberately no figures
appear above: rehearse from `data/corridor_fixture.csv`, which the bake
generates, so the script you say out loud and the number on screen come from the
same query. The earlier version of this section quoted "4,345 casualty crashes,
48 killed" while the pipeline produced 4,736 and 55.

---

## 8. Approved visual reference

| Screen | Path | Direction | Notes |
|---|---|---|---|
| Map + drawer | `~/.gstack/projects/Jeffreys-World-NYC-Collision-Intelligence-DOT-build-/designs/dot-map-drawer-20260815/wireframe.html` | Dark civic workspace, map-led, drawer as a real column | Panel A shows what §5 produced before this review; panel B is the approved direction; panel C draws the classifier boundary case |

Hand-built wireframe, not an AI mockup — the gstack designer has no API key
configured on this machine. It uses real measured figures rather than
placeholders, which for this product is the point: the design problem is data
semantics, not visual style.

Build from panel B. It is the visual source alongside `DESIGN.md`.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | clean (2026-08-08) | mode: HOLD_SCOPE, 0 critical gaps |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | clean (2026-08-16) | 10 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | clean (2026-08-16) | score: 4/10 → 9/10, 9 decisions |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**Verification:** all 18 dataset figures in §0.2 and §2.5 were re-measured
against `crashes.parquet` on 2026-08-15 and matched exactly. All 12 derived
corridor figures in the previous §2.3 failed to reproduce from the §2.4 rules
(0/12) and have been replaced by a generated fixture.

**DESIGN:** §5 rated 4/10 and rewritten to 9/10; `DESIGN.md` added as the UI
source of truth. The load-bearing findings: the inherited palette assigns one red
to both fatality and data-incompleteness, and §2.7 added a third meaning to the
same screen — resolved by giving severity, certainty and completeness their own
perceptual channels. The pydeck map is a WebGL canvas with no keyboard or
screen-reader path, so the Featured corridors dropdown is now the designated
accessible equivalent rather than a demo convenience. Primary controls moved out
of the sidebar because Streamlit collapses it at the 768px width §5 named as a
requirement. Wireframe at
`~/.gstack/projects/…/designs/dot-map-drawer-20260815/wireframe.html`.

**CROSS-MODEL:** not run in either review — Codex CLI is not installed on this
machine, and the Claude-subagent fallback was not authorised in these sessions.
Install with `npm install -g @openai/codex` for cross-model coverage on the next
pass. Both reviews are therefore single-model; the eng review's ten findings were
verified against the Parquet rather than reasoned, the design review's nine were
not independently challenged.

**VERDICT:** CEO + ENG + DESIGN CLEARED — ready to implement.

NO UNRESOLVED DECISIONS
