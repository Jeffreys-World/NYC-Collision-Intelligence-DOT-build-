"""Street name normalisation for NYC collision data.

Raw street names fragment badly — Flatbush Avenue appears as 5+ distinct values.
This module applies deterministic normalisation rules (§2.4 of the spec) so that
corridor matching works correctly downstream.

Critical constraint: do NOT strip single-digit numbers followed by a space.
'3 AVENUE' is a real street; only strip when padded by 2+ spaces.
"""

from __future__ import annotations

import re

# ── Suffix standardisation map ──────────────────────────────────────────────
_SUFFIX_MAP: dict[str, str] = {
    "AVENUE": "AVE",
    "DRIVE": "DR",
    "EXPRESSWAY": "EXPY",
    "EXPWY": "EXPY",
    "PARKWAY": "PKWY",
    "PKY": "PKWY",
    "STREET": "ST",
    "BOULEVARD": "BLVD",
    "ROAD": "RD",
    "TURNPIKE": "TPKE",
}

# Pattern: 2+ spaces between a leading number and the street name
_LEADING_NUMBER_RE = re.compile(r"^[0-9]{2,}\s{2,}")

# Pattern: direction / ramp suffix noise after the core street name
_RAMP_NOISE_RE = re.compile(
    r"\s+(?:WB|EB|NB|SB|NW|NE|SW|SE)\b.*$", re.IGNORECASE
)
_RAMP_ET_RE = re.compile(r"\s+ET\s+\d+.*$", re.IGNORECASE)


def normalise_street_name(raw: str | None) -> str | None:
    """Normalise a single raw street name string.

    Returns None when the input is None, empty, or whitespace-only.

    Rules (applied in order):
    1. Strip leading house numbers padded by 2+ spaces
    2. Collapse repeated whitespace, uppercase
    3. Standardise suffixes (AVENUE→AVE, etc.)
    4. Strip ramp/direction noise
    """
    if not raw or not raw.strip():
        return None

    s = raw.strip()

    # Rule 1: strip leading house number when padded by 2+ spaces
    # Critical: '3 AVENUE' must survive — only 2+ spaces trigger stripping
    if _LEADING_NUMBER_RE.match(s):
        s = _LEADING_NUMBER_RE.sub("", s)

    # Rule 2: collapse whitespace, uppercase
    s = " ".join(s.split()).upper()

    # Rule 3: standardise suffixes — apply to every word, not just the last,
    # because direction/ramp noise follows the suffix in raw names
    words = [_SUFFIX_MAP.get(w, w) for w in s.split()]
    s = " ".join(words)

    # Rule 4: strip ramp/direction noise
    s = _RAMP_ET_RE.sub("", s)
    s = _RAMP_NOISE_RE.sub("", s)

    return s if s else None


def pick_street(
    on_street: str | None,
    cross_street: str | None,
) -> str | None:
    """Pick and normalise the best available street name.

    Prefer on_street_name; fall back to cross_street_name.
    """
    result = normalise_street_name(on_street)
    if result is not None:
        return result
    return normalise_street_name(cross_street)
