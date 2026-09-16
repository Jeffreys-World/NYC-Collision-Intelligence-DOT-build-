"""The completeness finding on the first screen (PR2, T10/T11).

Three properties matter, and each has a failure that would ship quietly:

1. It is chosen by rule. The headline names a corridor; a hand-picked name is a
   typed figure by another route (non-negotiable #1).
2. It does not move. It reads crashes_raw, not crashes_filtered, so no filter on
   the page can change it. A finding that shifts when someone drags the date
   picker is not a finding.
3. It agrees with scripts/verify_figures.py, which computes the city-wide pair
   independently from `borough IS NULL` rather than from `borough_source`.

No figure from the real data is typed into this file. The integration tests
compare two computations against each other, never against a literal.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app import presentation
from app.presentation import FindingRow, completeness_finding, headline_row

ROOT = Path(__file__).resolve().parent.parent


def _row(label, killed, killed_reported, road_class="highway", crashes=10):
    return FindingRow(label=label, canonical=label.upper(), road_class=road_class,
                      crashes=crashes, killed=killed, killed_reported=killed_reported)


def _featured(*rows):
    return pd.DataFrame(rows, columns=["corridor", "canonical", "expected_class"])


def _citywide(killed=100, dropped=40):
    return pd.DataFrame([{"first_crash": pd.Timestamp("2019-01-01"),
                          "last_crash": pd.Timestamp("2026-06-11"),
                          "killed": killed, "killed_dropped": dropped}])


# --- the headline is chosen by rule ------------------------------------------

def test_headline_prefers_the_deadliest_corridor_shown_at_zero():
    rows = (_row("Surface", killed=90, killed_reported=10, road_class="surface"),
            _row("Small", killed=5, killed_reported=0),
            _row("Big", killed=50, killed_reported=0))
    assert headline_row(rows).label == "Big"


def test_headline_falls_back_to_most_hidden_when_nothing_is_at_zero():
    """A weaker true sentence, never a false one: with no corridor at zero, the
    headline cannot say 'shows no traffic deaths'."""
    rows = (_row("A", killed=30, killed_reported=25),
            _row("B", killed=20, killed_reported=5))
    chosen = headline_row(rows)
    assert chosen.label == "B" and chosen.killed_reported > 0


def test_no_headline_when_nothing_is_hidden():
    rows = (_row("A", killed=3, killed_reported=3),)
    assert headline_row(rows) is None


def test_headline_ties_break_on_featured_order():
    rows = (_row("First", killed=12, killed_reported=0),
            _row("Second", killed=12, killed_reported=0))
    assert headline_row(rows).label == "First"


# --- the join onto the featured list ------------------------------------------

def test_a_featured_corridor_with_no_crashes_renders_explicit_zeros():
    corridors = pd.DataFrame([{"canonical": "A", "crashes": 5, "killed": 2,
                               "crashes_reported": 1, "killed_reported": 0}])
    featured = _featured(("Alpha", "A", "highway"), ("Ghost", "G", "surface"))
    f = completeness_finding(corridors, _citywide(), featured)
    ghost = next(r for r in f.rows if r.label == "Ghost")
    assert (ghost.crashes, ghost.killed, ghost.killed_reported, ghost.hidden) == (0, 0, 0, 0)
    assert len(f.rows) == 2


def test_rows_sort_by_deaths_and_totals_add_up():
    corridors = pd.DataFrame([
        {"canonical": "A", "crashes": 5, "killed": 2, "crashes_reported": 1, "killed_reported": 1},
        {"canonical": "B", "crashes": 9, "killed": 7, "crashes_reported": 0, "killed_reported": 0},
    ])
    f = completeness_finding(corridors, _citywide(),
                             _featured(("Alpha", "A", "surface"), ("Beta", "B", "highway")))
    assert [r.label for r in f.rows] == ["Beta", "Alpha"]
    assert f.featured_killed == 9 and f.featured_hidden == 8
    assert f.headline.label == "Beta"


def test_a_highway_with_no_deaths_does_not_count_as_shown_at_zero():
    """Zero in the standard view is only a finding if there were deaths to
    drop. Counting an empty highway would inflate 'N highways show zero'."""
    corridors = pd.DataFrame([
        {"canonical": "A", "crashes": 5, "killed": 0, "crashes_reported": 0, "killed_reported": 0},
        {"canonical": "B", "crashes": 9, "killed": 7, "crashes_reported": 0, "killed_reported": 0},
    ])
    f = completeness_finding(corridors, _citywide(),
                             _featured(("Alpha", "A", "highway"), ("Beta", "B", "highway")))
    assert len(f.highways) == 2
    assert [r.label for r in f.highways_at_zero] == ["Beta"]


def test_city_percentage():
    f = completeness_finding(pd.DataFrame(), _citywide(killed=200, dropped=50),
                             _featured(("Alpha", "A", "highway")))
    assert f.city_pct_dropped == pytest.approx(25.0)
    assert f.first_crash == date(2019, 1, 1)


def test_no_finding_without_a_citywide_row():
    assert completeness_finding(pd.DataFrame(), _citywide().iloc[0:0],
                                _featured(("Alpha", "A", "highway"))) is None


def test_the_cache_key_carries_no_filter():
    """The signature is the contract: a key that could take a date range would
    invite routing the query through the filtered view to match it."""
    import inspect
    assert list(inspect.signature(presentation.finding_cache_key).parameters) == ["source_label"]
    assert presentation.finding_cache_key("x") != presentation.map_cache_key("x")


# --- against the committed Parquet ------------------------------------------

@pytest.fixture(scope="module")
def con():
    from app.data import get_connection, resolve_source
    source = resolve_source()
    if source.kind == "none":
        pytest.skip("no committed Parquet in this environment")
    return get_connection.__wrapped__(source.reader)


def _live_finding(con):
    import csv

    from app.data import finding_frames
    featured_csv = ROOT / "data" / "featured_corridors.csv"
    with featured_csv.open(encoding="utf-8-sig", newline="") as fh:
        featured = pd.DataFrame(csv.DictReader(l for l in fh if not l.startswith(">")))
    return completeness_finding(*finding_frames.__wrapped__(con, ("t",)), featured)


def test_no_filter_moves_the_finding(con):
    from app.data import build_view

    build_view(con, date(2019, 1, 1), date(2026, 6, 11), False)
    before = _live_finding(con)
    build_view(con, date(2024, 3, 1), date(2024, 3, 1), True)
    after = _live_finding(con)
    assert before == after
    assert before.headline is not None


def test_citywide_pair_agrees_with_verify_figures(con):
    """Two definitions, one set of rows: the app counts borough_source !=
    'reported', verify_figures.py counts borough IS NULL. If a re-bake ever
    makes those diverge, the headline and the published §0.2 table would state
    different numbers for the same claim."""
    spec = importlib.util.spec_from_file_location(
        "verify_figures", ROOT / "scripts" / "verify_figures.py")
    vf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vf)
    figures = vf.compute(ROOT / "data" / "processed" / "crashes.parquet")

    f = _live_finding(con)
    assert f.city_killed == figures["total_deaths"]
    assert f.city_killed_dropped == figures["deaths_in_borough_less_rows"]


def test_featured_table_agrees_with_verify_figures(con):
    """The static table's figures against verify_figures.compute_finding, which
    uses `borough IS NOT NULL` and its own tie-break rather than the app's code.
    Two code paths, compared with each other, no literal in between."""
    spec = importlib.util.spec_from_file_location(
        "verify_figures", ROOT / "scripts" / "verify_figures.py")
    vf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vf)
    expected = vf.compute_finding(ROOT / "data" / "processed" / "crashes.parquet")

    f = _live_finding(con)
    assert f.headline.canonical == expected["headline_corridor"]
    assert f.headline.killed == expected["headline_corridor_deaths"]
    assert f.headline.killed_reported == expected["headline_corridor_deaths_reported"]
    assert f.featured_killed == expected["featured_deaths"]
    assert f.featured_hidden == expected["featured_deaths_hidden"]
    assert len(f.highways) == expected["featured_highways"]
    assert len(f.highways_at_zero) == expected["featured_highways_at_zero"]


def test_the_preselected_corridor_opens_with_a_working_estimator(con):
    """T12 preselects the headline corridor. The estimator and export are gated
    on an EB match, so preselecting an unmatched corridor would trade three
    empty boxes for a disabled estimator and a blocked export on first paint."""
    from app.data import build_view, query

    f = _live_finding(con)
    build_view(con, date(2019, 1, 1), date(2026, 6, 11), False)
    table = query.__wrapped__(con, "corridor_table", ("t-preselect",))
    row = presentation.eb_row_for(table, f.headline.canonical)
    assert presentation.is_eb_matched(row)
