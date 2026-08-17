-- Spec §2.7 + §4.2: the ranked corridor table is the accessibility equivalent
-- of the map (DESIGN.md §5) and must carry the same figures the map shows.
--
-- Observed figures come from crashes_filtered (the user's date range, honest
-- and labelled observed). eb_estimate/eb_matched come from the pre-fit
-- eb_corridors table, which is a fixed rollup over the model's own train/
-- holdout window, not date-range filterable — that is why it is joined, not
-- recomputed here. A corridor absent from eb_corridors is UNMATCHED, per
-- §4.2, never silently shown as if it had no EB estimate at all.
SELECT
    f.canonical                                              AS corridor,
    count(*)                                                  AS crashes,
    sum(f.number_of_persons_injured)                          AS injured,
    sum(f.number_of_persons_killed)                           AS killed,
    sum(CASE WHEN f.is_fatal OR f.is_injury THEN 1 ELSE 0 END) AS casualty_crashes,
    sum(CASE WHEN f.borough_source != 'reported' THEN 1 ELSE 0 END) AS other_tools_drop,
    e.eb_estimate                                              AS eb_estimate,
    coalesce(e.eb_matched, FALSE)                              AS eb_matched,
    e.coverage                                                 AS eb_coverage
FROM crashes_filtered f
LEFT JOIN eb_corridors e ON e.canonical = f.canonical
WHERE f.canonical IS NOT NULL
GROUP BY f.canonical, e.eb_estimate, e.eb_matched, e.coverage
ORDER BY coalesce(e.eb_estimate, 0) DESC, crashes DESC;
