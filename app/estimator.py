"""Countermeasure and budget estimator (spec §3).

Costs and CMFs are editable planning defaults sourced from
`data/countermeasures.csv`, never invented — §0.3 #4. Every number here
multiplies through from that file; see its header for provenance and the one
honest gap (daylighting has no dedicated CMF anywhere in the Clearinghouse).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COUNTERMEASURES_CSV = ROOT / "data" / "countermeasures.csv"


@dataclass(frozen=True)
class Treatment:
    """One row of data/countermeasures.csv. §4.1: a dataclass, not a dict."""

    treatment: str
    label: str
    road_class: str
    unit: str
    unit_cost_usd: float
    cmf: float
    cmf_star_rating: int | None
    cmf_setting: str
    cmf_id: str
    cmf_source_url: str
    cost_source_url: str
    note: str

    @property
    def reduction_pct(self) -> float:
        """§3.2: CMF is a multiplier, always displayed alongside its % form."""
        return (1 - self.cmf) * 100

    @property
    def has_rated_cmf(self) -> bool:
        return bool(self.cmf_star_rating)


def _as_float(value: str, default: float = 0.0) -> float:
    value = (value or "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@lru_cache(maxsize=1)
def load_countermeasures() -> dict[str, Treatment]:
    """Keyed on `treatment`, matching app.road_class's HIGHWAY/SURFACE_TREATMENTS."""
    if not COUNTERMEASURES_CSV.exists():
        return {}
    with COUNTERMEASURES_CSV.open(encoding="utf-8-sig", newline="") as fh:
        rows = (line for line in fh if not line.startswith(">"))
        table = {}
        for row in csv.DictReader(rows):
            key = (row.get("treatment") or "").strip()
            if not key:
                continue
            star = (row.get("cmf_star_rating") or "").strip()
            table[key] = Treatment(
                treatment=key,
                label=(row.get("label") or key).strip(),
                road_class=(row.get("road_class") or "").strip(),
                unit=(row.get("unit") or "").strip(),
                unit_cost_usd=_as_float(row.get("unit_cost_usd")),
                cmf=_as_float(row.get("cmf"), default=1.0),
                cmf_star_rating=int(star) if star else None,
                cmf_setting=(row.get("cmf_setting") or "").strip(),
                cmf_id=(row.get("cmf_id") or "").strip(),
                cmf_source_url=(row.get("cmf_source_url") or "").strip(),
                cost_source_url=(row.get("cost_source_url") or "").strip(),
                note=(row.get("note") or "").strip(),
            )
    return table


def expected_reduction(baseline_expected_harm: float, cmf: float) -> float:
    """Expected harm avoided = EB baseline * (1 - CMF). Never apply a CMF to a
    raw observed count (§2.7) — the caller must pass an EB estimate."""
    return max(baseline_expected_harm * (1 - cmf), 0.0)


def cost_per_unit(total_cost: float, units_avoided: float) -> float | None:
    """None when nothing was avoided — §5's 'Enter a unit cost' / CMF-at-1.0
    empty states exist precisely so this never renders as `inf`."""
    if units_avoided <= 0:
        return None
    return total_cost / units_avoided
