-- City-wide half of the completeness finding. Unfiltered for the same reason
-- as finding_corridors.sql: see that file. One row.
--
-- Must agree with scripts/verify_figures.py's total_deaths and
-- deaths_in_borough_less_rows, which compute the same pair independently from
-- `borough IS NULL`. The two definitions select the same 269,810 rows; that
-- script is what would notice if they ever stopped doing so.
SELECT
    min(crash_date)                                                 AS first_crash,
    max(crash_date)                                                 AS last_crash,
    coalesce(sum(number_of_persons_killed), 0)                      AS killed,
    coalesce(sum(number_of_persons_killed)
             FILTER (WHERE borough_source != 'reported'
                        OR borough_source IS NULL), 0)              AS killed_dropped
FROM crashes_raw;
