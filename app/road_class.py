"""Road classification for the countermeasure branch (spec §3.1).

The estimator offers different treatments to different kinds of road:

    highway / bridge / tunnel  ->  guardrail & attenuator retrofit,
                                   high-friction surface treatment
    surface                    ->  signal upgrade, road diet, refuge island,
                                   leading pedestrian interval, daylighting

Offering a road diet on the Belt Parkway discredits the tool instantly, so this
module has exactly one job and does it from a committed, curated list —
`data/limited_access.csv`. ANYTHING NOT ON THE LIST IS SURFACE. There is no
threshold and no name rule, because both were measured failing:

* A name rule sends HORACE HARDING EXPY — the Long Island Expressway's 30 mph
  service road, 1,792 crashes — to the highway branch, and would leave BRIDGE ST
  and WILLIAMSBRIDGE RD there too.
* An unlabeled-borough threshold fails in the other direction. Spec §3.1
  measured Nassau Expy at 85.7% and VANWYCK EXPY at 83.6%, so a 90% gate offers
  both a road diet; Cross Bronx Expy lands at 90.6% or 89.1% depending on an
  unrelated string-matching decision elsewhere in the pipeline, which means the
  countermeasure offered on the Cross Bronx flips on a coin toss.

The unlabeled share is kept as a SECONDARY signal. When it and the list
disagree, `classify` says so, and the caller surfaces it. That disagreement is
how a road missing from the list gets found — it is a feature of the design, not
an error to suppress. DESIGN.md §5 turns it into a correctable control at the top
of the drawer, showing its basis, so the engineer fixes it in the room.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMITED_ACCESS_CSV = ROOT / "data" / "limited_access.csv"

SURFACE = "surface"
LIMITED_ACCESS_CLASSES = ("highway", "bridge", "tunnel")

# Above this, a road absent from the list is worth a second look. Deliberately
# NOT a classifier — it never changes the answer, it only raises a flag. 0.90 is
# the threshold §3.1 rejected as a rule, reused here as what it is actually good
# for: a smoke alarm, not a decision.
SUSPICIOUS_UNLABELED_SHARE = 0.90


@dataclass(frozen=True)
class RoadClass:
    """The classification and everything needed to defend it on screen."""

    canonical: str
    road_class: str          # "highway" | "bridge" | "tunnel" | "surface"
    basis: str               # "lion" | "curated" | "not-listed"
    note: str = ""
    lion_share: float | None = None
    unlabeled: float | None = None
    warning: str = ""        # non-empty when the secondary signal disagrees

    @property
    def is_limited_access(self) -> bool:
        return self.road_class in LIMITED_ACCESS_CLASSES


@lru_cache(maxsize=1)
def limited_access_table() -> dict[str, dict[str, str]]:
    """Load the curated list, keyed on canonical name.

    Leading '>' lines carry the reasoning next to the data and are stripped
    before the header is read — the same convention as data/street_aliases.csv,
    and for the same reason: a comment containing a comma would otherwise parse
    into a plausible-looking row.
    """
    if not LIMITED_ACCESS_CSV.exists():
        return {}
    with LIMITED_ACCESS_CSV.open(encoding="utf-8-sig", newline="") as fh:
        rows = (line for line in fh if not line.startswith(">"))
        table = {}
        for row in csv.DictReader(rows):
            name = (row.get("canonical") or "").strip().upper()
            if not name:
                continue
            table[name] = row
    return table


def _as_float(value: str | None) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def classify(canonical: str | None, unlabeled_share: float | None = None) -> RoadClass:
    """Classify one canonical street name.

    `unlabeled_share` is optional and never changes the answer. Passing it only
    enables the §3.1 cross-check: a road that is not on the list but whose
    crashes almost never carry a borough is either missing from the list or a
    genuine surface street with unusual paperwork, and either way somebody should
    look. The warning names the road, because a warning that does not name the
    road cannot be acted on.
    """
    if not canonical:
        return RoadClass(canonical="", road_class=SURFACE, basis="not-listed",
                         note="no canonical street name")

    name = canonical.strip().upper()
    row = limited_access_table().get(name)

    if row is None:
        warning = ""
        if unlabeled_share is not None and unlabeled_share >= SUSPICIOUS_UNLABELED_SHARE:
            warning = (
                f"{name} is not on the limited-access list but "
                f"{unlabeled_share:.0%} of its crashes carry no borough. Either it "
                f"belongs on the list, or it is a surface street whose crashes are "
                f"reported unusually. Treating it as surface."
            )
        return RoadClass(canonical=name, road_class=SURFACE, basis="not-listed",
                         unlabeled=unlabeled_share, warning=warning)

    listed_unlabeled = _as_float(row.get("unlabeled"))
    warning = ""
    if unlabeled_share is not None and unlabeled_share < 0.50:
        warning = (
            f"{name} is on the limited-access list, but only "
            f"{unlabeled_share:.0%} of its crashes lack a borough — limited-access "
            f"roads normally sit far higher. Worth confirming the list entry."
        )

    return RoadClass(
        canonical=name,
        road_class=(row.get("road_class") or "highway").strip().lower(),
        basis=(row.get("basis") or "curated").strip().lower(),
        note=(row.get("note") or "").strip(),
        lion_share=_as_float(row.get("lion_share")),
        unlabeled=unlabeled_share if unlabeled_share is not None else listed_unlabeled,
        warning=warning,
    )


# Spec §3.1. Treatments are named here; their costs, CMFs, star ratings and
# citations live in data/countermeasures.csv, because §3.2 forbids inventing a
# CMF and requires every one of them to carry a source.
HIGHWAY_TREATMENTS = (
    "guardrail_attenuator_retrofit",
    "high_friction_surface_treatment",
)

SURFACE_TREATMENTS = (
    "signal_upgrade_smart_phasing",
    "road_diet",
    "pedestrian_refuge_island",
    "leading_pedestrian_interval",
    "daylighting",
)


def treatments_for(road: RoadClass) -> tuple[str, ...]:
    """Only the countermeasures valid for this kind of road."""
    return HIGHWAY_TREATMENTS if road.is_limited_access else SURFACE_TREATMENTS
