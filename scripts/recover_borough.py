"""Offline point-in-polygon borough recovery (spec §6 step 2).

    .venv/Scripts/python scripts/recover_borough.py \
        --crashes data/raw/crashes_cleaned.csv \
        --boundaries data/raw/boroughs_water-included.geojson \
        --out data/raw/crashes_recovered.parquet

This runs on a laptop and NEVER in the deployed app. Its output is baked into
the committed Parquet, which is why geopandas sits in requirements-dev.txt and
not requirements.txt — shipping GDAL to Streamlit Community Cloud is a common
build failure for zero runtime benefit.

§0.3 #2: `borough` is NEVER overwritten. Recovered values land in
`borough_recovered`, with `borough_source` in {reported, recovered,
unrecoverable}, so the original NYPD field survives untouched and every figure
can be recomputed either way.

WATER-INCLUDED BOUNDARIES, NOT SHORELINE-CLIPPED. Verified 2026-08-16 by area:
the water-included polygons total 468.3 sq mi against the clipped 302.1 sq mi,
a factor of 1.55. The clipped variant drops points over water, and points over
water is precisely where the elevated and waterfront highways sit — the Belt
Parkway runs along Jamaica Bay, and the corridor §7 opens the demo on would
lose exactly the rows this tool exists to recover.

THE GATE IS STRATIFIED. Three checks, all must pass, and NO RECOVERY FIGURE MAY
BE PUBLISHED UNTIL THEY DO. The reason is a population mismatch that a single
agreement number cannot see: agreement is measured on rows that HAVE a borough,
while recovery is applied to rows that LACK one. Those populations are disjoint
by construction and differ roughly twentyfold in limited-access share, so the
agreement number can read 97% while tens of thousands of highway rows are
silently lost.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.streets import canonical_street  # noqa: E402

# NYPD writes boroughs uppercase; the DCP GeoJSON writes them title-case.
BOROUGHS = {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"}

# Provisional road class, used ONLY for the stratified gate below. The estimator
# classifies from the curated `data/limited_access.csv` instead (spec §3.1),
# because a suffix rule cannot know that a service road is a surface street. For
# the gate this is enough: the question is whether highway-ish rows are being
# lost at a different rate from surface rows, and a suffix split answers it.
_HIGHWAY_TOKENS = ("EXPY", "PKWY", "BRIDGE", "TUNNEL", "THRUWAY")


def road_class(name: str | None) -> str:
    if not name:
        return "unknown"
    if name.endswith(" SERVICE RD"):
        return "surface"          # a service road is a surface street, always
    return "highway" if any(t in name for t in _HIGHWAY_TOKENS) else "surface"


def load_crashes(path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(
        f"SELECT * FROM read_csv_auto('{path.as_posix()}', sample_size=-1)"
    ).df()
    # (0,0) is absent data wearing a coordinate costume (spec §4.1). Null it
    # before anything spatial touches it, or null island joins to no polygon and
    # quietly becomes 'unrecoverable' for a reason nobody can see later.
    null_island = (df["latitude"] == 0) & (df["longitude"] == 0)
    df.loc[null_island, ["latitude", "longitude"]] = pd.NA
    print(f"  {int(null_island.sum()):,} (0,0) coordinate pairs nulled")
    return df


def recover(df: pd.DataFrame, boundaries: Path) -> pd.DataFrame:
    boros = gpd.read_file(boundaries)
    if boros.crs is None:
        raise SystemExit("boundary file has no CRS; refusing to guess")
    boros = boros.to_crs(4326)
    namecol = next(c for c in boros.columns if c.lower() in ("boroname", "boro_name"))
    boros = boros[[namecol, "geometry"]].rename(columns={namecol: "poly_borough"})
    boros["poly_borough"] = boros["poly_borough"].str.upper().str.strip()

    unknown = set(boros["poly_borough"]) - BOROUGHS
    if unknown:
        raise SystemExit(f"unexpected borough names in the polygons: {unknown}")

    has_coords = df["latitude"].notna() & df["longitude"].notna()
    print(f"  {int(has_coords.sum()):,} rows carry coordinates")

    # Point takes (lon, lat) — IN THAT ORDER. Reversing it silently places every
    # crash in the Indian Ocean, joins nothing, and reports 0% recovery, which
    # reads like a bad polygon file rather than a transposed tuple.
    pts = gpd.GeoDataFrame(
        df.loc[has_coords, []].copy(),
        geometry=[Point(xy) for xy in zip(df.loc[has_coords, "longitude"],
                                          df.loc[has_coords, "latitude"])],
        crs="EPSG:4326",
    )
    joined = gpd.sjoin(pts, boros, how="left", predicate="within")
    # A point on a shared border can match two polygons and duplicate the row.
    joined = joined[~joined.index.duplicated(keep="first")]

    df["poly_borough"] = pd.NA
    df.loc[joined.index, "poly_borough"] = joined["poly_borough"]

    reported = df["borough"].notna()
    recovered = ~reported & df["poly_borough"].notna()

    df["borough_recovered"] = df["borough"].where(reported, df["poly_borough"])
    df["borough_source"] = "unrecoverable"
    df.loc[reported, "borough_source"] = "reported"
    df.loc[recovered, "borough_source"] = "recovered"
    return df


def gate(df: pd.DataFrame) -> bool:
    """Three checks. All must pass. Returns True only if every one does."""
    ok = True

    print("\n--- GATE 1: agreement where NYPD gave us a borough AND coordinates ---")
    both = df["borough"].notna() & df["poly_borough"].notna()
    agree = (df.loc[both, "borough"].str.upper().str.strip()
             == df.loc[both, "poly_borough"]).sum()
    n_both = int(both.sum())
    pct = agree / n_both * 100 if n_both else 0.0
    print(f"  {agree:,} of {n_both:,} agree = {pct:.2f}%")
    if pct < 90:
        print("  FAIL: below 90% means the CRS or the axis order is wrong "
              "(Point takes (lon, lat)); it is not a data-quality finding.")
        ok = False
    else:
        print("  PASS")

    print("\n--- GATE 2: recovery rate by road class ---")
    # The DENOMINATOR is unlabeled rows THAT CARRY COORDINATES, not all unlabeled
    # rows. A row with no coordinates cannot be recovered by any polygon, so
    # including it measures NYPD's geocoding completeness and calls the result a
    # polygon failure. The first version of this gate did exactly that and failed
    # at 74.94% on highways while every highway point that had a coordinate was
    # in fact recovered — a false alarm that would have sent someone hunting a
    # CRS bug that was not there.
    #
    # Both figures are printed, because they answer different questions:
    # `rate_pct` tests the polygons, `of_all_unlabeled_pct` is the real recovery
    # ceiling and the honest number for the §2.6 badge.
    unl = df[df["borough"].isna()].copy()
    names = [canonical_street(a, b)[0]
             for a, b in zip(unl["on_street_name"], unl["cross_street_name"])]
    unl["road_class"] = [road_class(n) for n in names]
    unl["has_coords"] = unl["latitude"].notna() & unl["longitude"].notna()

    tbl = unl.groupby("road_class").agg(
        unlabeled=("borough_source", "size"),
        with_coords=("has_coords", "sum"),
        recovered=("borough_source", lambda s: (s == "recovered").sum()),
    )
    tbl["rate_pct"] = (tbl["recovered"] / tbl["with_coords"] * 100).round(2)
    tbl["of_all_unlabeled_pct"] = (tbl["recovered"] / tbl["unlabeled"] * 100).round(2)
    print(tbl.to_string())
    hw = tbl.loc["highway"] if "highway" in tbl.index else None
    if hw is None or hw["rate_pct"] < 95:
        print("  FAIL: a coordinate-carrying highway row that does not land in a "
              "borough polygon is the shoreline-clipped failure — waterfront and "
              "elevated roads fall outside the clipped variant.")
        ok = False
    else:
        print("  PASS")

    print("\n--- GATE 3: Belt Pkwy, the corridor the demo opens on ---")
    belt = df[[canonical_street(a, b)[0] == "BELT PKWY"
               for a, b in zip(df["on_street_name"], df["cross_street_name"])]]
    belt_unl = belt[belt["borough"].isna()]
    belt_coord = belt_unl[belt_unl["latitude"].notna()]
    got = int((belt_unl["borough_source"] == "recovered").sum())
    print(f"  Belt Pkwy rows: {len(belt):,} | unlabeled: {len(belt_unl):,} "
          f"| unlabeled with coordinates: {len(belt_coord):,}")
    print(f"  recovered: {got:,}")
    if len(belt_coord) and got / len(belt_coord) < 0.95:
        print(f"  FAIL: only {got/len(belt_coord)*100:.1f}% of Belt Pkwy's "
              f"coordinate-carrying unlabeled rows recovered.")
        ok = False
    else:
        print("  PASS")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crashes", type=Path, required=True)
    ap.add_argument("--boundaries", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    print("Loading crashes...")
    df = load_crashes(args.crashes)
    print(f"  {len(df):,} rows")

    print("Recovering boroughs...")
    df = recover(df, args.boundaries)

    if not gate(df):
        print("\nGATES FAILED. Publishing no recovery figure, and writing no "
              "output — a half-recovered Parquet that looks fine is worse than "
              "none, because every downstream number inherits the error.",
              file=sys.stderr)
        return 1

    counts = df["borough_source"].value_counts()
    print("\n--- ALL GATES PASSED ---")
    print(counts.to_string())

    df = df.drop(columns=["poly_borough"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, index=False)
    print(f"\nWrote {args.out} ({args.out.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
