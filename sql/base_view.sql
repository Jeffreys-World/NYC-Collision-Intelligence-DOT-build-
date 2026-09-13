-- The ONE place the common filter predicates live (eng review decision 11).
-- Every chart query selects from crashes_filtered, so changing a filter is one
-- edit here rather than nine edits across nine files.
--
-- Why a params TABLE instead of bound parameters: DuckDB cannot prepare a
-- CREATE VIEW statement ("Unexpected prepared parameter"). Interpolating the
-- user's dates into the SQL string would be an injection seam. So the dates go
-- into a one-row table via a parameterised INSERT (which CAN be prepared), and
-- the view reads that table. User input never touches SQL text. The casualty
-- flag goes through the same table for the same reason — never formatted into
-- this file's text, even though a boolean looks harmless.
--
-- The casualty toggle lives HERE, not in corridor_table.sql, and that is the
-- point of the file. It used to be a pandas filter applied to the drawer's
-- rows only (streamlit_app.py, after the query), so the drawer counted
-- casualty crashes while the ranked table beside it counted all of them. The
-- table is the map's designated accessible equivalent (DESIGN.md §5), so the
-- two surfaces that must agree were the two that did not. Filtering at the
-- one shared view makes them agree by construction rather than by two edits
-- that have to stay in step.
--
-- The map is deliberately unaffected: it reads eb_cells, not this view, and
-- the EB model is fit on casualties regardless of the toggle. The map caption
-- says so rather than pretending the toggle did something.
CREATE OR REPLACE VIEW crashes_filtered AS
SELECT
    c.*,
    date_trunc('month', c.crash_date)       AS crash_month,
    date_part('year',   c.crash_date)       AS crash_year,
    date_part('hour',   c.crash_datetime)   AS crash_hour,
    dayname(c.crash_date)                   AS crash_dayname,
    date_part('isodow', c.crash_date)       AS crash_dow,
    (c.number_of_persons_killed  > 0)       AS is_fatal,
    (c.number_of_persons_injured > 0)       AS is_injury
FROM crashes_raw c, filter_params p
WHERE c.crash_date BETWEEN p.date_from AND p.date_to
  -- is_fatal / is_injury are computed in the SELECT above and cannot be
  -- referenced from this WHERE in the same statement, so the predicate is
  -- spelled out against the raw columns. Keep the two definitions identical.
  AND (NOT p.casualty_only
       OR c.number_of_persons_killed > 0
       OR c.number_of_persons_injured > 0);
