-- The ONE place the common filter predicates live (eng review decision 11).
-- Every chart query selects from crashes_filtered, so changing a filter is one
-- edit here rather than nine edits across nine files.
--
-- Why a params TABLE instead of bound parameters: DuckDB cannot prepare a
-- CREATE VIEW statement ("Unexpected prepared parameter"). Interpolating the
-- user's dates into the SQL string would be an injection seam. So the dates go
-- into a one-row table via a parameterised INSERT (which CAN be prepared), and
-- the view reads that table. User input never touches SQL text.
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
WHERE c.crash_date BETWEEN p.date_from AND p.date_to;
