"""Tests for sql/corridor_table.sql and the low-coverage flag it feeds.

Regression coverage for a real bug: `coverage` (a data-completeness ratio) can
be populated for a corridor that was never matched to the EB fit at all
(`eb_matched = False`), because completeness is computed independently of
whether LION had a street to score. The first cut of the ranked-table warning
counted those too and flagged 1,206 corridors instead of the real 75 —
thousands of ordinary unscored side streets alongside the handful of actual
bridge/tunnel cases the warning exists to catch.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.data import build_view, get_connection, query, resolve_source

LOW_COVERAGE_THRESHOLD = 0.5


def _corridor_table() -> pd.DataFrame:
    source = resolve_source()
    con = get_connection(source.reader)
    build_view(con, date(2019, 1, 1), date(2026, 6, 11))
    return query.__wrapped__(con, "corridor_table", ("test",))


def test_coverage_can_be_populated_without_a_match():
    # Documents the surprising precondition the bug above depended on: this
    # is expected behaviour of the data, not itself a defect.
    table = _corridor_table()
    unmatched_with_coverage = table[~table["eb_matched"] & table["eb_coverage"].notna()]
    assert len(unmatched_with_coverage) > 0


def test_low_coverage_flag_requires_eb_matched():
    table = _corridor_table()
    low_coverage = (
        table["eb_matched"]
        & table["eb_coverage"].notna()
        & (table["eb_coverage"] < LOW_COVERAGE_THRESHOLD)
    )
    # The real number, independently re-measured against data/eb_corridors.csv
    # directly: 75 matched corridors under 50% coverage. Gating on eb_matched
    # is what keeps this from also catching the ~1,131 unmatched corridors
    # that happen to carry a coverage ratio.
    assert low_coverage.sum() == 75
    assert set(low_coverage[low_coverage].index).issubset(
        set(table[table["eb_matched"]].index)
    )


def test_belt_pkwy_is_not_flagged_low_coverage():
    # Sanity anchor: a well-geocoded surface-adjacent highway should never
    # trip this warning.
    table = _corridor_table()
    row = table[table["corridor"] == "BELT PKWY"].iloc[0]
    assert row["eb_matched"]
    assert row["eb_coverage"] >= LOW_COVERAGE_THRESHOLD


def test_brooklyn_bridge_is_flagged_low_coverage():
    # NYPD does not geocode crashes on a span — the canonical example from
    # NEXT-SESSION.md's "bridge-shaped hole" finding.
    table = _corridor_table()
    row = table[table["corridor"] == "BROOKLYN BRIDGE"].iloc[0]
    assert row["eb_matched"]
    assert row["eb_coverage"] < LOW_COVERAGE_THRESHOLD
