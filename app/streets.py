"""Street-name normalisation (spec §2.4). Everything downstream depends on it.

Raw street names fragment badly. `FLATBUSH AVENUE` (2,889 rows) and
`FLATBUSH AVE` (433) are the same street; matching one literal spelling misses
most of the corridor, on screen, in front of executives.

The rules run in the order the spec fixes, because the order is load-bearing:
the house-number strip needs the ORIGINAL spacing, so it has to precede the
whitespace collapse.

    1. strip leading house numbers  -- cross_street_name ONLY
    2. collapse whitespace, uppercase
    3. standardise suffixes         -- token-wise, not just terminal
    4. strip ramp / direction noise
    5. (caller) prefer on_street_name, fall back to cross_street_name
    6. apply the explicit alias table

Rules alone provably cannot finish the job, which is why step 6 exists — see
`data/street_aliases.csv`. Measured 2026-08-16: Van Wyck splits 4,232 / 1,423 on
a missing internal space (`VAN WYCK EXPWY` vs `VANWYCK EXPRESSWAY`), and no
general rule closes that without also merging roads that must stay apart.

MEASURED PROPERTIES OF THE RAW COLUMNS (2026-08-16, against crashes.parquet):

* `on_street_name` is TRUNCATED AT 32 CHARACTERS — 916 rows sit at exactly 32.
  `cross_street_name` runs to 40. This is why the service-road guard below
  matches `SERVICE R` as a prefix: `'GRAND CENTRAL PARKWAY SERVICE RO'` and
  `'CROSS BRONX EXPRESSWAY SERVICE R'` are both exactly 32 characters, and a
  guard spelled `SERVICE ROAD` would miss both and fold a surface street into a
  parkway.
* `on_street_name` has ZERO values with a padded house number; `cross_street_name`
  has 166,443 of 217,510. Hence rule 1 is scoped by column.
* The complete parenthetical universe is three patterns: `(BQE)` on 1,371 rows
  (always `GOWANUS EXPY (BQE)`), `(CDR)` on 723, and one truncated `(WESTBO`.
  Stripping them never merges two distinct roads, because the host name is what
  survives — verified, not assumed.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALIAS_CSV = ROOT / "data" / "street_aliases.csv"

# Rule 1. A house number is digits followed by TWO OR MORE spaces. The spec's own
# example, `3468  RICHMOND RD`, is a cross-street value.
#
# The 2+ space quantifier is belt; scoping the call by column is braces. Either
# alone would be enough today, and neither alone is enough forever: 100,728
# `on_street_name` values begin with a digit and a SINGLE space — `3 AVENUE`,
# `5 AVENUE` — all real streets, and collapsing them would be silent.
_HOUSE_NUMBER = re.compile(r"^\s*\d+(?:-\d+)?\s{2,}")

# Parentheticals, including the truncated `(WESTBO` with no closing paren.
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)?")

_WHITESPACE = re.compile(r"\s+")

# Rule 3. Applied token-wise rather than only to the terminal token, so
# `FLATBUSH AVENUE EXTENSION` normalises its AVENUE too. DRIVE and PLACE are here
# because both sit in the top-18 terminal tokens (10,884 and 7,058) and the
# spec's original list omitted them.
_SUFFIXES = {
    "AVENUE": "AVE", "AV": "AVE",
    "EXPRESSWAY": "EXPY", "EXPWY": "EXPY", "EXPRESSWY": "EXPY", "EP": "EXPY",
    "PARKWAY": "PKWY", "PKY": "PKWY", "PARKWY": "PKWY", "PY": "PKWY",
    "STREET": "ST",
    "BOULEVARD": "BLVD", "BOULEVARDE": "BLVD",
    "ROAD": "RD",
    "TURNPIKE": "TPKE", "TPK": "TPKE",
    "DRIVE": "DR",
    "PLACE": "PL",
}

# Rule 4. Everything from the first noise token onward is dropped.
#
# Deliberately ABSENT: bare EAST / WEST / NORTH / SOUTH. They look like direction
# noise and are not — `WEST END AVE` and `EAST BROADWAY` are real streets, and
# `WEST SERVICE ROAD` (23 rows) would truncate to nothing at all. Only the
# unambiguous bound-forms are noise.
# EXTENSION is deliberately absent too. `FLATBUSH AVENUE EXTENSION` (620 rows)
# and `CROSS BRONX EXPRESSWAY EXTENSION` (35, plus 84 misspelled `EXTENTION`)
# are separate named roads, not noise on the parent. Folding them in would
# inflate two featured corridors. The alias table records that as a decision.
_NOISE = {
    "RAMP", "EXIT", "ET", "EN", "ENT", "ENTRANCE",
    "WB", "EB", "NB", "SB",
    "W/B", "E/B", "N/B", "S/B",
    "EASTBOUND", "WESTBOUND", "NORTHBOUND", "SOUTHBOUND",
    # The 32-character truncation clips these mid-word. Same cause as
    # `SERVICE RO` and `BROOKLYN QUEENS EXPY EXI`; no street is named any of
    # them, so folding them in is safe.
    "EASTBOUN", "WESTBOUN", "NORTHBOUN", "SOUTHBOUN",
}

# A service road is a SURFACE street and must never fold into the parkway or
# expressway it parallels — offering a road diet on the Belt Parkway discredits
# the tool, and mis-classifying a service road is how that happens. Matched as a
# prefix because the 32-character truncation produces `SERVICE R`, `SERVICE RO`
# and `SERVICE ROA` as well as the full spelling.
# The `SR` alternative catches `MAJOR DEEGAN EXPRESSWAY SR` (3 rows), where the
# source abbreviates the service road to two letters. It runs before suffix
# standardisation, so it has to spell out the unstandardised forms. Getting this
# wrong puts a surface street into the estimator's highway branch and offers it
# guardrail — the §3.1 failure mode.
_SERVICE_ROAD = re.compile(
    r"\bSERVICE\s+R(?:D|O|OA|OAD)?\b|\b(?:EXPRESSWAY|EXPWY|EXPY)\s+SR\b"
)

# Two road names joined by a space-delimited separator. Measured 2026-08-16:
# 26 rows carry `&` and 540 carry `/`, against 12,464 distinct on_street_name
# values.
_TWO_ROADS = re.compile(r"\s[&/]\s")


def _strip_house_number(value: str) -> str:
    return _HOUSE_NUMBER.sub("", value)


def _standardise_tokens(tokens: list[str]) -> list[str]:
    return [_SUFFIXES.get(t, t) for t in tokens]


def _strip_noise(tokens: list[str]) -> list[str]:
    """Drop everything from the first noise token onward.

    Never drops the FIRST token: a name that opens with what looks like noise is
    a name, not noise, and truncating it to the empty string would turn a
    matchable row into an unmatched one for no gain.
    """
    for i, tok in enumerate(tokens):
        if i > 0 and tok in _NOISE:
            return tokens[:i]
    return tokens


def normalize_name(raw: str | None, *, is_cross_street: bool = False) -> str | None:
    """Apply rules 1-4 to one raw value. Returns None for absent or empty input.

    `is_cross_street` gates rule 1 and defaults to False, so the dangerous
    direction is the one you have to ask for. Calling this on `on_street_name`
    can never strip a leading number, which makes collapsing `3 AVENUE` into
    `AVENUE` structurally impossible rather than dependent on a quantifier
    staying correct forever.
    """
    if raw is None:
        return None
    value = str(raw)
    if is_cross_street:
        value = _strip_house_number(value)

    value = _PARENTHETICAL.sub(" ", value)
    value = _WHITESPACE.sub(" ", value).strip().upper()
    if not value:
        return None

    # The service-road tail is normalised and then protected: the noise strip
    # runs over the head only, so `GRAND CENTRAL PARKWAY SERVICE RO` keeps its
    # tail and stays a surface street.
    # A value naming two roads at once belongs to both, so it is assigned to
    # neither: `G.C.P. / L.I.E.` and `ATLANTIC AVENUE & GEORGIA AVENUE` are an
    # interchange and an intersection. Picking one side would inflate that
    # corridor's count, and picking both would double-count citywide.
    #
    # The separator must be space-delimited. `BROOKLYN QUEENS EXPRESSWAY W/B`
    # (18 rows) carries a slash inside a direction token, not between two roads,
    # and must keep normalising to the BQE.
    if _TWO_ROADS.search(value):
        return None

    service_road = bool(_SERVICE_ROAD.search(value))
    if service_road:
        # Re-collapse: excising the tail from `FDR DRIVE SERVICE ROAD NORTHBOUN`
        # leaves a double space behind, and a doubled space survives into the
        # joined name as an empty token.
        value = _WHITESPACE.sub(" ", _SERVICE_ROAD.sub(" ", value)).strip()

    tokens = _standardise_tokens(value.split(" "))
    tokens = _strip_noise(tokens)
    if not tokens:
        return None

    name = " ".join(tokens)
    if service_road:
        name = f"{name} SERVICE RD"
    return name or None


@lru_cache(maxsize=1)
def alias_table() -> dict[str, str]:
    """Rule 6. Explicit, committed, and tested — never a regex heuristic.

    Keyed on the output of rules 1-4, so an alias maps one post-rule spelling to
    the canonical one. Rows whose canonical value is empty are deliberate
    non-matches: an interchange like `G.C.P. / L.I.E.` belongs to two corridors
    at once, and assigning it to one would inflate that corridor's count.
    """
    if not ALIAS_CSV.exists():
        return {}
    with ALIAS_CSV.open(encoding="utf-8-sig", newline="") as fh:
        # Leading '>' lines carry the reasoning for the table next to the table.
        # They are skipped before the header is read, so csv.DictReader never
        # sees them as data — a comment containing a comma would otherwise parse
        # into a plausible-looking alias row.
        rows = (line for line in fh if not line.startswith(">"))
        return {
            row["raw_normalized"].strip().upper(): row["canonical"].strip().upper()
            for row in csv.DictReader(rows)
            if row.get("raw_normalized")
        }


def canonical_name(raw: str | None, *, is_cross_street: bool = False) -> str | None:
    """Rules 1-4 then rule 6. The single entry point callers should use."""
    name = normalize_name(raw, is_cross_street=is_cross_street)
    if name is None:
        return None
    canonical = alias_table().get(name, name)
    return canonical or None


def canonical_street(on_street: str | None, cross_street: str | None) -> tuple[str | None, str]:
    """Rule 5. Prefer `on_street_name`; fall back to `cross_street_name`.

    Returns `(name, source)` where source is one of `on` / `cross` / `none`, so
    a caller can tell a matched corridor from a fallback match — §4.2's rule
    that a fallback announces itself applies to this seam too.

    `off_street_name` is deliberately not in the chain: it is non-null only when
    `on_street_name` already is, so it adds nothing but a third code path.
    """
    name = canonical_name(on_street)
    if name is not None:
        return name, "on"
    name = canonical_name(cross_street, is_cross_street=True)
    if name is not None:
        return name, "cross"
    return None, "none"
