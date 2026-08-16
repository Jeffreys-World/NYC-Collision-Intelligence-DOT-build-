"""
Locks the freshness-line rules from spec §0.1, as amended by the eng review on
2026-08-16.

Two separate failures are being prevented here.

1. HARDCODED COVERAGE. The original spec required the literal string
   "Complete through 2025-12-31". That is ISSUE-002 rebuilt: a static figure
   describing data that a re-bake can change. Coverage must be derived.

2. A DECAYING LAG. The original spec also required "NYPD reporting lag ~65
   days". 65 was true on 2026-08-15 and grows by one every day, so a demo that
   slips two weeks shows a number that is quietly wrong — in the one UI element
   whose entire job is proving the tool is honest about data age.

The second test is the important one: it mechanically stops anyone putting an
elapsed-days figure back into the line.
"""

import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from data import UPSTREAM_THROUGH, PULLED_ON, freshness_line  # noqa: E402

APP_DIR = Path(__file__).resolve().parent.parent / "app"


def test_coverage_is_derived_from_the_argument():
    """Whatever date the data reports is the date that renders."""
    assert "2025-12-31" in freshness_line(date(2025, 12, 31))
    assert "2024-06-30" in freshness_line(date(2024, 6, 30))


def test_coverage_is_not_hardcoded():
    """A re-baked Parquet must move the line, not be contradicted by it."""
    a = freshness_line(date(2025, 12, 31))
    b = freshness_line(date(2023, 1, 1))
    assert a != b, "the line must change when the data's coverage changes"
    assert "2025-12-31" not in b, "a stale coverage date leaked through"


def test_line_carries_no_elapsed_days_figure():
    """The regression lock. No 'lag ~65 days', no 'N days ago', no countdown.

    Any integer followed by 'day' or 'days' is a figure that decays. The two
    real dates in the line are fixed points in the past and are allowed.
    """
    line = freshness_line(date(2025, 12, 31))
    assert not re.search(r"\d+\s*days?\b", line, flags=re.IGNORECASE), (
        f"freshness line contains an elapsed-days figure that will rot: {line!r}"
    )
    assert "lag" not in line.lower(), "'lag' invites a decaying number next to it"


def test_line_states_the_feed_date_as_a_fact():
    """The upstream date belongs in the line, as a date, not as a duration."""
    line = freshness_line(date(2025, 12, 31))
    assert UPSTREAM_THROUGH in line
    assert PULLED_ON in line


def test_no_module_computes_today():
    """Bounds and freshness come from the DATA, never from the clock.

    A picker defaulting to 'last 30 days' against a feed that stopped in 2025
    returns zero rows and reads as a broken app.
    """
    offenders = []
    for path in APP_DIR.glob("*.py"):
        src = path.read_text(encoding="utf-8")
        # strip comments and docstrings cheaply: only flag executable-looking use
        for pattern in (r"\bdate\.today\s*\(", r"\bdatetime\.now\s*\(",
                        r"\bdatetime\.today\s*\("):
            for m in re.finditer(pattern, src):
                line_start = src.rfind("\n", 0, m.start()) + 1
                if src[line_start:m.start()].lstrip().startswith("#"):
                    continue
                offenders.append(f"{path.name}: {m.group(0)}")
    assert not offenders, (
        "app code must not read the clock; derive from the data instead: "
        + ", ".join(offenders)
    )
