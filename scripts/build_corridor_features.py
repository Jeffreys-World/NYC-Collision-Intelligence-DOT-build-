"""Join LION road attributes onto canonical street names (input to the SPF).

    .venv/bin/python scripts/build_corridor_features.py \
        --units ~/Downloads/jeffrey-portfolio/nyc-crash-risk-forecast/data/cache/units-*.parquet \
        --out data/raw/corridor_features.parquet

`nyc-crash-risk-forecast` IS READ-ONLY. This script reads its LION unit cache
and writes nothing back. Nothing here may modify that repo: its published
headline belongs to its own pedestrian-casualty label, and changing anything
underneath it would silently change that claim. See scripts/fit_eb.py.

WHY THIS IS A SCRIPT. Same reason as scripts/fetch_boundaries.py: the previous
corridor_features.parquet was built by hand, lived only in gitignored
data/raw/, and did not survive the move to macOS on 2026-08-16. The SPF cannot
be refit without it, so it is now reproducible.

WHAT `is_highway` IN THE SOURCE ACTUALLY MEANS — measured, not assumed.

The sibling repo's `is_highway` column is NOT a limited-access flag, and using
it as one puts surface streets into the estimator's highway branch (spec §3.1's
named failure). Measured 2026-08-16 against the unit cache, `is_highway = 1` is
exactly `rw_type != 1`, which sweeps in 3,861 ALLEY units, 723 PEDESTRIAN PATH
and 708 DRIVEWAY. It means "not an ordinary street", not "limited access".

The honest signal is LION's own `rw_type`. Each code below was identified by
reading the streets that carry it, not from a codebook:

    1  Street        104,101 units, avg 25.2 mph
    2  Highway         4,534 units, avg 46.5 mph   BELT PKWY, LIE, VAN WYCK
    3  Bridge          3,765 units                 WILLIAMSBURG BRG, RFK BRG
    4  Tunnel            171 units                 HOLLAND TUNL, LINCOLN TUNL
    5  Boardwalk         147 units
    6  Path / greenway 11,806 units                HUDSON RIVER GREENWAY
    7  Step street       321 units
    8  Driveway        1,734 units
    9  Ramp            4,587 units                 `... EXPRESSWAY ENTRANCE NB`
    10 Alley           3,861 units
    12 Non-physical        8 units
    13 Connector         331 units
    14 Ferry route     1,171 units

Type 2 averaging 46.5 mph against type 1's 25.2 is what makes this credible:
the code separates roads the way the estimator needs them separated.

So this emits `limited_access_share` — the length share of a street's units on
types 2, 3 and 4 — as a MEASURED covariate. It is deliberately not the
estimator's classifier: spec §3.1 requires a curated committed list for that,
because LION knows the Verrazzano is a bridge but not that a parkway service
road is a surface street. This share is what BUILDS and CROSS-CHECKS that list.

AGGREGATION IS LENGTH-WEIGHTED. A street is many LION units of unequal length,
and a plain mean lets a 40-foot stub count as much as a half-mile run. Speed,
lanes and width are all per-unit properties of a road that vary along it, so
they are averaged by length or the short units dominate.
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.streets import canonical_name  # noqa: E402

# Limited access. Bridges and tunnels are here because spec §3.1 puts bridges in
# the curated list: you cannot walk across the Verrazzano, and the
# countermeasures that apply to it are the highway set.
#
# RAMPS (9) ARE IN THE NUMERATOR, and getting this wrong was measured rather
# than argued. Ramp units carry the ramp's own name — `VAN WYCK EXPRESSWAY
# ENTRANCE NB` — which normalises to the parent expressway, so excluding type 9
# from the numerator while its length stayed in the denominator DEFLATED exactly
# the roads that have ramps. Van Wyck Expy came out at 0.494 and a majority rule
# would have called the Van Wyck a surface street and offered it a road diet:
# spec §3.1's named failure, reproduced by the classifier meant to prevent it.
#
# Counting ramps as limited access separates the two populations cleanly:
#
#     BELT PKWY   0.998    ATLANTIC AVE  0.043
#     GOWANUS     1.000    BROADWAY      0.002
#     VAN WYCK    0.843    QUEENS BLVD   0.015
#     GCP         0.784    FLATBUSH AVE  0.005
#
# 0.78 against 0.04 is a gap a threshold can sit in safely. 0.49 was not. A ramp
# is limited-access infrastructure by character — no pedestrians, merge speeds —
# so this is also the correct answer and not merely the convenient one.
LIMITED_ACCESS_TYPES = ("2", "3", "4", "9")


def resolve_units(pattern: str) -> Path:
    """Accept a glob so the cache's content-hash suffix need not be typed out."""
    expanded = str(Path(pattern).expanduser())
    hits = sorted(glob.glob(expanded))
    if not hits:
        raise SystemExit(
            f"no LION unit cache matched {expanded}\n"
            "  This is the sibling repo's data/cache/units-*.parquet. It is\n"
            "  READ-ONLY input; point --units at wherever that repo is checked out."
        )
    if len(hits) > 1:
        print(f"  {len(hits)} caches matched; using the newest: {Path(hits[-1]).name}")
    return Path(hits[-1])


def load_units(path: Path) -> pd.DataFrame:
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT full_street_name, length_ft, rw_type, posted_speed,
               number_travel_lanes, streetwidth, is_highway, degenerate_length
        FROM read_parquet('{path.as_posix()}')
        WHERE unit_type = 'corridor'
    """).df()
    print(f"  {len(df):,} corridor units")

    # A unit with no length carries no weight and would make every weighted mean
    # NaN for a street built only of them. Dropped loudly rather than silently.
    bad = df["length_ft"].isna() | (df["length_ft"] <= 0)
    if bad.any():
        print(f"  {int(bad.sum()):,} units dropped for non-positive length")
        df = df[~bad]
    return df


def build(df: pd.DataFrame) -> pd.DataFrame:
    """Canonicalise LION names, then aggregate to one row per canonical street.

    The join to crash data is by NAME, so LION's spelling has to go through the
    exact same normaliser the crash side uses — that is the whole point of
    app/streets.py being one module. `KINGS HWY` in LION and `KINGS HIGHWAY` in
    NYPD are one street, and only the shared normaliser knows it.
    """
    df = df.copy()
    df["canonical"] = [canonical_name(n) for n in df["full_street_name"]]
    unmatched = df["canonical"].isna()
    print(f"  {int(unmatched.sum()):,} units whose name normalises to nothing "
          f"(interchanges, two-road names)")
    df = df[~unmatched]

    df["rw_type"] = df["rw_type"].astype(str)
    df["la_len"] = df["length_ft"].where(df["rw_type"].isin(LIMITED_ACCESS_TYPES), 0.0)

    # Length-weighted numerator for each attribute. Weight is the length of the
    # units that actually REPORT the attribute, so a street that posts a speed on
    # half its length is averaged over that half rather than diluted toward zero.
    for col, out in (("posted_speed", "speed"),
                     ("number_travel_lanes", "lanes"),
                     ("streetwidth", "width")):
        df[f"_{out}_num"] = (df[col] * df["length_ft"]).where(df[col].notna())
        df[f"_{out}_den"] = df["length_ft"].where(df[col].notna())

    g = df.groupby("canonical")
    out = pd.DataFrame({
        "n_units": g.size(),
        "length_ft": g["length_ft"].sum(),
        "la_length_ft": g["la_len"].sum(),
        # Carried through unchanged so the cross-check in the docstring stays
        # possible, under a name that says what it is rather than what it is not.
        "lion_not_ordinary_street": g["is_highway"].max(),
    })
    for out_col in ("speed", "lanes", "width"):
        num = g[f"_{out_col}_num"].sum(min_count=1)
        den = g[f"_{out_col}_den"].sum(min_count=1)
        out[out_col] = (num / den.replace(0, pd.NA)).astype(float)

    out["limited_access_share"] = (out["la_length_ft"] / out["length_ft"]).astype(float)

    # `is_highway` keeps its name because scripts/fit_eb.py reads it as a
    # covariate, but its DEFINITION is now the measured length share, not the
    # source's not-an-ordinary-street flag. Majority of the street's length on a
    # highway, bridge or tunnel.
    out["is_highway"] = (out["limited_access_share"] >= 0.5).astype(int)

    out = out.reset_index()
    print(f"  {len(out):,} canonical streets")
    print(f"  {int(out['is_highway'].sum()):,} majority limited-access by length")
    return out


def report(out: pd.DataFrame) -> None:
    """Show the boundary cases, because that is where this gets used wrong."""
    print("\nLongest majority limited-access streets:")
    top = out[out["is_highway"] == 1].nlargest(12, "length_ft")
    print(top[["canonical", "length_ft", "limited_access_share", "speed", "lanes"]]
          .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))

    # A service road is a surface street that shares its parent's name prefix,
    # and is the §3.1 failure mode the estimator must not hit. If any of these
    # come out majority limited-access, the normaliser's service-road guard has
    # regressed.
    sr = out[out["canonical"].str.endswith(" SERVICE RD", na=False)]
    bad_sr = sr[sr["is_highway"] == 1]
    print(f"\nService roads: {len(sr):,}, of which majority limited-access: "
          f"{len(bad_sr):,} (expect 0)")
    if len(bad_sr):
        print(bad_sr[["canonical", "limited_access_share"]].to_string(index=False))

    mixed = out[(out["limited_access_share"] > 0.05)
                & (out["limited_access_share"] < 0.95)].nlargest(10, "length_ft")
    print("\nMixed streets — part highway, part surface. These are exactly the "
          "rows a curated list has to decide by hand:")
    print(mixed[["canonical", "length_ft", "limited_access_share"]]
          .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--units", required=True,
                    help="path or glob to the sibling repo's units-*.parquet (READ-ONLY)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    units = resolve_units(args.units)
    print(f"Reading {units}")
    df = load_units(units)

    print("Aggregating to canonical streets...")
    out = build(df)
    report(out)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.out, index=False)
    print(f"\nWrote {args.out} ({args.out.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
