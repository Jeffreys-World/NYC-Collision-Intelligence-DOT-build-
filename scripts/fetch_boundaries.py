"""Fetch NYC borough boundaries, WATER-INCLUDED, and verify them by area.

    .venv/bin/python scripts/fetch_boundaries.py \
        --out data/raw/boroughs_water-included.geojson

WHY THIS IS A SCRIPT AND NOT A DOWNLOAD YOU DO ONCE BY HAND.

The boundary file lives in gitignored `data/raw/`, so it is not in the repo, and
on 2026-08-16 the project moved machines and every artifact in `data/raw/` was
gone: the raw pull, the cleaned CSV, the recovered Parquet and this GeoJSON. The
crash pull could be reproduced because `scripts/pull_data.py` exists. The
boundaries could not, because that download had only ever happened in a shell.
A pipeline step that lives in somebody's terminal history is not a pipeline
step. So this is committed, and the whole chain now rebuilds from a bare clone.

WATER-INCLUDED, NOT SHORELINE-CLIPPED — the distinction the spec turns on.

NYC Open Data publishes both, under names that differ by one parenthetical:

    gthc-hcne / yqww-f9f3   Borough Boundaries                    (clipped)
    wh2p-dxnf / 53n2-m85m   Borough Boundaries (water areas included)

Spec §6 step 2 requires the water-included variant. The clipped polygons stop at
the shoreline, and points over water are exactly where the elevated and
waterfront highways sit — the Belt Parkway runs along Jamaica Bay. Using the
clipped file silently drops the rows this tool exists to recover, and it fails
as a plausible-looking 97% agreement rather than as an error.

Grabbing the wrong one is a one-character mistake in a dataset id, so this script
does not trust the id. It VERIFIES BY AREA, which is a property of the geometry
itself: water-included totals ~468 sq mi against the clipped ~302, a factor of
1.55. That gate cannot be passed by the wrong file.

The `?method=export&format=GeoJSON` geospatial endpoint returns an empty
FeatureCollection here — it queues an export job rather than serving the data —
so this reads the ROW endpoint, where `the_geom` is already GeoJSON, and
assembles the FeatureCollection itself.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

# Water-included. See the docstring before changing this.
DATASET = "wh2p-dxnf"
URL = f"https://data.cityofnewyork.us/resource/{DATASET}.json"

TIMEOUT = 120

EXPECTED = {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"}

# The DCP polygons carry shape_area in square feet (EPSG:2263, the state plane
# foot system). 5280^2 = 27,878,400 sq ft in a square mile.
SQ_FT_PER_SQ_MI = 27_878_400.0

# Measured 2026-08-16: water-included 468.3 sq mi, shoreline-clipped 302.1.
# The window is wide enough to survive an ordinary boundary revision and far too
# narrow to admit the clipped file.
AREA_MIN_SQ_MI = 400.0
AREA_MAX_SQ_MI = 540.0
CLIPPED_SQ_MI = 302.1


def fetch(url: str) -> list[dict]:
    """Read the row endpoint.

    urllib, not requests, and the reason is recorded in scripts/pull_data.py:
    on a TLS-intercepting network requests fails with CERTIFICATE_VERIFY_FAILED
    because it carries its own certifi bundle, while urllib uses the OS trust
    store. This fetch is five rows and needs no session, retry or backoff, so it
    takes the dependency-free path rather than pulling in truststore.
    """
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        if r.status != 200:
            raise SystemExit(f"HTTP {r.status} from {url}")
        return json.loads(r.read().decode("utf-8"))


def build(rows: list[dict]) -> tuple[dict, float]:
    """Assemble a FeatureCollection and total the published area."""
    features = []
    total_sq_ft = 0.0
    for row in rows:
        geom = row.get("the_geom")
        name = (row.get("boroname") or "").strip()
        if geom is None:
            raise SystemExit(f"row for {name!r} carries no geometry")
        total_sq_ft += float(row.get("shape_area") or 0.0)
        features.append({
            "type": "Feature",
            # recover_borough.py looks for a boroname/boro_name property and
            # uppercases it itself, so the casing here is left as published.
            "properties": {"boroname": name, "borocode": row.get("borocode")},
            "geometry": geom,
        })

    fc = {
        "type": "FeatureCollection",
        # recover_borough.py refuses to guess a CRS. GeoJSON is WGS84 by
        # definition (RFC 7946) and the row endpoint serves lon/lat, but the
        # member is written explicitly so geopandas reads a CRS off the file
        # rather than inferring one.
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3/CRS84"}},
        "features": features,
    }
    return fc, total_sq_ft / SQ_FT_PER_SQ_MI


def verify(fc: dict, area_sq_mi: float) -> None:
    """Refuse to write anything that is not the water-included file."""
    names = {(f["properties"]["boroname"] or "").upper().strip() for f in fc["features"]}
    print(f"  boroughs: {', '.join(sorted(names))}")
    if names != EXPECTED:
        raise SystemExit(f"expected the five boroughs, got {sorted(names)}")

    print(f"  total published area: {area_sq_mi:.1f} sq mi "
          f"(water-included ~468.3, shoreline-clipped ~{CLIPPED_SQ_MI})")
    if not (AREA_MIN_SQ_MI <= area_sq_mi <= AREA_MAX_SQ_MI):
        raise SystemExit(
            f"area {area_sq_mi:.1f} sq mi is outside "
            f"[{AREA_MIN_SQ_MI}, {AREA_MAX_SQ_MI}]. Near {CLIPPED_SQ_MI} means "
            f"this is the SHORELINE-CLIPPED file, which drops points over water "
            f"and would lose the waterfront highway rows the recovery exists to "
            f"find. Check the dataset id against the docstring."
        )
    print("  PASS: this is the water-included variant")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    print(f"Fetching {URL}")
    rows = fetch(URL)
    print(f"  {len(rows)} rows")

    fc, area = build(rows)
    verify(fc, area)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fc), encoding="utf-8")
    print(f"\nWrote {args.out} ({args.out.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as e:
        print(f"\nFATAL: could not reach NYC Open Data: {e}", file=sys.stderr)
        raise SystemExit(1)
