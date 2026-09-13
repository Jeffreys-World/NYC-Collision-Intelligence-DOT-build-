"""The casualty toggle, and the disagreement it used to cause.

The toggle was a pandas filter applied to the DRAWER's rows after the query,
in app/streamlit_app.py. The ranked table beside it queried the unfiltered
view. So with the toggle on, the drawer counted casualty crashes and the table
counted all of them, for the same corridor, on the same screen.

That pairing is the worst one available: DESIGN.md §5 makes the ranked table
the map's accessible equivalent, so the two surfaces that are required to
carry the same figures were the two that did not.

The fix is structural, not a second filter kept in step with the first: the
predicate moved into sql/base_view.sql, which every query reads from. These
tests pin that the agreement is by construction.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.data import build_view, get_connection, query, resolve_source

DATE_FROM = date(2019, 1, 1)
DATE_TO = date(2026, 6, 11)


@pytest.fixture(scope="module")
def con():
    source = resolve_source()
    if source.kind == "none":
        pytest.skip("no committed Parquet in this environment")
    return get_connection.__wrapped__(source.reader)


def _table(con, casualty_only: bool):
    build_view(con, DATE_FROM, DATE_TO, casualty_only)
    return query.__wrapped__(con, "corridor_table", ("t", casualty_only))


def _drawer_rows(con, canonical: str, casualty_only: bool):
    build_view(con, DATE_FROM, DATE_TO, casualty_only)
    con.execute("CREATE TABLE IF NOT EXISTS selection_params (corridor VARCHAR)")
    con.execute("DELETE FROM selection_params")
    con.execute("INSERT INTO selection_params VALUES (?)", [canonical])
    return query.__wrapped__(con, "selection_rows", ("t", canonical, casualty_only))


# --- the toggle does something ----------------------------------------------

def test_the_toggle_actually_filters():
    """Guards the inverse failure: a bound boolean that never reaches the
    predicate leaves the toggle inert, and an inert control is worse than an
    absent one because the user believes it."""
    source = resolve_source()
    if source.kind == "none":
        pytest.skip("no committed Parquet in this environment")
    con = get_connection.__wrapped__(source.reader)

    build_view(con, DATE_FROM, DATE_TO, False)
    all_rows = con.execute("SELECT count(*) FROM crashes_filtered").fetchone()[0]
    build_view(con, DATE_FROM, DATE_TO, True)
    casualty_rows = con.execute("SELECT count(*) FROM crashes_filtered").fetchone()[0]

    assert 0 < casualty_rows < all_rows


def test_the_filtered_view_contains_only_casualty_crashes(con):
    build_view(con, DATE_FROM, DATE_TO, True)
    non_casualty = con.execute(
        "SELECT count(*) FROM crashes_filtered "
        "WHERE number_of_persons_killed = 0 AND number_of_persons_injured = 0"
    ).fetchone()[0]
    assert non_casualty == 0


def test_the_unfiltered_view_is_the_default(con):
    """Spec §1.3: off by default, every crash counts. A default that quietly
    filters is a figure everyone downstream gets wrong."""
    build_view(con, DATE_FROM, DATE_TO)
    with_default = con.execute("SELECT count(*) FROM crashes_filtered").fetchone()[0]
    build_view(con, DATE_FROM, DATE_TO, False)
    explicit_off = con.execute("SELECT count(*) FROM crashes_filtered").fetchone()[0]
    assert with_default == explicit_off


# --- REGRESSION: the table and the drawer agree -----------------------------

@pytest.mark.parametrize("casualty_only", [False, True])
@pytest.mark.parametrize("canonical", ["BELT PKWY", "ATLANTIC AVE", "BROADWAY"])
def test_table_and_drawer_totals_agree(con, canonical, casualty_only):
    """The named regression from the 2026-09-12 engineering review.

    Both surfaces must report the same crash count, the same injured and the
    same killed for the same corridor under the same filters. Before the
    predicate moved into the shared view, the drawer's count was the casualty
    subset and the table's was everything, and only the drawer moved when the
    toggle flipped.
    """
    table = _table(con, casualty_only)
    table_row = table[table["corridor"] == canonical]
    assert len(table_row) == 1, f"{canonical} missing from the ranked table"
    table_row = table_row.iloc[0]

    rows = _drawer_rows(con, canonical, casualty_only)

    assert len(rows) == int(table_row["crashes"])
    assert int(rows["number_of_persons_injured"].sum()) == int(table_row["injured"])
    assert int(rows["number_of_persons_killed"].sum()) == int(table_row["killed"])
    assert int((rows["is_fatal"] | rows["is_injury"]).sum()) == int(
        table_row["casualty_crashes"])


def test_the_toggle_moves_both_surfaces_together(con):
    """Not just that they agree, but that they agree AFTER changing. Two
    surfaces can agree while both are stale."""
    canonical = "BELT PKWY"

    off_table = _table(con, False)
    off_row = off_table[off_table["corridor"] == canonical].iloc[0]
    off_rows = len(_drawer_rows(con, canonical, False))

    on_table = _table(con, True)
    on_row = on_table[on_table["corridor"] == canonical].iloc[0]
    on_rows = len(_drawer_rows(con, canonical, True))

    assert int(on_row["crashes"]) < int(off_row["crashes"])
    assert on_rows < off_rows
    assert on_rows == int(on_row["crashes"])


def test_casualty_crashes_equal_total_crashes_when_the_toggle_is_on(con):
    """With the filter applied at the view, every remaining crash IS a
    casualty crash. If these two columns ever differ under the toggle, the
    predicate and the is_fatal/is_injury definitions have drifted apart —
    they are spelled out separately in base_view.sql and must stay identical.
    """
    table = _table(con, True)
    mismatched = table[table["crashes"] != table["casualty_crashes"]]
    assert mismatched.empty, (
        f"{len(mismatched)} corridors where the casualty predicate and the "
        f"is_fatal/is_injury flags disagree"
    )


# --- the completeness figure survives the toggle ----------------------------

def test_the_completeness_count_is_filtered_too_not_left_whole(con):
    """other_tools_drop must count within the filtered set. A completeness
    figure computed over everything, shown beside a filtered crash count,
    would read as a share greater than it is — and completeness is this
    project's whole argument."""
    on = _table(con, True)
    off = _table(con, False)
    on_row = on[on["corridor"] == "BELT PKWY"].iloc[0]
    off_row = off[off["corridor"] == "BELT PKWY"].iloc[0]

    assert int(on_row["other_tools_drop"]) <= int(on_row["crashes"])
    assert int(on_row["other_tools_drop"]) < int(off_row["other_tools_drop"])


# --- the filter never reaches SQL text --------------------------------------

def test_the_casualty_flag_is_bound_never_formatted():
    """DuckDB cannot prepare a CREATE VIEW, which is why filter_params exists.
    A boolean looks harmless enough to interpolate; this pins that nobody
    started doing it, because the exception is what erodes the rule."""
    from pathlib import Path

    sql = (Path(__file__).resolve().parent.parent / "sql" / "base_view.sql").read_text(
        encoding="utf-8")
    assert "p.casualty_only" in sql
    assert "{" not in sql and "%s" not in sql, "SQL text is being formatted"

    import inspect

    from app import data
    src = inspect.getsource(data.build_view)
    assert "INSERT INTO filter_params VALUES (?, ?, ?)" in src
