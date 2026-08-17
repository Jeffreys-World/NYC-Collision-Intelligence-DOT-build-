"""The one runtime network call in the deployed app (spec §1.2).

A user-triggered "check for newer records" action: it queries the Socrata API,
shows exactly what came back, and reports it honestly.

WHY THE APP MAKES A CALL WHOSE ANSWER IS ALMOST ALWAYS "NOTHING NEWER". That IS
the answer, and demonstrating it beats asserting it. §0.1 says a DOT engineer
will ask whether this is current and that the answer decides the demo. A
presenter claiming the feed lags is making a claim; a button that queries the
live API in the room and returns the same date already on screen turns the
room's scepticism into the product's evidence.

    ┌──────────────┐   $select=max(crash_date)   ┌─────────────────┐
    │ check_feed() │────────────────────────────▶│  Socrata h9gi   │
    └──────┬───────┘   injected `get`             └─────────────────┘
           │
           ▼
    FeedCheck(outcome, newest_on_feed, coverage_through, headline, detail)
                │
      ┌─────────┼──────────────┬──────────────────┐
      ▼         ▼              ▼                  ▼
  NO_NEWER   NEWER        UNREACHABLE          REFUSED
  the        the feed     could not reach      the API answered
  expected   moved ahead  the API at all       with an error
  result     of the app

FOUR OUTCOMES, NEVER THREE. A failed call must never look like a successful call
that found nothing — that is §4.2's loud-not-seamless rule applied to the only
place the deployed app can now fail. "The feed has nothing newer" and "we could
not ask" are opposite facts, and collapsing them would let a network failure
render as reassurance.

CONSTRAINTS THIS MODULE IS BUILT TO SATISFY (§1.2):

* The HTTP getter is INJECTED. Every test runs offline; CI never makes a network
  call. A test suite whose result depends on NYC Open Data being up is not a
  test suite.
* NO `duckdb` IMPORT, and no contact with the `Source` seam in app/data.py. The
  live check reports ON the feed; it never becomes a data source for anything
  the app renders. Being structurally unable to is cheaper than a rule saying it
  must not.
* NO NEW RUNTIME DEPENDENCY. This uses `urllib` from the standard library, not
  `requests`. requirements.txt is what Streamlit Community Cloud installs into a
  ~1 GB container, and adding an HTTP client to it for one query would be a real
  cost for no benefit. It is also what scripts/fetch_boundaries.py settled on,
  for the separate reason that urllib uses the OS certificate store and survives
  a TLS-intercepting network where requests' bundled certifi does not.
* NO ELAPSED-DAYS FIGURE, EVER, and none of §0.1's banned words in any string a
  user can see. tests/test_live.py greps this module for both, so the rule is
  enforced by CI rather than by memory.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Callable, Protocol

import streamlit as st

DATASET = "h9gi-nx95"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET}.json"

# Short on purpose. This runs while somebody is standing in front of a room; a
# 30-second hang is a worse demo than a clean "could not reach the API".
TIMEOUT_SECONDS = 8.0

# Outcomes. Deliberately named without §0.1's banned words, because these
# strings end up in logs and in the export's assumptions block.
NO_NEWER = "no_newer_records"
NEWER = "newer_records"
UNREACHABLE = "unreachable"
REFUSED = "refused"


class FeedUnreachable(RuntimeError):
    """The API could not be reached at all — DNS, TLS, timeout, connection."""


class FeedRefused(RuntimeError):
    """The API answered, and the answer was an error or was unreadable."""


class Getter(Protocol):
    """The injected HTTP seam. Takes a URL, returns the response body."""

    def __call__(self, url: str, *, timeout: float) -> str: ...


def _app_token() -> str | None:
    """Raises the Socrata rate-limit ceiling. Unauthenticated calls work fine
    for this app's single-click usage; the token only matters if someone
    mashes the button repeatedly during a demo. Missing secrets file (e.g.
    CI, a fresh clone) must not break the call, so every failure mode here
    just means "no token" rather than an exception.
    """
    try:
        return st.secrets.get("SOCRATA_APP_TOKEN") or None
    except Exception:
        return None


def urllib_get(url: str, *, timeout: float) -> str:
    """The real getter. The only place this module touches the network."""
    headers = {"Accept": "application/json"}
    token = _app_token()
    if token:
        headers["X-App-Token"] = token
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise FeedRefused(f"HTTP {response.status}")
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # The API answered. 429 and 5xx are its answers, not a failure to reach
        # it, and they are reported as such rather than as "unreachable".
        raise FeedRefused(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise FeedUnreachable(str(exc.reason)) from exc
    except TimeoutError as exc:
        raise FeedUnreachable("timed out") from exc


@dataclass(frozen=True)
class FeedCheck:
    """What one check found. §4.1: a result object, never a loose dict."""

    outcome: str
    coverage_through: date
    headline: str
    detail: str
    newest_on_feed: date | None = None
    newer_record_count: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome in (NO_NEWER, NEWER)

    @property
    def is_error(self) -> bool:
        """§3.4: block the export while any section is in a degraded state."""
        return not self.succeeded


def _max_date_url() -> str:
    return f"{ENDPOINT}?{urllib.parse.urlencode({'$select': 'max(crash_date) AS newest'})}"


def _count_newer_url(coverage_through: date) -> str:
    query = {
        "$select": "count(1) AS n",
        "$where": f"crash_date > '{coverage_through:%Y-%m-%d}T23:59:59'",
    }
    return f"{ENDPOINT}?{urllib.parse.urlencode(query)}"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    # Socrata returns floating timestamps: '2026-06-11T00:00:00.000'
    return date.fromisoformat(value[:10])


def _read_rows(body: str) -> list[dict]:
    try:
        rows = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FeedRefused("the API returned something that is not JSON") from exc
    if not isinstance(rows, list):
        raise FeedRefused("the API returned an unexpected shape")
    return rows


def check_feed(coverage_through: date, *, get: Getter = urllib_get,
               timeout: float = TIMEOUT_SECONDS) -> FeedCheck:
    """Ask the API what it carries, and compare it to what this app ships.

    `coverage_through` comes from the DATA via app.data.date_bounds, never from
    a constant and never from today(). §0.1: both halves of anything we say
    about freshness have to be facts that cannot rot.

    Never raises. Every failure becomes a FeedCheck whose outcome says what went
    wrong, because a raised exception inside a Streamlit callback replaces the
    section with a traceback.
    """
    try:
        rows = _read_rows(get(_max_date_url(), timeout=timeout))
        newest = _parse_date(rows[0].get("newest") if rows else None)
    except FeedUnreachable as exc:
        return FeedCheck(
            outcome=UNREACHABLE,
            coverage_through=coverage_through,
            headline="Could not reach the NYPD collision feed.",
            detail=(f"The check did not complete, so this says nothing about "
                    f"whether newer records exist ({exc}). Everything on screen "
                    f"still comes from the shipped extract, which is complete "
                    f"through {coverage_through:%Y-%m-%d}. Try again, or carry on "
                    f"— nothing in the app depends on this call."),
        )
    except FeedRefused as exc:
        return FeedCheck(
            outcome=REFUSED,
            coverage_through=coverage_through,
            headline="The NYPD collision feed refused the request.",
            detail=(f"The API answered with an error ({exc}), so the result is "
                    f"unknown rather than empty. Everything on screen still comes "
                    f"from the shipped extract, complete through "
                    f"{coverage_through:%Y-%m-%d}."),
        )

    if newest is None:
        return FeedCheck(
            outcome=REFUSED,
            coverage_through=coverage_through,
            headline="The NYPD collision feed returned no date.",
            detail=("The API answered but gave no maximum crash date, so the "
                    "result is unknown rather than empty. Everything on screen "
                    f"still comes from the shipped extract, complete through "
                    f"{coverage_through:%Y-%m-%d}."),
        )

    if newest <= coverage_through:
        return FeedCheck(
            outcome=NO_NEWER,
            coverage_through=coverage_through,
            newest_on_feed=newest,
            newer_record_count=0,
            headline=f"The feed carries nothing after {newest:%Y-%m-%d}.",
            detail=(f"Checked just now against the NYPD feed, which reports its "
                    f"newest crash as {newest:%Y-%m-%d}. This extract is complete "
                    f"through {coverage_through:%Y-%m-%d}, so there is nothing to "
                    f"add. NYPD collision records are a police-reporting pipeline "
                    f"and arrive well after the crash — this tool is built for "
                    f"chronic-risk prioritisation, where multi-year patterns are "
                    f"stable and the reporting delay does not weaken them."),
        )

    count = None
    try:
        rows = _read_rows(get(_count_newer_url(coverage_through), timeout=timeout))
        if rows and rows[0].get("n") is not None:
            count = int(rows[0]["n"])
    except (FeedUnreachable, FeedRefused):
        # The headline fact — that the feed moved ahead — is already established.
        # Losing the count degrades the detail, not the finding.
        count = None

    counted = f"{count:,} records" if count is not None else "records"
    return FeedCheck(
        outcome=NEWER,
        coverage_through=coverage_through,
        newest_on_feed=newest,
        newer_record_count=count,
        headline=f"The feed has moved ahead, to {newest:%Y-%m-%d}.",
        detail=(f"The NYPD feed now reports crashes through {newest:%Y-%m-%d}, "
                f"and this extract is complete through {coverage_through:%Y-%m-%d} "
                f"— {counted} sit beyond it. The app is still showing only the "
                f"shipped extract: nothing on screen has changed, and no figure "
                f"here includes those records. Re-run the offline refresh "
                f"(scripts/pull_data.py) and re-bake to pick them up."),
    )
