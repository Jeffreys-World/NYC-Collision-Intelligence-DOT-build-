"""Tests for the §3.1 road classification.

Every street name below is a REAL canonical value produced by
app.streets.canonical_street from data/raw/crashes_recovered.parquet, with the
crash counts measured on 2026-08-16. Spec §4.1: tests use real raw values, never
invented ones — an invented name cannot reproduce the failure that matters,
which is a real road landing in the wrong branch.
"""

from __future__ import annotations

import pytest

from app.road_class import (
    HIGHWAY_TREATMENTS,
    SURFACE_TREATMENTS,
    classify,
    limited_access_table,
    treatments_for,
)

# Real limited-access roads, with their crash counts for context.
LIMITED_ACCESS = [
    ("BELT PKWY", 13063),
    ("BROOKLYN QUEENS EXPY", 9004),
    ("GRAND CENTRAL PKWY", 8526),
    ("LONG ISLAND EXPY", 8500),
    ("FDR DR", 6800),
    ("CROSS BRONX EXPY", 6322),
    ("VAN WYCK EXPY", 6224),
    ("MAJOR DEEGAN EXPY", 6006),
    ("CROSS ISLAND PKWY", 5526),
    ("HENRY HUDSON PKWY", 3630),
    ("STATEN ISLAND EXPY", 2863),
    ("NASSAU EXPY", 710),
]

# Surface streets that a name rule or a share rule would misclassify. Each one
# is a measured counter-example, not a hypothetical.
SURFACE_TRAPS = [
    ("HORACE HARDING EXPY", "the LIE's 30 mph service road; named EXPY, LION share 0.00"),
    ("SHORE PKWY", "the Belt Parkway's service road"),
    ("EASTERN PKWY", "surface boulevard, LION share 0.02"),
    ("OCEAN PKWY", "surface boulevard, LION share 0.04"),
    ("KINGS HWY", "named HWY, LION share 0.00"),
    ("PELHAM PKWY", "surface, LION share 0.06"),
    ("UNION TPKE", "surface, LION share 0.01"),
    ("FORT HAMILTON PKWY", "surface, LION share 0.01"),
    ("BAY PKWY", "surface, LION share 0.02"),
    ("ROCKAWAY PKWY", "surface, LION share 0.00"),
    ("BRIDGE ST", "a street named Bridge, in Brooklyn"),
    ("WILLIAMSBRIDGE RD", "contains BRIDGE, is a Bronx surface street"),
    ("BAINBRIDGE AVE", "contains BRIDGE"),
    ("KINGSBRIDGE AVE", "contains BRIDGE"),
    ("E KINGSBRIDGE RD", "contains BRIDGE"),
    ("W KINGSBRIDGE RD", "contains BRIDGE"),
    ("KINGSBRIDGE TERRACE", "contains BRIDGE"),
    ("SUNRISE HWY", "limited access only outside the city; the NYC portion is surface"),
    ("ATLANTIC AVE", "the §7 surface-street contrast to Belt Pkwy"),
    ("BROADWAY", "featured corridor, surface"),
    ("FLATBUSH AVE", "featured corridor, surface"),
    ("LINDEN BLVD", "featured corridor, surface"),
]

BRIDGES = [
    "VERRAZANO BRIDGE UPPER",
    "VERRAZANO BRIDGE LOWER",
    "TRIBOROUGH BRIDGE",
    "BRONX WHITESTONE BRIDGE",
    "THROGS NECK BRIDGE",
    "BROOKLYN BRIDGE",
    "MANHATTAN BR UPPER",
    "WILLIAMSBURG BRIDGE OUTER ROADWA",
    "QUEENSBORO BRIDGE LOWER ROADWAY",
    "ALEXANDER HAMILTON BRIDGE",
]

TUNNELS = ["QUEENS MIDTOWN TUNNEL", "BROOKLYN BATTERY TUNNEL"]


@pytest.mark.parametrize("name,crashes", LIMITED_ACCESS)
def test_limited_access_roads_classify_as_limited_access(name, crashes):
    road = classify(name)
    assert road.is_limited_access, (
        f"{name} ({crashes:,} crashes) must not reach the surface branch — "
        f"§3.1: offering a road diet on it discredits the tool"
    )


@pytest.mark.parametrize("name,why", SURFACE_TRAPS)
def test_surface_streets_are_never_limited_access(name, why):
    road = classify(name)
    assert not road.is_limited_access, f"{name} is surface: {why}"
    assert road.road_class == "surface"
    assert road.basis == "not-listed"


@pytest.mark.parametrize("name", BRIDGES)
def test_bridges_take_the_highway_branch(name):
    road = classify(name)
    assert road.road_class == "bridge"
    assert road.is_limited_access
    assert treatments_for(road) == HIGHWAY_TREATMENTS


@pytest.mark.parametrize("name", TUNNELS)
def test_tunnels_take_the_highway_branch(name):
    road = classify(name)
    assert road.road_class == "tunnel"
    assert road.is_limited_access


def test_horace_harding_is_the_reason_this_is_a_list():
    """The single most important negative case in the file.

    Named EXPY, 1,792 crashes, 64% of them with no borough — and it is the Long
    Island Expressway's service road, posting 30 mph. Both a name rule and a
    share rule put it in the highway branch.
    """
    road = classify("HORACE HARDING EXPY", unlabeled_share=0.64)
    assert road.road_class == "surface"
    assert treatments_for(road) == SURFACE_TREATMENTS
    assert "road_diet" in treatments_for(road)


def test_surface_and_highway_treatment_sets_are_disjoint():
    assert not set(HIGHWAY_TREATMENTS) & set(SURFACE_TREATMENTS)


def test_road_diet_is_never_offered_on_a_limited_access_road():
    for name, _ in LIMITED_ACCESS:
        assert "road_diet" not in treatments_for(classify(name)), name


def test_unlabeled_share_never_changes_the_classification():
    """§3.1: the share is a secondary signal only. It may warn; it may not decide."""
    for share in (0.0, 0.5, 0.95, 1.0):
        assert classify("ATLANTIC AVE", unlabeled_share=share).road_class == "surface"
        assert classify("BELT PKWY", unlabeled_share=share).is_limited_access


def test_high_unlabeled_share_off_the_list_raises_a_named_warning():
    """This is how a road missing from the list gets found."""
    road = classify("SOME UNLISTED RD", unlabeled_share=0.97)
    assert road.road_class == "surface"
    assert road.warning
    assert "SOME UNLISTED RD" in road.warning, "a warning must name the road"


def test_low_unlabeled_share_on_the_list_raises_a_warning():
    road = classify("BELT PKWY", unlabeled_share=0.10)
    assert road.is_limited_access, "the warning must not change the answer"
    assert road.warning
    assert "BELT PKWY" in road.warning


def test_no_warning_when_the_signals_agree():
    assert not classify("BELT PKWY", unlabeled_share=0.98).warning
    assert not classify("ATLANTIC AVE", unlabeled_share=0.11).warning


def test_missing_name_is_surface_and_says_so():
    road = classify(None)
    assert road.road_class == "surface"
    assert road.basis == "not-listed"


def test_lookup_is_case_and_whitespace_insensitive():
    assert classify("  belt pkwy  ").is_limited_access


def test_every_row_carries_a_recognised_class_and_basis():
    for name, row in limited_access_table().items():
        assert row["road_class"] in ("highway", "bridge", "tunnel"), name
        assert row["basis"] in ("lion", "curated"), name


def test_curated_overrides_record_why():
    """A row that contradicts LION must say on what grounds.

    LAURELTON PKWY is the case: LION reports a 0.00 limited-access share for a
    road that is plainly a limited-access parkway. Overriding a measurement
    silently is how a list stops being trustworthy.
    """
    road = classify("LAURELTON PKWY")
    assert road.is_limited_access
    assert road.basis == "curated"
    assert road.note, "a curated override must carry its reasoning"


def test_the_list_stays_small():
    """§3.1 calls this a small, closed, stable set.

    A list that grows without bound has become a rule with extra steps, and
    somebody has started adding roads to make a number come out.
    """
    assert len(limited_access_table()) < 120
