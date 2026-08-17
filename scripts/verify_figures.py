"""Recompute every published figure, and diff it against what the docs claim.

    .venv/bin/python scripts/verify_figures.py
    .venv/bin/python scripts/verify_figures.py --source data/raw/crashes_recovered.parquet

WHY THIS EXISTS. Spec §0.2 carries a table of verified dataset figures, README
repeats several of them, and the CI workflow asserts a row count. On 2026-08-15
all eighteen matched. On 2026-08-16 the coverage was extended from 2025-12-31 to
2026-06-11 and every one of them went stale at once — while still reading as
verified fact, because a number in prose carries no timestamp.

The spec's own §2.3 makes the argument better than this docstring can: a table of
hand-copied counts became a second source of truth, and the engineering review
reproduced ZERO of twelve. The fix there was to generate the fixture. This is the
same fix for the figures.

So the numbers below are computed, printed as a paste-ready block, and DIFFED
against the values currently written into the docs. A figure that moves shows up
as a FAIL here rather than as a wrong number in front of a DOT engineer.

Run it after any re-pull. It is also the source for the §0.2 table: paste the
block it prints, do not retype it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "data" / "processed" / "crashes.parquet"

# What the documents currently claim, and where. Update these in the SAME commit
# that updates the prose, or this script stops meaning anything.
#
# Values are those written on 2026-08-16 for the 2019-01-01..2026-06-11 slice.
# NOTE ON DRIFT. The first run of this script against a fresh 2026-08-16 pull
# reproduced sixteen of eighteen figures and moved two: rows_with_casualties
# 290,352 -> 290,354 and rows_no_coordinates 66,420 -> 66,419. Both pulls were
# taken on the same day. NYPD amends published records, so the feed is not
# byte-stable even at a fixed max date, and a figure written into prose starts
# drifting immediately. That is the argument for this script in one line.
PUBLISHED = {
    "rows": 848_739,
    "rows_with_casualties": 290_354,
    "rows_no_coordinates": 66_419,
    "crashes_no_borough": 269_810,
    "total_deaths": 1_945,
    "deaths_in_borough_less_rows": 861,
    "unlabeled_carrying_coordinates": 221_658,
    "distinct_vehicle_type_code1": 1_430,
}

# Percentages and ratios are checked to a tolerance, because they are printed to
# one or two decimals and a rounding difference is not a regression.
PUBLISHED_PCT = {
    "pct_with_casualties": (34.2, 0.05),
    "pct_no_borough": (31.8, 0.05),
    "pct_deaths_in_borough_less": (44.3, 0.05),
    "fatality_rate_unlabeled": (3.191, 0.002),
    "fatality_rate_labeled": (1.872, 0.002),
    "fatality_ratio": (1.70, 0.01),
    "pct_unlabeled_with_coords": (82.2, 0.05),
}


def compute(source: Path) -> dict:
    con = duckdb.connect()
    reader = f"read_parquet('{source.as_posix()}')"

    row = con.execute(f"""
        SELECT
            count(*)                                                     AS rows,
            count(*) FILTER (WHERE number_of_persons_injured > 0
                                OR number_of_persons_killed > 0)         AS rows_with_casualties,
            count(*) FILTER (WHERE latitude IS NULL OR longitude IS NULL) AS rows_no_coordinates,
            count(*) FILTER (WHERE borough IS NULL)                      AS crashes_no_borough,
            sum(number_of_persons_killed)                                AS total_deaths,
            sum(number_of_persons_killed) FILTER (WHERE borough IS NULL) AS deaths_in_borough_less_rows,
            count(*) FILTER (WHERE borough IS NULL
                               AND latitude IS NOT NULL
                               AND longitude IS NOT NULL)                AS unlabeled_carrying_coordinates,
            count(DISTINCT vehicle_type_code1)                           AS distinct_vehicle_type_code1,
            min(crash_date)                                              AS first_crash,
            max(crash_date)                                              AS last_crash
        FROM {reader}
    """).df().iloc[0].to_dict()

    f = {k: (int(v) if k not in ("first_crash", "last_crash") else v)
         for k, v in row.items()}

    labeled = f["rows"] - f["crashes_no_borough"]
    deaths_labeled = f["total_deaths"] - f["deaths_in_borough_less_rows"]

    # Deaths per 1,000 crashes. The unlabeled rows are overwhelmingly highway,
    # which is why their rate is the higher one — the §2.6 finding.
    f["fatality_rate_unlabeled"] = f["deaths_in_borough_less_rows"] / f["crashes_no_borough"] * 1000
    f["fatality_rate_labeled"] = deaths_labeled / labeled * 1000
    f["fatality_ratio"] = f["fatality_rate_unlabeled"] / f["fatality_rate_labeled"]

    f["pct_with_casualties"] = f["rows_with_casualties"] / f["rows"] * 100
    f["pct_no_borough"] = f["crashes_no_borough"] / f["rows"] * 100
    f["pct_deaths_in_borough_less"] = f["deaths_in_borough_less_rows"] / f["total_deaths"] * 100
    f["pct_unlabeled_with_coords"] = (f["unlabeled_carrying_coordinates"]
                                      / f["crashes_no_borough"] * 100)

    cols = {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()}
    if "borough_source" in cols:
        rec = con.execute(
            f"SELECT borough_source, count(*) n FROM {reader} GROUP BY 1"
        ).df().set_index("borough_source")["n"].to_dict()
        f["recovery"] = {k: int(v) for k, v in rec.items()}
    return f


def render(f: dict) -> str:
    """The §0.2 table, ready to paste. Never retype these."""
    return "\n".join([
        "| Measure | Value |",
        "|---|---|",
        f"| Rows ({f['first_crash']:%Y}–{f['last_crash']:%Y-%m-%d}) | {f['rows']:,} |",
        f"| Rows with casualties (injured > 0 OR killed > 0) | {f['rows_with_casualties']:,} "
        f"(**{f['pct_with_casualties']:.1f}%**) |",
        f"| Rows with no coordinates | {f['rows_no_coordinates']:,} |",
        f"| Crashes with no `borough` value | {f['crashes_no_borough']:,} "
        f"(**{f['pct_no_borough']:.1f}%**) |",
        f"| Total deaths | {f['total_deaths']:,} |",
        f"| Deaths in rows with no borough | {f['deaths_in_borough_less_rows']:,} "
        f"(**{f['pct_deaths_in_borough_less']:.1f}%**) |",
        f"| Fatality rate, unlabeled vs labeled | {f['fatality_rate_unlabeled']:.3f} vs "
        f"{f['fatality_rate_labeled']:.3f} per 1,000 (**{f['fatality_ratio']:.2f}×**) |",
        f"| Unlabeled rows **carrying coordinates** | {f['unlabeled_carrying_coordinates']:,} "
        f"({f['pct_unlabeled_with_coords']:.1f}% of unlabeled) |",
        f"| Distinct raw `vehicle_type_code1` values | {f['distinct_vehicle_type_code1']:,} |",
    ])


def diff(f: dict) -> int:
    """Compare against what the docs claim. Returns the number of mismatches."""
    bad = 0
    print(f"\n{'figure':<34}{'computed':>14}{'published':>14}   status")
    print("-" * 78)
    for key, claimed in PUBLISHED.items():
        got = f[key]
        ok = got == claimed
        bad += not ok
        print(f"{key:<34}{got:>14,}{claimed:>14,}   {'ok' if ok else 'CHANGED'}")
    for key, (claimed, tol) in PUBLISHED_PCT.items():
        got = f[key]
        ok = abs(got - claimed) <= tol
        bad += not ok
        print(f"{key:<34}{got:>14.3f}{claimed:>14.3f}   {'ok' if ok else 'CHANGED'}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = ap.parse_args()

    if not args.source.exists():
        raise SystemExit(f"no such file: {args.source}")

    print(f"Source: {args.source}")
    f = compute(args.source)
    print(f"Coverage: {f['first_crash']:%Y-%m-%d} .. {f['last_crash']:%Y-%m-%d}")
    if "recovery" in f:
        r = f["recovery"]
        print(f"Borough recovery: " + " · ".join(f"{k} {v:,}" for k, v in sorted(r.items())))

    print("\n--- §0.2 table, paste-ready ---\n")
    print(render(f))

    bad = diff(f)
    if bad:
        print(f"\n{bad} figure(s) differ from what the docs claim.")
        print("Update CLAUDE_CODE_PROMPT.md §0.2, README.md, .github/workflows/tests.yml")
        print("and the PUBLISHED dict in this file — in ONE commit, or the next")
        print("reader cannot tell which number is current.")
        return 1
    print("\nAll published figures reproduce.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
