"""Street normalisation tests (spec §2.4).

Every fixture value in this file is a REAL raw value read off
`data/processed/crashes.parquet` on 2026-08-16, with its row count in the
comment. Spec §4.1: test cleaning rules with real raw values, not invented ones.
An invented fixture proves the regex does what you wrote; a real one proves it
does what the data needs.
"""

from __future__ import annotations

import csv
from pathlib import Path

import duckdb
import pytest

from app.streets import canonical_name, canonical_street, normalize_name

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "data" / "processed" / "crashes.parquet"
CORRIDORS = ROOT / "data" / "featured_corridors.csv"


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = (line for line in fh if not line.startswith(">"))
        return list(csv.DictReader(rows))


# ---------------------------------------------------------------- rule 1

def test_house_number_stripped_from_cross_street():
    """`3468  RICHMOND RD` — the spec's own example, and a cross-street value."""
    assert canonical_name("3468  RICHMOND RD", is_cross_street=True) == "RICHMOND RD"


def test_house_number_never_stripped_from_on_street():
    """The regression the spec names explicitly.

    100,728 on_street_name values begin with a digit and a single space. If the
    house-number rule ever escapes its column, `3 AVENUE` collapses to `AVENUE`
    and takes a real corridor with it — silently, because the result still looks
    like a street name.
    """
    assert canonical_name("3 AVENUE") == "3 AVE"
    assert canonical_name("5 AVENUE") == "5 AVE"


def test_single_spaced_digit_survives_even_in_the_cross_street_column():
    """Belt AND braces. The column scope is one guard; `\\s{2,}` is the other.

    `3 AVENUE` appearing as a cross street must still survive, because a house
    number in this data is always followed by two or more spaces.
    """
    assert canonical_name("3 AVENUE", is_cross_street=True) == "3 AVE"


# ---------------------------------------------------------------- rule 3

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BELT PARKWAY", "BELT PKWY"),                      # 12,043 rows
        ("LONG ISLAND EXPRESSWAY", "LONG ISLAND EXPY"),     # 7,901
        ("ATLANTIC AVENUE", "ATLANTIC AVE"),                # 5,179
        ("LINDEN BOULEVARD", "LINDEN BLVD"),                # 3,740
        ("FDR DRIVE", "FDR DR"),                            # 6,246
        ("VAN WYCK EXPWY", "VAN WYCK EXPY"),                # 4,232
    ],
)
def test_suffix_standardisation(raw, expected):
    assert canonical_name(raw) == expected


def test_suffix_rule_is_token_wise_not_terminal_only():
    """`FLATBUSH AVENUE EXTENSION` (620 rows) carries AVENUE mid-name.

    A terminal-token-only rule would leave it as `FLATBUSH AVENUE EXTENSION`
    while the parent road normalised to `FLATBUSH AVE`, splitting one street
    across two spellings for the sake of the word that follows it.
    """
    assert canonical_name("FLATBUSH AVENUE EXTENSION") == "FLATBUSH AVE EXTENSION"


# ---------------------------------------------------------------- rule 4

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("BELT PARKWAY RAMP", "BELT PKWY"),                              # 326
        ("BROOKLYN QUEENS EXPRESSWAY RAMP", "BROOKLYN QUEENS EXPY"),     # 694
        ("CROSS BRONX EXPY RAMP", "CROSS BRONX EXPY"),                   # 426
        ("BELT PARKWAY EXIT 5 EASTBOUND", "BELT PKWY"),                  # 17
        ("BELT PARKWAY EXIT 24 A WB", "BELT PKWY"),                      # 12
        ("LONG ISLAND EXPWY WB ET 18", "LONG ISLAND EXPY"),              # 1
        ("BROOKLYN QUEENS EXPRESSWAY W/B", "BROOKLYN QUEENS EXPY"),      # 18
        ("BELT PY EB EN CROSS BAY BLVD NB", "BELT PKWY"),                # 4
        ("MAJOR DEEGAN EP SB EN JEROME AV", "MAJOR DEEGAN EXPY"),        # 7
        ("LINDEN BOULEVARD WB TURNLANE", "LINDEN BLVD"),                 # 1
    ],
)
def test_ramp_and_direction_noise_is_stripped(raw, expected):
    assert canonical_name(raw) == expected


def test_noise_strip_never_eats_the_first_token():
    """`WEST SERVICE ROAD` (23 rows) must not truncate to nothing.

    It also proves why bare EAST/WEST are not noise tokens: `WEST END AVE` and
    `EAST BROADWAY` are real streets.
    """
    assert canonical_name("WEST SERVICE ROAD") == "WEST SERVICE RD"
    assert canonical_name("WEST END AVENUE") == "WEST END AVE"
    assert canonical_name("EAST BROADWAY") == "EAST BROADWAY"


def test_parentheticals_are_stripped():
    """The whole parenthetical universe is `(BQE)`, `(CDR)` and one `(WESTBO`."""
    assert canonical_name("LONG ISLAND EXPRESSWAY (CDR)") == "LONG ISLAND EXPY"
    assert canonical_name("BROOKLYN QUEENS EXPY (CDR)") == "BROOKLYN QUEENS EXPY"


# --------------------------------------------------- the service-road guard

@pytest.mark.parametrize(
    "raw,expected",
    [
        # Both of these are exactly 32 characters — the truncation limit of the
        # on_street_name column. A guard spelled `SERVICE ROAD` misses both.
        ("GRAND CENTRAL PARKWAY SERVICE RO", "GRAND CENTRAL PKWY SERVICE RD"),
        ("CROSS BRONX EXPRESSWAY SERVICE R", "CROSS BRONX EXPY SERVICE RD"),
        ("CLEARVIEW EXPRESSWAY SERVICE ROA", "CLEARVIEW EXPY SERVICE RD"),
        ("GRAND CENTRAL PARKWAY SERVICE RD", "GRAND CENTRAL PKWY SERVICE RD"),
        ("VAN WYCK EXPRESSWAY SERVICE ROAD", "VAN WYCK EXPY SERVICE RD"),
        ("FDR SERVICE ROAD", "FDR SERVICE RD"),
    ],
)
def test_service_roads_normalise_but_never_fold_into_the_parent(raw, expected):
    """A service road is a SURFACE street (spec §2.4 rule 6, §3.1).

    Folding `GRAND CENTRAL PARKWAY SERVICE RO` into `GRAND CENTRAL PKWY` would
    put a surface street into the highway branch of the estimator and offer it
    guardrail instead of a crosswalk.
    """
    assert canonical_name(raw) == expected


def test_service_road_is_a_different_corridor_from_its_parent():
    parent = canonical_name("GRAND CENTRAL PARKWAY")
    service = canonical_name("GRAND CENTRAL PARKWAY SERVICE RO")
    assert parent != service


# ---------------------------------------------------------------- rule 6

def test_alias_closes_the_missing_space_split():
    """Van Wyck splits 4,232 / 1,423 on one absent space. No rule closes that."""
    assert canonical_name("VAN WYCK EXPWY") == "VAN WYCK EXPY"
    assert canonical_name("VANWYCK EXPRESSWAY") == "VAN WYCK EXPY"


def test_alias_closes_a_source_misspelling():
    """`CROSS BRONX EXTENTION`, 84 rows, misspelled upstream."""
    assert canonical_name("CROSS BRONX EXTENTION") == "CROSS BRONX EXPY EXTENSION"
    assert canonical_name("CROSS BRONX EXPRESSWAY EXTENSION") == "CROSS BRONX EXPY EXTENSION"


def test_extensions_stay_separate_from_their_parent():
    """A decision, recorded so it cannot become an accident.

    Flatbush Avenue Extension is a different road from Flatbush Avenue. Folding
    it in would inflate a featured corridor.
    """
    assert canonical_name("FLATBUSH AVENUE") != canonical_name("FLATBUSH AVENUE EXTENSION")
    assert canonical_name("FLATBUSH AVENUE EXT") == "FLATBUSH AVE EXTENSION"


def test_values_naming_two_roads_are_deliberately_unmatched():
    """`G.C.P. / L.I.E.` belongs to two corridors at once.

    Assigning it to one inflates that corridor; assigning it to both
    double-counts citywide. So it is assigned to neither, on purpose.
    """
    assert canonical_name("G.C.P. / LAGUARDIA (CDR)") is None
    assert canonical_name("G.C.P / L.I.E. (CDR)") is None
    assert canonical_name("ATLANTIC AVENUE & GEORGIA AVENUE") is None
    assert canonical_name("Flatbush Ave & Kings highway") is None


def test_the_two_road_rule_does_not_eat_a_direction_token():
    """`BROOKLYN QUEENS EXPRESSWAY W/B` (18 rows) has a slash inside `W/B`.

    The separator must be space-delimited, or a direction token reads as a
    second road and 18 rows silently leave the corridor.
    """
    assert canonical_name("BROOKLYN QUEENS EXPRESSWAY W/B") == "BROOKLYN QUEENS EXPY"


def test_service_road_excision_does_not_leave_a_doubled_space():
    """`Fdr drive service road northboun` — the tail sits mid-string.

    Cutting it out without re-collapsing whitespace produced
    `FDR DR  NORTHBOUN SERVICE RD`, which is a different key from every other
    FDR service-road spelling.
    """
    assert canonical_name("Fdr drive service road northboun") == "FDR DR SERVICE RD"
    assert "  " not in (canonical_name("FDR DRIVE SERVICE ROAD") or "")


def test_abbreviated_service_road_is_still_a_surface_street():
    """`MAJOR DEEGAN EXPRESSWAY SR` abbreviates the service road to two letters.

    Read as a highway it gets offered guardrail (§3.1). It must land on the same
    key as the spelled-out form.
    """
    assert canonical_name("MAJOR DEEGAN EXPRESSWAY SR") == "MAJOR DEEGAN SERVICE RD"
    assert canonical_name("MAJOR DEEGAN EXPRESSWAY SR SB") == "MAJOR DEEGAN SERVICE RD"
    assert canonical_name("MAJOR DEEGAN SERVICE ROAD") == "MAJOR DEEGAN SERVICE RD"


def test_gowanus_does_not_fold_into_the_bqe():
    """`GOWANUS EXPY (BQE)` is 1,371 rows and a distinct corridor.

    Stripping the parenthetical must leave the host name standing, not adopt the
    road named inside the brackets.
    """
    assert canonical_name("GOWANUS EXPY (BQE)") == "GOWANUS EXPY"


def test_wyckoff_avenue_does_not_fold_into_van_wyck():
    assert canonical_name("WYCKOFF AVENUE") == "WYCKOFF AVE"


# ---------------------------------------------------------------- rule 5

def test_prefers_on_street_and_reports_which_column_matched():
    name, source = canonical_street("BELT PARKWAY", "3468  RICHMOND RD")
    assert (name, source) == ("BELT PKWY", "on")


def test_falls_back_to_cross_street_and_says_so():
    name, source = canonical_street(None, "3468  RICHMOND RD")
    assert (name, source) == ("RICHMOND RD", "cross")


def test_reports_no_match_rather_than_guessing():
    assert canonical_street(None, None) == (None, "none")
    assert canonical_street("", "   ") == (None, "none")


# ------------------------------------- the featured corridors, against the data

@pytest.mark.skipif(not PARQUET.exists(), reason="committed Parquet not present")
@pytest.mark.parametrize("row", _read_csv(CORRIDORS), ids=lambda r: r["corridor"])
def test_no_high_volume_spelling_is_stranded_near_a_featured_corridor(row):
    """Spec §2.4: assert every featured corridor's alias set is complete.

    Catching a MISSING alias needs a net cast by similarity, not by prefix. The
    first version of this test probed on the canonical's leading word and was
    useless in both directions: `VAN` collected `PENNSYLVANIA AVENUE`, while
    `BROOKLYN QNS EXPRESSWAY` — 113 real BQE rows — was invisible to a probe on
    `BROOKLYN QUEENS`.

    So: canonicalise every distinct raw value, keep those that land close to a
    featured corridor's canonical name, and require each to be either that
    corridor or a road on the reviewed separate-roads list.

    The n >= 5 floor is a stated decision, not an oversight. Below it the field
    is single-row typos (`belt parkwayy`, `belt parrkway`), and a suite that
    fails on those trains people to ignore it.
    """
    canonical = row["canonical"]
    con = duckdb.connect()

    distinct = con.execute(
        f"""
        SELECT on_street_name, count(*) AS n
        FROM read_parquet('{PARQUET.as_posix()}')
        WHERE on_street_name IS NOT NULL
        GROUP BY 1 HAVING count(*) >= 5
        """
    ).fetchall()

    stranded = []
    for raw, n in distinct:
        got = canonical_name(raw)
        if got is None or got == canonical:
            continue
        similarity = con.execute(
            "SELECT jaro_winkler_similarity(?, ?)", [got, canonical]
        ).fetchone()[0]
        if similarity >= 0.88:
            stranded.append((n, raw, got))

    # Roads that sit close to a featured corridor by name and are genuinely
    # different streets. Two whole classes are excluded by suffix — a service
    # road is a surface street beside its parent, and an Extension is its own
    # named road — and the rest are listed one by one, so adding to this set is
    # a decision somebody makes on purpose.
    reviewed_separate = {"W BROADWAY", "E BROADWAY", "BROADWAY TERRACE",
                         "LINDEN PL", "LINDEN ST"}
    leaked = [
        (n, raw, got) for n, raw, got in stranded
        if got not in reviewed_separate
        and not got.endswith(" SERVICE RD")
        and not got.endswith(" EXTENSION")
    ]
    assert not leaked, (
        f"{row['corridor']}: {len(leaked)} spelling(s) normalise to something "
        f"close to {canonical!r} but not equal to it. Add an alias to "
        f"data/street_aliases.csv, or add the road to reviewed_separate:\n"
        + "\n".join(f"  {n:>6} rows  {raw!r} -> {got!r}"
                    for n, raw, got in sorted(leaked, reverse=True))
    )


@pytest.mark.skipif(not PARQUET.exists(), reason="committed Parquet not present")
@pytest.mark.parametrize("row", _read_csv(CORRIDORS), ids=lambda r: r["corridor"])
def test_every_featured_corridor_matches_rows_in_the_data(row):
    """The corridor's canonical name must actually exist in the data.

    Cheap, and it catches the failure mode that a normalisation unit test never
    will: a `canonical` value in featured_corridors.csv that no raw row ever
    produces. Writing `FDR DRIVE` where the rules emit `FDR DR` would give the
    dropdown an entry that selects nothing, and every figure in the drawer would
    read zero without anything having thrown.

    Deliberately asserts only "> 0". The pinned per-corridor figures belong in
    data/corridor_fixture.csv, which the bake generates and a golden test
    guards — spec §2.3 keeps counts out of hand-maintained files.
    """
    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT on_street_name, count(*) AS n
        FROM read_parquet('{PARQUET.as_posix()}')
        WHERE on_street_name IS NOT NULL
        GROUP BY 1
        """
    ).fetchall()

    matched = sum(n for raw, n in rows if canonical_name(raw) == row["canonical"])
    assert matched > 0, (
        f"{row['corridor']}: no raw on_street_name value normalises to "
        f"{row['canonical']!r}. The canonical in featured_corridors.csv is "
        f"wrong, or a rule changed underneath it."
    )
