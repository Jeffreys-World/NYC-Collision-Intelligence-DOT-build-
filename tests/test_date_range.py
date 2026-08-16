"""
Regression: ISSUE-003 — the date picker crashed the entire dashboard.
Found by /qa on 2026-08-09 in the seed repo; ported here 2026-08-16.

st.date_input in range mode returns a 1-tuple between the first and second
click. The app unpacked it straight into two names, so the first click on the
only filter in the app raised ValueError and replaced every chart with a red
traceback.

Ported unchanged because the bug is a property of Streamlit, not of that app.
"""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from data import normalize_date_range  # noqa: E402

LO, HI = date(2019, 1, 1), date(2025, 12, 31)


def test_single_date_tuple_does_not_raise():
    """The exact bug: one click mid-selection returns a 1-tuple.

    Before the fix this raised
    "ValueError: not enough values to unpack (expected 2, got 1)".
    """
    picked = (date(2019, 1, 15),)
    lo, hi = normalize_date_range(picked, LO, HI)
    assert lo == date(2019, 1, 15)
    assert hi == date(2019, 1, 15), "a half-selected range must collapse to that one day"


def test_normal_two_date_range_passes_through():
    lo, hi = normalize_date_range((date(2020, 3, 1), date(2021, 6, 30)), LO, HI)
    assert (lo, hi) == (date(2020, 3, 1), date(2021, 6, 30))


def test_cleared_selection_falls_back_to_full_range():
    """An empty tuple must not produce a range that selects nothing."""
    assert normalize_date_range((), LO, HI) == (LO, HI)
    assert normalize_date_range(None, LO, HI) == (LO, HI)


def test_bare_date_object_is_accepted():
    """Non-range mode, or a host returning a plain date rather than a tuple."""
    assert normalize_date_range(date(2022, 7, 4), LO, HI) == (date(2022, 7, 4),) * 2


def test_list_is_handled_like_a_tuple():
    """Streamlit has returned lists in some versions; shape, not type, matters."""
    assert normalize_date_range([date(2020, 1, 1), date(2020, 12, 31)], LO, HI) == (
        date(2020, 1, 1), date(2020, 12, 31)
    )


@pytest.mark.parametrize("picked", [
    (date(2019, 5, 5),),
    [date(2019, 5, 5)],
    (),
    [],
    None,
    date(2019, 5, 5),
    (date(2019, 5, 5), date(2019, 6, 6)),
])
def test_always_returns_two_unpackable_values(picked):
    """The contract the app depends on: this can always be unpacked into two."""
    a, b = normalize_date_range(picked, LO, HI)
    assert a is not None and b is not None
    assert a <= b, "start must never be after end"
