-- DESIGN.md §3 / CLAUDE_CODE_PROMPT.md §2.7: colour and rank by the cell-level
-- Empirical Bayes estimate, not raw observed harm, and not a corridor rollup.
--
-- eb_cells is the fit's own output (scripts/fit_eb.py) — a fixed rollup over
-- the model's train/holdout window, independent of the app's date-range
-- picker. That is a deliberate, labelled choice (see the freshness/EB caveat
-- in the UI), not an oversight: re-fitting EB on every date-range drag would
-- be both wrong (the model needs its own multi-year window to shrink toward)
-- and too slow for a Streamlit rerun.
--
-- eb_matched is always TRUE here because eb_cells only contains cells that
-- were scored; unscored cells (no LION street match) never reach the map,
-- which is the correct behaviour, not a bug — an unmatched cell has no basis
-- for an estimate and must not be drawn as if it did.
SELECT
    lat_c,
    lon_c,
    canonical,
    observed,
    eb_estimate,
    eb_weight,
    is_highway,
    limited_access_share
FROM read_parquet('data/raw/eb_cells.parquet')
WHERE eb_matched;
