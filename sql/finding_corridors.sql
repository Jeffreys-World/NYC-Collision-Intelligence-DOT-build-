-- The completeness finding, per corridor. Reads crashes_raw, NOT
-- crashes_filtered, and that is the whole point of the file.
--
-- Every other query in sql/ reads the filtered view, so every other figure on
-- the page moves when someone drags the date picker or flips the casualty
-- toggle. This one must not. "The standard view shows 0 deaths on the Belt
-- Pkwy; there have been 56" is a property of the dataset, and a headline that
-- changes under the reader's hand is not a finding (TODOS.md T11). The cache
-- key follows the same rule: presentation.finding_cache_key carries the
-- source and nothing else.
--
-- "Standard view" means rows with a borough NYPD reported. Any borough-level
-- view drops the rest, which is borough_source != 'reported' — the same
-- definition the drawer's completeness badge uses. Every figure here is
-- OBSERVED; nothing from the Empirical Bayes fit enters it.
SELECT
    canonical,
    count(*)                                                        AS crashes,
    coalesce(sum(number_of_persons_killed), 0)                      AS killed,
    count(*) FILTER (WHERE borough_source = 'reported')             AS crashes_reported,
    coalesce(sum(number_of_persons_killed)
             FILTER (WHERE borough_source = 'reported'), 0)         AS killed_reported
FROM crashes_raw
WHERE canonical IS NOT NULL
GROUP BY canonical;
