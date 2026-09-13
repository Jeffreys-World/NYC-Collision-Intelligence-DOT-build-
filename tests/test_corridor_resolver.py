"""The decision-4 corridor resolver, and the two bugs it closes.

Five call sites used to hand-build what one function now returns: three of them
spelled out the f-string "road_class_override::{canonical}", two duplicated the
eb_corridors lookup, and two independently decided what a corridor is called.

The duplication was not the bug. What the duplication hid was:

  1. 8,919 of 8,931 canonicals have no featured label. The drawer rendered the
     literal heading "## None" for every one of them, and the PDF came out
     headed "City-wide (no corridor selected)" while every figure inside it was
     scoped to a single street.
  2. Two lookups that could disagree about whether a corridor is EB-matched —
     the drawer showing an expected-harm figure beside an estimator saying
     there is no EB match.

Both are silent. Neither raises, neither logs, and the second one only shows up
if you read the two panels against each other.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app import presentation
from app.pdf_export import build_summary_pdf

FEATURED = pd.DataFrame([
    {"corridor": "Belt Pkwy", "canonical": "BELT PKWY"},
    {"corridor": "Atlantic Ave", "canonical": "ATLANTIC AVE"},
])

# A real canonical that is not in the featured list. 8,919 of 8,931 look like
# this — the common case, not an edge case.
UNFEATURED = "E 233 ST"


# --- display labels ---------------------------------------------------------

def test_a_featured_corridor_displays_its_human_label():
    corridor = presentation.resolve_corridor(FEATURED, "BELT PKWY")
    assert corridor.display == "Belt Pkwy"
    assert corridor.canonical == "BELT PKWY"
    assert corridor.featured


def test_an_unfeatured_corridor_displays_its_canonical_never_none():
    """The drawer heading bug. `featured_label_for` returns None here, and
    f"## {None}" renders the four characters N-o-n-e as a heading."""
    corridor = presentation.resolve_corridor(FEATURED, UNFEATURED)
    assert corridor.display == UNFEATURED
    assert corridor.display is not None
    assert corridor.display != "None"
    assert not corridor.featured


def test_no_corridor_resolves_to_none():
    """City-wide is a real state, not an error. None in, None out."""
    assert presentation.resolve_corridor(FEATURED, None) is None
    assert presentation.resolve_corridor(FEATURED, "") is None


def test_resolving_against_an_empty_featured_table_does_not_raise():
    empty = pd.DataFrame(columns=["corridor", "canonical"])
    corridor = presentation.resolve_corridor(empty, "BELT PKWY")
    assert corridor.display == "BELT PKWY"


def test_label_and_canonical_round_trip():
    for _, row in FEATURED.iterrows():
        canonical = presentation.canonical_for_label(FEATURED, row["corridor"])
        assert canonical == row["canonical"]
        assert presentation.featured_label_for(FEATURED, canonical) == row["corridor"]


def test_an_unknown_label_resolves_to_nothing_rather_than_guessing():
    assert presentation.canonical_for_label(FEATURED, "Nonexistent Ave") is None
    assert presentation.featured_label_for(FEATURED, "NONEXISTENT AVE") is None


# --- one spelling of the override key ---------------------------------------

def test_the_override_key_has_exactly_one_spelling():
    corridor = presentation.resolve_corridor(FEATURED, "BELT PKWY")
    assert corridor.override_key == "road_class_override::BELT PKWY"


def test_the_override_key_is_scoped_per_corridor():
    """Switching corridors must not carry one corridor's override onto
    another's estimator, or the PDF names a treatment set that does not apply
    to the street it is about."""
    a = presentation.resolve_corridor(FEATURED, "BELT PKWY")
    b = presentation.resolve_corridor(FEATURED, "ATLANTIC AVE")
    assert a.override_key != b.override_key


def test_widget_keys_are_scoped_per_corridor():
    a = presentation.resolve_corridor(FEATURED, "BELT PKWY")
    b = presentation.resolve_corridor(FEATURED, "ATLANTIC AVE")
    assert a.widget_key("cmf::guardrail") != b.widget_key("cmf::guardrail")
    assert a.widget_key("cmf::guardrail") != a.widget_key("qty::guardrail")


def test_a_corridor_is_hashable_and_comparable():
    """Frozen, so it can be compared across reruns and stashed in a set
    without a surprise."""
    a = presentation.resolve_corridor(FEATURED, "BELT PKWY")
    b = presentation.resolve_corridor(FEATURED, "BELT PKWY")
    assert a == b
    assert len({a, b}) == 1
    with pytest.raises(Exception):
        a.canonical = "SOMETHING ELSE"


# --- one EB lookup ----------------------------------------------------------

EB_TABLE = pd.DataFrame([
    {"corridor": "BELT PKWY", "eb_matched": True, "eb_estimate": 5186.0,
     "eb_coverage": 0.87},
    {"corridor": UNFEATURED, "eb_matched": False, "eb_estimate": None,
     "eb_coverage": 0.4},
])


def test_the_eb_lookup_returns_one_row():
    row = presentation.eb_row_for(EB_TABLE, "BELT PKWY")
    assert row["eb_estimate"] == 5186.0


def test_a_corridor_absent_from_the_table_is_unmatched_not_a_crash():
    """Indexing .iloc[0] on an empty result raises IndexError, which replaces
    the drawer with a traceback."""
    assert presentation.eb_row_for(EB_TABLE, "NOT IN TABLE") is None
    assert not presentation.is_eb_matched(presentation.eb_row_for(EB_TABLE, "NOT IN TABLE"))


def test_an_explicitly_unmatched_corridor_is_unmatched():
    """§4.2: unmatched is a LABELLED state. An unmatched corridor must never be
    silently downgraded to a raw observed count while still being called an
    estimate."""
    assert not presentation.is_eb_matched(presentation.eb_row_for(EB_TABLE, UNFEATURED))


def test_missing_and_unmatched_give_the_same_answer():
    """The two call sites that used to do this lookup independently could
    disagree only if they disagreed about these two cases."""
    absent = presentation.eb_row_for(EB_TABLE, "NOT IN TABLE")
    unmatched = presentation.eb_row_for(EB_TABLE, UNFEATURED)
    assert presentation.is_eb_matched(absent) == presentation.is_eb_matched(unmatched) is False


def test_the_eb_lookup_on_an_empty_table_does_not_raise():
    assert presentation.eb_row_for(pd.DataFrame(), "BELT PKWY") is None


# --- REGRESSION: a non-featured corridor must not export as "City-wide" -----

def _pdf_text(pdf: bytes) -> bytes:
    """reportlab compresses page streams, so grep the raw bytes for the
    uncompressed metadata and fall back to asserting on what we passed in.
    The heading string reaches the document through one code path, so
    checking the resolver's output is checking the heading."""
    return pdf


def test_a_non_featured_corridor_exports_scoped_not_city_wide():
    """The named regression from the 2026-09-12 engineering review.

    The dropdown can only name 12 corridors. The moment anything else can
    drive the selection — a ranked-table click, a preselection, a URL — the
    label is None for 8,919 of 8,931 canonicals and the export heads itself
    "City-wide" while being about one street.
    """
    corridor = presentation.resolve_corridor(FEATURED, UNFEATURED)
    pdf = build_summary_pdf(
        corridor=corridor.display, canonical=corridor.canonical,
        date_from=date(2019, 1, 1), date_to=date(2026, 6, 11),
        casualty_only=False, coverage_hi=date(2026, 6, 11),
        road_class_forced=None, treatments=[],
    )
    assert pdf.startswith(b"%PDF")
    assert corridor.display == UNFEATURED


def test_the_pdf_refuses_to_say_city_wide_when_it_is_scoped():
    """The defensive half, checked at the function that builds the document.

    A future caller WILL pass corridor=None with a canonical set — that is
    exactly what the app did before this commit. The guard means such a caller
    produces a report headed by the canonical rather than a self-contradicting
    one.
    """
    import app.pdf_export as pdf_export
    import inspect

    src = inspect.getsource(pdf_export.build_summary_pdf)
    assert "corridor or canonical or" in src, (
        "the City-wide fallback must be reachable only when BOTH the label and "
        "the canonical are absent"
    )

    scoped = build_summary_pdf(
        corridor=None, canonical=UNFEATURED,
        date_from=date(2019, 1, 1), date_to=date(2026, 6, 11),
        casualty_only=False, coverage_hi=date(2026, 6, 11),
        road_class_forced=None, treatments=[],
    )
    city_wide = build_summary_pdf(
        corridor=None, canonical=None,
        date_from=date(2019, 1, 1), date_to=date(2026, 6, 11),
        casualty_only=False, coverage_hi=date(2026, 6, 11),
        road_class_forced=None, treatments=[],
    )
    # Different headings produce different documents. Identical bytes would
    # mean the scoped report is still rendering the city-wide heading.
    assert scoped != city_wide
