"""§0.1 copy rules, enforced by CI rather than by memory.

THIS FILE CARRIES NON-NEGOTIABLE #2. It used to live in tests/test_live.py,
pinned to app/live.py. The 2026-09-12 engineering review (decision 9) retired
that module, and flagged the deletion as a critical gap: delete app/live.py
without moving this test and the rule stops being enforced anywhere, silently,
while the suite stays green. So it is repointed at TWO surfaces, not one:

  1. app/feed.py's COPY table and every string it renders, and
  2. the user-facing copy in app/streamlit_app.py itself.

(2) is the wider net and the one that was never covered before. The banned
vocabulary has always been reachable from the page's own markdown, not just
from the feed module, and nothing was checking it.

The rule: a query that runs now is not data that is from now. This app shows a
2019-2025 extract. Any copy implying otherwise is a false claim about data
freshness made in front of the one audience that would catch it.
"""

from __future__ import annotations

import ast
import re
from datetime import date
from pathlib import Path

import pytest

from app import feed

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"

COVERAGE = date(2026, 6, 11)

# Phrases banned outright.
BANNED = ["real-time", "real time", "realtime", "live crash data",
          "today's crashes", "up to the minute", "up-to-the-minute",
          "latest data", "as of today"]

# "current" is banned as a standalone claim about the data. Matched with word
# boundaries so that words containing it ("concurrent", "currency") are not
# false positives.
BANNED_WORDS = ["current", "currently"]


def _rendered_feed_strings() -> list[str]:
    """Every string a user can see from app/feed.py: the headline, the detail
    and the export note of every one of the ten outcomes, plus the whole COPY
    table including the labels COPY-only keys carry (buttons, captions)."""
    figures = {
        feed.Status.ALIGNED: dict(records_after=0, feed_newest=COVERAGE),
        feed.Status.BEHIND: dict(records_after=36424, feed_newest=date(2026, 7, 1)),
        feed.Status.AHEAD: dict(records_after=0, feed_newest=date(2026, 1, 1)),
    }
    out = list(feed.COPY.values())
    for status in feed.Status:
        check = feed.FeedCheck(
            status, COVERAGE, http_status=503,
            server_date="Sat, 16 Aug 2026 12:00:00 GMT",
            **figures.get(status, {}),
        )
        out.append(feed.headline(check))
        out.append(feed.detail(check))
        note = feed.export_note(check)
        if note:
            out.append(note)
    return out


def _app_user_facing_strings() -> list[tuple[str, str]]:
    """Every string literal in app/streamlit_app.py, with its line number.

    The whole module, not a curated list: the page's copy is written inline in
    st.markdown / st.caption / help= arguments, and a curated list is exactly
    what rots when someone adds a sentence. Docstrings are excluded — they are
    written for the next engineer, not the user, and one of them legitimately
    discusses the banned vocabulary in order to forbid it.
    """
    src = (APP_DIR / "streamlit_app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    docstrings.add(id(first.value))

    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings):
            out.append((f"streamlit_app.py:{node.lineno}", node.value))
    return out


# --- app/feed.py ------------------------------------------------------------

@pytest.mark.parametrize("phrase", BANNED)
def test_no_banned_phrase_reaches_the_user_from_the_feed_module(phrase):
    for text in _rendered_feed_strings():
        assert phrase not in text.lower(), f"§0.1 bans {phrase!r}: {text!r}"


@pytest.mark.parametrize("word", BANNED_WORDS)
def test_no_banned_word_reaches_the_user_from_the_feed_module(word):
    pattern = re.compile(rf"\b{word}\b", re.IGNORECASE)
    for text in _rendered_feed_strings():
        assert not pattern.search(text), f"§0.1 bans {word!r}: {text!r}"


# --- app/streamlit_app.py ---------------------------------------------------
#
# The page's copy differs from the feed module's in one way that matters: it
# contains DISCLAIMERS. The freshness popover says, in as many words, "This is
# not a real-time feed" and "it does not show today's crashes". Those sentences
# contain the banned phrases precisely BECAUSE the rule is being honoured, and
# a flat substring ban would force the page to stop saying the true thing.
# (tests/test_live.py made the same distinction for a different reason: it
# stripped comments and strings out of app/live.py before grepping, so the
# module could document a rule without failing it.)
#
# So the check is scoped to AFFIRMATIVE claims: a banned phrase is an offence
# unless the clause containing it is negated. The escape is deliberately
# narrow — negation must appear in the SAME clause, before the phrase — and
# test_the_negation_escape_does_not_admit_an_affirmative_claim below pins that
# it cannot be widened into a loophole by accident.

_NEGATORS = re.compile(
    r"\b(not|never|no|does not|doesn't|isn't|is not|cannot|can't|without)\b",
    re.IGNORECASE,
)


def _affirmative_hits(text: str, pattern: re.Pattern) -> list[str]:
    """Matches of `pattern` in `text` that are NOT inside a negated clause.

    Clause boundaries are sentence and comma breaks. The negator has to come
    before the match within the same clause, which is what makes "it does not
    show today's crashes" pass and "showing today's crashes" fail.
    """
    hits = []
    for match in pattern.finditer(text):
        # Only separators actually PRESENT count. rfind returns -1 when absent,
        # and -1 + len(sep) silently ate the first character of the clause for
        # the two-character "**" separator, which turned "Never a real-time
        # view" into "ever a real-time" and lost the negator.
        starts = [text.rfind(sep, 0, match.start()) + len(sep)
                  for sep in (".", ",", ";", ":", "\n", "**")
                  if text.rfind(sep, 0, match.start()) != -1]
        clause_start = max(starts, default=0)
        clause = text[clause_start:match.start()]
        if not _NEGATORS.search(clause):
            hits.append(text[clause_start:match.end()].strip())
    return hits


@pytest.mark.parametrize("phrase", BANNED)
def test_no_banned_phrase_reaches_the_user_from_the_page(phrase):
    pattern = re.compile(re.escape(phrase), re.IGNORECASE)
    offenders = [f"{where}: {hit!r}"
                 for where, text in _app_user_facing_strings()
                 for hit in _affirmative_hits(text, pattern)]
    assert not offenders, f"§0.1 bans {phrase!r} as a claim — " + "; ".join(offenders)


@pytest.mark.parametrize("word", BANNED_WORDS)
def test_no_banned_word_reaches_the_user_from_the_page(word):
    pattern = re.compile(rf"\b{word}\b", re.IGNORECASE)
    offenders = [f"{where}: {hit!r}"
                 for where, text in _app_user_facing_strings()
                 for hit in _affirmative_hits(text, pattern)]
    assert not offenders, f"§0.1 bans {word!r} as a claim — " + "; ".join(offenders)


def test_the_negation_escape_does_not_admit_an_affirmative_claim():
    """The loophole guard. The escape above exists so the page can say 'this is
    NOT a real-time feed'. It must not also let 'shows real-time data' through.
    """
    pattern = re.compile("real-time", re.IGNORECASE)

    # honoured: the disclaimer the popover actually ships
    assert not _affirmative_hits("This is not a real-time feed.", pattern)
    assert not _affirmative_hits("It does not show real-time crashes.", pattern)
    assert not _affirmative_hits("Never a real-time view.", pattern)

    # broken: the claims §0.1 exists to stop
    assert _affirmative_hits("Shows real-time crash data.", pattern)
    assert _affirmative_hits("This is a real-time feed.", pattern)
    # a negation in a PREVIOUS clause must not launder the next one
    assert _affirmative_hits(
        "This is not a map. It is a real-time feed.", pattern)
    assert _affirmative_hits(
        "The lag is not small, but the view is real-time.", pattern)


# --- non-negotiable #2: no elapsed-days figure, ever ------------------------

def test_no_elapsed_days_figure_reaches_the_user_from_either_surface():
    """'~65 days' was true only on 2026-08-15 and grows by one every day, so it
    is wrong the moment a demo slips. Any integer followed by day/days is a
    figure that decays.

    Fixed dates are fine and are what the freshness line uses. The deadline
    copy ("no answer within 6 seconds") is a duration, not an elapsed figure,
    and seconds are deliberately not matched here.
    """
    decaying = re.compile(r"\b\d[\d,]*\s*days?\b", re.IGNORECASE)
    offenders = [f"feed.py: {t!r}" for t in _rendered_feed_strings() if decaying.search(t)]
    offenders += [f"{where}: {t!r}" for where, t in _app_user_facing_strings()
                  if decaying.search(t)]
    assert not offenders, ("§0.1 forbids an elapsed-days figure: "
                           + "; ".join(offenders))


def test_neither_surface_derives_freshness_from_the_clock():
    """Both halves of any freshness statement must be facts that cannot rot.

    Coverage is passed in, derived from the data by app.data.date_bounds. The
    feed's date comes from the feed's own Date header. Neither is 'now'.
    tests/test_freshness.py globs app/*.py for the clock calls themselves; this
    test covers the arithmetic that would build a duration out of two dates.
    """
    offenders = []
    for name in ("feed.py", "streamlit_app.py"):
        src = (APP_DIR / name).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Attribute) and node.attr == "days":
                offenders.append(f"{name}:{node.lineno} .days")
            if isinstance(node, ast.Name) and node.id == "timedelta":
                offenders.append(f"{name}:{node.lineno} timedelta")
    assert not offenders, ("elapsed-time arithmetic in user-facing modules: "
                           + ", ".join(offenders))
