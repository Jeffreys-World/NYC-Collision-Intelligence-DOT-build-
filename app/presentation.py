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
from dataclasses import dataclass
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


# ------------------------------------------------------- the corridor resolver
#
# Five call sites, one function, one stored key format. Before this existed,
# three sites hand-built the f-string "road_class_override::{canonical}" and
# two duplicated the eb_corridors lookup:
#
#     drawer heading        ─┐
#     drawer road class     ─┤
#     estimator branch      ─┼──►  resolve_corridor()  ──►  Corridor
#     estimator eb lookup   ─┤          │
#     PDF export            ─┘          ├─ .canonical    the join key, always
#                                       ├─ .display      never None, never "None"
#                                       └─ .override_key one spelling, one place
#
# The bug this closes is not the duplication, it is what the duplication hid.
# 8,919 of 8,931 canonicals have no featured label. The drawer rendered
# "## None" for every one of them, and the PDF came out headed "City-wide (no
# corridor selected)" while scoped to a single corridor — a confidently wrong
# document, which is worse than a blank one.

@dataclass(frozen=True)
class Corridor:
    """One selected corridor, resolved once.

    `canonical` is the join key used by every query. `display` is what a human
    reads, and it is NEVER None: a corridor with no featured label displays as
    its own canonical name, which is an ordinary street name in caps, not an
    error state.
    """

    canonical: str
    display: str
    featured: bool

    @property
    def override_key(self) -> str:
        """The session_state key holding this corridor's road-class override.

        One spelling, one place. Three call sites used to hand-build this
        f-string, and a typo in any of them would have silently dropped a
        user's override on its way to the PDF — an export that is confidently
        wrong about which treatment set applies.
        """
        return f"road_class_override::{self.canonical}"

    def widget_key(self, prefix: str) -> str:
        """Per-corridor widget keys (include / cmf / qty / cost).

        Scoped to the canonical so switching corridors does not carry one
        corridor's slider values onto another's estimator.
        """
        return f"{prefix}::{self.canonical}"


def featured_label_for(featured: pd.DataFrame, canonical: str | None) -> str | None:
    """The human label for a canonical, or None if it is not a featured one."""
    if canonical is None or featured.empty:
        return None
    match = featured.loc[featured["canonical"] == canonical, "corridor"]
    return str(match.iloc[0]) if len(match) else None


def canonical_for_label(featured: pd.DataFrame, label: str | None) -> str | None:
    """The canonical behind a dropdown label, or None."""
    if label is None or featured.empty:
        return None
    match = featured.loc[featured["corridor"] == label, "canonical"]
    return str(match.iloc[0]) if len(match) else None


def resolve_corridor(featured: pd.DataFrame, canonical: str | None) -> Corridor | None:
    """The one way to turn a canonical into something renderable.

    None in, None out — a city-wide view is a real state, not an error. Every
    other case returns a Corridor whose `display` is safe to put in a heading.
    """
    if not canonical:
        return None
    label = featured_label_for(featured, canonical)
    return Corridor(canonical=canonical, display=label or canonical,
                    featured=label is not None)


def eb_row_for(table: pd.DataFrame, canonical: str | None) -> pd.Series | None:
    """This corridor's row in the EB-joined corridor table, or None.

    Two call sites did this lookup independently (the drawer and the
    estimator), and they could disagree about whether a corridor was matched
    if either one's filter drifted — the drawer showing an expected-harm
    figure beside an estimator saying there is no EB match.
    """
    if canonical is None or table.empty:
        return None
    match = table[table["corridor"] == canonical]
    return match.iloc[0] if len(match) else None


def is_eb_matched(row: pd.Series | None) -> bool:
    """§4.2: unmatched is a LABELLED state, never a silent downgrade to a raw
    observed count still being called an estimate. A missing row and an
    explicit eb_matched=False are the same answer here: no."""
    return row is not None and bool(row["eb_matched"])


# ------------------------------------------------------- selection arbitration
#
# The dropdown and the ranked table can each set the corridor, and Streamlit
# re-runs the whole script on any widget change, so both re-emit their value on
# every run. Without a rule they fight: the page renders one corridor's map
# beside another's drawer, and which one wins depends on render order rather
# than on anything the user did.
#
# The rule is LAST TOUCHED WINS, implemented with widget callbacks rather than
# by comparing values across runs. A callback fires only for the widget the
# user actually changed, before the rerun, which is what "last touched" means.
#
# And only the CANONICAL is ever stored. Never the row index — see
# canonical_at_row.

CITY_WIDE_LABEL = "(none — city-wide)"


def selected_row_indices(widget_state) -> list[int]:
    """Row indices out of st.dataframe's selection state, defensively.

    The shape is {"selection": {"rows": [...], "columns": [...]}}. Parsed with
    .get() at every level because a widget that has never been interacted with
    returns None, and a Streamlit version bump that adds a level would
    otherwise raise inside a callback — where an exception is invisible.
    """
    if not isinstance(widget_state, dict):
        return []
    selection = widget_state.get("selection")
    if not isinstance(selection, dict):
        return []
    rows = selection.get("rows")
    return [int(r) for r in rows] if isinstance(rows, list) else []


def canonical_at_row(displayed: list[str], row: int) -> str | None:
    """The canonical at a displayed row position, bounds-checked.

    THE TRAP THIS EXISTS FOR: st.dataframe returns a POSITIONAL index into the
    frame as rendered. The ranked table re-sorts whenever the casualty toggle
    or the date range changes, so a stored index quietly points at a different
    corridor after any re-sort — the page keeps showing a selection, it is
    just the wrong one, and nothing anywhere raises.

    So the index is resolved to a canonical HERE, at the moment of the click,
    against the frame that was actually on screen, and the canonical is what
    gets stored. The index is never persisted and never re-read.

    Out of range returns None rather than raising: this runs inside a widget
    callback, where an exception has nowhere to surface.
    """
    if 0 <= row < len(displayed):
        return displayed[row]
    return None


# ---------------------------------------------------------------- cache keys

def query_cache_key(source_label: str, date_from: date, date_to: date,
                    casualty_only: bool, canonical: str | None) -> tuple:
    """The key for a query that depends on WHICH corridor is selected.

    Only `selection_rows` does. Dates are stringified because a `date` is
    hashable but its repr is what makes a cache miss debuggable in a log.
    """
    return (source_label, str(date_from), str(date_to),
            bool(casualty_only), canonical)


def table_cache_key(source_label: str, date_from: date, date_to: date,
                    casualty_only: bool) -> tuple:
    """The key for a query that reads `crashes_filtered` city-wide.

    The canonical is absent because `corridor_table` does not read
    `selection_params` — it aggregates every corridor regardless of what is
    selected. Including the canonical anyway (which is what the single shared
    key used to do) multiplied the cache entries for an identical result by
    the 8,931 corridors that can be selected, in a ~1 GB container. That is
    the same unbounded-growth failure decision 2 set max_entries for, arriving
    through the key instead of through the ceiling.
    """
    return (source_label, str(date_from), str(date_to), bool(casualty_only))


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
