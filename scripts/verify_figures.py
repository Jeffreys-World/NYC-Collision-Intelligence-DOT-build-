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
    # The first screen's finding (PR2, T10/T11), written 2026-09-16. The app
    # computes these through sql/finding_corridors.sql over borough_source;
    # compute_finding() below recomputes them independently, with its own SQL,
    # so a drift in either shows up here.
    "headline_corridor_deaths": 56,
    "headline_corridor_deaths_reported": 0,
    "featured_deaths": 288,
    "featured_deaths_hidden": 225,
    "featured_highways": 8,
    "featured_highways_at_zero": 7,
}

# The corridor the headline names. The app chooses it by rule
# (presentation.headline_row), so a different winner is a changed claim.
PUBLISHED_HEADLINE_CORRIDOR = "BELT PKWY"
FEATURED_CSV = ROOT / "data" / "featured_corridors.csv"

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

    # Deaths per 1,000 crashes, comparing borough-missing rows against
    # borough-present rows. That is the whole comparison — it is NOT a highway
    # vs surface-street comparison, and an earlier version of this comment
    # glossed it as one ("the unlabeled rows are overwhelmingly highway").
    # They are not: 106,209 of the 269,810 borough-missing rows (39%) are on a
    # limited-access road, carrying 389 of their 861 deaths (45%). Limited
    # access is the largest single contributor to the gap, not the explanation
    # for it. The §2.6 finding is that the rate differs by completeness, which
    # is what these two lines measure.
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


def compute_finding(source: Path) -> dict:
    """The featured-corridor finding, from the Parquet and the featured CSV.

    Deliberately NOT a call into app/presentation.py: this script is the check
    on the app, so it must not share the app's code path. `borough IS NULL` is
    the standard-view definition here; the app uses borough_source.
    """
    import csv

    with FEATURED_CSV.open(encoding="utf-8-sig", newline="") as fh:
        featured = list(csv.DictReader(l for l in fh if not l.startswith(">")))
    classes = {r["canonical"]: r["expected_class"] for r in featured}

    rows = duckdb.connect().execute(f"""
        SELECT canonical,
               coalesce(sum(number_of_persons_killed), 0)                          AS killed,
               coalesce(sum(number_of_persons_killed) FILTER (WHERE borough IS NOT NULL), 0) AS shown
        FROM read_parquet('{source.as_posix()}')
        WHERE canonical IN (SELECT unnest(?))
        GROUP BY canonical
    """, [list(classes)]).fetchall()
    stats = {c: (int(k), int(v)) for c, k, v in rows}
    for c in classes:
        stats.setdefault(c, (0, 0))

    at_zero = [(k, c) for c, (k, v) in stats.items() if k > 0 and v == 0]
    order = list(classes)
    # Most deaths shown at zero; ties go to the CSV's order, as in the app.
    headline = (min(at_zero, key=lambda kc: (-kc[0], order.index(kc[1])))[1]
                if at_zero else None)
    highways = [c for c in classes if classes[c] == "highway"]
    return {
        "headline_corridor": headline,
        "headline_corridor_deaths": stats[headline][0] if headline else 0,
        "headline_corridor_deaths_reported": stats[headline][1] if headline else 0,
        "featured_deaths": sum(k for k, _ in stats.values()),
        "featured_deaths_hidden": sum(k - v for k, v in stats.values()),
        "featured_highways": len(highways),
        "featured_highways_at_zero": sum(1 for c in highways
                                         if stats[c][0] > 0 and stats[c][1] == 0),
    }


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
    got, claimed = f.get("headline_corridor"), PUBLISHED_HEADLINE_CORRIDOR
    ok = got == claimed
    bad += not ok
    print(f"{'headline_corridor':<34}{str(got):>14}{claimed:>14}   {'ok' if ok else 'CHANGED'}")
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
    f.update(compute_finding(args.source))
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
