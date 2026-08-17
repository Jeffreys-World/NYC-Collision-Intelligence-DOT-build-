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
    """
    lo, hi = con.execute(
        "SELECT min(crash_date), max(crash_date) FROM crashes_raw"
    ).fetchone()
    return lo, hi


def freshness_line(coverage_to: date) -> str:
    """The line §0.1 requires on every screen.

    Both halves are facts that cannot rot: coverage is read from the data, and
    the feed date is a fixed point in the past. Deliberately NOT "lag ~N days" —
    that grows by one per day and is wrong the moment a demo slips.
    """
    return (f"Complete through {coverage_to:%Y-%m-%d} · "
            f"NYPD feed last carried {UPSTREAM_THROUGH}, pulled {PULLED_ON}")


def build_view(con: duckdb.DuckDBPyConnection, date_from: date, date_to: date) -> None:
    """(Re)create `crashes_filtered` for the user's date range.

    The dates go through a one-row `filter_params` table rather than into the
    view's SQL text. DuckDB refuses to prepare a CREATE VIEW statement, and
    string-formatting user input into SQL is the injection seam we are avoiding.
    INSERT *can* be prepared, so the values stay bound.
    """
    con.execute("CREATE TABLE IF NOT EXISTS filter_params (date_from DATE, date_to DATE)")
    con.execute("DELETE FROM filter_params")
    con.execute("INSERT INTO filter_params VALUES (?, ?)", [date_from, date_to])
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


@st.cache_data(show_spinner=False)
def query(_con: duckdb.DuckDBPyConnection, name: str, cache_key: tuple):
    """Run a named query against the shared view.

    `_con` is underscore-prefixed so Streamlit does not try to hash the
    connection. `cache_key` carries the values that actually change the result
    (source + date range + filters), so the cache invalidates when they do.

    The map layer is cached the same way, on (corridor, filters, zoom) — see
    DESIGN.md §3. Streamlit reruns the whole script on every widget change, so
    without that key, dragging a cost slider re-serialises the entire map.
    """
    return _con.execute(read_sql(name)).df()
