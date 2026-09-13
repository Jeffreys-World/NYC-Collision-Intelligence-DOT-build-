"""Unit coverage for app/presentation.py.

None of this could be tested before. It was inline in app/streamlit_app.py, a
straight-line script that only executes inside a Streamlit session, so the
colour ramp, the number formatting and the low-coverage rule were reachable
only by loading the page and looking at it. Two of them had shipped bugs that a
test this cheap would have caught on the first run.
"""

from __future__ import annotations

import ast
import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app import presentation

ROOT = Path(__file__).resolve().parent.parent


# --- the structural rule that makes this module testable at all -------------

def test_presentation_imports_no_streamlit():
    """The whole point of the module. If it can import streamlit, the next
    edit will, and the logic goes back to being unreachable from a test."""
    src = (ROOT / "app" / "presentation.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(m == "streamlit" or m.startswith("streamlit.")
                   for m in imported), f"streamlit reached presentation.py: {imported}"


# --- the severity ramp ------------------------------------------------------

def test_the_ramp_ends_on_the_design_stops():
    assert presentation.severity_color(0.0)[:3] == [46, 125, 91]
    assert presentation.severity_color(1.0)[:3] == [180, 35, 44]


def test_the_ramp_is_monotonic_in_redness():
    """Higher expected harm must never read as less severe than lower.

    The measure is R minus G, not the raw red channel, and that is not a
    workaround — it is what the DESIGN.md §1 ramp actually encodes. The stops
    run green(46,125,91) -> amber(201,162,39) -> orange(217,119,6) ->
    red(180,35,44), so the red channel RISES to orange and then FALLS into the
    final red, and the green channel rises into amber before collapsing. Amber
    is high in both by construction. R-G runs -79, 39, 98, 145: strictly
    increasing across every stop, which is the severity signal a reader sees.
    """
    redness = [(lambda c: c[0] - c[1])(presentation.severity_color(n / 200))
               for n in range(201)]
    assert redness == sorted(redness)
    assert redness[0] < 0 < redness[-1]


def test_alpha_rises_with_the_value():
    """A dense field of low-harm cells must not hide the high-harm ones."""
    assert presentation.severity_color(0.0)[3] < presentation.severity_color(1.0)[3]


@pytest.mark.parametrize("value", [-5.0, -0.0001, 1.0001, 99.0, float("inf")])
def test_the_ramp_clamps_out_of_range_input(value):
    """An out-of-range norm must not raise or index past the last stop — that
    is a blank map, mid-demo, from one unexpected number."""
    rgba = presentation.severity_color(value)
    assert len(rgba) == 4
    assert all(0 <= channel <= 255 for channel in rgba)


def test_norm_spreads_a_skewed_distribution():
    """The reason for the log scale. eb_estimate is right-skewed by about an
    order of magnitude; on a linear scale the median cell would sit at ~1% of
    the ramp and the whole map would read as one flat green field."""
    skewed = pd.Series([0.1] * 90 + [1.0] * 8 + [500.0, 5000.0])
    norm = presentation.severity_norm(skewed)
    assert 0.0 <= norm.min() and norm.max() <= 1.0
    median_position = float(norm.median())
    linear_median = skewed.median() / skewed.quantile(0.98)
    assert median_position > linear_median * 4


def test_norm_of_an_empty_series_does_not_raise():
    """An environment without the EB fit gets an empty map with its own
    message, not a traceback."""
    assert presentation.severity_norm(pd.Series(dtype=float)).empty


def test_with_severity_colors_does_not_mutate_its_input():
    cells = pd.DataFrame({"eb_estimate": [1.0, 2.0, 3.0]})
    out = presentation.with_severity_colors(cells)
    assert "color" not in cells.columns
    assert list(out.columns) == ["eb_estimate", "norm", "color"]
    assert all(len(c) == 4 for c in out["color"])


def test_with_severity_colors_handles_an_empty_frame():
    out = presentation.with_severity_colors(pd.DataFrame({"eb_estimate": []}))
    assert out.empty
    assert "color" in out.columns


def test_legend_stops_of_an_empty_series_are_zero_not_nan():
    """NaN would render as 'median nan' in the legend."""
    stops = presentation.severity_legend_stops(pd.Series(dtype=float))
    assert stops == {"p50": 0.0, "p90": 0.0, "p98": 0.0}
    assert not any(math.isnan(v) for v in stops.values())


# --- the low-coverage rule --------------------------------------------------

def _table(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["corridor", "eb_matched", "eb_coverage"])


def test_low_coverage_requires_a_match():
    """The bug this rule exists because of. A coverage ratio can be populated
    for a corridor that was never matched to the EB fit at all, because
    completeness is computed independently of whether LION had a street to
    score. Leaving eb_matched out flagged 1,206 corridors instead of 75."""
    table = _table([
        {"corridor": "MATCHED LOW", "eb_matched": True, "eb_coverage": 0.2},
        {"corridor": "UNMATCHED LOW", "eb_matched": False, "eb_coverage": 0.2},
        {"corridor": "MATCHED FINE", "eb_matched": True, "eb_coverage": 0.9},
    ])
    flagged = set(table.loc[presentation.low_coverage_mask(table), "corridor"])
    assert flagged == {"MATCHED LOW"}


def test_low_coverage_ignores_a_missing_ratio():
    table = _table([{"corridor": "NO RATIO", "eb_matched": True, "eb_coverage": None}])
    assert not presentation.low_coverage_mask(table).any()


def test_low_coverage_is_strict_at_the_threshold():
    """Exactly at 0.5 is not flagged. The rule is 'under half'."""
    table = _table([
        {"corridor": "AT", "eb_matched": True, "eb_coverage": 0.5},
        {"corridor": "UNDER", "eb_matched": True, "eb_coverage": 0.4999},
    ])
    flagged = set(table.loc[presentation.low_coverage_mask(table), "corridor"])
    assert flagged == {"UNDER"}


def test_low_coverage_of_an_empty_table_is_an_empty_mask():
    assert not presentation.low_coverage_mask(_table([])).any()


# --- number formatting ------------------------------------------------------

def test_counts_are_thousands_separated():
    assert presentation.format_count(12755) == "12,755"
    assert presentation.format_count(0) == "0"


def test_an_absent_count_is_an_em_dash_not_a_zero():
    """Zero and 'we do not know' are different facts, and this app's whole
    argument is about not conflating them."""
    assert presentation.format_count(None) == "—"
    assert presentation.format_count(float("nan")) == "—"


def test_expected_harm_keeps_its_trailing_zero():
    """Without the explicit decimal the ranked table dropped it, so 5186.0
    rendered '5186' beside 3100.2 and the decimal points stopped lining up
    down the one column the table is ranked by."""
    assert presentation.format_expected_harm(5186.0) == "5186.0"
    assert presentation.format_expected_harm(3100.24) == "3100.2"


def test_a_sub_dollar_cost_is_not_rendered_as_zero():
    """The shipped bug: whole-dollar formatting rendered every result under $1
    as '$0', which reads as a broken metric rather than a small one. At the
    estimator's default quantity of 1.00 that is the common case — both
    countermeasures on the page showed '$0'."""
    assert presentation.format_cost_per_unit(0.037) == "$0.04"
    assert presentation.format_cost_per_unit(0.0092) == "$0.01"
    assert presentation.format_cost_per_unit(0.0) == "$0.00"


def test_a_large_cost_drops_the_cents():
    assert presentation.format_cost_per_unit(1234567.89) == "$1,234,568"
    assert presentation.format_cost_per_unit(99.994) == "$99.99"
    assert presentation.format_cost_per_unit(100.4) == "$100"


def test_an_undefined_cost_is_an_em_dash():
    """cost_per_unit is None when nothing is avoided: dividing by zero harm
    avoided has no answer, and '$0' would claim the treatment is free."""
    assert presentation.format_cost_per_unit(None) == "—"
    assert presentation.format_cost_per_unit(float("nan")) == "—"
    assert presentation.format_cost_per_unit(float("inf")) == "—"


# --- cache keys -------------------------------------------------------------

def test_every_filter_changes_the_query_key():
    base = presentation.query_cache_key(
        "parquet", date(2019, 1, 1), date(2025, 12, 31), False, None)
    variants = [
        presentation.query_cache_key("other", date(2019, 1, 1), date(2025, 12, 31), False, None),
        presentation.query_cache_key("parquet", date(2020, 1, 1), date(2025, 12, 31), False, None),
        presentation.query_cache_key("parquet", date(2019, 1, 1), date(2024, 12, 31), False, None),
        presentation.query_cache_key("parquet", date(2019, 1, 1), date(2025, 12, 31), True, None),
        presentation.query_cache_key("parquet", date(2019, 1, 1), date(2025, 12, 31), False, "BELT PKWY"),
    ]
    assert len(set(variants) | {base}) == 6, "two filters collide on one key"


def test_the_query_key_is_hashable():
    """st.cache_data hashes the key. An unhashable member raises at runtime,
    in the browser, on the first query."""
    hash(presentation.query_cache_key(
        "parquet", date(2019, 1, 1), date(2025, 12, 31), True, "BELT PKWY"))


def test_the_map_key_is_not_a_constant():
    """The bug it replaces: the map was fetched with a hardcoded
    ('cell_map',), so any new map state would have served a stale frame
    forever. No unit test can catch a stale frame; this one catches the
    constant that causes it."""
    a = presentation.map_cache_key("committed 2019-2025 pull")
    b = presentation.map_cache_key("some other source")
    assert a != b


def test_the_map_key_deliberately_ignores_the_date_range():
    """Not an omission. eb_cells is the EB fit's own output over its own
    multi-year train/holdout window; it does not move when the user drags the
    date picker, and the model is fit on casualties regardless of the toggle.
    Adding those to the key would evict the whole 77,747-cell map on every
    filter change for no change in what it draws.
    """
    assert presentation.map_cache_key("x") == presentation.map_cache_key("x")
    assert len(presentation.map_cache_key("x")) == 2
