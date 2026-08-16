# DELIVERABLES — outstanding work

## Two honest caveats

- [ ] **EB model is unfinished and its current output is unusable.** Fitting at whole-corridor level gave +0.00pp lift — EB equalled the observed count to four significant figures. Correct statistics at the wrong granularity; shipping it would be raw observed harm wearing an EB label, exactly what §2.7 forbids. The fix is written into the file's docstring: refit on ~110m street-cells where counts are small. The bad CSV was deleted so nobody picks it up by mistake.
- [ ] **The live-path workflow didn't finish writing files.** Its synthesized contract is good and is sitting in its journal — `NEXT-SESSION.md` has the path and a summary of what it had already decided, so the next session resumes from it rather than starting cold.

## Top of the list, in order

- [ ] **Finish `scripts/fit_eb.py` at cell granularity** — marked `UNFINISHED` at the top. Unit becomes `(canonical, round(lat,3), round(lon,3))`; a corridor's estimate is the sum of its cells' shrunken estimates. Label is ALL-MODE casualties, not pedestrian.
- [ ] **Recover the live-path contract from the workflow journal** — read it before re-implementing `app/live.py`; the synthesized contract there is good.
- [ ] **Build `data/limited_access.csv`** — needed for the estimator's highway/surface branch.
- [ ] **THE BAKE — owner's review checkpoint.** Stop and show before committing it (§6 step 2: bake exactly once).
- [ ] **Update all 18 stale figures + the CI gate** — `.github/workflows/tests.yml` still asserts exactly 812,315 rows and will fail. Update together in the same commit as the bake: `CLAUDE_CODE_PROMPT.md` §0.2, `README.md`, and the workflow.

## Two things flagged but deliberately left undone

- [ ] **Rewrite spec §1.2** — it still says there's no runtime API path, which the owner's decision overrode.
- [ ] **Decide on `nyc-crash-risk-forecast`** — left untouched since changing its label would change its published headline; owner's call.
