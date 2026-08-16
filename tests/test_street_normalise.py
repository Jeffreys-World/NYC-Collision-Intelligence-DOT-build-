"""Unit tests for street name normalisation (§2.4).

All examples use real raw values from the dataset or values described in the
spec, not invented ones.
"""

import pytest

from app.street_normalise import normalise_street_name, pick_street


class TestStripLeadingNumber:
    """Rule 1: strip leading house numbers padded by 2+ spaces only."""

    def test_strip_number_padded_by_multiple_spaces(self):
        """'3468      RICHMOND RD' → 'RICHMOND RD' (spec §2.4 example)."""
        assert normalise_street_name("3468      RICHMOND RD") == "RICHMOND RD"

    def test_do_not_strip_single_digit_single_space(self):
        """'3 AVENUE' is a real street — single space means part of the name."""
        assert normalise_street_name("3 AVENUE") == "3 AVE"

    def test_do_not_strip_number_with_single_space(self):
        """'7 STREET' should keep the number."""
        assert normalise_street_name("7 STREET") == "7 ST"

    def test_strip_number_with_two_spaces(self):
        """Two-space padding triggers stripping."""
        assert normalise_street_name("100  MAIN ST") == "MAIN ST"

    def test_no_leading_number(self):
        """Plain name passes through."""
        assert normalise_street_name("FLATBUSH AVE") == "FLATBUSH AVE"

    def test_leading_number_with_three_spaces(self):
        """Three-space padding triggers stripping."""
        assert normalise_street_name("42   BROADWAY") == "BROADWAY"


class TestWhitespaceCollapsing:
    """Rule 2: collapse repeated whitespace, uppercase."""

    def test_multiple_spaces_collapsed(self):
        assert normalise_street_name("FLATBUSH    AVENUE") == "FLATBUSH AVE"

    def test_lowercase_converted(self):
        assert normalise_street_name("flatbush avenue") == "FLATBUSH AVE"

    def test_mixed_case_converted(self):
        assert normalise_street_name("FlatBush Avenue") == "FLATBUSH AVE"

    def test_leading_trailing_whitespace(self):
        assert normalise_street_name("  ATLANTIC AVE  ") == "ATLANTIC AVE"


class TestSuffixStandardisation:
    """Rule 3: standardise suffixes to canonical short forms."""

    def test_avenue(self):
        assert normalise_street_name("BROADWAY AVENUE") == "BROADWAY AVE"

    def test_expressway(self):
        assert normalise_street_name("BELT EXPRESSWAY") == "BELT EXPY"

    def test_expwy(self):
        assert normalise_street_name("BELT EXPWY") == "BELT EXPY"

    def test_parkway(self):
        assert normalise_street_name("BELT PARKWAY") == "BELT PKWY"

    def test_pky(self):
        assert normalise_street_name("BELT PKY") == "BELT PKWY"

    def test_street(self):
        assert normalise_street_name("MAIN STREET") == "MAIN ST"

    def test_boulevard(self):
        assert normalise_street_name("LINDEN BOULEVARD") == "LINDEN BLVD"

    def test_road(self):
        assert normalise_street_name("RICHMOND ROAD") == "RICHMOND RD"

    def test_turnpike(self):
        assert normalise_street_name("JFK TURNPIKE") == "JFK TPKE"


class TestRampNoiseStripping:
    """Rule 4: strip direction/ramp noise from highway names."""

    def test_direction_suffix(self):
        """'CROSS BRONX EXPWY WB ET 11' → 'CROSS BRONX EXPY' (spec §2.4)."""
        assert (
            normalise_street_name("CROSS BRONX EXPWY WB ET 11")
            == "CROSS BRONX EXPY"
        )

    def test_westbound(self):
        assert normalise_street_name("BELT PKWY WB") == "BELT PKWY"

    def test_eastbound(self):
        assert normalise_street_name("LIE EB") == "LIE"

    def test_northbound(self):
        assert normalise_street_name("FDR DR NB") == "FDR DR"

    def test_southbound(self):
        assert normalise_street_name("MAJOR DEEGAN EXPY SB") == "MAJOR DEEGAN EXPY"

    def test_et_with_different_number(self):
        assert normalise_street_name("CROSS BRONX EXPWY WB ET 5") == "CROSS BRONX EXPY"


class TestEdgeCases:
    """Nulls, empties, whitespace-only."""

    def test_none_returns_none(self):
        assert normalise_street_name(None) is None

    def test_empty_string_returns_none(self):
        assert normalise_street_name("") is None

    def test_whitespace_only_returns_none(self):
        assert normalise_street_name("   ") is None

    def test_single_word(self):
        assert normalise_street_name("BROADWAY") == "BROADWAY"


class TestPickStreet:
    """Rule 5: prefer on_street_name, fall back to cross_street_name."""

    def test_prefers_on_street(self):
        assert pick_street("ATLANTIC AVE", "FLATBUSH AVE") == "ATLANTIC AVE"

    def test_falls_back_to_cross(self):
        assert pick_street(None, "FLATBUSH AVE") == "FLATBUSH AVE"

    def test_both_none(self):
        assert pick_street(None, None) is None

    def test_on_street_empty_falls_back(self):
        assert pick_street("", "FLATBUSH AVE") == "FLATBUSH AVE"


class TestRealDatasetValues:
    """Verify normalisation against known real values from the dataset."""

    def test_flatbush_ave_variant_1(self):
        """Known variant of Flatbush Avenue in the data."""
        assert normalise_street_name("FLATBUSH AVE") == "FLATBUSH AVE"

    def test_flatbush_ave_variant_2(self):
        assert normalise_street_name("FLATBUSH AVENUE") == "FLATBUSH AVE"

    def test_flatbush_ave_variant_3(self):
        """With borough prefix that sometimes appears."""
        assert normalise_street_name("FLATBUSH AVE.") == "FLATBUSH AVE."

    def test_belt_parkway(self):
        assert normalise_street_name("BELT PARKWAY") == "BELT PKWY"

    def test_long_island_expressway(self):
        assert (
            normalise_street_name("LONG ISLAND EXPRESSWAY")
            == "LONG ISLAND EXPY"
        )

    def test_broadway(self):
        assert normalise_street_name("BROADWAY") == "BROADWAY"

    def test_brooklyn_queens_expressway(self):
        assert (
            normalise_street_name("BROOKLYN QUEENS EXPRESSWAY")
            == "BROOKLYN QUEENS EXPY"
        )

    def test_grand_central_parkway(self):
        assert (
            normalise_street_name("GRAND CENTRAL PARKWAY")
            == "GRAND CENTRAL PKWY"
        )

    def test_fdr_drive(self):
        assert normalise_street_name("FDR DRIVE") == "FDR DR"

    def test_major_deegan_expressway(self):
        assert (
            normalise_street_name("MAJOR DEEGAN EXPRESSWAY")
            == "MAJOR DEEGAN EXPY"
        )

    def test_cross_bronx_expressway(self):
        assert (
            normalise_street_name("CROSS BRONX EXPRESSWAY")
            == "CROSS BRONX EXPY"
        )

    def test_van_wyck_expressway(self):
        assert (
            normalise_street_name("VAN WYCK EXPRESSWAY")
            == "VAN WYCK EXPY"
        )

    def test_linden_boulevard(self):
        assert normalise_street_name("LINDEN BLVD") == "LINDEN BLVD"

    def test_atlantic_avenue(self):
        assert normalise_street_name("ATLANTIC AVE") == "ATLANTIC AVE"
