"""
The user-triggered feed check. One button, one request, two figures, nine outcomes.

Spec §1.2 originally read "There is no runtime API path in the deployed app."
That was reversed on 2026-08-16 (option C). The reversal is deliberately narrow,
and every reason §1.2 gave still binds — this module is built so that none of
them can bite:

    §1.2 said                          this module answers
    ─────────────────────────────────  ──────────────────────────────────────────
    a live client fetches records      it fetches no records. It asks for two
    the UI may not show                scalars: the feed's newest crash_date and
                                       how many rows sit after this build's
                                       coverage. Neither ever enters a chart.
    rate limits and 429s               a 429 is a first-class, named outcome with
                                       its own sentence, not a generic error.
    pagination bugs                    nothing is paginated. See _select().
    schema drift on the demo path      a drifted schema lands in UNRECOGNISED and
                                       says so; no figure moves.

The module is named for the noun the UI already uses. `freshness_line()` says
"NYPD feed last carried 2026-06-11", so the module, the functions and the copy
all speak of "the feed". The word this file will not use is the one §0.1 exists
to police: a query that runs now is not data that is from now, and a codebase
that names the module after the query invites exactly that conflation.

    ┌──────────────────────┐
    │ render_feed_check()  │  the ONLY st.* surface. @st.fragment.
    └──────────┬───────────┘
               │ if st.button(...)          <- the only reachable path to a socket
               ▼
    ┌──────────────────────┐   daemon thread + queue, 6.0s wall deadline
    │ check_feed()         │──────────────────────────────────┐
    └──────────┬───────────┘                                  │
               │                                              ▼
               │                                    ┌───────────────────┐
               │                                    │ _fetch()          │
               │◄───────────────────────────────────│ stdlib urllib,    │
               │      evidence dict, never raises   │ no Streamlit      │
               ▼                                    └───────────────────┘
    ┌──────────────────────┐
    │ _classify()          │──► FeedCheck(status, coverage_to, ...)
    │ pure, total          │    frozen. __post_init__ makes a failed result
    └──────────────────────┘    carrying a figure impossible to construct.
               │
               ▼
    st.session_state["feed.check"]   — never a cache decorator. See CACHING below.

WHAT THIS MODULE MUST NEVER DO, and the mechanism that stops it:

* Feed a number into the app. Nothing here is imported by the data layer; the
  DuckDB view, the map key and the extract's trustworthiness flag are untouched.
  tests/test_feed_isolation.py fails the moment that changes.
* Fire on a rerun. The call sits inside `if st.button(...)`. Streamlit reruns the
  whole script on every widget change, so an ambient call would hit the network
  on a cost-slider drag.
* Degrade silently into Parquet figures (§4.2). FeedCheck.__post_init__ raises.
* Read a clock. The timestamp shown is the server's own `Date` response header,
  verbatim. tests/test_freshness.py::test_no_module_computes_today globs app/*.py
  and would catch a local clock here — correctly.

TRANSPORT: stdlib urllib.request, and NOT `requests`. This is measured, not
taste, and the usual dependency-weight argument is FALSE here — streamlit 1.61.1
declares `requests<3,>=2.27` as a hard dependency, so `requests` is already
installed in the deployed container and adding it to requirements.txt would pull
zero new wheels. The real reason is local rehearsability. Measured on this
machine, 2026-08-16:

    stdlib urllib  -> HTTP 200 in 0.33s (0.94s cold)
    requests       -> SSLError CERTIFICATE_VERIFY_FAILED

This repo is developed behind a TLS interceptor — the exact failure
scripts/pull_data.py:46-51 documents. `requests` carries its own certifi bundle
and fails; stdlib `ssl` reads the OS trust store, which already trusts the
interceptor, and succeeds. The two honest ways to make `requests` work here are
both worse: calling truststore.inject_into_ssl() from a runtime module mutates
global SSL state for the whole Streamlit process (a runtime module quietly
re-trusting an interceptor is the opposite of §4.2's "loud"), or shipping
truststore to Community Cloud where it does nothing. A check whose success path
can only be observed on the Day 7 deployed rehearsal is a check that ships
untested, in the week with no time left to fix it.

NO APP TOKEN, EVER. Anonymous access returned 200 in 0.20-0.94s across every
probe on 2026-08-16; a token raises rate limits, it does not gate access.
Dropping it keeps .env.example's committed "the deployed app needs no secret"
true, keeps the local and deployed paths identical (what you rehearse is what
you demo), and avoids reading Streamlit's secrets store at all — that read
raises when no secrets.toml exists, which is a startup crash on a laptop, the
worst possible place to introduce one.

CACHING: st.session_state only, a deliberate documented deviation from §1.4
("cache all loaders"). This is not a loader, it is a user-triggered action, and
the loader cache has three properties that are each wrong here:
  1. entries are evictable under memory pressure on a ~1 GB container, and an
     eviction RE-EXECUTES the producer — firing the network on an unrelated
     widget change, the precise ambient call the button-gate exists to forbid;
  2. it does not cache exceptions, so a raising probe re-fires on every rerun;
  3. a TTL is actively wrong. Pressing "Check again" inside the TTL would replay
     the first response, and an engineer who presses twice and sees a
     byte-identical server `Date` has caught the tool faking a query. That is
     worse than not shipping the feature.
session_state is never evicted and never re-executes its producer.
"""

from __future__ import annotations

import html
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, fields
from datetime import date
from enum import Enum
from urllib.parse import quote, urlencode

import streamlit as st

FEED_URL = "https://data.cityofnewyork.us/resource/h9gi-nx95.json"

# Identifies the caller and costs one line. Deliberately NOT justified as
# WAF insurance — that is folklore here. Measured 2026-08-16: the default
# Python-urllib/3.12 also returns 200.
USER_AGENT = "nyc-collision-intelligence/1.0"

# urlopen(timeout=) is a SOCKET hint. It does not bound a stalled DNS
# resolution or a TLS handshake that never completes, which is the whole
# reason the wall deadline below exists and is enforced in the main thread.
SOCKET_TIMEOUT = 5.0
WALL_DEADLINE = 6.0

# Measured real payloads are 12-51 bytes. Anything larger is a captive-portal
# sign-in page, not the feed, so there is nothing to gain by reading it all.
MAX_BODY_BYTES = 65_536

SESSION_KEY = "feed.check"

# Every user-visible string, in one place, so tests/test_feed_copy.py can scan
# the whole surface for §0.1's banned vocabulary rather than hoping a reviewer
# spots it in a render call.
COPY: dict[str, str] = {
    "popover_title": "Newer records",
    "prelude": ("This check asks the feed a question. It cannot make the feed "
                "answer differently — NYPD reporting sets that pace, not this tool."),
    "trigger": "Check the feed for newer records",
    "trigger_help": ("Sends one query to data.cityofnewyork.us and shows the "
                     "response. No figure on this page changes."),
    "spinner": "Asking data.cityofnewyork.us for records dated after {coverage_to}…",
    "disabled": "Checking the feed is switched off in this deployment.",

    # --- the feed answered
    "aligned_headline": "Feed checked — nothing newer than this build.",
    "aligned_detail": ("The feed holds no crash records dated after {coverage_to}, "
                       "and its newest record is dated {feed_newest}. This build "
                       "covers through {coverage_to}."),
    "aligned_note": ("The check compares crash dates only. It does not detect "
                     "revisions to records already in this build."),

    "behind_headline": "Feed checked — it holds {n:,} records this build does not.",
    "behind_detail": ("The feed holds {n:,} crash records dated after {coverage_to}, "
                      "the newest dated {feed_newest}. No figure on this page "
                      "includes them. Re-run scripts/pull_data.py and re-bake the "
                      "extract to fold them in."),

    "ahead_headline": ("Feed checked — its newest record is older than this "
                       "build's coverage."),
    "ahead_detail": ("The feed's newest record is dated {feed_newest}; this build "
                     "covers through {coverage_to}. NYPD may have withdrawn or "
                     "revised records since the extract was pulled. Treat the "
                     "coverage window as the extract's, not the feed's."),

    # --- it did not
    "unreachable_headline": "Feed check failed — could not reach data.cityofnewyork.us.",
    "unreachable_detail": ("The network is unreachable from here. Press the button "
                           "again, or carry on without it."),

    "timed_out_headline": "Feed check failed — no answer within {deadline:.0f} seconds.",
    "timed_out_detail": ("data.cityofnewyork.us did not answer in time. Press the "
                         "button again, or carry on without it."),

    "rate_limited_headline": ("Feed check failed — the feed rate-limited the "
                              "request (HTTP 429)."),
    "rate_limited_detail": "Wait a moment, then check again.",

    "rejected_headline": "Feed check failed — the feed rejected the query (HTTP {status}).",
    "rejected_detail": ("This is a defect in the query, not a network problem. "
                        "Fix it in app/feed.py."),

    "service_error_headline": "Feed check failed — the feed returned HTTP {status}.",
    "service_error_detail": ("That is their service, not this app. Press the button "
                             "again, or carry on without it."),

    "not_json_headline": "Feed check failed — the reply was not feed data.",
    "not_json_detail": ("It arrived as {content_type}. A network sign-in page may "
                        "be intercepting requests."),

    "unrecognised_headline": ("Feed check failed — the feed answered in a shape "
                              "this check does not recognise."),
    "unrecognised_detail": ("The feed's schema may have changed. Nothing was "
                            "retrieved."),

    # Appended to EVERY failure detail, by detail() rather than by a render call,
    # so a layout tweak cannot drop it. This is the sentence that stops a dead
    # network casting doubt on the analysis sitting above the strip. Reviewers
    # will want to vary it for style. They must not.
    "unchanged": ("Nothing on this screen changed. Every figure here comes from "
                  "the committed extract, which does not need the network."),

    # --- evidence panel
    "server_date": "Server response header: {server_date}",
    "no_server_date": "The server sent no date header.",
    "evidence": "Show what was sent and what came back",
    "evidence_request": "Request",
    "evidence_status": "Status",
    "evidence_round_trip": "Round trip",
    "evidence_last_modified": "Dataset last modified (server header)",
    "evidence_body": "Response body",
    "again": "Check again",

    # --- export (§3.4). Stamped with the SERVER's date, so each line is a fixed
    # historical fact that cannot rot in a PDF that leaves the building.
    "export_aligned": ("Feed check: on {server_date}, data.cityofnewyork.us "
                       "reported no crash records dated after {coverage_to}, its "
                       "newest dated {feed_newest}."),
    "export_behind": ("Feed check: on {server_date}, data.cityofnewyork.us reported "
                      "{n:,} crash records dated after {coverage_to}, newest "
                      "{feed_newest}. Those records are not included in any figure "
                      "in this report."),
    "export_ahead": ("Feed check: on {server_date}, data.cityofnewyork.us reported "
                     "its newest record dated {feed_newest}, older than this "
                     "report's coverage through {coverage_to}."),
}


class Status(str, Enum):
    """Nine outcomes. Each one owns a distinct sentence in COPY.

    A generic something-went-wrong is what turns a network hiccup into a
    credibility loss: "could not reach the feed" is itself a small inaccuracy
    when the feed answered in 0.17s and rejected our SoQL, in the one panel
    whose entire job is accuracy.
    """

    # the feed answered
    ALIGNED = "aligned"
    BEHIND = "behind"
    AHEAD = "ahead"
    # it did not
    UNREACHABLE = "unreachable"
    TIMED_OUT = "timed_out"
    RATE_LIMITED = "rate_limited"
    REJECTED = "rejected"
    SERVICE_ERROR = "service_error"
    NOT_JSON = "not_json"
    UNRECOGNISED = "unrecognised"


@dataclass(frozen=True)
class FeedCheck:
    """One check's result. Frozen, primitives only, one honest flag.

    Mirrors the shape the data layer already uses for its own seam: a frozen
    dataclass whose boolean says whether the numbers may be quoted.

    EXACTLY TWO feed-derived values ever cross this module's boundary:
    `records_after` and `feed_newest`. A third is a §0.1 decision, not a
    refactor. This cap is the structural defence against the scope creep this
    feature invites — "show the newest few rows", "check just this corridor".
    The corridor-scoped check is the most seductive and the worst: a
    feed-side corridor count would differ from this build's for reasons rooted
    in street normalisation and aliasing (see app/streets.py) rather than
    freshness, producing a contradiction on stage that takes three minutes to
    explain.

    __post_init__ is the whole §4.2 story. A silently degraded result carrying
    a Parquet number as if it came from the feed is not a bug you can write —
    it is a value you cannot construct.
    """

    status: Status
    coverage_to: date               # echoed from date_bounds(), never hardcoded

    # --- feed-derived values. EXACTLY TWO.
    records_after: int | None = None
    feed_newest: date | None = None

    # --- evidence: what the SERVER said about itself, verbatim.
    #
    # A client-side OSError text is deliberately absent. This panel's frame is
    # "what came back", and rendering an errno under that heading would be the
    # small dishonesty the panel exists to rule out.
    url: str = ""
    http_status: int | None = None
    server_date: str | None = None      # the server's own Date header
    last_modified: str | None = None
    content_type: str | None = None
    body: str | None = None             # raw, truncated to MAX_BODY_BYTES
    server_message: str | None = None   # from a 4xx JSON {"message": ...}
    round_trip_s: float | None = None

    @property
    def answered(self) -> bool:
        return self.status in (Status.ALIGNED, Status.BEHIND, Status.AHEAD)

    def __post_init__(self) -> None:
        if not self.answered and (self.records_after is not None
                                  or self.feed_newest is not None):
            raise ValueError("a failed check may not carry a feed figure (§4.2)")
        if self.answered and (self.records_after is None or self.feed_newest is None):
            raise ValueError("an answered check must carry both feed figures")


# --------------------------------------------------------------------- query

def _select(coverage_to: date) -> str:
    """One SoQL conditional aggregate returning BOTH values, always.

    Measured against the real endpoint on 2026-08-16:

        coverage 2026-06-11 -> [{"newest":"2026-06-11T00:00:00.000","n_after":"0"}]
        coverage 2025-12-31 -> [{"newest":"2026-06-11T00:00:00.000","n_after":"36424"}]

    both in 0.33s warm.

    The obvious shape — count(1) with a $where filter — has a trap that lands
    on the SUCCESS path, in the demo's main case. §1.2 records that Socrata
    omits null keys entirely; a $where-filtered aggregate that matches nothing
    therefore returns literally [{"n":"0"}], with NO `newest` key. The panel
    would lose the feed's own date exactly when it most needs to state it.
    Running max() and sum(case(...)) over the UNFILTERED table sidesteps that:
    both keys are present in every state. Parse with .get() anyway.

    Side benefit for the demo: the request URL shown in the evidence panel
    literally contains this build's coverage date, so an engineer reading over
    a shoulder can see the app asking exactly the right question.

    NO $order, and that omission needs saying out loud because a reviewer who
    knows §1.2 will look for it. $order exists to make PAGINATION stable, and
    it is meaningless against a single-row aggregate with no $offset. The
    rule's intent — never paginate unordered — is preserved by never
    paginating. If anyone later adds a row-returning query to this module,
    $order=crash_date becomes mandatory again.
    """
    cutoff = f"{coverage_to:%Y-%m-%d}T23:59:59"
    return (f"max(crash_date) AS newest, "
            f"sum(case(crash_date > '{cutoff}', 1, true, 0)) AS n_after")


def build_url(coverage_to: date) -> str:
    """The ONE url string that is both sent and displayed.

    `safe` keeps the SoQL punctuation unescaped so the string stays pasteable
    into a browser address bar. That is not cosmetic: the evidence panel's
    whole product is that a DOT engineer can copy this out of st.code, paste it
    into their own browser in the room, and get the same answer. A percent-
    encoded blob is technically identical and rhetorically useless.
    """
    query = urlencode({"$select": _select(coverage_to)},
                      quote_via=quote, safe="$,()>'=<:")
    return f"{FEED_URL}?{query}"


# ----------------------------------------------------------------- transport

_EVIDENCE_FIELDS = {"url", "http_status", "server_date", "last_modified",
                    "content_type", "body", "server_message", "round_trip_s"}


def _evidence(**kwargs) -> dict:
    """Keep the dict's keys a strict subset of FeedCheck's field names.

    Every construction below splats this into FeedCheck(**evidence), so a typo
    would otherwise surface as a TypeError inside the one function that is not
    allowed to raise.
    """
    known = {f.name for f in fields(FeedCheck)}
    assert _EVIDENCE_FIELDS <= known
    return {k: v for k, v in kwargs.items() if k in _EVIDENCE_FIELDS}


def _server_message(body: str | None) -> str | None:
    """Socrata's 4xx bodies are JSON carrying a `message` key.

    Measured 2026-08-16 against a deliberately broken column name:
        {"message": "Query coordinator error: query.soql.no-such-column; ..."}
    Rendering it verbatim is what tells a developer afterwards that this was a
    schema break rather than a network break.
    """
    if not body:
        return None
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    if isinstance(parsed, dict):
        msg = parsed.get("message") or parsed.get("error")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()
    return None


def _read(headers, body_bytes: bytes, url: str, status: int, started: float) -> dict:
    body = body_bytes.decode("utf-8", errors="replace")
    get = headers.get if headers is not None else (lambda _k: None)
    return _evidence(
        url=url,
        http_status=status,
        # The server's own clock, verbatim. NEVER ours — see the module
        # docstring and tests/test_freshness.py::test_no_module_computes_today.
        server_date=get("Date"),
        last_modified=get("Last-Modified"),
        content_type=get("Content-Type"),
        body=body,
        server_message=_server_message(body) if status >= 400 else None,
        # monotonic, not a wall clock: a round-trip duration is a measured
        # event, not a date, and it does not decay between now and the demo.
        round_trip_s=time.monotonic() - started,
    )


def _fetch(url: str) -> dict:
    """Raw transport. No Streamlit import reachable from here, and it NEVER raises.

    Runs on a bare daemon thread, which has no ScriptRunContext — any st.* call
    made here would be a silent no-op plus a warning, so there are none.

    ZERO RETRIES. scripts/pull_data.py's six-with-backoff is correct for an
    848,000-row unattended pull and catastrophic on stage: it would turn a
    6-second failure into a 40-second hang while a room watches. The button is
    the retry.
    """
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=SOCKET_TIMEOUT) as response:
            return _read(response.headers, response.read(MAX_BODY_BYTES),
                         url, response.status, started)
    except urllib.error.HTTPError as exc:
        # HTTPError IS the response, so a 4xx/5xx still carries headers and a
        # body worth showing. It subclasses OSError, so it must be caught first.
        try:
            body_bytes = exc.read(MAX_BODY_BYTES)
        except Exception:
            body_bytes = b""
        return _read(exc.headers, body_bytes, url, exc.code, started)
    except Exception:
        # URLError, socket.timeout, ssl errors, and anything else the stack
        # invents. Nothing came back, so there is no evidence to show beyond
        # the URL that was attempted.
        return _evidence(url=url, round_trip_s=time.monotonic() - started)


def _run_with_deadline(fn, seconds: float) -> tuple[str, object]:
    """Return ("ok", value) | ("raised", exc) | ("timeout", None) within `seconds`.

    Verified against a blackhole address on 2026-08-16: the main thread was
    freed at 6.02s with the worker still alive and abandoned. Without this the
    entire Streamlit script stays open behind a stalled handshake, the
    websocket looks frozen, and every queued widget interaction backs up behind
    it — the worst failure available during a demo.

    A daemon thread plus a Queue, deliberately NOT a thread pool: a
    single-worker pool lets one hung call poison every later click, and
    abandoning a pooled future is undefined. A daemon thread is abandonable by
    definition and cannot keep the process alive.

    The orphan thread holding a socket is a real, accepted cost. It dies on its
    own SOCKET_TIMEOUT. Do not "fix" it with a pool.
    """
    box: queue.Queue = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            box.put(("ok", fn()))
        except BaseException as exc:  # noqa: BLE001 - reported, never swallowed
            box.put(("raised", exc))

    threading.Thread(target=worker, name="feed-check", daemon=True).start()
    try:
        return box.get(timeout=seconds)
    except queue.Empty:
        return ("timeout", None)


# ---------------------------------------------------------------- classifying

def _as_int(value) -> int | None:
    """Socrata returns every scalar as a string (§4.1): "36424", not 36424."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _as_date(value) -> date | None:
    """Slice to 10 chars before parsing.

    Measured values carry a '.000' suffix — "2026-06-11T00:00:00.000" — and a
    future 'Z' would break a naive fromisoformat on 3.10. The date is the only
    part this check uses.
    """
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _classify(payload, coverage_to: date, evidence: dict) -> FeedCheck:
    """Pure and TOTAL. Anything unexpected lands in UNRECOGNISED, never a raise.

        n_after > 0                          -> BEHIND
        n_after == 0, newest == coverage_to  -> ALIGNED
        n_after == 0, newest <  coverage_to  -> AHEAD
        anything else                        -> UNRECOGNISED

    AHEAD is not a theoretical branch. Socrata republishes, so NYPD can
    withdraw or revise records after a pull, leaving the feed's newest date
    behind the extract's coverage. Treating that as impossible produces
    nonsense copy in front of the one audience that would notice.

    The two impossible combinations — a positive count with a newest date at or
    before coverage, and a zero count with a newest date after it — are
    self-contradictory answers, so they are reported as unrecognised rather
    than resolved in the feed's favour.
    """
    def unrecognised() -> FeedCheck:
        return FeedCheck(Status.UNRECOGNISED, coverage_to, **evidence)

    if not isinstance(payload, list) or len(payload) != 1:
        return unrecognised()
    row = payload[0]
    if not isinstance(row, dict):
        return unrecognised()

    n_after = _as_int(row.get("n_after"))
    newest = _as_date(row.get("newest"))
    if n_after is None or newest is None or n_after < 0:
        return unrecognised()

    if n_after > 0:
        if newest <= coverage_to:
            return unrecognised()
        status = Status.BEHIND
    elif newest == coverage_to:
        status = Status.ALIGNED
    elif newest < coverage_to:
        status = Status.AHEAD
    else:
        return unrecognised()

    return FeedCheck(status, coverage_to, records_after=n_after,
                     feed_newest=newest, **evidence)


def check_feed(coverage_to: date, *, fetch=_fetch,
               deadline_s: float = WALL_DEADLINE) -> FeedCheck:
    """The one entry point. NEVER raises.

    Any exception that escapes — from the transport, from a shape this code has
    never seen, from a future edit — becomes Status.UNRECOGNISED, which
    announces itself in the panel rather than replacing the app with a
    traceback (§4.1). It still fails loudly in tests, where _classify and
    FeedCheck are exercised directly and __post_init__ raises.

    `coverage_to` comes from date_bounds() and is never hardcoded, so when the
    offline re-pull moves coverage the check re-aims itself with no code change.

    `fetch` and `deadline_s` are keyword arguments so every branch below is
    unit-testable with no network at all. CI has no guaranteed internet and
    must never depend on Socrata being up.
    """
    url = build_url(coverage_to)
    try:
        outcome, value = _run_with_deadline(lambda: fetch(url), deadline_s)

        if outcome == "timeout":
            return FeedCheck(Status.TIMED_OUT, coverage_to, url=url)
        if outcome == "raised" or not isinstance(value, dict):
            return FeedCheck(Status.UNRECOGNISED, coverage_to, url=url)

        evidence = _evidence(**value)
        evidence.setdefault("url", url)
        status_code = evidence.get("http_status")

        if status_code is None:
            return FeedCheck(Status.UNREACHABLE, coverage_to, **evidence)
        if status_code == 429:
            return FeedCheck(Status.RATE_LIMITED, coverage_to, **evidence)
        if status_code >= 500:
            return FeedCheck(Status.SERVICE_ERROR, coverage_to, **evidence)
        if status_code >= 400:
            # Never retried, carrying pull_data.py's earned rule forward: a 400
            # means the query is wrong, and retrying a wrong query forever
            # helps nobody. The distinct status is what tells a developer this
            # was a schema break.
            return FeedCheck(Status.REJECTED, coverage_to, **evidence)
        if status_code != 200:
            return FeedCheck(Status.UNRECOGNISED, coverage_to, **evidence)

        # The captive-portal guard, and the sneakiest failure at a conference
        # venue: a sign-in page returning 200 with an HTML body is the only
        # failure that could otherwise render as a successful answer. Guarded
        # three ways — the content type must say json, the body must parse, and
        # _classify insists on the shape. This guard is what makes "a query
        # that runs now is not data from now" safe to say out loud.
        content_type = (evidence.get("content_type") or "").lower()
        if "json" not in content_type:
            return FeedCheck(Status.NOT_JSON, coverage_to, **evidence)
        try:
            payload = json.loads(evidence.get("body") or "")
        except ValueError:
            return FeedCheck(Status.NOT_JSON, coverage_to, **evidence)

        return _classify(payload, coverage_to, evidence)
    except Exception:
        return FeedCheck(Status.UNRECOGNISED, coverage_to, url=url)


# --------------------------------------------------------------------- copy

def _fmt(key: str, check: FeedCheck, **extra) -> str:
    return COPY[key].format(
        coverage_to=f"{check.coverage_to:%Y-%m-%d}",
        feed_newest=f"{check.feed_newest:%Y-%m-%d}" if check.feed_newest else "",
        n=check.records_after or 0,
        status=check.http_status if check.http_status is not None else "",
        content_type=check.content_type or "an unstated type",
        deadline=WALL_DEADLINE,
        **extra,
    )


def headline(check: FeedCheck) -> str:
    """One sentence per Status. Pure.

    Every state leads with a distinct WORD — "Feed checked —" or "Feed check
    failed —" — because DESIGN.md §1 forbids carrying a verdict on colour
    alone, and because the completeness channel this panel uses has no
    severity hue to carry it with.
    """
    return _fmt(f"{check.status.value}_headline", check)


def detail(check: FeedCheck) -> str:
    """One paragraph per Status. Pure.

    The trailing sentence is appended HERE rather than in the render call:
    on a failure, "Nothing on this screen changed"; on an aligned answer, the
    note that this compares crash dates only and does not see revisions. A
    layout change cannot drop either one.
    """
    text = _fmt(f"{check.status.value}_detail", check)
    if check.status is Status.REJECTED and check.server_message:
        text = f"{check.server_message} {text}"
    if check.status is Status.ALIGNED:
        return f"{text} {COPY['aligned_note']}"
    if not check.answered:
        return f"{text} {COPY['unchanged']}"
    return text


def export_note(check: FeedCheck | None) -> str | None:
    """One line for the PDF's assumptions block (§3.4), on SUCCESS ONLY.

    None when no check ran, and None when a check failed. A failed probe
    establishes nothing, and "we tried and failed" in a document that leaves
    the building invites distrust of figures that are fine.

    None as well when the server sent no Date header: the line's value is that
    it is a fixed historical fact, and an undated claim in a PDF is not one.

    This function is the ONLY route from this module into an export, and it can
    only ever be reached from a FeedCheck whose __post_init__ let it carry
    figures — which is §3.4's real prohibition (no number from an untrustworthy
    source reaches an export) enforced by the type rather than by discipline.
    """
    if check is None or not check.answered or not check.server_date:
        return None
    return _fmt(f"export_{check.status.value}", check,
                server_date=check.server_date)


def is_enabled() -> bool:
    """Environment only. Never Streamlit's secrets store — that read raises when
    no secrets.toml exists, which is a startup crash on a laptop.

    Set FEED_CHECK=off in the Community Cloud environment to remove the button
    entirely, so a presenter facing a hostile network cannot invoke the network
    at all.
    """
    return os.environ.get("FEED_CHECK", "on").strip().lower() != "off"


# ----------------------------------------------------------------------- UI

# DESIGN.md §1: the COMPLETENESS channel only — neutral surface, hairline, and
# a hatched left edge for anything that is not a clean answer. Never a severity
# hue. A red "feed check failed" banner would say "people died here" in this
# palette AND overstate the failure, since a dead network leaves every figure
# exactly as trustworthy as it was. (#B4232C on this base also measures ~2.9:1
# and fails the 3:1 non-text bar.)
#
# For the same reason this module never calls st.error / st.success / st.info:
# st.info poaches --expected, which is reserved for Empirical Bayes figures and
# nothing else, and st.success reads as low-harm green where green already
# means something on this screen.
_HATCH = ("repeating-linear-gradient(45deg,var(--ink-faint,#5C6873) 0 2px,"
          "transparent 2px 5px)")


def _strip_html(check: FeedCheck) -> str:
    # Hatch on BEHIND, AHEAD and every failure; a clean edge on ALIGNED. The
    # hatch is the completeness texture, so it reads as "this build does not
    # hold everything", which is true of all three of those states and of a
    # check that never got an answer.
    edge_image = "none" if check.status is Status.ALIGNED else _HATCH
    caption = (COPY["server_date"].format(server_date=check.server_date)
               if check.server_date else COPY["no_server_date"])
    return (
        '<div style="display:flex;margin:8px 0 4px 0;border-radius:2px;'
        'overflow:hidden;background:var(--panel-2,#1C242C);'
        'border:1px solid var(--line,#2A343E);">'
        f'<div style="flex:0 0 4px;background-color:{edge};'
        f'background-image:{edge_image};"></div>'
        '<div style="padding:12px 14px;">'
        f'<div style="color:var(--ink,#E6EDF3);font-size:16px;line-height:1.45;">'
        f'{html.escape(headline(check))}</div>'
        f'<div style="color:var(--ink-dim,#8B98A5);font-size:16px;line-height:1.5;'
        f'margin-top:6px;">{html.escape(detail(check))}</div>'
        f'<div style="color:var(--ink-faint,#5C6873);font-size:14px;'
        f'margin-top:8px;">{html.escape(caption)}</div>'
        '</div></div>'
    )


def _render_result(check: FeedCheck, coverage_to: date) -> None:
    st.markdown(_strip_html(check), unsafe_allow_html=True)

    # Collapsed on an answer — the headline IS the answer and the proof is one
    # click away. Expanded on a failure, where the details ARE the message.
    with st.expander(COPY["evidence"], expanded=not check.answered):
        st.caption(COPY["evidence_request"])
        # st.code carries Streamlit's own copy button, which is the point: a DOT
        # engineer can paste this into their own browser, in the room, and get
        # the same answer. That converts "trust us" into "check us".
        st.code(check.url or build_url(coverage_to), language=None)

        rows = []
        if check.http_status is not None:
            rows.append(f"{COPY['evidence_status']}: {check.http_status}")
        if check.round_trip_s is not None:
            rows.append(f"{COPY['evidence_round_trip']}: {check.round_trip_s:.2f}s")
        if check.last_modified:
            rows.append(f"{COPY['evidence_last_modified']}: {check.last_modified}")
        # Deliberately NOT rendered: X-SODA2-Data-Out-Of-Date. It is a real
        # header on every response (measured 2026-08-16: `false`) and it means
        # the secondary index is in sync with the truth store. A DOT engineer
        # reading it over a shoulder reads "the data is not out of date", which
        # hands the room a currency claim in the server's own words — defeating
        # §0.1 through a channel none of the copy rules cover. The header set
        # here is curated for that reason, not trimmed for space.
        if rows:
            st.markdown("  \n".join(rows))

        if check.body is not None:
            st.caption(COPY["evidence_body"])
            st.code(check.body, language=None)


@st.fragment
def render_feed_check(coverage_to: date) -> None:
    """The ONLY st.* surface in this module. Render it directly beneath the
    freshness line (DESIGN.md §3 line 1; spec §5 "the freshness line is
    operable, not decorative").

    The split between the popover and the result strip is LOAD-BEARING, not a
    layout preference. st.popover closes on the rerun a button click causes,
    and that behaviour is version-dependent — so a result rendered inside the
    popover could vanish at the exact moment the room is watching, a silent and
    unrecoverable demo failure. Rendering the strip outside, driven purely by
    session_state, makes popover behaviour irrelevant to whether the answer is
    visible. It also puts the evidence in DOM order immediately after the
    freshness line, in the natural reading and tab path — DESIGN.md §5 requires
    text alternatives to sit where a keyboard user actually reaches them,
    because the map itself has no accessible path.

    @st.fragment so a click reruns this component alone: the map layer is never
    re-serialised and the page does not flash while the request is in flight.
    A fragment rerun does not propagate, so an export reads session_state on
    its own next full rerun — which the export button click itself causes, so
    the ordering is always correct. Drop the fragment if it fights the layout;
    it is an optimisation, not a correctness requirement.

    This function must NEVER write to the section-error registry §3.4's export
    blocker reads. The line, drawn explicitly: a section blocks export iff it
    produces a number that appears in the export. This panel produces none, so
    a dead venue network must not kill the closing beat of the demo.
    """
    with st.popover(COPY["popover_title"]):
        st.markdown(COPY["prelude"])
        if not is_enabled():
            st.markdown(COPY["disabled"])
        else:
            # Secondary, never type="primary": this is a supporting proof, not
            # the page's main action. Native control, in tab order, >=44px, no
            # map dependency — fully operable on DESIGN.md §5's accessible path.
            if st.button(COPY["trigger"], key="feed_check_trigger"):
                _run(coverage_to)
            st.caption(COPY["trigger_help"])

    check = st.session_state.get(SESSION_KEY)
    if check is None:
        return

    _render_result(check, coverage_to)
    if is_enabled() and st.button(COPY["again"], key="feed_check_again"):
        _run(coverage_to)
        st.rerun(scope="fragment")


def _run(coverage_to: date) -> None:
    """The single reachable path to a socket: a human pressing a button.

    No nonce, no lazy "check if stale" on load, no TTL that could expire
    mid-demo, and no cooldown or session budget. Streamlit serialises reruns
    per session, so a nervous double-click produces two sequential 0.33s
    requests — honest and harmless. A throttle would cost an extra status,
    extra copy and a disabled-button state for no demo benefit.
    """
    label = COPY["spinner"].format(coverage_to=f"{coverage_to:%Y-%m-%d}")
    with st.spinner(label):
        st.session_state[SESSION_KEY] = check_feed(coverage_to)
