"""Tests for the §3.4 executive summary export."""

from __future__ import annotations

from datetime import date

from app.pdf_export import build_summary_pdf


def test_builds_valid_pdf_bytes_with_no_treatments():
    pdf = build_summary_pdf(
        corridor="Belt Pkwy", canonical="BELT PKWY",
        date_from=date(2019, 1, 1), date_to=date(2026, 6, 11),
        casualty_only=False, coverage_hi=date(2026, 6, 11),
        road_class_forced=None, treatments=[],
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500


def test_builds_valid_pdf_with_treatments_and_override():
    pdf = build_summary_pdf(
        corridor="Atlantic Ave", canonical="ATLANTIC AVE",
        date_from=date(2019, 1, 1), date_to=date(2026, 6, 11),
        casualty_only=True, coverage_hi=date(2026, 6, 11),
        road_class_forced="surface",
        treatments=[{
            "treatment": "Road diet", "cmf": 0.53, "quantity": 1.0,
            "unit_cost_usd": 32500.0, "capex": 32500.0,
            "expected_harm_avoided": 12.3, "cost_per_unit": 2642.3,
        }],
    )
    assert pdf.startswith(b"%PDF")


def test_no_corridor_selected_still_builds():
    pdf = build_summary_pdf(
        corridor=None, canonical=None,
        date_from=date(2019, 1, 1), date_to=date(2026, 6, 11),
        casualty_only=False, coverage_hi=date(2026, 6, 11),
        road_class_forced=None, treatments=[],
    )
    assert pdf.startswith(b"%PDF")
