"""Pure presentation logic. NO `streamlit` import, by design and by test.

Everything here was inline in app/streamlit_app.py, which is a straight-line
script: 632 lines that only run inside a Streamlit session, so none of it could
be exercised by a test. The colour ramp, the number formatting, the low-
coverage rule and the cache-key construction are all total functions of their
arguments and all of them had bugs that shipped (see the notes on
`format_cost_per_unit` and `low_coverage_mask`). Extracting them is what makes
those bugs regressions instead of surprises.

The rule this module enforces structurally: if it imports streamlit, it does
not belong here. tests/test_presentation.py asserts that.

    streamlit_app.py                 presentation.py
    ────────────────────             ──────────────────────────────
    map layer          ──────────►   severity_norm() ─► severity_color()
    ranked table       ──────────►   low_coverage_mask()
    drawer + estimator ──────────►   format_count() / format_expected_harm()
                                     format_cost_per_unit()
    every cached query ──────────►   query_cache_key()

`streamlit_app.py` keeps the st.* calls and the layout. This module keeps
everything that has a right answer.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd

# scripts/fit_eb.py prints a warning list of corridors whose EB estimate sits
# over a badly incomplete coordinate footprint (bridges and tunnels above all —
# NYPD does not geocode crashes on a span, see the bridge-shaped-hole finding
# in NEXT-SESSION.md). 0.5 is the same cut point that list uses: below it, a
# corridor's `eb_estimate` is a real number over less than half its actual
# harm, and presenting it without saying so is exactly the §4.2 failure the
# coverage columns exist to prevent.
LOW_COVERAGE_THRESHOLD = 0.5

# DESIGN.md §1 severity ramp: green -> amber -> orange -> red.
SEVERITY_STOPS: tuple[tuple[int, int, int], ...] = (
    (46, 125, 91), (201, 162, 39), (217, 119, 6), (180, 35, 44),
)

# The 98th percentile is the top of the scale, not the maximum. eb_estimate is
# heavily right-skewed (median ~1.2, 98th pct ~18) and a handful of extreme
# corridors would otherwise compress every other cell into the first stop.
SEVERITY_CLIP_QUANTILE = 0.98


# --------------------------------------------------------------- the map ramp

def severity_color(norm: float) -> list[int]:
    """One normalised value (0..1) to an RGBA list for pydeck.

    Alpha rises with the value so a dense field of low-harm cells does not
    hide the handful of high-harm ones underneath it.
    """
    norm = min(max(float(norm), 0.0), 1.0)
    span = len(SEVERITY_STOPS) - 1
    idx = min(int(norm * span), span - 1)
    frac = norm * span - idx
    lo, hi = SEVERITY_STOPS[idx], SEVERITY_STOPS[idx + 1]
    return [int(lo[i] + (hi[i] - lo[i]) * frac) for i in range(3)] + [
        int(140 + 100 * norm)
    ]


def severity_norm(values: pd.Series) -> pd.Series:
    """Expected harm to a 0..1 position on the ramp, on a log scale.

    A linear scale leaves almost every cell the same shade of green with a few
    red outliers, because the distribution is right-skewed by roughly an order
    of magnitude. log1p spreads the range out so the map reads as a gradient
    rather than a scatter of hot spots on a flat green field.

    An empty input returns an empty series rather than raising: an environment
    without the EB fit gets an empty map with its own message, not a traceback.
    """
    if values.empty:
        return values.astype(float)
    vmax = max(float(values.quantile(SEVERITY_CLIP_QUANTILE)), 0.01)
    log_vmax = math.log1p(vmax)
    return (values.clip(upper=vmax).map(math.log1p) / log_vmax).clip(0, 1)


def with_severity_colors(cells: pd.DataFrame, column: str = "eb_estimate") -> pd.DataFrame:
    """`cells` plus `norm` and `color`. Returns a new frame; never mutates.

    Called from inside app/data.py's cached map loader so 77,747 rows are
    mapped through Python once per cache key rather than on every rerun.
    Streamlit reruns the whole script on any widget change, so before this
    moved inside the cache, dragging a cost slider re-ran the ramp over every
    cell in the city.
    """
    if cells.empty:
        return cells.assign(norm=pd.Series(dtype=float),
                            color=pd.Series(dtype=object))
    norm = severity_norm(cells[column])
    return cells.assign(norm=norm, color=norm.map(severity_color))


def severity_legend_stops(values: pd.Series) -> dict[str, float]:
    """The three figures the map legend prints, computed once."""
    if values.empty:
        return {"p50": 0.0, "p90": 0.0, "p98": 0.0}
    return {
        "p50": float(values.quantile(0.50)),
        "p90": float(values.quantile(0.90)),
        "p98": float(values.quantile(0.98)),
    }


# ------------------------------------------------------------ the ranked table

def low_coverage_mask(table: pd.DataFrame,
                      threshold: float = LOW_COVERAGE_THRESHOLD) -> pd.Series:
    """Which corridors carry a coverage warning.

    `eb_matched` is part of the condition, and that is the whole point. A
    coverage ratio can be populated for a corridor that was never matched to
    the EB fit at all, because completeness is computed independently of
    whether LION had a street to score. The first cut of this rule left
    eb_matched out and flagged 1,206 corridors instead of the real 75 —
    thousands of ordinary unscored side streets alongside the handful of actual
    bridge and tunnel cases the warning exists to catch.
    """
    if table.empty:
        return pd.Series(dtype=bool, index=table.index)
    return (table["eb_matched"].fillna(False).astype(bool)
            & table["eb_coverage"].notna()
            & (table["eb_coverage"] < threshold))


# -------------------------------------------------------------- number format

def format_count(value) -> str:
    """Thousands-separated, or an em dash for nothing. Never a bare '0' for
    a value that is absent rather than zero."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{int(value):,}"


def format_expected_harm(value) -> str:
    """One decimal, always — including the trailing zero.

    Without the explicit decimal the ranked table dropped it, so 5186.0
    rendered "5186" beside 3100.2 and the decimal points stopped lining up
    down the one column the table is ranked by.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{float(value):.1f}"


def format_cost_per_unit(value) -> str:
    """Cents below $100, whole dollars above, em dash for undefined.

    Whole dollars rendered every sub-dollar result as "$0", which reads as a
    broken metric rather than a small one — and at the estimator's default
    quantity of 1.00 that is the COMMON case, not an edge: $92 of guardrail
    against 2489.3 expected harm avoided is $0.04, not nothing. Both
    countermeasures on the page reported "$0" until this rule existed.
    """
    if value is None or (isinstance(value, float)
                         and (math.isnan(value) or math.isinf(value))):
        return "—"
    value = float(value)
    if abs(value) < 100:
        return f"${value:,.2f}"
    return f"${value:,.0f}"


# ---------------------------------------------------------------- cache keys

def query_cache_key(source_label: str, date_from: date, date_to: date,
                    casualty_only: bool, canonical: str | None) -> tuple:
    """The key for anything reading `crashes_filtered`.

    Every value that can change the result, and nothing that cannot. Dates are
    stringified because a `date` is hashable but its repr is what makes a cache
    miss debuggable in a log.
    """
    return (source_label, str(date_from), str(date_to),
            bool(casualty_only), canonical)


def map_cache_key(source_label: str) -> tuple:
    """The key for the cell map, which reads `eb_cells`, NOT `crashes_filtered`.

    This is deliberately NOT query_cache_key, and the difference is the bug it
    replaces. The map used to be fetched with a hardcoded ("cell_map",), a
    constant — so any new map state would have served a stale frame forever,
    and no unit test can catch that.

    The date range and the casualty toggle are absent on purpose, not by
    omission. eb_cells is the EB fit's own output over its own multi-year
    train/holdout window; it does not move when the user drags the date picker,
    and the EB model is fit on casualties regardless of the toggle (the map
    caption says so). The source label IS here, because dropping a re-baked
    Parquet in must invalidate the map along with everything else.

    Anything that DOES change what the map draws — a second layer, a reveal
    state, a colour-by switch — belongs in this tuple, in the same commit that
    adds it. That rule is the only gate; there is no test for it.
    """
    return ("cell_map", source_label)
