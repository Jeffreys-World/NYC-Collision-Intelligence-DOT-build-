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
-- The WHERE below is doing real work, and an earlier version of this comment
-- claimed it was not ("eb_matched is always TRUE here because eb_cells only
-- contains cells that were scored"). eb_cells carries 95,910 rows and 18,163
-- of them have eb_matched = FALSE. Dropping the predicate would put 18,163
-- unscored cells on the map coloured as if they had an estimate, which is the
-- §4.2 failure this file exists to avoid: an unmatched cell has no basis for
-- an estimate and must not be drawn as if it did.
--
-- eb_cells is registered as a view by app/data.py::_ensure_eb_views, the same
-- way eb_corridors is. Reading it through the view rather than a relative
-- read_parquet() path means this file works regardless of the process's
-- working directory, and an environment that has not run the fit yet gets an
-- empty result (and the app's "run scripts/fit_eb.py" message) instead of an
-- IO error.
SELECT
    lat_c,
    lon_c,
    canonical,
    observed,
    eb_estimate,
    eb_weight,
    is_highway,
    limited_access_share
FROM eb_cells
WHERE eb_matched;
