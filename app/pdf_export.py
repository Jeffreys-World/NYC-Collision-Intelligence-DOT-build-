"""Executive summary export (spec §3.4).

Carries selection geometry, date window, filters applied, unit costs and CMFs
used with their citations, data completeness date, feed date, and the §3.3
caveats — an export without its assumptions attached is a liability. The
caller (app/streamlit_app.py) is responsible for blocking this while any
section is in a degraded state (§4.2); this module has no opinion on that,
it only renders what it is given.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

CAVEAT_TEXT = (
    "Planning estimate, not an evaluation. Crash counts are not adjusted for "
    "traffic volume, so high-volume corridors rank high partly because they "
    "are busy. CMFs describe an average effect across many sites, not a "
    "guaranteed outcome at one. High-crash sites also regress toward the "
    "mean, so a naive before-and-after comparison will over-credit any "
    "treatment."
)

FEED_CAVEAT = (
    "This is not a real-time feed. NYPD collision records are a "
    "police-reporting pipeline; this extract is complete through the date "
    "below, and the public feed's own most recent record is separately "
    "dated. This tool is built for chronic-risk prioritisation over "
    "multi-year patterns, which the reporting lag does not weaken."
)


def build_summary_pdf(
    *,
    corridor: str | None,
    canonical: str | None,
    date_from: date,
    date_to: date,
    casualty_only: bool,
    coverage_hi: date,
    road_class_forced: str | None,
    treatments: list[dict],
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    caveat_style = ParagraphStyle(
        "Caveat", parent=styles["BodyText"], textColor=colors.HexColor("#8B98A5"),
        fontSize=9, leading=12,
    )

    story = []
    story.append(Paragraph("NYC Collision Intelligence — Executive Summary", styles["Title"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Corridor: {corridor or 'City-wide (no corridor selected)'}", styles["Heading2"]))
    if road_class_forced:
        story.append(Paragraph(f"Road class (analyst override): {road_class_forced}",
                                styles["BodyText"]))
    story.append(Spacer(1, 12))

    assumptions = [
        ["Assumption", "Value"],
        ["Date window", f"{date_from:%Y-%m-%d} to {date_to:%Y-%m-%d}"],
        ["Casualty-only filter", "On" if casualty_only else "Off"],
        ["Data complete through", f"{coverage_hi:%Y-%m-%d}"],
        ["Canonical street match", canonical or "—"],
    ]
    tbl = Table(assumptions, colWidths=[2.2 * inch, 3.8 * inch])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161C22")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#2A343E")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 12))

    if treatments:
        story.append(Paragraph("Selected countermeasures", styles["Heading2"]))
        rows = [["Treatment", "CMF", "Qty", "Unit cost", "CAPEX", "Expected harm avoided"]]
        total_capex = 0.0
        total_avoided = 0.0
        for t in treatments:
            rows.append([
                t["treatment"], f"{t['cmf']:.2f}", f"{t['quantity']:g}",
                f"${t['unit_cost_usd']:,.0f}", f"${t['capex']:,.0f}",
                f"{t['expected_harm_avoided']:.1f}",
            ])
            total_capex += t["capex"]
            total_avoided += t["expected_harm_avoided"]
        rows.append(["Total", "", "", "", f"${total_capex:,.0f}", f"{total_avoided:.1f}"])
        ctbl = Table(rows, colWidths=[1.8 * inch, 0.6 * inch, 0.6 * inch,
                                       0.9 * inch, 0.9 * inch, 1.2 * inch])
        ctbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#161C22")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#2A343E")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ]))
        story.append(ctbl)
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "CMFs sourced from the FHWA CMF Clearinghouse; see "
            "data/countermeasures.csv for each treatment's CMF ID, star "
            "rating, measured setting and source URL.", caveat_style))
        story.append(Spacer(1, 12))
    else:
        story.append(Paragraph("No countermeasures selected.", styles["BodyText"]))
        story.append(Spacer(1, 12))

    story.append(Paragraph("Caveats", styles["Heading2"]))
    story.append(Paragraph(CAVEAT_TEXT, caveat_style))
    story.append(Spacer(1, 6))
    story.append(Paragraph(FEED_CAVEAT, caveat_style))

    doc.build(story)
    return buf.getvalue()
