# NYC Collision Intelligence (DOT build)

A chronic-risk prioritisation tool for NYC DOT transit and safety engineers, built on the
NYPD Motor Vehicle Collisions dataset. Streamlit + DuckDB over a committed Parquet.

## Non-negotiables

1. **No figure is ever typed.** Every number in the app, the README, or any design doc is
   computed from `data/processed/crashes.parquet`. `scripts/verify_figures.py` recomputes all
   18 published figures and diffs them against what the docs claim — run it before publishing
   any number. A previous spec carried twelve hand-copied corridor counts and zero reproduced.
2. **No elapsed-days figure, ever.** "~65 days", "three months stale" and friends are true on
   one date and wrong the next. Freshness is stated as two fixed dates. Enforced by a copy
   test in `tests/test_live.py`.
3. **`DESIGN.md` wins over the spec** where they disagree. It is the UI source of truth.
4. **Observed vs expected is never blurred.** Observed figures are labelled observed;
   anything from the Empirical Bayes fit is labelled expected. An unmatched corridor is
   labelled unmatched, never silently downgraded to a raw count while still called an estimate.
5. **`borough` is never overwritten in place.** Recovery writes `borough_recovered` and
   `borough_source` alongside it.
6. **No invented CMFs.** Every crash modification factor carries an FHWA Clearinghouse source
   and star rating, or is held at 1.00 and labelled unrated. Never borrow a proxy.
7. **The bake writes nothing without `--commit`.** `scripts/bake.py` is a dry run by default;
   every re-bake is a permanent blob in git history.

## Environment

- Python 3.12. The interpreter is `.venv/bin/python` (`.venv/Scripts/python.exe` on Windows).
- Never write `py` in a script or a GitHub Actions workflow — ubuntu runners have no `py`.
- `requirements.txt` is runtime-only and is what Streamlit Community Cloud installs.
  `requirements-dev.txt` adds geopandas/statsmodels for offline steps that never deploy.
- `jq` is not installed on this machine. Use Python's `json` module to build JSONL.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in
doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec
