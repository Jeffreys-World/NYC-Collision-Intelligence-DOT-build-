-- Row-level crashes for the selected corridor, within the user's date range.
-- Feeds the drawer's KPI rows (crashes, casualty crashes, injured, killed) and
-- its completeness badge, all of which count over real rows rather than a
-- pre-aggregated table. An earlier version of this comment cited three drawer
-- charts (contributing factors, victim split, hour of week) that were never
-- built and have no code anywhere in the repo. Selection
-- goes through a params TABLE, same reasoning as filter_params in
-- app/data.py::build_view: DuckDB cannot prepare a CREATE VIEW, so the value
-- is bound via an INSERT instead of interpolated into SQL text.
SELECT f.*
FROM crashes_filtered f, selection_params s
WHERE f.canonical = s.corridor;
