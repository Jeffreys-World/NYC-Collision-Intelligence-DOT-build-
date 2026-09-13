"""The structural guarantees app/feed.py's docstring claims for itself.

The docstring at app/feed.py:53 has named this file since the module was
written; it did not exist until the 2026-09-12 engineering review wired the
module in (decision 9). A promised test that is absent is worse than no
promise: it reads as coverage nobody has.

Every test here is STRUCTURAL, not behavioural. The point is that the feed
check cannot quietly become a data source, no matter what a later edit intends.
If it cannot reach DuckDB or the Source seam, it cannot feed a number into a
chart. If it never reads a clock, it cannot produce a freshness figure that
decays. Conventions rot; an import graph does not.
"""

from __future__ import annotations

import ast
import inspect
import io
import tokenize
from pathlib import Path

from app import feed

ROOT = Path(__file__).resolve().parent.parent
SOURCE = inspect.getsource(feed)


def module_code() -> str:
    """The module's executable CODE, with every comment and string removed.

    Grepping raw source punishes the file for explaining itself: app/feed.py
    documents at length that it must not import duckdb and must not read a
    clock, so those words appear in it precisely BECAUSE the rules are being
    honoured. Its user-facing copy is checked separately, in
    tests/test_feed_copy.py.
    """
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(SOURCE).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


def imported_modules() -> set[str]:
    """Every module app/feed.py imports, read from its syntax tree.

    Read from the AST rather than by substring: a probe for "import data"
    matches inside `from dataclasses import dataclass`, which is the kind of
    false positive that gets a real test deleted for being annoying.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(SOURCE)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


# --- it reports ON the feed; it never becomes a data source -----------------

def test_feed_never_reaches_duckdb_or_the_source_seam():
    assert "duckdb" not in imported_modules()
    assert not any(m == "app.data" or m.startswith("app.data.")
                   for m in imported_modules())
    assert "resolve_source" not in module_code()
    assert "crashes_filtered" not in module_code()


def test_no_app_module_imports_feed_except_the_page():
    """The containment claim, checked from the other direction.

    app/feed.py not importing the data layer is half the guarantee. The other
    half is that the data layer does not import IT — otherwise a feed figure
    could travel into a query by the back door. Only the page may import it.
    """
    offenders = []
    for path in sorted((ROOT / "app").glob("*.py")):
        if path.name in ("feed.py", "streamlit_app.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            imported = set()
            if isinstance(node, ast.Import):
                imported = {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported = {node.module or ""} | {a.name for a in node.names}
            if any(n == "feed" or n == "app.feed" or n.startswith("app.feed.")
                   for n in imported):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, ("only the page may import app/feed.py: "
                           + ", ".join(offenders))


# --- it never reads a clock -------------------------------------------------

def test_feed_never_derives_a_figure_from_the_local_clock():
    """The timestamp shown is the server's own Date response header, verbatim.

    time.monotonic() IS allowed and is used: a round-trip duration is a
    measured event, not a date, and it does not decay between now and a demo.
    What is forbidden is anything that could become an elapsed-days figure.
    """
    code = module_code()
    for smell in (".days", "timedelta", "date.today", "datetime.now",
                  "datetime.today", "time.time"):
        assert smell not in code, (
            f"{smell!r} in app/feed.py — §0.1 forbids a freshness figure "
            f"computed from the local clock"
        )


def test_the_only_clock_call_is_monotonic():
    calls = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(ast.parse(SOURCE))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "time"
    }
    assert calls <= {"time.monotonic"}, f"unexpected clock calls: {calls}"


# --- it costs no runtime dependency -----------------------------------------

def test_feed_adds_no_runtime_dependency():
    """requirements.txt is what Community Cloud installs into a ~1 GB
    container. urllib is standard library, so this feature costs zero wheels.

    `requests` is deliberately NOT used even though streamlit already pulls it
    in: this repo is developed behind a TLS interceptor, where requests' own
    certifi bundle fails CERTIFICATE_VERIFY_FAILED and stdlib ssl (which reads
    the OS trust store) succeeds. See the module docstring's TRANSPORT note.
    """
    assert "requests" not in imported_modules()
    assert "urllib.request" in imported_modules()

    runtime = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for line in runtime.splitlines():
        name = line.strip()
        if not name or name.startswith("#"):
            continue
        assert not name.lower().startswith(("requests", "httpx", "aiohttp")), (
            f"the feed check must add no HTTP dependency: {name!r}")


def test_no_api_token_is_read_from_anywhere():
    """Anonymous access returns 200; a token raises rate limits, it does not
    gate access. Reading Streamlit's secrets store raises when no secrets.toml
    exists, which would be a startup crash on a laptop."""
    code = module_code()
    assert "st.secrets" not in code
    assert "app_token" not in code.lower()
    assert "X-App-Token" not in SOURCE


# --- the network is reachable only from a button ----------------------------

def test_the_transport_is_injectable():
    """Without this the tests could not run offline and CI would flake."""
    signature = inspect.signature(feed.check_feed)
    assert "fetch" in signature.parameters
    assert signature.parameters["fetch"].default is feed._fetch
    assert signature.parameters["deadline_s"].default == feed.WALL_DEADLINE


def test_check_feed_is_called_from_exactly_one_place_in_the_module():
    """The single reachable path to a socket is _run(), which sits inside
    `if st.button(...)`. Streamlit reruns the whole script on every widget
    change, so a second, ungated call site would hit the network on a
    cost-slider drag."""
    call_sites = [
        node.lineno for node in ast.walk(ast.parse(SOURCE))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "check_feed"
    ]
    assert len(call_sites) == 1, f"check_feed called at lines {call_sites}"


def test_the_module_uses_no_cache_decorator():
    """session_state only, a documented deviation from §1.4. A cache entry is
    evictable under memory pressure, and an eviction RE-EXECUTES the producer —
    firing the network on an unrelated widget change, which is the precise
    ambient call the button gate exists to forbid."""
    code = module_code()
    assert "cache_data" not in code
    assert "cache_resource" not in code
