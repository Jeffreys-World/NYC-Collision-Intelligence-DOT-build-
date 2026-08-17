"""Tests for the §3.2 countermeasure estimator."""

from __future__ import annotations

from app.estimator import (
    cost_per_unit,
    expected_reduction,
    load_countermeasures,
)
from app.road_class import HIGHWAY_TREATMENTS, SURFACE_TREATMENTS


def test_every_treatment_named_in_road_class_has_a_row():
    table = load_countermeasures()
    for key in (*HIGHWAY_TREATMENTS, *SURFACE_TREATMENTS):
        assert key in table, f"{key} is missing from data/countermeasures.csv"


def test_no_row_invents_a_cmf_above_one_without_a_rating():
    # §0.3 #4: every real CMF must be sourced. A CMF of exactly 1.0 with no
    # star rating is the documented "no evidence found" case (daylighting);
    # anything else claiming an effect must carry a rating and a source.
    for t in load_countermeasures().values():
        if t.cmf != 1.0:
            assert t.cmf_star_rating, f"{t.treatment} claims an effect with no CMF rating"
            assert t.cmf_source_url, f"{t.treatment} claims an effect with no source"


def test_daylighting_is_the_documented_gap_not_a_guess():
    table = load_countermeasures()
    daylighting = table["daylighting"]
    assert daylighting.cmf == 1.0
    assert not daylighting.has_rated_cmf


def test_road_diet_and_refuge_island_are_split_and_priced_differently():
    table = load_countermeasures()
    assert table["road_diet"].unit_cost_usd != table["pedestrian_refuge_island"].unit_cost_usd


def test_lpi_and_daylighting_are_cheaper_than_road_diet_by_roughly_an_order_of_magnitude():
    table = load_countermeasures()
    road_diet = table["road_diet"].unit_cost_usd
    assert table["leading_pedestrian_interval"].unit_cost_usd < road_diet / 5
    assert table["daylighting"].unit_cost_usd < road_diet / 5


def test_expected_reduction_applies_cmf_to_the_eb_baseline():
    assert expected_reduction(100.0, 0.75) == 25.0
    assert expected_reduction(100.0, 1.0) == 0.0


def test_expected_reduction_never_negative():
    assert expected_reduction(10.0, 1.5) == 0.0


def test_cost_per_unit_is_none_when_nothing_avoided():
    assert cost_per_unit(50_000.0, 0.0) is None
    assert cost_per_unit(50_000.0, -1.0) is None


def test_cost_per_unit_divides():
    assert cost_per_unit(50_000.0, 25.0) == 2_000.0
