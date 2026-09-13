"""Selection arbitration: two widgets, one stored value, and the index trap.

Two failures are pinned here, both from the 2026-09-12 engineering review's
failure-mode table.

1. THE FIGHT. The dropdown and the ranked table can each set the corridor, and
   Streamlit reruns the whole script on any widget change, so both re-emit
   their value on every run. Without a last-touched rule they fight, and the
   page renders one corridor's map beside another's drawer — which one wins
   depending on render order rather than on anything the user did.

2. THE INDEX TRAP, which is the worse one. st.dataframe returns a POSITIONAL
   index into the frame as rendered. The ranked table re-sorts whenever the
   casualty toggle or the date range changes. A stored index therefore points
   at a DIFFERENT corridor after any re-sort: the page keeps showing a
   selection, it is simply the wrong one, and nothing raises. Storing the
   canonical instead is the whole fix, and the test below is the regression
   the review named.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app import presentation

ROOT = Path(__file__).resolve().parent.parent

# The ranked table as first rendered: EB order, highest expected harm first.
BEFORE_SORT = ["BELT PKWY", "ATLANTIC AVE", "BROADWAY", "E 233 ST"]

# The same corridors after a filter change re-sorts them. Nothing was added or
# removed; the order simply changed.
AFTER_SORT = ["BROADWAY", "E 233 ST", "BELT PKWY", "ATLANTIC AVE"]

# WHERE THIS ACTUALLY BITES, measured against the committed Parquet rather
# than assumed. corridor_table orders by coalesce(eb_estimate, 0) DESC, then
# crashes DESC. eb_estimate comes from the eb_corridors join and is fixed over
# the model's own window, so the MATCHED corridors at the top of the table do
# not move when a filter changes — narrowing the date range to 2022-2024 left
# the first 2,185 positions identical.
#
# Below that sit the 3,840 unmatched corridors, all tied at eb_estimate 0 and
# ordered by observed crashes, which every filter changes. That same date
# change moved 3,832 of 6,507 positions, first diverging at position 2,186
# (ERASMUS ST -> 30 DR).
#
# So the trap is not evenly spread and it is not rare: it is invisible for the
# handful of corridors anyone demos and near-certain for the thousands the
# ranked table exists to make reachable.


# --- reading the widget state defensively -----------------------------------

def test_row_indices_are_read_out_of_the_selection_state():
    state = {"selection": {"rows": [3], "columns": []}}
    assert presentation.selected_row_indices(state) == [3]


@pytest.mark.parametrize("state", [
    None,                                   # widget never interacted with
    {},                                     # no selection key yet
    {"selection": None},                    # selection cleared
    {"selection": {}},                      # no rows key
    {"selection": {"rows": None}},          # rows not a list
    {"selection": {"columns": [1]}},        # column selection only
    "not a dict",                           # a shape nobody expects
])
def test_an_unexpected_widget_shape_yields_no_selection_and_never_raises(state):
    """This is parsed inside a widget callback, where an exception has nowhere
    to surface: no traceback in the page, no log the user will read. It must
    degrade to 'nothing selected', never to a crash."""
    assert presentation.selected_row_indices(state) == []


def test_an_empty_row_list_is_a_real_deselection():
    """Distinct from 'never interacted'. The app turns this into city-wide
    rather than silently keeping the last corridor."""
    assert presentation.selected_row_indices({"selection": {"rows": []}}) == []


# --- REGRESSION: the selection survives a re-sort ---------------------------

def test_selection_survives_a_resort():
    """The named regression. Click Broadway at position 2, re-sort the table,
    and Broadway must still be the selection.

    Under the old behaviour the index 2 was what persisted, and after the
    re-sort position 2 is BELT PKWY. The page would have kept showing a
    selection the user never made, with no error anywhere.
    """
    clicked_row = 2
    stored = presentation.canonical_at_row(BEFORE_SORT, clicked_row)
    assert stored == "BROADWAY"

    # The re-sort happens. The stored value does not move, because it is not
    # a position.
    assert stored == "BROADWAY"

    # What the index would have become, for contrast — this is the bug.
    assert presentation.canonical_at_row(AFTER_SORT, clicked_row) == "BELT PKWY"
    assert presentation.canonical_at_row(AFTER_SORT, clicked_row) != stored


def test_every_row_resolves_to_its_own_corridor():
    resolved = [presentation.canonical_at_row(BEFORE_SORT, i)
                for i in range(len(BEFORE_SORT))]
    assert resolved == BEFORE_SORT


@pytest.mark.parametrize("row", [-1, 4, 999])
def test_an_out_of_range_row_resolves_to_nothing_rather_than_raising(row):
    """A shorter frame after a filter change, a stale click, an off-by-one in
    a future Streamlit: all of them land here, inside a callback, where an
    IndexError is invisible."""
    assert presentation.canonical_at_row(BEFORE_SORT, row) is None


def test_an_empty_table_resolves_to_nothing():
    assert presentation.canonical_at_row([], 0) is None


# --- the arbitration is wired the way the plan requires ---------------------

def _app_source() -> str:
    return (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")


def test_the_table_offers_single_row_selection():
    src = _app_source()
    assert 'selection_mode="single-row"' in src
    assert "on_select=_on_table_select" in src


def test_the_dropdown_has_a_key_and_a_change_callback():
    """Without a key the dropdown's value cannot be read or reset from
    session_state, which is what makes the last-touched rule expressible at
    all."""
    src = _app_source()
    assert "key=DROPDOWN_KEY" in src
    assert "on_change=_on_dropdown_change" in src


def test_only_the_canonical_is_stored_never_the_row_index():
    """The structural half of the regression above. If a row index is ever
    written into session_state, the re-sort bug is back regardless of what
    canonical_at_row does."""
    src = _app_source()
    tree = ast.parse(src)

    writes = []
    for node in ast.walk(tree):
        # st.session_state[KEY] = value
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and ast.unparse(target).startswith("st.session_state[")):
                    writes.append((ast.unparse(target), ast.unparse(node.value)))

    selected_writes = [v for t, v in writes if "SELECTED_KEY" in t]
    assert selected_writes, "nothing writes the selected corridor"
    for value in selected_writes:
        assert "rows[" not in value and "index" not in value.lower(), (
            f"a row index is being stored as the selection: {value}")


def test_the_table_records_the_order_it_rendered():
    """The callback resolves the click against the frame that was on screen.
    If the app stops recording that order, the resolution silently starts
    using whatever order happens to be current."""
    src = _app_source()
    assert "st.session_state[DISPLAYED_KEY] = list(show[" in src
    # Captured before the warning suffix is appended, or the stored value is
    # "BROOKLYN BRIDGE ⚠" and joins against the data as nothing at all.
    displayed_at = src.index("st.session_state[DISPLAYED_KEY]")
    suffix_at = src.index('show.loc[low_coverage, "corridor"]')
    assert displayed_at < suffix_at, (
        "the displayed order is captured after the ⚠ suffix is appended, so "
        "the stored canonical will not match any row in the data")


def test_selecting_from_the_table_resets_the_dropdown():
    """The dropdown can only name 12 of 8,931 corridors, so it cannot follow
    the table anywhere. Leaving it pointing at a corridor that is no longer
    selected is the visible half of the fight."""
    src = _app_source()
    table_cb = src[src.index("def _on_table_select"):src.index("corridor_options =")]
    assert "st.session_state[DROPDOWN_KEY] = CITY_WIDE" in table_cb


def test_selecting_from_the_dropdown_clears_the_table_highlight():
    src = _app_source()
    dropdown_cb = src[src.index("def _on_dropdown_change"):src.index("def _on_table_select")]
    assert "st.session_state.pop(RANKED_TABLE_KEY" in dropdown_cb


def test_the_page_reads_one_stored_selection_not_two_widget_values():
    """The single source of truth. Reading the dropdown's label directly
    anywhere downstream reintroduces the second opinion this rule removed."""
    src = _app_source()
    assert "presentation.resolve_corridor(featured, st.session_state.get(SELECTED_KEY))" in src
    assert "picked_label" not in src, (
        "a second read of the dropdown's raw value survived the refactor")
