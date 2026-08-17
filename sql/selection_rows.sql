-- Row-level crashes for the selected corridor, within the current date range.
-- Feeds the drawer's contributing-factor / victim-split / hour-of-week charts,
-- all of which need real rows rather than a pre-aggregated table. Selection
-- goes through a params TABLE, same reasoning as filter_params in
-- app/data.py::build_view: DuckDB cannot prepare a CREATE VIEW, so the value
-- is bound via an INSERT instead of interpolated into SQL text.
SELECT f.*
FROM crashes_filtered f, selection_params s
WHERE f.canonical = s.corridor;
