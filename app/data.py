"""
Data access. One seam between the app and whatever is backing it.

Seeded from Jeffreys-World/Motor-Vehicle-Collisions---Crashes-Dashboard on
2026-08-16 (spec §0.3 #1). The source-resolution seam, the DuckDB connection
handling and the recovery-column synthesis are carried over unchanged in
behaviour — they are QA-hardened and rewriting them would discard real work.

Dropped in the port: `gap_direction` and `FULL_TABLE_DEATH_SHARE`. Those encode
the dashboard's "39.8% of deaths sit in unlabeled rows" finding, which is that
product's argument, not this one's.

    data/processed/crashes.parquet   -> PRODUCTION. The committed 2019-2025 pull.
    (absent)                         -> NO_DATA. App renders the finding only.

    ┌──────────────────┐
    │ resolve_source() │──► Source(kind, reader, label, trustworthy)
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐   base_view.sql   ┌───────────────────┐
    │ get_connection() │──────────────────►│ crashes_filtered  │
    │ (st.cache_res.)  │  $source bound     │  (shared view)    │
    └──────────────────┘                    └─────────┬─────────┘
                                                      │
                                      every chart query selects from here

§4.2: a fallback must announce itself. `Source.trustworthy` is False for any
source whose numbers must never reach an export. The same rule governs the
Empirical Bayes join (§2.7): an unmatched corridor is LABELLED unmatched, never
silently downgraded to a raw observed count while still being called an estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import duckdb
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"

PARQUET = ROOT / "data" / "processed" / "crashes.parquet"
EB_CORRIDORS_CSV = ROOT / "data" / "eb_corridors.csv"
EB_CELLS_PARQUET = ROOT / "data" / "raw" / "eb_cells.parquet"

# Static by design, and both halves are facts that cannot rot.
#
# UPSTREAM_THROUGH describes the SOURCE feed, not what this app ships. Never
# render it as the app's coverage: the shipped slice is 2019-2025, so a header
# reading "data through 2026-06-11" over a map that stops in 2025 is false.
# Coverage is derived from the data itself — see `date_bounds` and
# `freshness_line`.
#
# Never compute an elapsed-days figure from these. "~65 days" was true only on
# 2026-08-15 and grows by one every day; a demo that slips two weeks shows a
# number that is quietly wrong. Found by /qa on 2026-08-09 (ISSUE-002) and
# re-flagged by the eng review on 2026-08-16.
UPSTREAM_THROUGH = "2026-06-11"
PULLED_ON = "2026-08-08"


@dataclass(frozen=True)
class Source:
    kind: str            # "parquet" | "none"
    reader: str          # a DuckDB table function, or "" when kind == "none"
    label: str           # human-readable, shown in the UI
    trustworthy: bool    # False means: render, but never let a number be quoted


def resolve_source() -> Source:
    if PARQUET.exists():
        return Source("parquet", f"read_parquet('{PARQUET.as_posix()}')",
                      "committed 2019-2025 pull", True)
    return Source("none", "", "no data file present", False)


@st.cache_resource(show_spinner=False)
def get_connection(reader: str) -> duckdb.DuckDBPyConnection:
    """One in-process DuckDB connection, reused across Streamlit reruns.

    Keyed on `reader` so dropping a re-baked Parquet in rebuilds the view
    instead of serving a stale cache.
    """
    con = duckdb.connect(database=":memory:")
    # Two names on purpose. `crashes_base` wraps the reader; `crashes_raw` adds
    # the recovery columns on top. Defining crashes_raw in terms of itself is a
    # self-reference DuckDB rejects with "infinite recursion detected".
    con.execute(f"CREATE OR REPLACE VIEW crashes_base AS SELECT * FROM {reader}")
    _ensure_recovery_columns(con)
    _ensure_eb_views(con)
    return con


def _ensure_eb_views(con: duckdb.DuckDBPyConnection) -> None:
    """Register the EB fit's own outputs as views, keyed the same as crashes.

    Both are `scripts/fit_eb.py` output, refit independently of a Streamlit
    rerun — the app reads them, it never computes them. Absent gracefully: a
    dev environment that has not run the fit yet gets empty views rather than
    a crash, and every EB figure downstream reads as unmatched rather than
    zero (§4.2).
    """
    if EB_CORRIDORS_CSV.exists():
        con.execute(
            f"CREATE OR REPLACE VIEW eb_corridors AS "
            f"SELECT * FROM read_csv_auto('{EB_CORRIDORS_CSV.as_posix()}')"
        )
    else:
        con.execute(
            "CREATE OR REPLACE VIEW eb_corridors AS "
            "SELECT NULL::VARCHAR AS canonical, NULL::DOUBLE AS eb_estimate, "
            "NULL::BOOLEAN AS eb_matched, NULL::DOUBLE AS coverage WHERE FALSE"
        )

    if EB_CELLS_PARQUET.exists():
        con.execute(
            f"CREATE OR REPLACE VIEW eb_cells AS "
            f"SELECT * FROM read_parquet('{EB_CELLS_PARQUET.as_posix()}')"
        )
    else:
        con.execute(
            "CREATE OR REPLACE VIEW eb_cells AS "
            "SELECT NULL::DOUBLE AS lat_c, NULL::DOUBLE AS lon_c, "
            "NULL::VARCHAR AS canonical, NULL::DOUBLE AS observed, "
            "NULL::DOUBLE AS eb_estimate, NULL::DOUBLE AS eb_weight, "
            "NULL::BOOLEAN AS is_highway, NULL::DOUBLE AS limited_access_share, "
            "NULL::BOOLEAN AS eb_matched WHERE FALSE"
        )


def _ensure_recovery_columns(con: duckdb.DuckDBPyConnection) -> None:
    """Make the schema stable whether or not the borough recovery has run yet.

    The bake (§6 step 2) adds `borough_recovered` and `borough_source`. Until it
    does, synthesise them so every downstream query is valid: `reported` where
    NYPD gave us a borough, NULL where it did not. Nothing is invented — a row
    with no borough stays unlabeled, which is the honest state and the finding.

    §0.3 #2: `borough` is NEVER overwritten in place.
    """
    cols = {r[0] for r in con.execute("DESCRIBE crashes_base").fetchall()}
    if "borough_source" in cols:
        con.execute("CREATE OR REPLACE VIEW crashes_raw AS SELECT * FROM crashes_base")
        return
    con.execute(
        """
        CREATE OR REPLACE VIEW crashes_raw AS
        SELECT *,
               borough AS borough_recovered,
               CASE WHEN borough IS NOT NULL THEN 'reported' END AS borough_source
        FROM crashes_base
        """
    )


def normalize_date_range(picked, lo, hi):
    """Coerce whatever st.date_input returns into exactly (date_from, date_to).

    Extracted so it can be tested without a browser. In range mode
    st.date_input returns a 1-TUPLE between the first and second click, and
    unpacking that straight into two names raises

        ValueError: not enough values to unpack (expected 2, got 1)

    which replaced the entire dashboard with a traceback on the first click of
    the only filter in the app. Found by /qa on 2026-08-09 (ISSUE-003).

        two dates  -> (a, b)
        one date   -> (a, a)     mid-selection: show that single day
        cleared    -> (lo, hi)   fall back to the full range
        bare date  -> (d, d)
    """
    if isinstance(picked, (list, tuple)):
        if len(picked) >= 2:
            return picked[0], picked[1]
        if len(picked) == 1:
            return picked[0], picked[0]
        return lo, hi
    if picked is None:
        return lo, hi
    return picked, picked


def read_sql(name: str) -> str:
    return (SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")


def date_bounds(con: duckdb.DuckDBPyConnection) -> tuple[date, date]:
    """Bounds come from the DATA, never from today().

    The upstream feed stopped at 2026-06-11 and the shipped slice ends earlier
    still. A picker defaulting to "last 30 days" would return zero rows and read
    as a broken app.

    `crash_date` is a DuckDB TIMESTAMP column, so `.fetchone()` returns
    `datetime.datetime`, not `datetime.date`, despite this function's return
    type. Coerce with `.date()` here rather than downstream: found live via
    /qa when `app.live.check_feed` raised `TypeError: can't compare
    datetime.datetime to datetime.date` comparing this value's datetime
    against a plain `date` parsed from the Socrata feed — a crash on the
    freshness popover's one button, every time, for every user.
    """
    lo, hi = con.execute(
        "SELECT min(crash_date), max(crash_date) FROM crashes_raw"
    ).fetchone()
    return lo.date(), hi.date()


def freshness_line(coverage_to: date) -> str:
    """The line §0.1 requires on every screen.

    Both halves are facts that cannot rot: coverage is read from the data, and
    the feed date is a fixed point in the past. Deliberately NOT "lag ~N days" —
    that grows by one per day and is wrong the moment a demo slips.
    """
    return (f"Complete through {coverage_to:%Y-%m-%d} · "
            f"NYPD feed last carried {UPSTREAM_THROUGH}, pulled {PULLED_ON}")


def build_view(con: duckdb.DuckDBPyConnection, date_from: date, date_to: date,
               casualty_only: bool = False) -> None:
    """(Re)create `crashes_filtered` for the user's filters.

    Every filter goes through a one-row `filter_params` table rather than into
    the view's SQL text. DuckDB refuses to prepare a CREATE VIEW statement, and
    string-formatting user input into SQL is the injection seam we are avoiding.
    INSERT *can* be prepared, so the values stay bound — including the boolean,
    which looks harmless enough to interpolate and is not worth the exception.

    `casualty_only` defaults to False, matching spec §1.3: every crash counts
    unless the user asks otherwise.

    DROP the view before recreating it. CREATE OR REPLACE VIEW alone is not
    enough here: the table is recreated below it, and a view holding a stale
    column list over a redefined params table is the kind of failure that only
    shows up after a schema change.
    """
    con.execute("DROP TABLE IF EXISTS filter_params CASCADE")
    con.execute(
        "CREATE TABLE filter_params "
        "(date_from DATE, date_to DATE, casualty_only BOOLEAN)"
    )
    con.execute("INSERT INTO filter_params VALUES (?, ?, ?)",
                [date_from, date_to, bool(casualty_only)])
    con.execute(read_sql("base_view"))


def set_selection(con: duckdb.DuckDBPyConnection, corridor: str | None) -> None:
    """(Re)point `selection_params` at the corridor the drawer is showing.

    Same reasoning as `build_view`: DuckDB cannot prepare a CREATE VIEW, so the
    value goes in via a parameterised INSERT into a one-row table rather than
    being interpolated into SQL text. `corridor=None` clears the drawer to a
    value no canonical name can ever equal, so `selection_rows` returns zero
    rows instead of raising.
    """
    con.execute("CREATE TABLE IF NOT EXISTS selection_params (corridor VARCHAR)")
    con.execute("DELETE FROM selection_params")
    con.execute("INSERT INTO selection_params VALUES (?)", [corridor or "\x00none\x00"])


# CACHE KEY GRAPH. Which function is keyed on what, and why one of them is
# keyed differently on purpose.
#
#   build_view(dates, casualty_only)
#        │  rewrites crashes_filtered in place — NOT cached, it is a write
#        ▼
#   crashes_filtered ──► query(_con, name, cache_key)
#                            key: query_cache_key(source, from, to,
#                                                 casualty_only, canonical)
#                            every value that changes the result, and nothing
#                            that does not. max_entries bounds it.
#
#   eb_cells ─────────► map_cells(_con, cache_key)
#                            key: map_cache_key(source)
#                            NOT the query key. eb_cells is the fit's own
#                            output over its own multi-year window; it does
#                            not move with the date picker.
#
# The bug this graph replaces: the map was fetched through `query` with a
# hardcoded ("cell_map",) — a CONSTANT. Every map state resolved to the same
# entry, so any new state would have served a stale frame forever, and no unit
# test can catch a stale frame. See presentation.map_cache_key.

# ~1 GB on Community Cloud, and the drawer key includes the canonical: 8,931
# corridors × filter combinations is unbounded growth in a container that
# cannot afford it. 64 is roughly a working session's worth of back-and-forth
# and is cheap to raise. Unset (the previous state) means no ceiling at all.
MAX_QUERY_CACHE_ENTRIES = 64

# One per source label in practice. The map frame is the largest object the
# app caches (77,747 rows with a colour list per row), so this stays small.
MAX_MAP_CACHE_ENTRIES = 4


@st.cache_data(show_spinner=False, max_entries=MAX_QUERY_CACHE_ENTRIES)
def query(_con: duckdb.DuckDBPyConnection, name: str, cache_key: tuple):
    """Run a named query against the shared view.

    `_con` is underscore-prefixed so Streamlit does not try to hash the
    connection. `cache_key` carries the values that actually change the result
    (source + date range + filters), so the cache invalidates when they do.
    Build it with `presentation.query_cache_key`, never by hand.
    """
    return _con.execute(read_sql(name)).df()


@st.cache_data(show_spinner=False, max_entries=MAX_MAP_CACHE_ENTRIES)
def map_cells(_con: duckdb.DuckDBPyConnection, cache_key: tuple):
    """The map's cells, coloured, computed once per key.

    The colouring used to happen in the page script: `_color()` was a pure
    Python function mapped over 77,747 rows on EVERY rerun, outside any cache.
    Streamlit reruns the whole script on any widget change, so dragging a cost
    slider in the estimator re-ran the severity ramp over every cell in the
    city before rendering a number that had nothing to do with the map.

    Key with `presentation.map_cache_key`. Anything that changes what the map
    DRAWS belongs in that tuple, in the same commit that adds it.
    """
    from app import presentation

    return presentation.with_severity_colors(_con.execute(read_sql("cell_map")).df())
