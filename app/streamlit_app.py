"""NYC Collision Intelligence — DOT build. Entry point.

Layout is DESIGN.md §3: freshness line, sticky control bar, map (≥65% width)
beside the drawer as a real `st.columns` column. See CLAUDE_CODE_PROMPT.md §7
for the demo sequence this screen has to support end to end.

RENDER ORDER, and what gates what. Streamlit runs this file top to bottom on
every widget change, so the order below is the control flow — there is no
router and no component tree to read it off.

    sidebar filters (date range, casualty toggle)
            │
            ▼
    build_view(con, date_from, date_to, casualty_only)
            │   ONE place the filter predicates live. Everything downstream
            │   reads `crashes_filtered`, so the table and the drawer cannot
            ▼   disagree about what is filtered.
    ┌───────────────────────── cache_key ─────────────────────────┐
    │  query_cache_key(source, dates, casualty_only, canonical)   │
    └───────┬─────────────────────┬───────────────────┬───────────┘
            │                     │                   │
            ▼                     ▼                   ▼
    ┌───────────────┐   ┌──────────────────┐   ┌──────────────┐
    │ map_cells()   │   │ selection_rows   │   │ corridor_    │
    │ map_cache_key │   │ (drawer)         │   │ table (rank) │
    │ NOT this key  │   └──────────────────┘   └──────────────┘
    └───────────────┘            │                   │
      eb_cells does not          └─────────┬─────────┘
      move with the date                   │
      picker — see                         ▼
      presentation.map_cache_key   ┌─────────────────┐
                                   │ estimator (§3)  │  gated on eb_matched
                                   └────────┬────────┘
                                            ▼
                                   ┌─────────────────┐
                                   │ export gate     │  blocked if ANY
                                   └─────────────────┘  section degraded

SELECTION ARBITRATION is the one place two widgets converge. The dropdown and
the ranked table can each set the corridor, they both re-emit on every rerun,
and without a rule they fight — one corridor's map beside another's drawer.
`resolve_selection()` is that rule: last touched wins, and only `canonical` is
stored, never a row index. See its docstring for why the index is the trap.

Pure logic lives in app/presentation.py, which imports no streamlit and is
unit-tested. Anything here that has a right answer independent of the session
belongs there, not in this file.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

# `streamlit run app/streamlit_app.py` puts app/ on sys.path, not the repo
# root, so `from app import ...` fails with ModuleNotFoundError. Insert the
# root before any sibling-package import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pydeck as pdk
import streamlit as st

from app import estimator, feed, presentation, road_class, theme
from app.data import (
    build_view,
    date_bounds,
    finding_frames,
    freshness_line,
    get_connection,
    map_cells,
    normalize_date_range,
    query,
    resolve_source,
    set_selection,
)

ROOT = Path(__file__).resolve().parent.parent
FEATURED_CSV = ROOT / "data" / "featured_corridors.csv"
BOROUGH_BOUNDARIES = ROOT / "data" / "raw" / "boroughs_water-included.geojson"

# Lives in app/presentation.py now, alongside the rule that reads it. Re-
# exported under the old name because the threshold appears in user-facing
# copy below and the two must not be able to drift apart.
LOW_COVERAGE_THRESHOLD = presentation.LOW_COVERAGE_THRESHOLD

st.set_page_config(page_title="NYC Collision Intelligence — DOT", layout="wide")

theme.inject("light" if st.session_state.get("light_mode_toggle") else "dark")


# ---------------------------------------------------------------------------
# Data bootstrap
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_featured_corridors() -> pd.DataFrame:
    with FEATURED_CSV.open(encoding="utf-8-sig", newline="") as fh:
        rows = (line for line in fh if not line.startswith(">"))
        return pd.DataFrame(csv.DictReader(rows))


@st.cache_data(show_spinner=False)
def load_borough_boundaries() -> dict:
    """Outline-only geographic context for the map (§2.1's severity colour
    channel stays uncontested — this layer carries no fill)."""
    return json.loads(BOROUGH_BOUNDARIES.read_text(encoding="utf-8"))


source = resolve_source()

if not source.trustworthy:
    st.markdown(
        '<div class="trust-banner">Running without the committed data file — '
        "figures below are illustrative only. See NEXT-SESSION.md to rebuild "
        "the data layer.</div>",
        unsafe_allow_html=True,
    )

con = get_connection(source.reader) if source.kind != "none" else None

if con is None:
    st.title("NYC Collision Intelligence")
    st.error(
        "No data file present (data/processed/crashes.parquet). "
        "Run `scripts/bake.py --commit` after rebuilding the data layer — "
        "see README.md."
    )
    st.stop()

coverage_lo, coverage_hi = date_bounds(con)
featured = load_featured_corridors()


# ---------------------------------------------------------------------------
# First screen — title, the finding, freshness (PR2, T10)
# ---------------------------------------------------------------------------
#
# There used to be a nine-bullet "What each part of this page does" expander
# here. It sat between the reader and the finding, and one of its bullets was
# false: it said the casualty toggle restricted "every figure on the page",
# when the map never moved with it. The page now opens on the finding instead,
# and each control's own help text says what that control does.

title_col, theme_col = st.columns([5, 1])
with title_col:
    st.markdown(
        '<h1 style="margin-bottom:0.1rem">NYC Collision Intelligence</h1>'
        # 34rem keeps the line under ~75 characters at 1440px; 64rem measured
        # 131, nearly double what the eye can track back to the margin.
        '<p style="color:var(--ink-dim);font-size:1rem;margin-top:0;max-width:34rem">'
        "Chronic-risk prioritisation for NYC DOT. Ranks streets by "
        "<strong>expected</strong> harm (Empirical Bayes) and keeps the crashes "
        "borough-level views drop."
        "</p>",
        unsafe_allow_html=True,
    )
with theme_col:
    # No explicit st.rerun() here — Streamlit already reruns the whole script
    # on any widget change, and this widget's own `key` is what makes
    # st.session_state["light_mode_toggle"] available at the top of the NEXT
    # run, before theme.inject() is called. Forcing a second manual rerun
    # right after reading the value raced against Streamlit's own automatic
    # one and intermittently corrupted the render (page went blank until a
    # full reload) — found while testing this exact toggle live.
    st.toggle(
        "Light mode", key="light_mode_toggle",
        help="Switch the page between the dark workspace theme this app "
             "ships with and a light, print-friendlier palette. Every colour "
             "keeps the same meaning in both — only the background flips.",
    )

# THE FINDING. Computed once per source from the UNFILTERED data — never from
# crashes_filtered, so no control on this page can move it. Every number in
# the sentence below comes from finding_frames; none is typed.
finding = presentation.completeness_finding(
    *finding_frames(con, presentation.finding_cache_key(source.label)), featured)

if finding is not None and finding.headline is not None:
    h = finding.headline
    shown = ("no traffic deaths" if h.killed_reported == 0
             else f"{h.killed_reported:,} traffic death"
                  + ("" if h.killed_reported == 1 else "s"))
    claim_col, table_col = st.columns([3, 2], gap="large")
    with claim_col:
        st.markdown(
            '<div class="finding-claim">'
            f'<p class="finding-big">On the {h.label}, a borough-level crash view '
            f"shows {shown}. There have been <strong>{h.killed:,}</strong>.</p>"
            '<p class="finding-sub">'
            f"{finding.city_killed_dropped:,} of the city’s "
            f"{finding.city_killed:,} traffic deaths "
            f"({finding.city_pct_dropped:.1f}%) are in crashes NYPD recorded with "
            "no borough. Every borough-level view drops them. This one keeps them. "
            f"Observed deaths, {finding.first_crash:%Y-%m-%d} to "
            f"{finding.last_crash:%Y-%m-%d}, before any filter below."
            "</p></div>",
            unsafe_allow_html=True,
        )
    with table_col:
        # THE STATIC FINDING TABLE (T11, decision 10). The same numbers the
        # reveal would demonstrate, stated flat so a cold reader has them
        # before touching anything. A real <table>, not st.dataframe: the
        # dataframe is a canvas, and this is the text statement of the finding.
        # Whether the reveal gets built is judged against this table on the
        # deployed URL — see TODOS.md "The interactive reveal".
        body = "".join(
            "<tr>"
            f'<th scope="row">{r.label}'
            f'<span class="finding-class">{r.road_class}</span></th>'
            f"<td>{r.killed:,}</td>"
            f'<td class="{"finding-zero" if r.killed and not r.killed_reported else ""}">'
            f"{r.killed_reported:,}</td>"
            "</tr>"
            for r in finding.rows
        )
        n_high, n_zero = len(finding.highways), len(finding.highways_at_zero)
        st.markdown(
            '<table class="finding-table">'
            "<caption>Observed traffic deaths on the "
            f"{len(finding.rows)} featured corridors, all years</caption>"
            '<thead><tr><th scope="col">Corridor</th>'
            '<th scope="col">Deaths</th>'
            '<th scope="col">In a borough-level view</th></tr></thead>'
            f"<tbody>{body}</tbody>"
            '<tfoot><tr><th scope="row">All featured</th>'
            f"<td>{finding.featured_killed:,}</td>"
            f"<td>{finding.featured_killed - finding.featured_hidden:,}</td>"
            "</tr></tfoot></table>"
            '<p class="finding-note">'
            f"A borough-level view hides {finding.featured_hidden:,} of these "
            f"{finding.featured_killed:,} deaths. {n_zero} of the {n_high} "
            "featured highways show none at all."
            "</p>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Freshness line — persistent, every screen, §0.1 / §5
# ---------------------------------------------------------------------------

fresh_col, why_col, check_col = st.columns([5, 1, 1])
with fresh_col:
    st.markdown(
        f'<span style="color:var(--ink-dim);font-size:0.875rem">'
        f"{freshness_line(coverage_hi)}</span>",
        unsafe_allow_html=True,
    )
with why_col:
    with st.popover("Why the lag? ▾", use_container_width=True):
        st.markdown(
            "**This is not a real-time feed.** NYPD collision records are a "
            "police-reporting pipeline: a crash is filed, then investigated, "
            "then it reaches the public API — routinely weeks to months "
            "later.\n\n"
            "**This tool is built for chronic-risk prioritisation**, not "
            "incident response. It ranks streets by multi-year expected harm. "
            "That ranking is stable well before every recent crash has "
            "finished being reported, so the lag does not weaken it.\n\n"
            "**What this tool does not claim:** it does not show today's "
            "crashes, and it does not know about a crash that has not yet "
            "reached NYPD's public feed."
        )
with check_col:
    # app/feed.py owns its own popover, its own button and its own result
    # strip — the strip renders OUTSIDE the popover on purpose, driven by
    # session_state, because st.popover closes on the rerun a button click
    # causes and a result rendered inside it could vanish at the moment
    # someone is watching. Do not re-implement the outcome classification
    # here: ten outcomes, each with its own sentence, all in feed.py.
    #
    # This replaced app/live.py, which classified four outcomes and rendered
    # them through st.success / st.warning / st.error. Those three are wrong
    # on this page for a reason DESIGN.md §1 states: green already means
    # low harm on this screen and red already means people died, so a red
    # "feed check failed" banner overstates a dead network AND poaches the
    # severity channel. feed.py draws on the completeness channel instead.
    feed.render_feed_check(coverage_hi)


# ---------------------------------------------------------------------------
# Sticky control bar — corridor, casualty toggle, date range (§2.2, §5)
# ---------------------------------------------------------------------------

st.markdown('<div style="border-top:1px solid var(--line);margin:0.5rem 0"></div>',
            unsafe_allow_html=True)

# --- selection arbitration (decision 8) ------------------------------------
#
# Two widgets can set the corridor and both re-emit on every rerun. LAST
# TOUCHED WINS, and the rule is implemented with callbacks rather than by
# diffing values across runs: a callback fires only for the widget the user
# actually changed, which is exactly what "last touched" means.
#
# ONE value is stored — SELECTED_KEY, always a canonical, never a row index.
# See presentation.canonical_at_row for why the index is the trap.

SELECTED_KEY = "selected_canonical"
DROPDOWN_KEY = "corridor_select"
RANKED_TABLE_KEY = "ranked_table"
DISPLAYED_KEY = "ranked_table_canonicals"
CITY_WIDE = presentation.CITY_WIDE_LABEL

# DISPLAYED_KEY holds the canonicals in the order the ranked table last
# rendered them, written when the table renders and read by its callback.
# Deliberately session_state and not a module global: Streamlit callbacks fire
# at the start of the rerun, before the script body re-executes, so a module
# global would happen to hold the right value through the callback's closure
# over the previous run's namespace. "Happens to" is not a contract worth
# betting a wrong selection on. session_state persistence is documented.


def _on_dropdown_change() -> None:
    label = st.session_state.get(DROPDOWN_KEY)
    canonical = (None if not label or label.startswith("(none")
                 else presentation.canonical_for_label(featured, label))
    st.session_state[SELECTED_KEY] = canonical
    # Clear the table's highlight. Leaving it lit next to a dropdown showing
    # something else is the visible half of the fight this rule settles.
    st.session_state.pop(RANKED_TABLE_KEY, None)


def _on_table_select() -> None:
    rows = presentation.selected_row_indices(st.session_state.get(RANKED_TABLE_KEY))
    if not rows:
        # Deselecting a row is a real action: go back to city-wide rather
        # than silently keeping the last corridor.
        st.session_state[SELECTED_KEY] = None
        st.session_state[DROPDOWN_KEY] = CITY_WIDE
        return
    canonical = presentation.canonical_at_row(
        st.session_state.get(DISPLAYED_KEY, []), rows[0])
    if canonical is None:
        return
    st.session_state[SELECTED_KEY] = canonical
    # The dropdown can only name 12 of 8,931 corridors, so it cannot follow
    # the table anywhere. Reset it to city-wide rather than leave it pointing
    # at a corridor that is no longer the selected one.
    st.session_state[DROPDOWN_KEY] = CITY_WIDE


# PRESELECTION (T12). Open on the corridor the headline names, so the drawer,
# the estimator and the export all render populated on first paint instead of
# three "select a corridor above" boxes. The corridor comes from the finding's
# own rule, not a typed name, so the drawer beside the claim is always the
# claim's own example (Belt Pkwy on the committed data, which is EB-matched —
# tests/test_finding.py pins that, so the estimator opens working).
#
# Once per session, behind a sentinel. Seeding whenever SELECTED_KEY is empty
# would undo a user's deliberate choice of city-wide on the next rerun. Both
# keys are written before their widgets exist this run, which is the only
# point Streamlit allows writing a widget's key.
PRESELECTED_KEY = "preselection_done"
if not st.session_state.get(PRESELECTED_KEY):
    st.session_state[PRESELECTED_KEY] = True
    if finding is not None and finding.headline is not None:
        st.session_state[SELECTED_KEY] = finding.headline.canonical
        st.session_state[DROPDOWN_KEY] = finding.headline.label

corridor_options = [CITY_WIDE] + list(featured["corridor"])
c1, c2, c3 = st.columns([2, 1, 2])
with c1:
    st.selectbox(
        "Featured corridors", corridor_options,
        key=DROPDOWN_KEY, on_change=_on_dropdown_change,
        help="The keyboard and screen-reader equivalent of clicking the map "
             "(DESIGN.md §5). Selecting one opens the drawer. The ranked "
             "table below can select any of the 8,931 corridors, including "
             "the ones this list cannot name.",
    )
with c2:
    casualty_only = st.toggle(
        "Casualty crashes only", value=False,
        # Checked against the code on 2026-09-16, not assumed: the predicate is
        # in sql/base_view.sql, which the drawer and ranked table read. The map
        # reads eb_cells and the finding reads crashes_raw, so neither moves.
        help="Off by default (spec §1.3): includes every crash. On: only rows "
             "with an injury or a death. Applies to the observed figures in the "
             "drawer and the ranked table; the map and the finding at the top "
             "of the page do not change.",
    )
with c3:
    picked_range = st.date_input(
        "Date range", value=(coverage_lo, coverage_hi),
        min_value=coverage_lo, max_value=coverage_hi,
        help="Restricts observed figures (crashes, injured, killed) to this "
             "window. Does not change the Empirical Bayes estimate, which is "
             "fit once over its own training/holdout years, or the finding at "
             "the top of the page, which covers every year.",
    )

date_from, date_to = normalize_date_range(picked_range, coverage_lo, coverage_hi)
build_view(con, date_from, date_to, casualty_only)

# ONE resolved value from here down, read from the single stored canonical.
# `selected` is None (city-wide) or a Corridor carrying a display label that
# is never None and never the string "None" — see resolve_corridor.
selected = presentation.resolve_corridor(featured, st.session_state.get(SELECTED_KEY))
selected_canonical = selected.canonical if selected else None
selected_corridor = selected.display if selected else None
set_selection(con, selected_canonical)

# Two keys, not one. `cache_key` carries the canonical and belongs to
# selection_rows, the only query that reads selection_params. `table_key`
# omits it, because corridor_table aggregates every corridor regardless of
# what is selected — keying that on the canonical multiplied identical
# results by 8,931.
cache_key = presentation.query_cache_key(
    source.label, date_from, date_to, casualty_only, selected_canonical)
table_key = presentation.table_cache_key(
    source.label, date_from, date_to, casualty_only)


# ---------------------------------------------------------------------------
# Map + drawer (§2.1, §2.5, §2.7, DESIGN.md §3)
# ---------------------------------------------------------------------------

map_col, drawer_col = st.columns([2, 1], gap="medium")

with map_col:
    # Keyed on the source, NOT on the date range or the casualty toggle, and
    # never on a constant. presentation.map_cache_key documents which is which
    # and why. The colouring happens inside map_cells, so the 77,747-row ramp
    # runs once per key rather than on every rerun.
    cells = map_cells(con, presentation.map_cache_key(source.label))
    if casualty_only:
        # Cell layer colours by EB expected harm, which is casualty-based by
        # construction (scripts/fit_eb.py fits on casualty counts) — the
        # toggle has no further effect on this layer. Documented rather than
        # silently ignored.
        st.caption("The map colours by expected *casualty* harm regardless of "
                   "this toggle — the EB model is fit on casualties.")

    if cells.empty:
        st.info("No scored cells available. Run scripts/fit_eb.py to build "
                "data/raw/eb_cells.parquet.")
    else:
        show_3d = st.toggle(
            "Show as 3D height", value=False,
            help="Off (default): a flat heat map — easiest to read city-wide "
                 "patterns. On: also extrudes each cell by its expected harm.",
        )

        # THE LAYER SEAM (decision 1). Layers are named and assembled in one
        # list, bottom to top, rather than being appended inline among the
        # deck configuration. Decision 1 calls for a second data layer beside
        # the EB one — a completeness layer, showing per cell how much of that
        # cell's harm every borough-level view drops. It is NOT built here,
        # and not because it was forgotten: eb_cells carries no completeness
        # column, so that layer needs the new SQL the plan explicitly defers
        # with the reveal. Inventing a completeness figure to fill the slot
        # would break non-negotiable #1 to satisfy a diagram.
        #
        # What this seam buys is that adding it later is one entry in this
        # list, not a restructure of the deck call.
        #
        #     boundaries   geographic context, no fill
        #     eb_cells     expected harm, severity colour channel
        #     (deferred)   completeness, hatch/texture channel
        layers = []
        if BOROUGH_BOUNDARIES.exists():
            # Thin outline only, no fill — geographic context (which borough
            # is which) without competing with the severity colour channel.
            layers.append(pdk.Layer(
                "GeoJsonLayer",
                data=load_borough_boundaries(),
                stroked=True, filled=False,
                get_line_color=[139, 152, 165, 160],
                line_width_min_pixels=1,
            ))
        layers.append(pdk.Layer(
            "ColumnLayer",
            data=cells,
            get_position="[lon_c, lat_c]",
            get_elevation="eb_estimate" if show_3d else 0,
            elevation_scale=500 if show_3d else 0,
            extruded=show_3d,
            radius=55,
            get_fill_color="color",
            pickable=True,
            auto_highlight=True,
        ))
        view_state = pdk.ViewState(
            latitude=40.72, longitude=-73.94, zoom=9.6,
            pitch=35 if show_3d else 0,
        )
        deck = pdk.Deck(
            layers=layers,
            initial_view_state=view_state,
            map_provider="carto",
            map_style="dark",
            tooltip={"text": "{canonical}\nExpected harm: {eb_estimate}\nObserved (training window): {observed}"},
        )
        st.pydeck_chart(deck, use_container_width=True, height=560)

        legend = presentation.severity_legend_stops(cells["eb_estimate"])
        p50, p90, p98 = legend["p50"], legend["p90"], legend["p98"]
        st.markdown(
            '<div class="legend">'
            '<div class="legend-item">Expected harm per cell '
            '(Empirical Bayes, log scale):</div>'
            '<div class="legend-item" style="flex:1;min-width:220px">'
            '<div style="height:10px;border-radius:4px;background:'
            "linear-gradient(90deg,#2E7D5B,#C9A227,#D97706,#B4232C)\"></div>"
            f'<div style="display:flex;justify-content:space-between;flex-wrap:wrap;'
            f'gap:0.25rem 0.75rem;font-size:0.75rem">'
            f"<span>0</span><span>median {p50:.1f}</span>"
            f"<span>90th pct {p90:.1f}</span><span>98th pct+ {p98:.1f}</span></div>"
            "</div>"
            '<div class="legend-item">Cell ~111m × 84m. Height (if on) is the '
            "same value as colour, not a second variable.</div>"
            "</div>",
            unsafe_allow_html=True,
        )

with drawer_col:
    if selected_canonical is None:
        st.markdown(
            '<div class="info-box">Select a corridor above to open its '
            "detail — casualty crashes, deaths, road class, and the share of "
            "records other tools drop.</div>",
            unsafe_allow_html=True,
        )
    else:
        # No pandas filter here any more. The casualty toggle is applied in
        # sql/base_view.sql, so these rows and the ranked table's rows come
        # from the same filtered view and cannot disagree. See T3 in
        # docs/designs/ui-reveal-cold-open.md.
        detail_rows = query(con, "selection_rows", cache_key)

        rc = road_class.classify(selected.canonical)
        st.markdown(f"## {selected.display}")
        forced = st.selectbox(
            "Road class", ["highway", "bridge", "tunnel", "surface"],
            index=["highway", "bridge", "tunnel", "surface"].index(rc.road_class),
            key=selected.override_key,
            help=f"Basis: {rc.basis}" + (f" — {rc.note}" if rc.note else ""),
        )
        if forced != rc.road_class:
            st.caption(f"⚠ Overridden from '{rc.road_class}' ({rc.basis}) to "
                       f"'{forced}'. Recorded for export.")
        if rc.warning:
            st.caption(f"⚠ {rc.warning}")

        if detail_rows.empty:
            st.info(f"No casualty crashes on {selected_corridor} between "
                    f"{date_from:%Y-%m-%d} and {date_to:%Y-%m-%d}. Widen the "
                    "date range." if casualty_only else
                    f"No crashes on {selected_corridor} in this date range.")
        else:
            n_crashes = len(detail_rows)
            n_injured = int(detail_rows["number_of_persons_injured"].sum())
            n_killed = int(detail_rows["number_of_persons_killed"].sum())
            n_casualty = int((detail_rows["is_fatal"] | detail_rows["is_injury"]).sum())
            other_tools_drop = int((detail_rows["borough_source"] != "reported").sum())

            theme.kpi_row("Crashes", presentation.format_count(n_crashes),
                          "observed, this range")
            theme.kpi_row("Casualty crashes", presentation.format_count(n_casualty),
                          "observed")
            theme.kpi_row("Injured", presentation.format_count(n_injured), "observed")
            theme.kpi_row("Killed", presentation.format_count(n_killed), "observed")

            eb_row = presentation.eb_row_for(
                query(con, "corridor_table", table_key), selected.canonical)
            if presentation.is_eb_matched(eb_row):
                theme.kpi_row(
                    "Expected harm",
                    presentation.format_expected_harm(eb_row["eb_estimate"]),
                    "Empirical Bayes, cell-level rollup — not the ranking unit",
                )
                coverage = eb_row["eb_coverage"]
                if coverage is not None and coverage < LOW_COVERAGE_THRESHOLD:
                    st.warning(
                        f"Only {coverage:.0%} of this corridor's casualties carry "
                        "coordinates, so the estimate above is computed over a "
                        "badly incomplete footprint — most likely a bridge or "
                        "tunnel span, which NYPD does not geocode. Treat "
                        "'expected harm' here as a lower bound, not a full "
                        "estimate."
                    )
            else:
                st.caption("Observed only — no Empirical Bayes match for this corridor.")

            if n_crashes:
                pct = other_tools_drop / n_crashes * 100
                st.markdown(
                    f'<div class="completeness-badge">▨ Includes {other_tools_drop:,} '
                    f"crashes other tools drop ({pct:.0f}%)</div>",
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Ranked corridor table — the accessibility equivalent of the map (§5)
# ---------------------------------------------------------------------------

st.markdown("## Ranked corridors")
st.caption(
    "Text equivalent of the map, carrying the same figures. Ranked by "
    "cell-level Empirical Bayes expected harm where matched, then by "
    "observed crashes. Click a row to open that corridor — this table "
    "reaches all 8,931 corridors, not just the 12 the dropdown names."
)
table = query(con, "corridor_table", table_key)
if table.empty:
    st.info("No corridors in this date range.")
else:
    show = table.copy()
    # Captured BEFORE the ⚠ suffix is appended below, in the order the rows
    # are about to be rendered. _on_table_select resolves the clicked
    # position against this list, so the stored value is a canonical rather
    # than an index that a later re-sort would re-point.
    st.session_state[DISPLAYED_KEY] = list(show["corridor"])
    show["expected harm"] = show["eb_estimate"].where(show["eb_matched"]).round(1)
    low_coverage = presentation.low_coverage_mask(show)
    # The warning rides on the corridor name, not on the figure. Appending it
    # to "expected harm" forced that column to dtype string, which left-aligns
    # it while every other figure in the table right-aligns — the one column a
    # reader most wants to compare down was the one they could not. The caption
    # below already reads "corridor(s) above", so the name is where it belongs.
    show.loc[low_coverage, "corridor"] = show.loc[low_coverage, "corridor"] + " ⚠"
    show = show.rename(columns={
        "corridor": "corridor", "crashes": "crashes",
        "casualty_crashes": "casualty crashes", "injured": "injured",
        "killed": "killed", "other_tools_drop": "records other tools drop",
    })
    st.dataframe(
        show[["corridor", "crashes", "casualty crashes", "injured", "killed",
              "records other tools drop", "expected harm"]],
        use_container_width=True, hide_index=True, height=320,
        key=RANKED_TABLE_KEY,
        selection_mode="single-row",
        on_select=_on_table_select,
        column_config={
            # Without an explicit format the column drops trailing zeros, so
            # 5186.0 renders "5186" beside 3100.2 and the decimal points stop
            # lining up down the one column meant to be compared.
            "expected harm": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    if low_coverage.any():
        st.caption(
            f"⚠ low coverage: {int(low_coverage.sum())} corridor(s) above have "
            f"under {LOW_COVERAGE_THRESHOLD:.0%} coordinate coverage on their "
            "casualties — usually a bridge or tunnel span NYPD does not "
            "geocode. Their expected-harm figure is a lower bound, not a full "
            "estimate."
        )


# ---------------------------------------------------------------------------
# Countermeasure and budget estimator (§3)
# ---------------------------------------------------------------------------

st.markdown('<div style="border-top:1px solid var(--line);margin:1.5rem 0 0.5rem"></div>',
            unsafe_allow_html=True)
st.markdown("## Countermeasure & budget estimator")

export_blocked_reasons: list[str] = []
selected_capex_rows: list[dict] = []

if selected_canonical is None:
    st.markdown(
        '<div class="info-box">Select a corridor above to branch to '
        "highway or surface-street countermeasures.</div>",
        unsafe_allow_html=True,
    )
    export_blocked_reasons.append("no corridor selected")
else:
    rc_final = road_class.classify(selected.canonical)
    forced_road_class = st.session_state.get(selected.override_key,
                                             rc_final.road_class)
    treatments = road_class.treatments_for(
        road_class.RoadClass(canonical=selected.canonical,
                             road_class=forced_road_class,
                             basis=rc_final.basis)
    )

    eb_row = presentation.eb_row_for(
        query(con, "corridor_table", table_key), selected.canonical)

    if not presentation.is_eb_matched(eb_row):
        st.info("Observed only — no Empirical Bayes match for this corridor. "
                "A CMF must multiply an EB baseline (§2.7), so the estimator "
                "is unavailable until this corridor has a matched cell.")
        export_blocked_reasons.append(f"{selected.display} has no EB match")
    else:
        baseline_eb = float(eb_row["eb_estimate"])
        countermeasures = estimator.load_countermeasures()
        cols = st.columns(min(len(treatments), 3))
        for i, key in enumerate(treatments):
            t = countermeasures.get(key)
            with cols[i % len(cols)]:
                with st.container(border=True):
                    if t is None:
                        st.warning(f"{key}: missing from data/countermeasures.csv")
                        export_blocked_reasons.append(f"{key} has no cost/CMF row")
                        continue

                    st.markdown(f"**{t.label}**")
                    include = st.checkbox(
                        "Include in total", key=selected.widget_key(f"inc::{key}"),
                        help="Adds this treatment's CAPEX and expected harm "
                             "avoided into the 'Selected package' total below.",
                    )

                    cmf = st.slider(
                        "CMF", min_value=0.10, max_value=1.00,
                        value=round(t.cmf, 2), step=0.01, key=selected.widget_key(f"cmf::{key}"),
                        help="Crash Modification Factor: a multiplier on "
                             "expected harm, not a percentage — 0.75 means "
                             "harm falls to 75% of baseline (a 25% "
                             f"reduction). Default is the FHWA-sourced value"
                             f"{' (' + t.cmf_setting + ')' if t.cmf_setting else ''}. "
                             "Drag lower to model a stronger treatment.",
                    )
                    if cmf >= 1.0:
                        st.caption("No expected effect at CMF 1.00. Move the slider "
                                   "to estimate a reduction.")
                    else:
                        st.caption(f"CMF {cmf:.2f} ({(1 - cmf) * 100:.0f}% reduction)"
                                   + ("" if t.has_rated_cmf else " — unrated / no dedicated study, see data/countermeasures.csv"))

                    quantity = st.number_input(
                        f"Quantity ({t.unit})" if t.unit else "Quantity",
                        min_value=0.0, value=1.0, step=1.0, key=selected.widget_key(f"qty::{key}"),
                        help=f"How many {t.unit or 'units'} of this treatment "
                             "you're planning. Multiplies the unit cost below "
                             "to get total CAPEX.",
                    )
                    unit_cost = st.number_input(
                        "Unit cost (USD) — planning default, replace with your agency's figure",
                        min_value=0.0, value=float(t.unit_cost_usd), step=100.0,
                        key=selected.widget_key(f"cost::{key}"),
                        help="Editable planning default, not a fact — see "
                             "this treatment's source note below for where "
                             "the starting figure came from.",
                    )
                    if unit_cost == 0:
                        st.caption("Enter a unit cost to see cost per crash avoided.")

                    capex = unit_cost * quantity
                    avoided = estimator.expected_reduction(baseline_eb, cmf)
                    cost_per_crash = estimator.cost_per_unit(capex, avoided)

                    theme.kpi_row("CAPEX", f"${capex:,.0f}")
                    theme.kpi_row("Expected harm avoided",
                                  presentation.format_expected_harm(avoided))
                    theme.kpi_row("Cost per unit avoided",
                                  presentation.format_cost_per_unit(cost_per_crash))
                    st.caption(f"[FHWA CMF Clearinghouse]({t.cmf_source_url})" if t.cmf_source_url else "")

                    if include:
                        selected_capex_rows.append({
                            "treatment": t.label, "cmf": cmf, "quantity": quantity,
                            "unit_cost_usd": unit_cost, "capex": capex,
                            "expected_harm_avoided": avoided, "cost_per_unit": cost_per_crash,
                        })

        if selected_capex_rows:
            total_capex = sum(r["capex"] for r in selected_capex_rows)
            total_avoided = sum(r["expected_harm_avoided"] for r in selected_capex_rows)
            st.markdown("### Selected package")
            theme.kpi_row("Total CAPEX", f"${total_capex:,.0f}")
            theme.kpi_row("Total expected harm avoided",
                          presentation.format_expected_harm(total_avoided))

        st.markdown(
            '<div class="info-box">Planning estimate, not an evaluation. Crash '
            "counts are not adjusted for traffic volume, so high-volume "
            "corridors rank high partly because they are busy. CMFs describe "
            "an average effect across many sites, not a guaranteed outcome at "
            "one. High-crash sites also regress toward the mean, so a naive "
            "before-and-after comparison will over-credit any treatment."
            "</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Export (§3.4)
# ---------------------------------------------------------------------------

st.markdown("## Executive summary export")
if not source.trustworthy:
    export_blocked_reasons.append("data source is not trustworthy")

if export_blocked_reasons:
    st.button("Export PDF", disabled=True)
    st.caption("Fix the section showing an error before exporting. An export "
               "without every figure is a liability. (" +
               "; ".join(export_blocked_reasons) + ")")
else:
    from app.pdf_export import build_summary_pdf

    # `selected.display` rather than the dropdown's label. They are the same
    # string for the 12 featured corridors and different for the other 8,919:
    # the dropdown cannot name those at all, so the label was None and the PDF
    # came out headed "City-wide (no corridor selected)" while every figure in
    # it was scoped to one street. A document that is confidently wrong about
    # its own scope is worse than one that is blank.
    pdf_bytes = build_summary_pdf(
        corridor=selected.display if selected else None,
        canonical=selected.canonical if selected else None,
        date_from=date_from,
        date_to=date_to,
        casualty_only=casualty_only,
        coverage_hi=coverage_hi,
        road_class_forced=(st.session_state.get(selected.override_key)
                           if selected else None),
        treatments=selected_capex_rows,
    )
    st.download_button(
        "Export PDF", data=pdf_bytes,
        file_name=f"nyc-collision-summary-{selected_canonical or 'citywide'}.pdf",
        mime="application/pdf",
    )
