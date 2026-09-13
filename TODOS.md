# TODOS

Deferred during the engineering plan review on 2026-08-15, the design plan review on
2026-08-16, and the engineering plan review on 2026-09-12. Every item below "Next up" was cut
on purpose. Read the reason before reversing one.

**Next up** is the exception: scheduled work, not deferrals. PR1 landed on 2026-09-13
(`511e52c`..`45430ce`, 374 tests). PR2 is what follows, and it is strictly serial — T10
reorders the same file four PR1 tasks just edited, so these cannot run concurrently in
worktrees. The conflict surface is the entire script.

## Next up — PR2, the cold open

Source: `docs/designs/ui-reveal-cold-open.md`, Implementation Tasks T10-T13. Do them in
order.

### T10 — Delete the nine-bullet expander and rebuild the first screen

**What:** Remove the "What each part of this page does" expander (`streamlit_app.py:172-206`)
and rebuild the first screen as: headline claim, freshness line, live-feed button at top
level.

**Why:** The expander is a manual for a page that should explain itself, and it sits between
the reader and the finding. The 2026-09-13 design review scored hierarchy at D for exactly
this reason: the completeness claim — the sentence this project exists for — renders at 13px
in muted grey, below the fold, reachable only after using a dropdown, while the `<h1>` is
44px. Nine bullets of chrome ahead of it makes that worse.

**Context:** The expander carries a claim worth fixing rather than relocating. Line 187 says
the casualty toggle "restricts every figure on the page". Before T3 that was flatly false —
it restricted the drawer only. After T3 it is closer but still not true: every query over
`crashes_filtered` is filtered, and the map is not, because the map reads `eb_cells` and the
EB model is fit on casualties regardless of the toggle. The map's own caption already says
so. Whatever replaces this copy should say "every observed figure below the map", or say
nothing — checked against the code on 2026-09-13, not assumed.

`feed.py`'s popover is already top-level as of T6, so the live-feed button does not need
moving, only the copy around it. This is FINDING-001/-002 territory; the Design section below
maps those to tasks.

**Effort:** M
**Priority:** P1
**Depends on:** PR1 (landed)

### T11 — The static finding table

**What:** A fixed table stating the completeness finding in numbers: seven highways at zero,
Belt Pkwy at 56, 225 of 288 deaths hidden across the 12 featured corridors. Computed once at
load from the full Parquet, never over `crashes_filtered`.

**Why:** This is decision 10's static answer to the reveal. The hook is "this person found
something everyone else missed", and right now a cold reader has to operate the page to reach
it. A table states it before they touch anything.

**Context:** The "never over `crashes_filtered`" constraint is load-bearing and easy to get
wrong now that T3 routes the casualty toggle through `base_view.sql` — every query reading
that view moves when the user flips a filter, and a headline finding that changes when
someone drags a date picker is not a finding. Compute it from the Parquet directly, cache it
on the source label alone (`presentation.map_cache_key` is the shape to copy, not
`query_cache_key`). Non-negotiable #1 applies with full force: every figure comes from
`data/processed/crashes.parquet` and `scripts/verify_figures.py` must reproduce it. The
wireframe at `docs/designs/wireframe-reveal.html` carries the measured figures; the fabricated
EB estimates it also carries are recorded in Open Questions and must not be copied.

**Effort:** M
**Priority:** P1
**Depends on:** T10

### T12 — Preselect a corridor on load

**What:** Open with a corridor already selected, so nothing renders a "select a corridor
above" empty state. Satisfies success criterion 2.

**Why:** Three empty states on first paint was the design review's structural finding, and it
is the first thing a cold reviewer sees. A page that opens asking the visitor to do something
before it shows them anything spends their attention on navigation instead of the finding.

**Context:** Cheaper than it was. T5 made the selection a single stored canonical in
`st.session_state[SELECTED_KEY]`, so preselection is seeding that key before the widgets
render — not a new code path. Pick the corridor deliberately: Belt Pkwy is the finding's own
example (5,186.0 expected harm, 12,755 crashes other tools drop) and is EB-matched, so the
estimator and the export both open in a working state rather than a blocked one.

**Effort:** S
**Priority:** P1
**Depends on:** T11

### T13 — Deploy and look at it cold

**What:** Deploy, then open the link as a stranger would, with no context, and judge whether
the static table lands.

**Why:** This is the decision-10 trigger, and it gates two other items in this file: "The
interactive reveal" below, and the WCAG audit under Accessibility, which needs a live URL.
It is also the only test of the thing the whole project is for. Nothing in the suite can
answer it.

**Context:** The judgement is specific, not a vibe check: does the table read as a
*demonstration* or as a *claim*? If it reads as a claim, open the reveal item. Give it under
a minute, the way a portfolio reviewer would. Worth pairing with the deferred design findings
in the Design section, since a deploy is also what the accessibility audit is waiting on.

**Effort:** S
**Priority:** P1
**Depends on:** T12

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

### ~~Offline Socrata refresh script~~ — REVERSED BY THE OWNER, 2026-08-16

**Status: no longer deferred.** This entry used to say "No runtime API path in the
deployed app". The owner overrode that and chose a hybrid. **§1.2 is now the authority.**

**What changed:** the offline refresh stays, and the deployed app additionally gains one
user-triggered "check for newer records" call.

**Why the reversal:** the feed's lag is the first thing a DOT engineer challenges, and
§0.1 says that answer decides the demo. A live query answering it in the room beats a
presenter asserting it — the query returns the same date the app already shows, which
converts scepticism into the product's own evidence.

**The original reasoning was not wrong about the risks**, so those became the constraints
in §1.2 rather than a veto: an injected HTTP getter so CI never makes a network call, no
`duckdb` import and no contact with the `Source` seam, a failure that can never read as an
empty success, and a copy test grepping the module for §0.1's banned words.

**Still true and still the rule:** the offline pull is ported from the sibling repo, never
rewritten — `$order=crash_date` on every request, chunk reindexing to a fixed column list,
exponential backoff on 429/5xx, never retrying 400. That port is done, in
`scripts/pull_data.py`, and re-pulled 848,742 rows cleanly on 2026-08-16.

**Outstanding:** `app/live.py` itself. The workflow designing it on 2026-08-16 never wrote
files and its journal did not survive the move to macOS; the contract summary in
`NEXT-SESSION.md` is what remains.

**Effort:** M
**Priority:** P1
**Depends on:** None

## Interaction

### The interactive reveal — "See what other tools show"

**What:** A toggle on the first screen that re-renders the map, drawer and ranked table
against `borough_source = 'reported'` rows only, so the viewer watches the highway network
empty out. Deferred at the 2026-09-12 engineering review (decision 10D). PR1 ships the
static version: a table stating the same finding in fixed numbers, no interaction.

**Why:** The finding is the whole hook — seven NYC highways show zero traffic deaths in the
standard view and the Belt Parkway has fifty-six; across the 12 featured corridors the
standard view hides 225 of 288 deaths. A viewer who flips the control themselves believes it
in a way a table cannot match. It was deferred, not cut, because the static table may already
land, and the reveal costs a second query path through every component on the page.

**Context:** The revival trigger is specific: **open the deployed link cold, as a stranger
would, and judge whether the static table lands without it.** If the table reads as a claim
rather than a demonstration, build the reveal. Start at `docs/designs/ui-reveal-cold-open.md`
— Recommended Approach, then Implementation notes; the design work is done, the wireframe in
`docs/designs/wireframe-reveal.html` shows both states with measured figures. The engineering
shape was settled at the same review: the map is split into two pydeck layers (decision 1A)
so the reveal swaps a layer rather than re-serialising 77,747 cells, and the drawer figures
come from a SQL aggregate behind a bounded cache (decision 2A).

**What PR1 already did for this** (2026-09-13), so it is not re-derived: selection survival is
solved. The reveal re-sorts the ranked table and `st.dataframe` returns a positional index, so
a stored index would re-point — T5 resolves the click to a canonical at click time and stores
only that (`presentation.canonical_at_row`, `tests/test_selection.py`). The bounded cache
decision 2A asks for is in place (`data.MAX_QUERY_CACHE_ENTRIES`). The layer *seam* is in
place too, but the second layer is **not built**: `eb_cells` carries no completeness column,
so the completeness layer still needs the new SQL this item is really about. That SQL is the
remaining work, not the plumbing around it.

Edge case that is not a bug: 1,657 of 8,931 canonicals have no reported row at all and must
render explicit zeros, not blanks.

**Effort:** M
**Priority:** P2
**Depends on:** T13 (the trigger is a cold look at the live URL). PR1 has landed.

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

## Testing

### Re-test the WebGL blocker on CI before treating it as settled

**What:** `DELIVERABLES.md` records that headless browsers here have no GPU and
cannot create a WebGL context, so the pydeck map cannot be screenshotted or
asserted against. On 2026-09-13 a /design-review run drove gstack's headless
Chromium against the app on this machine and **the map rendered** — 77,747 live
cells in every screenshot in
`~/.gstack/projects/Jeffreys-World-GitHub/designs/design-audit-20260912/screenshots/`.
The console carried `GL Driver Message (OpenGL): GPU stall due to ReadPixels`,
which is a performance warning from a working GL context, not a failure to
create one.

**Why:** that claim is load-bearing. It drove decision 6A at the engineering
review and it is the stated blocker on the browser E2E item below. If it is
wrong, the E2E suite is cheaper than recorded and the map becomes assertable.

**Context:** this does not automatically transfer to GitHub Actions, which is a
different machine with different drivers — that is the actual question to
settle. Run one throwaway workflow that loads the app and screenshots the map
canvas. If it renders, correct `DELIVERABLES.md` and reopen the E2E item's
scope. If it does not, record which environment the limitation applies to,
because "this repo's sandbox" is now known to be too broad. Nothing has been
edited on the strength of one machine's result.

**Effort:** S
**Priority:** P2
**Depends on:** None

### Browser end-to-end tests for the map and the reveal

**What:** Real-browser tests that drive the deployed app: click a ranked-table row and assert
the drawer follows, flip the reveal and assert the map changes, select a corridor and assert
the selection survives the re-sort. Deferred at the 2026-09-12 engineering review (decision
6A), which scoped PR1 tests to pure logic plus three regressions.

**Why:** The three highest-risk behaviours in this app are all cross-component: selection
identity across a re-sort, the map cache key, and the drawer agreeing with the table. Unit
tests over extracted pure functions cover the arithmetic but cannot prove the wiring. Every
regression this app has shipped so far (ISSUE-001, ISSUE-002) was a wiring or rendering bug
that a unit test would not have caught.

**Context:** The blocker is environmental, not philosophical: headless browsers in this
repo's sandbox have no GPU and cannot create a WebGL context, so the pydeck map cannot be
screenshotted or asserted against in CI. This is recorded in `DELIVERABLES.md`. Two ways
forward, and the choice is the first thing to make: run the suite against the deployed
Streamlit Cloud URL from a runner that does have a GPU or a software GL fallback
(`--use-gl=swiftshader`), or keep CI GPU-free and assert only on the DOM — the ranked table
and drawer read from the same queries the map does, so the data path is testable even when
the canvas is not. The interaction list is already written: see the "Key Interactions to
Verify" and "Critical Paths" sections of
`~/.gstack/projects/Jeffreys-World-GitHub/jeffrey-main-eng-review-test-plan-20260912-201000.md`,
which is shaped for `/qa` to consume directly.

**Effort:** M
**Priority:** P2
**Depends on:** deploy, and PR1's pure-logic extraction landing first

## Design

### Deferred design findings from the 2026-09-13 /design-review

**What:** Four findings from the design audit that were deliberately not fixed in
that run, because each one is already a task in the committed engineering plan
and fixing it early would reorder `app/streamlit_app.py` ahead of PR1's spine.

**Why:** the audit graded the app C+ overall but **D on visual hierarchy and D on
interaction states**, and every point of that came from these four. The five
findings that were fixed were craft; these four are the structure.

**Context:** full report with screenshots at
`~/.gstack/projects/Jeffreys-World-GitHub/designs/design-audit-20260912/design-audit-localhost-8501.md`.

- **FINDING-001 (high)** — the app's central claim renders at 13px, weight 400,
  `#8B98A5`, at y=1422 in a 900px viewport, and only after a corridor is
  selected: `▨ Includes 12,755 crashes other tools drop (98%)`. The `<h1>` above
  it is 44px/700. → **T11**
- **FINDING-002 (high)** — selecting a corridor does not change the map by a
  single pixel. Root cause is known: the constant cache key at
  `streamlit_app.py:255`. → **Next Step 3 / T4**
- **FINDING-003 (high)** — three empty states on first paint (drawer, estimator,
  export), plus ~500px of dead black beside the map. → **T12**
- **FINDING-009 (high)** — the onboarding expander states that the casualty
  toggle "restricts every figure on the page". It filters the drawer only. Read
  live from the rendered page, not inferred. → **T3** fixes the behaviour, **T10**
  deletes the expander.

**Effort:** covered by existing tasks
**Priority:** P1
**Depends on:** PR1 landing first

## Dependencies

### Confirm plotly is gone and stays gone

**What:** `requirements.txt` pins `plotly>=5.24` and the repo has zero references to it.
PR1 removes the pin (decision 3A). This item is the follow-up: if a chart is ever wanted in
the drawer, decide deliberately whether to re-add plotly or use Streamlit's built-in charts.

**Why:** `requirements.txt` is what Streamlit Community Cloud installs. An unused pin is
install time and a dependency-surface claim the app does not make. It also misleads the next
person into thinking a charting library is already the house choice.

**Context:** `sql/selection_rows.sql` carries a comment citing three drawer charts that do
not exist — that comment is likely where the pin came from. Streamlit's native
`st.bar_chart` / `st.line_chart` cover what those three charts described and add nothing to
the install. Re-add plotly only if a chart needs interaction the built-ins cannot do, and if
so, pin it in the same commit as the chart, never ahead of it.

**Effort:** S
**Priority:** P4
**Depends on:** PR1

### Carry the feed check into the PDF's assumptions block

**What:** `app/feed.py::export_note` builds one line for the §3.4 assumptions block — "on
`<server date>`, data.cityofnewyork.us reported no crash records dated after `<coverage>`" —
and nothing calls it. T6 wired the module's UI surface (`render_feed_check`) but not this.
`build_summary_pdf` needs one more keyword argument and one more row.

**Why:** it is the strongest line available in the export and it costs almost nothing. A PDF
that leaves the building carrying the server's own dated statement is the difference between
"trust our extract" and "here is the feed agreeing with it, on this date". `export_note`
already returns None on a failed or undated check, so the failure modes are handled — it is
the one route from that module into an export and it is currently a dead end.

**Why it was not done in T6:** T6's scope was replacing `app/live.py` at the call site. This
changes `build_summary_pdf`'s signature and `tests/test_pdf_export.py` with it, which is a
separate commit and a separate reviewer question. Leaving `export_note` unwired does repeat
the shape of the problem decision 9 fixed (a documented function nothing calls), which is why
this is written down rather than left to be rediscovered.

**Effort:** S
**Priority:** P3
**Depends on:** nothing — PR1's T6 already landed the module

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
