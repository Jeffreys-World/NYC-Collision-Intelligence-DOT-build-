"""Golden test pinning the §2.3 corridor fixture.

Spec §2.3: the featured-corridor table carries INPUTS only, the bake emits
`data/processed/corridor_fixture.csv` with the real figures, "and a golden test
pins it so a normalisation change fails loudly instead of silently shifting every
number on screen."

This is that test. It recomputes each corridor's figures from the committed
Parquet and compares them against the committed fixture. The two can only agree
if the normaliser still groups crashes the way it did when the fixture was baked,
so a change to `app/streets.py`, to `data/street_aliases.csv`, or to the Parquet
itself shows up here as a failing assertion naming the corridor.

WHY THIS EXISTS AT ALL. The earlier spec carried twelve hand-copied corridor
counts and the engineering review on 2026-08-15 reproduced ZERO of twelve. The
§7 demo narrative is rehearsed from these figures, so the script somebody says out
loud and the number on screen have to come from the same query.

SKIPPED UNTIL THE BAKE RUNS. The fixture and the `canonical` column both arrive
with §6 step 2, which is the owner's review checkpoint and deliberately has not
happened. The test is committed ahead of it so the pin is live the moment the bake
lands, rather than being something to remember afterwards.
"""

from __future__ import annotations

from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "data" / "processed" / "crashes.parquet"
FIXTURE = ROOT / "data" / "processed" / "corridor_fixture.csv"

# Counts that must reproduce exactly. Shares are checked separately, to a
# tolerance, because they are rounded in the file.
EXACT_COLUMNS = [
    "crashes",
    "casualty_crashes",
    "injured",
    "killed",
    "pedestrians_injured",
    "pedestrians_killed",
    "crashes_other_tools_drop",
    "recovered",
    "unrecoverable",
    "with_coordinates",
    "cells",
]


def _parquet_has_canonical() -> bool:
    if not PARQUET.exists():
        return False
    cols = {
        row[0]
        for row in duckdb.connect()
        .execute(f"DESCRIBE SELECT * FROM read_parquet('{PARQUET.as_posix()}')")
        .fetchall()
    }
    return "canonical" in cols


pytestmark = pytest.mark.skipif(
    not (FIXTURE.exists() and _parquet_has_canonical()),
    reason=(
        "the corridor fixture and the baked `canonical` column arrive with §6 step 2, "
        "the owner's review checkpoint. Run `scripts/bake.py --commit` to activate "
        "this pin."
    ),
)


@pytest.fixture(scope="module")
def fixture_rows():
    import csv

    with FIXTURE.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def recomputed():
    """Recompute every corridor's figures straight from the Parquet.

    Deliberately written as one SQL statement rather than in pandas: this is the
    shape of query the app itself will run, so if the app and the fixture ever
    disagree, the cause is the normalisation and not a difference between two
    aggregation implementations.
    """
    return (
        duckdb.connect()
        .execute(
            f"""
            SELECT canonical,
                   count(*)                                          AS crashes,
                   count(*) FILTER (WHERE number_of_persons_injured > 0
                                       OR number_of_persons_killed > 0)
                                                                     AS casualty_crashes,
                   sum(number_of_persons_injured)                    AS injured,
                   sum(number_of_persons_killed)                     AS killed,
                   sum(number_of_pedestrians_injured)                AS pedestrians_injured,
                   sum(number_of_pedestrians_killed)                 AS pedestrians_killed,
                   count(*) FILTER (WHERE borough IS NULL)           AS crashes_other_tools_drop,
                   count(*) FILTER (WHERE borough_source = 'recovered')     AS recovered,
                   count(*) FILTER (WHERE borough_source = 'unrecoverable') AS unrecoverable,
                   count(*) FILTER (WHERE latitude IS NOT NULL)      AS with_coordinates,
                   count(DISTINCT (lat_c, lon_c)) FILTER (WHERE lat_c IS NOT NULL)
                                                                     AS cells
            FROM read_parquet('{PARQUET.as_posix()}')
            WHERE canonical IS NOT NULL
            GROUP BY canonical
            """
        )
        .df()
        .set_index("canonical")
    )


def test_fixture_covers_every_featured_corridor(fixture_rows):
    import csv

    featured = ROOT / "data" / "featured_corridors.csv"
    with featured.open(encoding="utf-8-sig") as fh:
        lines = [line for line in fh if not line.startswith(">")]
    wanted = {row["canonical"] for row in csv.DictReader(lines)}
    have = {row["canonical"] for row in fixture_rows}
    assert wanted == have, (
        f"the fixture and the featured-corridor table disagree. "
        f"missing from fixture: {sorted(wanted - have)}; "
        f"unexpected in fixture: {sorted(have - wanted)}"
    )


def test_every_figure_reproduces_from_the_parquet(fixture_rows, recomputed):
    """The pin itself.

    A normalisation change that regroups crashes moves these counts, and this is
    where it surfaces — naming the corridor and the column, so the failure says
    what happened rather than that a total changed somewhere.
    """
    problems = []
    for row in fixture_rows:
        name = row["canonical"]
        if name not in recomputed.index:
            problems.append(f"{name}: absent from the Parquet entirely")
            continue
        live = recomputed.loc[name]
        for column in EXACT_COLUMNS:
            expected = int(row[column])
            got = int(live[column])
            if expected != got:
                problems.append(
                    f"{name}.{column}: fixture {expected:,} vs Parquet {got:,} "
                    f"({got - expected:+,})"
                )
    assert not problems, (
        "the committed fixture no longer reproduces from the Parquet:\n  "
        + "\n  ".join(problems)
        + "\n\nIf a normalisation change caused this deliberately, re-run "
        "scripts/bake.py and commit the new fixture in the same change."
    )


def test_share_other_tools_drop_matches_its_own_counts(fixture_rows):
    """The §2.6 badge's share must equal its own numerator over its denominator.

    It is rendered directly on screen, so an inconsistency here is a wrong number
    in front of an engineer rather than a failed internal check.
    """
    for row in fixture_rows:
        crashes = int(row["crashes"])
        dropped = int(row["crashes_other_tools_drop"])
        share = float(row["share_other_tools_drop"])
        assert crashes > 0, row["canonical"]
        assert share == pytest.approx(dropped / crashes, abs=5e-5), (
            f"{row['canonical']}: share {share} does not match "
            f"{dropped:,}/{crashes:,}"
        )


def test_highway_corridors_carry_a_far_higher_dropped_share(fixture_rows):
    """§2.6's central contrast, pinned.

    Highway corridors sit far above surface ones on this measure, and that gap is
    the finding the product is built to show. If normalisation ever folds a
    service road into its parkway, the highway share falls and this fails.
    """
    by_class: dict[str, list[float]] = {}
    for row in fixture_rows:
        by_class.setdefault(row["expected_class"], []).append(
            float(row["share_other_tools_drop"])
        )
    assert "highway" in by_class and "surface" in by_class
    assert min(by_class["highway"]) > max(by_class["surface"]) + 0.30, (
        f"highway shares {sorted(by_class['highway'])} vs "
        f"surface {sorted(by_class['surface'])} — the §2.6 contrast has collapsed"
    )


def test_casualty_crashes_never_exceed_crashes(fixture_rows):
    for row in fixture_rows:
        assert int(row["casualty_crashes"]) <= int(row["crashes"]), row["canonical"]
        assert int(row["with_coordinates"]) <= int(row["crashes"]), row["canonical"]
