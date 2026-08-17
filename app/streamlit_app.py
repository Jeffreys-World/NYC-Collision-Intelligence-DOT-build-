"""NYC Collision Intelligence — DOT build. Entry point.

Layout is DESIGN.md §3: freshness line, sticky control bar, map (≥65% width)
beside the drawer as a real `st.columns` column. See CLAUDE_CODE_PROMPT.md §7
for the demo sequence this screen has to support end to end.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

# `streamlit run app/streamlit_app.py` puts app/ on sys.path, not the repo
# root, so `from app import ...` fails with ModuleNotFoundError. Insert the
# root before any sibling-package import.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import pydeck as pdk
import streamlit as st

from app import estimator, live, road_class, theme
from app.data import (
    build_view,
    date_bounds,
    freshness_line,
    get_connection,
    normalize_date_range,
    query,
    resolve_source,
    set_selection,
)

ROOT = Path(__file__).resolve().parent.parent
FEATURED_CSV = ROOT / "data" / "featured_corridors.csv"

# scripts/fit_eb.py prints a warning list of corridors whose EB estimate sits
# over a badly incomplete coordinate footprint (bridges and tunnels above
# all — NYPD does not geocode crashes on a span, see the bridge-shaped-hole
# finding in NEXT-SESSION.md). 0.5 is the same cut point that list uses: below
# it, a corridor's `eb_estimate` is a real number over less than half its
# actual harm, and presenting it without saying so is exactly the §4.2
# failure the coverage columns exist to prevent.
LOW_COVERAGE_THRESHOLD = 0.5

st.set_page_config(page_title="NYC Collision Intelligence — DOT", layout="wide")
theme.inject()


# ---------------------------------------------------------------------------
# Data bootstrap
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_featured_corridors() -> pd.DataFrame:
    with FEATURED_CSV.open(encoding="utf-8-sig", newline="") as fh:
        rows = (line for line in fh if not line.startswith(">"))
        return pd.DataFrame(csv.DictReader(rows))


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
# Freshness line — persistent, every screen, §0.1 / §5
# ---------------------------------------------------------------------------

fresh_col, popover_col = st.columns([6, 1])
with fresh_col:
    st.markdown(
        f'<span style="color:var(--ink-dim);font-size:0.875rem">'
        f"{freshness_line(coverage_hi)}</span>",
        unsafe_allow_html=True,
    )
with popover_col:
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
        if st.button("Check the live feed for anything newer", key="check_feed_btn"):
            with st.spinner("Querying the NYPD feed…"):
                check = live.check_feed(coverage_hi)
            if check.outcome == live.NO_NEWER:
                st.success(check.headline)
            elif check.outcome == live.NEWER:
                st.warning(check.headline)
            else:
                st.error(check.headline)
            st.caption(check.detail)


# ---------------------------------------------------------------------------
# Sticky control bar — corridor, casualty toggle, date range (§2.2, §5)
# ---------------------------------------------------------------------------

st.markdown('<div style="border-top:1px solid var(--line);margin:0.5rem 0"></div>',
            unsafe_allow_html=True)

corridor_options = ["(none — city-wide)"] + list(featured["corridor"])
c1, c2, c3 = st.columns([2, 1, 2])
with c1:
    picked_label = st.selectbox(
        "Featured corridors", corridor_options,
        help="The keyboard and screen-reader equivalent of clicking the map "
             "(DESIGN.md §5). Selecting one opens the drawer.",
    )
with c2:
    casualty_only = st.toggle(
        "Casualty crashes only", value=False,
        help="Off by default (spec §1.3): includes every crash. On: only rows "
             "with an injury or a death.",
    )
with c3:
    picked_range = st.date_input(
        "Date range", value=(coverage_lo, coverage_hi),
        min_value=coverage_lo, max_value=coverage_hi,
    )

date_from, date_to = normalize_date_range(picked_range, coverage_lo, coverage_hi)
build_view(con, date_from, date_to)

selected_corridor = None if picked_label.startswith("(none") else picked_label
selected_canonical = None
if selected_corridor is not None:
    match = featured.loc[featured["corridor"] == selected_corridor, "canonical"]
    selected_canonical = match.iloc[0] if len(match) else None
set_selection(con, selected_canonical)

cache_key = (source.label, str(date_from), str(date_to), casualty_only, selected_canonical)


# ---------------------------------------------------------------------------
# Map + drawer (§2.1, §2.5, §2.7, DESIGN.md §3)
# ---------------------------------------------------------------------------

map_col, drawer_col = st.columns([2, 1], gap="medium")

with map_col:
    cells = query(con, "cell_map", ("cell_map",))
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
        vmax = max(cells["eb_estimate"].quantile(0.98), 0.01)
        cells = cells.assign(
            norm=(cells["eb_estimate"].clip(upper=vmax) / vmax).clip(0, 1)
        )

        def _color(n: float) -> list[int]:
            # green -> amber -> orange -> red, DESIGN.md §1 severity ramp.
            stops = [(46, 125, 91), (201, 162, 39), (217, 119, 6), (180, 35, 44)]
            idx = min(int(n * (len(stops) - 1)), len(stops) - 2)
            frac = n * (len(stops) - 1) - idx
            a, b = stops[idx], stops[idx + 1]
            return [int(a[i] + (b[i] - a[i]) * frac) for i in range(3)] + [
                int(90 + 140 * n)
            ]

        cells = cells.assign(color=cells["norm"].map(_color))
        layer = pdk.Layer(
            "ColumnLayer",
            data=cells,
            get_position="[lon_c, lat_c]",
            get_elevation="eb_estimate",
            elevation_scale=400,
            radius=45,
            get_fill_color="color",
            pickable=True,
            auto_highlight=True,
        )
        view_state = pdk.ViewState(latitude=40.72, longitude=-73.94, zoom=9.6, pitch=35)
        deck = pdk.Deck(
            layers=[layer],
            initial_view_state=view_state,
            map_style=None,
            tooltip={"text": "{canonical}\nExpected harm: {eb_estimate}\nObserved (training): {observed}"},
        )
        st.pydeck_chart(deck, use_container_width=True, height=560)

    st.markdown(
        '<div class="legend">'
        '<div class="legend-item"><span class="legend-swatch" '
        'style="background:var(--sev-1)"></span>Low expected harm</div>'
        '<div class="legend-item"><span class="legend-swatch" '
        'style="background:var(--sev-4)"></span>High expected harm</div>'
        '<div class="legend-item">Height and colour both encode the '
        "Empirical Bayes estimate, per cell (~111m × 84m)</div>"
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
        detail_rows = query(con, "selection_rows", cache_key)
        if casualty_only:
            detail_rows = detail_rows[detail_rows["is_fatal"] | detail_rows["is_injury"]]

        rc = road_class.classify(selected_canonical)
        override_key = f"road_class_override::{selected_canonical}"
        st.markdown(f"### {selected_corridor}")
        forced = st.selectbox(
            "Road class", ["highway", "bridge", "tunnel", "surface"],
            index=["highway", "bridge", "tunnel", "surface"].index(rc.road_class),
            key=override_key,
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

            theme.kpi_row("Crashes", f"{n_crashes:,}", "observed, this range")
            theme.kpi_row("Casualty crashes", f"{n_casualty:,}", "observed")
            theme.kpi_row("Injured", f"{n_injured:,}", "observed")
            theme.kpi_row("Killed", f"{n_killed:,}", "observed")

            corridor_eb = query(con, "corridor_table", cache_key)
            eb_row = corridor_eb[corridor_eb["corridor"] == selected_canonical]
            if len(eb_row) and bool(eb_row.iloc[0]["eb_matched"]):
                theme.kpi_row(
                    "Expected harm", f"{eb_row.iloc[0]['eb_estimate']:.1f}",
                    "Empirical Bayes, cell-level rollup — not the ranking unit",
                )
                coverage = eb_row.iloc[0]["eb_coverage"]
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

st.markdown("### Ranked corridors")
st.caption(
    "Text equivalent of the map, carrying the same figures. Ranked by "
    "cell-level Empirical Bayes expected harm where matched, then by "
    "observed crashes."
)
table = query(con, "corridor_table", cache_key)
if table.empty:
    st.info("No corridors in this date range.")
else:
    show = table.copy()
    show["expected harm"] = show["eb_estimate"].where(show["eb_matched"]).round(1)
    # eb_coverage is a data-completeness ratio and can be populated even for
    # an UNMATCHED corridor (no EB fit at all) — gate on eb_matched too, or
    # thousands of never-scored minor streets get flagged as "low coverage"
    # alongside the handful of real bridge/tunnel cases this is meant to catch.
    low_coverage = (show["eb_matched"] & show["eb_coverage"].notna()
                    & (show["eb_coverage"] < LOW_COVERAGE_THRESHOLD))
    show["expected harm"] = show["expected harm"].astype("string")
    show.loc[low_coverage, "expected harm"] = (
        show.loc[low_coverage, "expected harm"] + " ⚠ low coverage"
    )
    show = show.rename(columns={
        "corridor": "corridor", "crashes": "crashes",
        "casualty_crashes": "casualty crashes", "injured": "injured",
        "killed": "killed", "other_tools_drop": "records other tools drop",
    })
    st.dataframe(
        show[["corridor", "crashes", "casualty crashes", "injured", "killed",
              "records other tools drop", "expected harm"]],
        use_container_width=True, hide_index=True, height=320,
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
st.markdown("### Countermeasure & budget estimator")

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
    rc_final = road_class.classify(selected_canonical)
    forced_road_class = st.session_state.get(f"road_class_override::{selected_canonical}",
                                              rc_final.road_class)
    treatments = road_class.treatments_for(
        road_class.RoadClass(canonical=selected_canonical, road_class=forced_road_class,
                              basis=rc_final.basis)
    )

    corridor_eb = query(con, "corridor_table", cache_key)
    eb_row = corridor_eb[corridor_eb["corridor"] == selected_canonical]
    eb_matched = len(eb_row) and bool(eb_row.iloc[0]["eb_matched"])

    if not eb_matched:
        st.info("Observed only — no Empirical Bayes match for this corridor. "
                "A CMF must multiply an EB baseline (§2.7), so the estimator "
                "is unavailable until this corridor has a matched cell.")
        export_blocked_reasons.append(f"{selected_corridor} has no EB match")
    else:
        baseline_eb = float(eb_row.iloc[0]["eb_estimate"])
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
                    include = st.checkbox("Include in total", key=f"inc::{key}::{selected_canonical}")

                    cmf = st.slider(
                        "CMF", min_value=0.10, max_value=1.00,
                        value=round(t.cmf, 2), step=0.01, key=f"cmf::{key}::{selected_canonical}",
                        help=f"Source: FHWA CMF Clearinghouse{' (' + t.cmf_setting + ')' if t.cmf_setting else ''}. "
                             "Star ratings vary by setting.",
                    )
                    if cmf >= 1.0:
                        st.caption("No expected effect at CMF 1.00. Move the slider "
                                   "to estimate a reduction.")
                    else:
                        st.caption(f"CMF {cmf:.2f} ({(1 - cmf) * 100:.0f}% reduction)"
                                   + ("" if t.has_rated_cmf else " — unrated / no dedicated study, see data/countermeasures.csv"))

                    quantity = st.number_input(
                        f"Quantity ({t.unit})" if t.unit else "Quantity",
                        min_value=0.0, value=1.0, step=1.0, key=f"qty::{key}::{selected_canonical}",
                    )
                    unit_cost = st.number_input(
                        "Unit cost (USD) — planning default, replace with your agency's figure",
                        min_value=0.0, value=float(t.unit_cost_usd), step=100.0,
                        key=f"cost::{key}::{selected_canonical}",
                    )
                    if unit_cost == 0:
                        st.caption("Enter a unit cost to see cost per crash avoided.")

                    capex = unit_cost * quantity
                    avoided = estimator.expected_reduction(baseline_eb, cmf)
                    cost_per_crash = estimator.cost_per_unit(capex, avoided)

                    theme.kpi_row("CAPEX", f"${capex:,.0f}")
                    theme.kpi_row("Expected harm avoided", f"{avoided:.1f}")
                    theme.kpi_row(
                        "Cost per unit avoided",
                        f"${cost_per_crash:,.0f}" if cost_per_crash is not None else "—",
                    )
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
            st.markdown("#### Selected package")
            theme.kpi_row("Total CAPEX", f"${total_capex:,.0f}")
            theme.kpi_row("Total expected harm avoided", f"{total_avoided:.1f}")

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

st.markdown("### Executive summary export")
if not source.trustworthy:
    export_blocked_reasons.append("data source is not trustworthy")

if export_blocked_reasons:
    st.button("Export PDF", disabled=True)
    st.caption("Fix the section showing an error before exporting. An export "
               "without every figure is a liability. (" +
               "; ".join(export_blocked_reasons) + ")")
else:
    from app.pdf_export import build_summary_pdf

    pdf_bytes = build_summary_pdf(
        corridor=selected_corridor,
        canonical=selected_canonical,
        date_from=date_from,
        date_to=date_to,
        casualty_only=casualty_only,
        coverage_hi=coverage_hi,
        road_class_forced=st.session_state.get(
            f"road_class_override::{selected_canonical}") if selected_canonical else None,
        treatments=selected_capex_rows,
    )
    st.download_button(
        "Export PDF", data=pdf_bytes,
        file_name=f"nyc-collision-summary-{selected_canonical or 'citywide'}.pdf",
        mime="application/pdf",
    )
