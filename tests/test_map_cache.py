"""The map's cache key, and the constant it replaces.

CRITICAL GAP from the 2026-09-12 engineering review. The map was fetched with

    query(con, "cell_map", ("cell_map",))

a hardcoded tuple — a CONSTANT. Every possible map state resolved to the same
cache entry, so the moment the map gained any new state (a second layer, a
reveal toggle, a colour-by switch) it would have served a stale frame forever.

The review recorded that no unit test can detect a stale frame: by the time
the frame is wrong, the cache has already decided. What a test CAN do is catch
the thing that causes it, which is a key that does not vary with the state it
is supposed to track. That is what this file does, plus the cheap structural
check that the constant has not come back.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path

import pytest

from app import data, presentation

ROOT = Path(__file__).resolve().parent.parent


# --- the key is not a constant ----------------------------------------------

def test_the_map_key_varies_with_the_source():
    """Dropping a re-baked Parquet in must invalidate the map along with
    everything else. Under the old constant it did not."""
    assert (presentation.map_cache_key("committed 2019-2025 pull")
            != presentation.map_cache_key("no data file present"))


def test_the_map_key_is_stable_for_the_same_source():
    """The other half. A key that varies when nothing changed evicts a
    77,747-row frame on every rerun, which is the opposite failure."""
    assert (presentation.map_cache_key("committed 2019-2025 pull")
            == presentation.map_cache_key("committed 2019-2025 pull"))


def test_the_map_key_and_the_query_key_never_collide():
    """They index the same st.cache_data namespace keyed by function, but the
    two shapes must stay visibly different so a mix-up at a call site reads as
    a mix-up rather than a cache hit."""
    query_key = presentation.query_cache_key(
        "parquet", date(2019, 1, 1), date(2025, 12, 31), False, None)
    assert presentation.map_cache_key("parquet") != query_key


def test_no_call_site_passes_a_literal_tuple_as_a_map_key():
    """The structural guard on the regression. A hand-built key at a call site
    is how the constant got there the first time.
    """
    src = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in ("query", "map_cells"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Tuple) and all(
                    isinstance(e, ast.Constant) for e in arg.elts):
                offenders.append(f"line {node.lineno}: {ast.unparse(arg)}")
    assert not offenders, (
        "cache keys must be built by presentation.query_cache_key / "
        "map_cache_key, never written inline: " + "; ".join(offenders))


def test_the_map_is_not_fetched_through_the_generic_query_helper():
    """cell_map has its own loader because its key is different in KIND, not
    just in value. Routing it back through `query` is how it would silently
    pick up the query key again."""
    src = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'query(con, "cell_map"' not in src
    assert "map_cells(con," in src


# --- the colouring happens once, inside the cache ---------------------------

def test_the_colour_ramp_runs_inside_the_cached_loader():
    """`_color()` used to be a pure Python function mapped over 77,747 rows on
    every rerun, outside any cache. Streamlit reruns the whole script on any
    widget change, so dragging a cost slider re-ran the severity ramp over
    every cell in the city before rendering a number about something else."""
    src = inspect.getsource(data.map_cells)
    assert "with_severity_colors" in src

    page = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert "with_severity_colors" not in page, (
        "the ramp is back in the page script, outside the cache")


def test_the_cached_map_carries_the_colour_column():
    source = data.resolve_source()
    if source.kind == "none":
        pytest.skip("no committed Parquet in this environment")
    con = data.get_connection.__wrapped__(source.reader)
    cells = data.map_cells.__wrapped__(
        con, presentation.map_cache_key(source.label))

    assert not cells.empty
    assert "color" in cells.columns
    assert "norm" in cells.columns
    assert all(len(c) == 4 for c in cells["color"].head(50))


# --- the caches are bounded (decision 2) ------------------------------------

def test_both_caches_set_an_explicit_entry_ceiling():
    """Unbounded st.cache_data over 8,931 corridors × filter combinations
    grows without limit in a ~1 GB Community Cloud container, and the failure
    only shows up in production. Neither decorator set max_entries or ttl
    before this."""
    # st.cache_data hands back a CachedFunc; the decorator arguments live on
    # its _info. Read through the source too, so this test still means
    # something if Streamlit renames that private attribute.
    assert data.query._info.max_entries == data.MAX_QUERY_CACHE_ENTRIES
    assert data.map_cells._info.max_entries == data.MAX_MAP_CACHE_ENTRIES
    assert data.MAX_QUERY_CACHE_ENTRIES > 0
    assert data.MAX_MAP_CACHE_ENTRIES > 0

    src = (ROOT / "app" / "data.py").read_text(encoding="utf-8")
    decorators = [line for line in src.splitlines()
                  if line.strip().startswith("@st.cache_data")]
    assert decorators, "no cached loaders found — did they move?"
    assert all("max_entries=" in line for line in decorators), (
        "an unbounded st.cache_data grows without limit in a ~1 GB container "
        "and the failure only shows up in production: " + str(decorators))
