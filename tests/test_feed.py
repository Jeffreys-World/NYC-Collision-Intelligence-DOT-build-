"""Behaviour tests for app/feed.py — the user-triggered feed check.

EVERY TEST HERE RUNS OFFLINE. `check_feed` takes an injected `fetch`, so
nothing in this file touches the network and CI never depends on NYC Open Data
being up. The canned payloads below are the real shapes the API returns,
recorded from live calls on 2026-08-16, when the feed's newest crash was
2026-06-11.

This file replaces tests/test_live.py. app/live.py was the thinner earlier cut
of the same feature and was retired by the 2026-09-12 engineering review
(decision 9): app/feed.py distinguishes ten outcomes where live.py had four,
and it was sitting in the repo imported by nothing.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import feed
from app.feed import FeedCheck, Status, check_feed

COVERAGE = date(2026, 6, 11)

JSON = "application/json;charset=utf-8"

# Recorded from the live API on 2026-08-16.
ALIGNED_BODY = '[{"newest":"2026-06-11T00:00:00.000","n_after":"0"}]'
BEHIND_BODY = '[{"newest":"2026-06-11T00:00:00.000","n_after":"36424"}]'


def fetcher(*, status=200, body=ALIGNED_BODY, content_type=JSON, **extra):
    """An injected fetch returning one canned evidence dict."""
    def _fetch(url: str) -> dict:
        return feed._evidence(
            url=url, http_status=status, body=body, content_type=content_type,
            server_date="Sat, 16 Aug 2026 12:00:00 GMT", round_trip_s=0.33,
            **extra,
        )

    return _fetch


def dead_fetch(url: str) -> dict:
    """What _fetch() returns when nothing came back at all: no status."""
    return feed._evidence(url=url, round_trip_s=6.0)


# --- the feed answered ------------------------------------------------------

def test_a_feed_level_with_this_build_is_aligned():
    check = check_feed(COVERAGE, fetch=fetcher())
    assert check.status is Status.ALIGNED
    assert check.answered
    assert check.records_after == 0
    assert check.feed_newest == COVERAGE


def test_a_feed_ahead_of_this_build_reports_the_count():
    check = check_feed(date(2025, 12, 31), fetch=fetcher(body=BEHIND_BODY))
    assert check.status is Status.BEHIND
    assert check.records_after == 36424
    assert check.feed_newest == date(2026, 6, 11)


def test_a_feed_behind_this_build_is_not_an_error():
    """Socrata republishes: NYPD can withdraw records after a pull, leaving the
    feed's newest date behind this extract's coverage. Not a failure."""
    check = check_feed(date(2026, 8, 1), fetch=fetcher())
    assert check.status is Status.AHEAD
    assert check.answered


def test_newer_records_are_never_silently_shown():
    """The app must say the records exist AND that it is not showing them."""
    check = check_feed(date(2025, 12, 31), fetch=fetcher(body=BEHIND_BODY))
    text = feed.detail(check)
    assert "36,424" in text
    assert "no figure on this page includes them" in text.lower()


# --- failure never reads as an empty success --------------------------------

@pytest.mark.parametrize("status,expected", [
    (429, Status.RATE_LIMITED),
    (400, Status.REJECTED),
    (403, Status.REJECTED),
    (500, Status.SERVICE_ERROR),
    (503, Status.SERVICE_ERROR),
    (301, Status.UNRECOGNISED),
])
def test_each_http_failure_gets_its_own_status(status, expected):
    """A generic something-went-wrong is what turns a network hiccup into a
    credibility loss, in the one panel whose whole job is accuracy."""
    check = check_feed(COVERAGE, fetch=fetcher(status=status, body='{"message":"x"}'))
    assert check.status is expected
    assert not check.answered


def test_nothing_coming_back_is_unreachable_not_nothing_newer():
    check = check_feed(COVERAGE, fetch=dead_fetch)
    assert check.status is Status.UNREACHABLE
    assert not check.answered


def test_a_stalled_request_times_out_and_frees_the_main_thread():
    import time

    def _hangs(url: str) -> dict:
        time.sleep(5)
        return feed._evidence(url=url)

    check = check_feed(COVERAGE, fetch=_hangs, deadline_s=0.2)
    assert check.status is Status.TIMED_OUT


def test_a_captive_portal_page_returning_200_is_not_an_answer():
    """The sneakiest failure at a conference venue: a sign-in page with an HTML
    body and an HTTP 200 is the only failure that could render as success."""
    check = check_feed(COVERAGE, fetch=fetcher(
        body="<html>Sign in to continue</html>", content_type="text/html"))
    assert check.status is Status.NOT_JSON
    assert not check.answered


def test_json_that_is_not_the_expected_shape_is_unrecognised():
    for body in ('[]', '[{"n":"0"}]', '{"newest":"2026-06-11"}',
                 '[{"newest":null,"n_after":"0"}]', '[{"newest":"x","n_after":"0"}]'):
        check = check_feed(COVERAGE, fetch=fetcher(body=body))
        assert check.status is Status.UNRECOGNISED, body


def test_self_contradictory_answers_are_not_resolved_in_the_feeds_favour():
    """A positive count with a newest date at or before coverage cannot both be
    true. Report it as unrecognised rather than picking a half to believe."""
    check = check_feed(COVERAGE, fetch=fetcher(
        body='[{"newest":"2026-06-11T00:00:00.000","n_after":"12"}]'))
    assert check.status is Status.UNRECOGNISED


@pytest.mark.parametrize("status", [s for s in Status])
def test_no_failed_status_can_carry_a_feed_figure(status):
    """§4.2 enforced by the type: a silently degraded result carrying a Parquet
    number as if it came from the feed is a value you cannot construct."""
    answered = status in (Status.ALIGNED, Status.BEHIND, Status.AHEAD)
    if answered:
        pytest.skip("answered statuses are required to carry both figures")
    with pytest.raises(ValueError):
        FeedCheck(status, COVERAGE, records_after=0, feed_newest=COVERAGE)


def test_an_answered_status_must_carry_both_figures():
    with pytest.raises(ValueError):
        FeedCheck(Status.ALIGNED, COVERAGE, records_after=0)


def test_check_feed_never_raises():
    """A raised exception in a Streamlit callback replaces the section with a
    traceback, which is exactly the §4.1 failure the app must not have."""
    def _explodes(url: str) -> dict:
        raise RuntimeError("anything at all")

    check = check_feed(COVERAGE, fetch=_explodes)
    assert check.status is Status.UNRECOGNISED


def test_a_fetch_returning_garbage_is_unrecognised_not_a_crash():
    check = check_feed(COVERAGE, fetch=lambda url: "not a dict")
    assert check.status is Status.UNRECOGNISED


# --- the export seam --------------------------------------------------------

def test_a_failed_check_contributes_nothing_to_an_export():
    """A failed probe establishes nothing, and 'we tried and failed' in a
    document that leaves the building invites distrust of figures that are
    fine."""
    assert feed.export_note(None) is None
    assert feed.export_note(check_feed(COVERAGE, fetch=dead_fetch)) is None


def test_a_successful_check_without_a_server_date_contributes_nothing():
    """The line's whole value is that it is a fixed historical fact. An undated
    claim in a PDF is not one."""
    check = FeedCheck(Status.ALIGNED, COVERAGE, records_after=0,
                      feed_newest=COVERAGE, server_date=None)
    assert feed.export_note(check) is None


def test_a_successful_check_contributes_a_dated_line():
    note = feed.export_note(check_feed(COVERAGE, fetch=fetcher()))
    assert note is not None
    assert "Sat, 16 Aug 2026 12:00:00 GMT" in note
    assert "2026-06-11" in note


# --- the kill switch --------------------------------------------------------

def test_the_button_can_be_removed_by_environment(monkeypatch):
    """A presenter facing a hostile network must be able to remove the network
    path entirely, without a redeploy that changes code."""
    monkeypatch.setenv("FEED_CHECK", "off")
    assert not feed.is_enabled()
    monkeypatch.setenv("FEED_CHECK", "on")
    assert feed.is_enabled()
    monkeypatch.delenv("FEED_CHECK")
    assert feed.is_enabled()


# --- every status renders ---------------------------------------------------

def _one_of_every_status() -> list[FeedCheck]:
    figures = {
        Status.ALIGNED: dict(records_after=0, feed_newest=COVERAGE),
        Status.BEHIND: dict(records_after=36424, feed_newest=date(2026, 7, 1)),
        Status.AHEAD: dict(records_after=0, feed_newest=date(2026, 1, 1)),
    }
    return [
        FeedCheck(s, COVERAGE, http_status=503, server_date="Sat, 16 Aug 2026 12:00:00 GMT",
                  **figures.get(s, {}))
        for s in Status
    ]


@pytest.mark.parametrize("check", _one_of_every_status(), ids=lambda c: c.status.value)
def test_every_status_has_its_own_headline_and_detail(check):
    """Regression: the strip's left-edge colour referenced an `edge` name that
    was never assigned, so the FIRST feed result ever rendered raised
    NameError. app/feed.py was imported by nothing, so no test and no run had
    reached that line. Rendering every status here is what catches the next one.
    """
    assert feed.headline(check).strip()
    assert feed.detail(check).strip()
    assert feed._strip_html(check).strip()


def test_the_headlines_are_all_distinct():
    headlines = {feed.headline(c) for c in _one_of_every_status()}
    assert len(headlines) == len(Status)


def test_every_state_leads_with_a_word_not_a_colour():
    """DESIGN.md §1 forbids carrying a verdict on colour alone, and this panel
    uses the completeness channel, which has no severity hue to carry it."""
    for check in _one_of_every_status():
        head = feed.headline(check)
        assert head.startswith("Feed check"), head
        assert ("failed" in head.lower()) == (not check.answered), head
