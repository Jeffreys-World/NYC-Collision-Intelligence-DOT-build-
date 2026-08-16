# TODOS

Deferred during the engineering plan review on 2026-08-15 and the design plan review on
2026-08-16. Every item here was cut on purpose. Read the reason before reversing one.

## Accessibility

### Verify the WCAG 2.2 AA target against the deployed app

**What:** Run a real keyboard, screen-reader and contrast pass on the live URL. Confirm the
Featured corridors dropdown reaches every function the map offers, and that the ranked
corridor table carries the same figures the map and drawer show.

**Why:** `DESIGN.md` §5 states WCAG 2.2 AA as the target. A target nobody verifies is a
claim, not a conformance level. The dashboard repo's `QA-REPORT-2026-08-09.md:95-96` records
accessibility as explicitly unscored — 15% of the health weight never measured. Saying "AA"
to a public-sector buyer and being wrong is worse than saying nothing.

**Context:** The map is a WebGL canvas and will never be directly accessible; that is
expected and not the thing to audit. The audit's job is to confirm the two designated
alternatives actually carry the full function: the dropdown as the keyboard and
screen-reader path, and the ranked table as the text equivalent. Specific things to check:
tab order through the sticky control bar, whether the drawer's correctable road-class
control is operable by keyboard, whether `st.popover` on the freshness line is reachable,
contrast on the severity ramp against `#0F1419`, and that `prefers-reduced-motion` actually
disables the drawer transition. Note the known trap: `#B4232C` on `#0E1117` measures ~2.9:1
and fails the 3:1 bar for focus indicators — the dashboard repo hit this and fixed it with
`currentColor`.

**Effort:** M
**Priority:** P1
**Depends on:** deploy (the audit needs the live URL, not localhost)

## Responsive

### Decide how the three-channel legend works below 820px

**What:** Settle how hue, fill-versus-outline and hatch are explained when the layout stacks
vertically.

**Why:** The colour system carries three independent meanings. Without a legend it is a
puzzle, and a viewer who cannot decode it may read a completeness badge as a harm signal —
the exact confusion the three-channel system was built to prevent.

**Context:** At ≥820px the legend sits under the map where there is room. Below 820px the
control bar stays, the map goes full width and the drawer stacks beneath it, so the vertical
budget is already committed. Options worth weighing: a collapsible legend in the control bar,
a legend inside the drawer header where it sits next to the marks it explains, or accepting
that narrow viewports show fewer channels at once and simplifying the map to hue-only there.
The third is defensible but must be a decision, not an accident.

**Effort:** S
**Priority:** P2
**Depends on:** the breakpoint layouts in `DESIGN.md` §3 landing first

## Data integrity

### Report the borough recovery as a three-way slice

**What:** Report recovery as `reported` / `recovered-surface-street` / `recovered-highway`
rather than collapsing it into the single `Includes N crashes other tools drop` badge.

**Why:** This is an existing project rule, not a new idea. The sibling dashboard repo's
CLAUDE.md carries it as non-negotiable #7, with the reasoning: collapsing recovery into one
corrected ranking makes the chart rank boroughs partly by highway mileage, which is not what
a reader thinks they are seeing. The DOT spec's §2.6 badge collapses it.

**Context:** Recovery is 213,246 rows, of which 35.39% sit on limited-access roads against
1.80% in the reported population. That skew is exactly why the three-way split exists — the
recovered rows are not a random sample of the city, they are disproportionately highway. The
badge is still worth showing; it just should not be the only view. Start from the sibling
repo's `sql/borough.sql`, which already slices this way.

**Effort:** S
**Priority:** P1
**Depends on:** the single Parquet bake (T2/T6)

### Exposure / AADT normalisation

**What:** Adjust crash counts for traffic volume so corridors rank by risk rather than by
busyness.

**Why:** Without it, the tool ranks high-volume corridors highly partly because they carry
more vehicles. §3.3's caveat block says so explicitly and must keep saying it.

**Context:** Not deferred by choice — NYC does not publish AADT at the granularity this tool
selects at. This is a genuine data gap, not a shortcut. If DOT provides segment-level volume
during a pilot, this becomes the single highest-value upgrade: it converts the ranking from
"where harm happened" to "where harm concentrates per unit of exposure". Until then §0.3 #5
stands and the caveat is mandatory wherever the tool ranks or recommends spending.

**Effort:** L
**Priority:** P2
**Depends on:** an external AADT source

## Data pipeline

### Offline Socrata refresh script

**What:** Keep the Socrata pull as a `scripts/` job that re-bakes the Parquet on a laptop.
No runtime API path in the deployed app.

**Why:** §0.1 forbids the app from displaying data newer than the shipped slice, so a
runtime client can only fetch records the UI may not show — while adding rate limits, 429s,
pagination bugs and schema drift to the live demo path.

**Context:** The hard parts are already solved in the sibling repo's `scripts/pull_data.py`
(253 lines): `$order=crash_date` on every request, chunk reindexing to a fixed column list,
exponential backoff on 429/5xx, never retrying 400. Do not rewrite it — port it. Revisit a
runtime path only if the product genuinely needs in-app refresh, which would first require
revisiting §0.1.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Interaction

### Radius selection (100–2000m)

**What:** Slider-driven circular selection on the map, alongside point-click and the
featured-corridor dropdown.

**Why:** Lets an engineer scope an analysis to a real intersection neighbourhood rather than
a whole named corridor.

**Context:** Cut because the §7 demo narrative never exercises it, and the spec's own cut
order sacrifices it before borough recovery. Cheap to add later: the aggregation it needs is
the same query shape as corridor stats, just with a `ST_Distance`-style predicate instead of
a street-name match. The drawer component does not need to change.

**Effort:** S
**Priority:** P3
**Depends on:** the map layer (T11)

### Vehicle-type breakdown in the drawer

**What:** Victim/vehicle composition per selection.

**Why:** A DOT engineer will ask what is hitting people on a given corridor.

**Context:** Cut because `vehicle_type_code1` has 1,380 distinct raw values and needs a
controlled taxonomy first. The scale of the problem is measured: `Sedan` alone splits across
`Sedan` (372,582), `4 dr sedan` (488), `2 dr sedan` (40), `SEDAN` (3) and `sedan` (1). §2.5
already permits omitting this from v1. When picked up, build the taxonomy the same way the
street alias table works — an explicit committed mapping with tests, not regex heuristics.

**Effort:** M
**Priority:** P3
**Depends on:** None

## Export

### XLSX export

**What:** Executive summary as `.xlsx` via `openpyxl`, alongside the PDF.

**Why:** Agency staff often want the numbers in a spreadsheet to re-cut themselves.

**Context:** Cut because the PDF carries the §7 closing beat and XLSX is a second serializer
for identical content. `openpyxl` is already in the sibling repo's `requirements-dev.txt`.
Whatever ships must carry the same assumptions block as the PDF — selection geometry, date
window, filters, unit costs, CMFs, completeness date, reporting lag and the §3.3 caveats. An
export without its assumptions attached is a liability.

**Effort:** S
**Priority:** P3
**Depends on:** PDF export
