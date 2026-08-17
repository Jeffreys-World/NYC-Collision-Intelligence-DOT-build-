"""Freeze the derived schema and bake the committed Parquet (spec §6 step 2).

    .venv/bin/python scripts/bake.py                 # DRY RUN — shows, writes nothing
    .venv/bin/python scripts/bake.py --commit        # actually writes

THIS IS THE OWNER'S REVIEW CHECKPOINT, AND THE DRY RUN IS THE DEFAULT ON PURPOSE.

Spec §6 step 2: freeze the full derived schema FIRST and bake EXACTLY ONCE. Every
re-bake leaves another permanent ~20MB blob in git history that cannot easily be
removed later, and a mid-week schema change invalidates the §2.3 corridor fixture
and the CI row-count gate. So the safe thing has to be the thing that happens
when you type the obvious command: this script shows you the schema, the figures
and the diff against what is already committed, and then does nothing unless you
pass --commit.

WHAT GOES IN, AND WHY EACH COLUMN IS THERE

    everything in crashes_recovered.parquet   the cleaned pull plus
                                             borough_recovered / borough_source
    canonical                                the normalised street name (§2.4).
                                             Baked because app/streets.py runs 848,739
                                             canonical_street() calls to produce it,
                                             which is ~30s — far too slow for a
                                             Streamlit rerun.
    canonical_source                         'on' | 'cross' | 'none'. §4.2: a
                                             fallback announces itself, and a
                                             corridor matched on the cross street
                                             is a weaker match than one matched on
                                             the on-street.
    lat_c, lon_c                             the EB unit key, round(lat/lon, 3).
                                             §6 step 2 requires the EB join key in
                                             the bake, and §2.1 bins the map on this
                                             same grid.

WHAT IS DELIBERATELY *NOT* BAKED

    road_class      Derived at runtime from data/limited_access.csv. That list is
                    meant to be CORRECTABLE — DESIGN.md §5 puts a correctable
                    road-class control at the top of the drawer precisely so an
                    engineer can fix a missing road in the room. Baking the
                    classification would mean a curated-list correction needs a
                    re-bake, and §6 step 2 says there is only ever one.
    eb_estimate     Same reason, more strongly. The EB model is still moving, and
                    it has already been refit twice. It belongs in its own artifact
                    joined on (canonical, lat_c, lon_c), not welded into the
                    crash-level Parquet where a model change costs a permanent blob.
    borough         NEVER overwritten (§0.3 #2). It is carried through untouched
                    and the recovered value lives beside it.

The script also emits data/processed/corridor_fixture.csv (§2.3), so the figures
the demo is rehearsed from and the figures on screen come from one query. The
featured-corridor table carries INPUTS only; this is where its outputs live.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.streets import canonical_street  # noqa: E402

RECOVERED = ROOT / "data" / "raw" / "crashes_recovered.parquet"
FEATURED = ROOT / "data" / "featured_corridors.csv"
OUT = ROOT / "data" / "processed" / "crashes.parquet"
FIXTURE = ROOT / "data" / "processed" / "corridor_fixture.csv"

# §2.1 and scripts/fit_eb.py bin on the same grid. One constant, one meaning.
CELL_DP = 3


def load() -> pd.DataFrame:
    if not RECOVERED.exists():
        raise SystemExit(
            f"{RECOVERED} is missing. Run the pipeline first — see NEXT-SESSION.md:\n"
            "  pull_data.py -> clean_crash_data.py -> fetch_boundaries.py "
            "-> recover_borough.py"
        )
    df = duckdb.connect().execute(
        f"SELECT * FROM read_parquet('{RECOVERED.as_posix()}')").df()
    print(f"  {len(df):,} rows, {len(df.columns)} columns from the recovery step")
    return df


def derive(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns, and nothing else."""
    print("  normalising street names (848k canonical_street calls, ~30s)...")
    pairs = [canonical_street(a, b)
             for a, b in zip(df["on_street_name"], df["cross_street_name"])]
    df["canonical"] = [p[0] for p in pairs]
    df["canonical_source"] = [p[1] for p in pairs]

    matched = df["canonical"].notna()
    print(f"  {int(matched.sum()):,} rows carry a canonical street "
          f"({matched.mean()*100:.2f}%), {int((~matched).sum()):,} unmatched")
    print("  match source: "
          + " · ".join(f"{k} {v:,}" for k, v in
                       df['canonical_source'].value_counts().items()))

    # The EB unit key. NULL where there is no coordinate — a cell cannot be
    # invented for a crash that has no position, and §4.1 forbids letting a
    # null-island or absent coordinate reach anything spatial.
    has_xy = df["latitude"].notna() & df["longitude"].notna()
    df["lat_c"] = df["latitude"].round(CELL_DP).where(has_xy)
    df["lon_c"] = df["longitude"].round(CELL_DP).where(has_xy)
    print(f"  {int(has_xy.sum()):,} rows carry an EB cell key "
          f"({int((~has_xy).sum()):,} have no coordinate)")

    cells = df.loc[has_xy & matched, ["canonical", "lat_c", "lon_c"]].drop_duplicates()
    print(f"  {len(cells):,} distinct (canonical, lat_c, lon_c) cells")
    return df


def corridor_fixture(df: pd.DataFrame) -> pd.DataFrame:
    """§2.3's outputs: the real figures for each featured corridor.

    A golden test pins this, so a normalisation change fails loudly instead of
    silently shifting every number on screen.
    """
    with FEATURED.open(encoding="utf-8-sig") as fh:
        rows = [line for line in fh if not line.startswith(">")]
    featured = pd.read_csv(io.StringIO("".join(rows)))

    out = []
    for row in featured.itertuples():
        sel = df[df["canonical"] == row.canonical]
        casualty = sel[(sel["number_of_persons_injured"] > 0)
                       | (sel["number_of_persons_killed"] > 0)]
        unlabeled = sel["borough"].isna()
        out.append({
            "corridor": row.corridor,
            "canonical": row.canonical,
            "expected_class": row.expected_class,
            "crashes": len(sel),
            "casualty_crashes": len(casualty),
            "injured": int(sel["number_of_persons_injured"].sum()),
            "killed": int(sel["number_of_persons_killed"].sum()),
            "pedestrians_injured": int(sel["number_of_pedestrians_injured"].sum()),
            "pedestrians_killed": int(sel["number_of_pedestrians_killed"].sum()),
            # The §2.6 badge: "Includes N crashes other tools drop". On highway
            # corridors this share is 92-98%, which makes the point with no extra
            # explanation.
            "crashes_other_tools_drop": int(unlabeled.sum()),
            "share_other_tools_drop": round(float(unlabeled.mean()), 4) if len(sel) else 0.0,
            "recovered": int((sel["borough_source"] == "recovered").sum()),
            "unrecoverable": int((sel["borough_source"] == "unrecoverable").sum()),
            "with_coordinates": int((sel["latitude"].notna()).sum()),
            "cells": int(sel.dropna(subset=["lat_c"])
                         .drop_duplicates(["lat_c", "lon_c"]).shape[0]),
        })
    return pd.DataFrame(out)


def report(df: pd.DataFrame, fixture: pd.DataFrame) -> None:
    print("\n=== FROZEN SCHEMA — this is what --commit would write ===")
    for i, (name, dtype) in enumerate(df.dtypes.items(), 1):
        added = "  <-- ADDED BY THE BAKE" if name in (
            "canonical", "canonical_source", "lat_c", "lon_c") else ""
        print(f"  {i:>2}. {name:<32}{str(dtype):<16}{added}")

    print("\n=== DIFF AGAINST THE COMMITTED PARQUET ===")
    if OUT.exists():
        old = duckdb.connect().execute(
            f"SELECT * FROM read_parquet('{OUT.as_posix()}') LIMIT 0").df()
        old_n = duckdb.connect().execute(
            f"SELECT count(*) FROM read_parquet('{OUT.as_posix()}')").fetchone()[0]
        lo, hi = duckdb.connect().execute(
            f"SELECT min(crash_date), max(crash_date) "
            f"FROM read_parquet('{OUT.as_posix()}')").fetchone()
        print(f"  committed: {old_n:,} rows, {len(old.columns)} cols, "
              f"{lo:%Y-%m-%d}..{hi:%Y-%m-%d}, {OUT.stat().st_size/1e6:.1f} MB")
        print(f"  new:       {len(df):,} rows, {len(df.columns)} cols, "
              f"{df['crash_date'].min():%Y-%m-%d}..{df['crash_date'].max():%Y-%m-%d}")
        gained = [c for c in df.columns if c not in old.columns]
        lost = [c for c in old.columns if c not in df.columns]
        print(f"  columns gained: {gained or 'none'}")
        print(f"  columns lost:   {lost or 'none'}")
        print(f"  rows gained:    {len(df) - old_n:+,}")
        print(f"\n  THE CI GATE WILL FAIL until .github/workflows/tests.yml is "
              f"updated from {old_n:,} to {len(df):,} rows.")
    else:
        print("  no committed Parquet present; this would be the first bake")

    print("\n=== §2.3 CORRIDOR FIXTURE ===")
    cols = ["corridor", "crashes", "casualty_crashes", "injured", "killed",
            "share_other_tools_drop", "cells"]
    print(fixture[cols].to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true",
                    help="actually write the Parquet and the fixture")
    args = ap.parse_args()

    print("Loading the recovered pull...")
    df = load()
    print("Deriving the frozen columns...")
    df = derive(df)
    fixture = corridor_fixture(df)
    report(df, fixture)

    if not args.commit:
        print("\n" + "=" * 72)
        print("DRY RUN — nothing was written.")
        print("Spec §6 step 2 bakes exactly once, and every re-bake is another")
        print("permanent blob in git history. Review the schema above, then re-run")
        print("with --commit. Update these IN THE SAME COMMIT:")
        print("  · CLAUDE_CODE_PROMPT.md §0.2      (scripts/verify_figures.py prints it)")
        print("  · README.md")
        print("  · .github/workflows/tests.yml     (the row-count gate)")
        print("  · the PUBLISHED dict in scripts/verify_figures.py")
        print("=" * 72)
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False, compression="zstd")
    fixture.to_csv(FIXTURE, index=False)
    print(f"\nWrote {OUT} ({OUT.stat().st_size/1e6:.1f} MB)")
    print(f"Wrote {FIXTURE}")
    print("\nNow update §0.2, README, the CI gate and verify_figures.py's PUBLISHED "
          "dict, in this same commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
