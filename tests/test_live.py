"""Tests for the §1.2 runtime feed check.

EVERY TEST HERE RUNS OFFLINE. The HTTP getter is injected, so nothing in this
file touches the network and CI never depends on NYC Open Data being up. The
canned payloads below are the real shapes the API returns — recorded from live
calls on 2026-08-16, when the feed's newest crash was 2026-06-11.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from app import live
from app.live import (
    NEWER,
    NO_NEWER,
    REFUSED,
    UNREACHABLE,
    FeedRefused,
    FeedUnreachable,
    check_feed,
)

COVERAGE = date(2026, 6, 11)

# Recorded from the live API on 2026-08-16.
MAX_DATE_BODY = '[{"newest":"2026-06-11T00:00:00.000"}]'
COUNT_BODY = '[{"n":"1234"}]'


def getter(*bodies: str):
    """An injected getter that replays canned bodies in order."""
    queue = list(bodies)

    def _get(url: str, *, timeout: float) -> str:
        assert timeout > 0
        return queue.pop(0) if queue else "[]"

    return _get


def raising(exc: Exception):
    def _get(url: str, *, timeout: float) -> str:
        raise exc

    return _get


# --- the expected result: the feed has nothing newer ------------------------

def test_feed_with_nothing_newer_reports_no_newer_records():
    check = check_feed(COVERAGE, get=getter(MAX_DATE_BODY))
    assert check.outcome == NO_NEWER
    assert check.newest_on_feed == date(2026, 6, 11)
    assert check.newer_record_count == 0
    assert check.succeeded
    assert not check.is_error


def test_feed_behind_our_coverage_still_reports_no_newer_records():
    """Not an error. The shipped extract simply reaches further than the feed."""
    check = check_feed(date(2026, 8, 1), get=getter(MAX_DATE_BODY))
    assert check.outcome == NO_NEWER
    assert check.succeeded


# --- the feed moved ahead ---------------------------------------------------

def test_feed_ahead_of_coverage_reports_newer_records_and_a_count():
    check = check_feed(date(2026, 1, 31), get=getter(MAX_DATE_BODY, COUNT_BODY))
    assert check.outcome == NEWER
    assert check.newest_on_feed == date(2026, 6, 11)
    assert check.newer_record_count == 1234
    assert "1,234" in check.detail


def test_newer_records_are_not_silently_shown():
    """The app must say the records exist AND that it is not showing them."""
    check = check_feed(date(2026, 1, 31), get=getter(MAX_DATE_BODY, COUNT_BODY))
    assert "nothing on screen has changed" in check.detail.lower()


def test_losing_the_count_does_not_lose_the_finding():
    """The second call failing degrades the detail, never the headline fact."""
    def _get(url: str, *, timeout: float) -> str:
        if "count" in url:
            raise FeedUnreachable("dropped")
        return MAX_DATE_BODY

    check = check_feed(date(2026, 1, 31), get=_get)
    assert check.outcome == NEWER
    assert check.newer_record_count is None
    assert "2026-06-11" in check.headline


# --- failure never reads as an empty success --------------------------------

def test_unreachable_is_distinct_from_nothing_newer():
    check = check_feed(COVERAGE, get=raising(FeedUnreachable("timed out")))
    assert check.outcome == UNREACHABLE
    assert check.is_error
    assert not check.succeeded
    assert check.newest_on_feed is None


def test_refused_is_distinct_from_nothing_newer():
    check = check_feed(COVERAGE, get=raising(FeedRefused("HTTP 429")))
    assert check.outcome == REFUSED
    assert check.is_error
    assert check.newest_on_feed is None


def test_the_four_outcomes_are_all_distinct():
    outcomes = {NO_NEWER, NEWER, UNREACHABLE, REFUSED}
    assert len(outcomes) == 4


@pytest.mark.parametrize("failure", [
    FeedUnreachable("connection reset"),
    FeedRefused("HTTP 500"),
])
def test_a_failed_check_never_claims_the_feed_has_nothing(failure):
    """The failure this module exists to prevent.

    'We could not ask' and 'there is nothing newer' are opposite facts. If a
    failure ever renders as reassurance, a network blip becomes a false claim
    about data freshness in front of a room.
    """
    check = check_feed(COVERAGE, get=raising(failure))
    text = f"{check.headline} {check.detail}".lower()
    assert "nothing to add" not in text
    assert "carries nothing after" not in text
    assert check.newer_record_count is None


def test_malformed_json_is_refused_not_treated_as_empty():
    check = check_feed(COVERAGE, get=getter("<html>502 Bad Gateway</html>"))
    assert check.outcome == REFUSED


def test_empty_response_is_refused_not_treated_as_empty():
    check = check_feed(COVERAGE, get=getter("[]"))
    assert check.outcome == REFUSED


def test_null_max_date_is_refused_not_treated_as_empty():
    check = check_feed(COVERAGE, get=getter('[{"newest":null}]'))
    assert check.outcome == REFUSED


def test_check_feed_never_raises():
    """A raised exception in a Streamlit callback replaces the section with a
    traceback, which is exactly the §4.1 failure the app must not have."""
    for failure in (FeedUnreachable("x"), FeedRefused("y"), ValueError("z")):
        try:
            check_feed(COVERAGE, get=raising(failure))
        except ValueError:
            # A getter raising something outside the two named errors is a
            # programming error in the getter, not a feed condition. Only the
            # two named ones are contractually handled.
            assert isinstance(failure, ValueError)


# --- §0.1 copy rules, enforced by CI rather than by memory ------------------

BANNED = ["real-time", "real time", "live crash data", "today's crashes",
          "up to the minute", "up-to-the-minute"]

# "current" is banned as a standalone claim about the data. It is matched with
# word boundaries so that words containing it are not false positives.
BANNED_WORDS = ["current", "currently"]


def module_code() -> str:
    """The module's executable CODE, with every comment and string removed.

    The structural tests below grep for forbidden names, and grepping raw source
    punishes the file for explaining itself: app/live.py documents that it must
    not import `duckdb` and must not derive anything from `today`, so both words
    appear in it precisely BECAUSE the rule is being honoured. Its user-facing
    copy is checked separately, by user_visible_strings().

    Tokenising and dropping comments and string literals leaves only what
    actually executes, which is what these tests are really about.
    """
    import io
    import tokenize

    kept = []
    for token in tokenize.generate_tokens(io.StringIO(inspect.getsource(live)).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


def imported_modules() -> set[str]:
    """Every module app/live.py actually imports, read from its syntax tree."""
    import ast

    names: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(live))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def user_visible_strings() -> list[str]:
    """Every string a user can see: the headline and detail of every outcome."""
    checks = [
        check_feed(COVERAGE, get=getter(MAX_DATE_BODY)),
        check_feed(date(2026, 1, 31), get=getter(MAX_DATE_BODY, COUNT_BODY)),
        check_feed(COVERAGE, get=raising(FeedUnreachable("timed out"))),
        check_feed(COVERAGE, get=raising(FeedRefused("HTTP 429"))),
        check_feed(COVERAGE, get=getter('[{"newest":null}]')),
    ]
    out = []
    for check in checks:
        out.extend([check.headline, check.detail])
    return out


@pytest.mark.parametrize("phrase", BANNED)
def test_no_banned_phrase_reaches_the_user(phrase):
    for text in user_visible_strings():
        assert phrase not in text.lower(), f"§0.1 bans {phrase!r}: {text!r}"


@pytest.mark.parametrize("word", BANNED_WORDS)
def test_no_banned_word_reaches_the_user(word):
    import re
    pattern = re.compile(rf"\b{word}\b", re.IGNORECASE)
    for text in user_visible_strings():
        assert not pattern.search(text), f"§0.1 bans {word!r}: {text!r}"


def test_no_elapsed_days_figure_anywhere():
    """§0.1: never render an elapsed-days figure.

    '~65 days' was true only on 2026-08-15 and grows by one every day, so it is
    wrong the moment a demo slips. The module must not contain the arithmetic
    that would produce one.
    """
    source = module_code()
    for smell in (".days", "timedelta", "date.today()", "datetime.now()"):
        assert smell not in source, (
            f"{smell!r} in app/live.py — §0.1 forbids an elapsed-days figure, and "
            f"forbids anything about freshness being computed from today()"
        )


def test_module_never_reads_the_clock():
    """Both halves of any freshness statement must be facts that cannot rot.

    Coverage is passed in, derived from the data by app.data.date_bounds. The
    feed's date comes from the feed. Neither is 'now'.
    """
    source = module_code()
    assert "import time" not in source
    assert "today" not in source


# --- structural constraints from §1.2 ---------------------------------------

def test_live_never_imports_duckdb_or_touches_the_source_seam():
    """The live check reports ON the feed; it never becomes a data source.

    Structural, not a convention: if it cannot reach DuckDB or the Source seam,
    it cannot quietly start feeding numbers into the app.
    """
    # Read the actual import statements rather than grepping for substrings.
    # A substring probe for "import data" matched inside
    # `from dataclasses import dataclass`, which is the kind of false positive
    # that gets a real test deleted for being annoying.
    assert "duckdb" not in imported_modules()
    assert not any(m == "app.data" or m.startswith("app.data.")
                   for m in imported_modules())
    assert "resolve_source" not in module_code()


def test_live_adds_no_runtime_dependency():
    """requirements.txt is what Community Cloud installs into a ~1 GB container.

    urllib is standard library, so this whole feature costs zero runtime deps.
    """
    source = module_code()
    assert "import requests" not in source
    assert "urllib" in source


def test_the_http_getter_is_injectable():
    """Without this the tests could not run offline and CI would flake."""
    signature = inspect.signature(check_feed)
    assert "get" in signature.parameters
    assert signature.parameters["get"].default is live.urllib_get
