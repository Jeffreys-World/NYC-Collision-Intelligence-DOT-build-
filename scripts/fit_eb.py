"""Fit a Safety Performance Function and Empirical Bayes estimate.

    .venv/bin/python scripts/fit_eb.py

WHY THIS EXISTS, AND WHY IT IS NOT THE SIBLING REPO'S MODEL.

`nyc-crash-risk-forecast` already carries a validated EB model, and spec §2.7
originally said to join to it. Its label, stated plainly in its own README, is
**pedestrian casualties** — and it deliberately down-weights highways, because
"pedestrians are rarely struck on limited-access roads". Measured against this
repo's Parquet on 2026-08-16, Belt Pkwy carries 8,011 injured and 55 killed but
only 37 pedestrian casualties: 0.5% of its harm. Colouring this product's map by
that model turns every highway green and destroys the §2.6 finding that the
borough-less rows — which are overwhelmingly highway — carry 44.3% of the deaths.

So the label here is ALL-MODE casualties (killed + injured, every road user).
The sibling repo is read STRICTLY READ-ONLY, for its LION road attributes only.
Its published validation figure (+18.4pp, CI +17.5 to +19.3) belongs to the
pedestrian label and MUST NOT be quoted for this model. This script computes its
own, or the product quotes none.

THE UNIT IS A STREET-CELL, NOT A WHOLE CORRIDOR. This was measured, not assumed.
Fitting at whole-corridor level on 2026-08-16 produced an EB estimate identical
to the observed count to four significant figures (Belt Pkwy: observed 5,936, EB
5,935.4) and a lift over raw ranking of +0.00pp. That is the statistically
correct answer to the wrong question: a corridor with thousands of casualties has
an observed count that is already a reliable estimate, so the shrinkage weight
collapses to 0.0002 and EB has nothing to do.

Empirical Bayes earns its keep where counts are small and noisy. So a unit here
is one canonical street within one 0.001-degree cell — `round(lat, 3),
round(lon, 3)` — which is the same grid §2.1 bins the map on, and close in size
to the sibling repo's 150ft segments. Most cells carry 0-5 casualties, which is
exactly the regime EB was built for. A corridor's estimate is then the SUM of its
cells' shrunken estimates, so the corridor figure inherits a real correction
instead of a rounding error, and the map can be coloured by the same numbers it
ranks on.

CELL SIZE, MEASURED. A 0.001-degree cell is **111m x 84m, about 0.94 ha** — not
"110m on a side", which is what this docstring used to claim. Longitude degrees
are shorter than latitude degrees by cos(latitude), which at 40.7 is 0.758, so
the cell is a rectangle with aspect ratio 1.31. What matters for dropping the
exposure offset is that the AREA is uniform: across the NYC latitude span
(40.499 to 40.913) it varies from 0.9413 to 0.9356 ha, a spread of 0.61%, or a
log-exposure shift of 0.006. The offset decision below is unaffected; only its
stated reason was wrong.

Defining the unit this way needs no LION geometry and no spatial join: every
crash already carries coordinates and a canonical street name.

WHAT THE CELL-LEVEL ROLLUP DOES TO A CORRIDOR, ALGEBRAICALLY. Cells are
equal-size and the covariates are properties of the street, so every cell on one
street shares a single mu, and therefore a single weight w. Summing the cells:

    corridor_eb = w * (n_cells * mu)  +  (1 - w) * corridor_observed

The corridor estimate is a genuine blend of what a road of this class is
expected to produce across its footprint and what this road actually produced.
That is the regression-to-the-mean correction §3.3 promises, and it is why the
whole-corridor fit could not deliver it: there, mu was in the thousands and w
rounded to zero.

METHOD (Highway Safety Manual, part B):

    SPF     negative binomial, casualties ~ road attributes, equal-size cells
    EB      w = 1 / (1 + mu/k),  estimate = w*mu + (1-w)*observed
            where k is the NB dispersion, Var = mu + mu^2/k

EB shrinks a cell's observed count toward what the model expects for a road of
its kind. That correction is the entire point: high-crash sites regress toward
the mean, so ranking on raw observed harm over-credits whichever sites had a bad
three years, and a naive before-and-after over-credits any treatment applied to
them (§3.3).

NO LENGTH OFFSET. The whole-corridor fit carried `log(length_ft)` as an exposure
offset because corridors differ in length by orders of magnitude. Cells do not:
every cell has the same area to within 0.61% citywide (see CELL SIZE above), so
the exposure term is a constant and belongs in the intercept. Keeping the offset
here would make the model explain a cell's harm by the length of the whole street
it sits on, which is not a property of the cell.

THE FOOTPRINT RULE — a defect this script shipped once, and the reason for
`observed_in_cells`. A cell requires coordinates, so 65,965 crashes (7.8%) that
carry a street name but no coordinate sit in no cell at all. The first version of
the rollup summed `eb_estimate` over cells and then compared it against a
full-corridor `observed` total that included those crashes. The two sides
measured different footprints, and the difference was read as EB shrinkage.

Measured: the gap is 18,499 of 248,856 training casualties (7.4%), and
`eb_estimate` summed to EXACTLY `observed_in_cells` — proof that citywide net
shrinkage was ~0 and the entire apparent correction was missing coordinates. It
was concentrated on precisely the roads §2.6 exists to defend: 17.5% of
limited-access corridors' training harm against 5.5% for surface. On Belt Pkwy,
686 casualties of coverage loss against 26 of real shrinkage — 96% of the
"EB correction" on the city's worst corridor was absent data wearing an EB label,
which is the §2.7 failure arriving by a new route.

It also manufactured a negative result. Holding the estimator fixed and changing
only the baseline's footprint moves corridor top-250 from -0.27pp to +0.04pp and
top-500 from -0.60pp to -0.00pp. **The negative corridor lift is retracted.**

So: a ranking benchmark must cover the same crashes the estimate does. Every
corridor row carries `observed_in_cells`, `holdout_in_cells` and `coverage`, the
validation compares like with like, and a corridor whose estimate omits part of
its harm says so rather than absorbing the difference.

AND THE MISSING COORDINATES ARE NOT RANDOM — THIS IS §2.6's SIBLING FAILURE.
Coordinate coverage of casualties, measured by road class on 2026-08-16:

    surface   0.943        highway   0.865
    bridge    0.153        tunnel    0.210

NYPD does not geocode crashes on a span; there is no street address in the middle
of the Brooklyn Bridge. So **any coordinate-derived estimate structurally
understates every bridge and tunnel in the city by roughly six times**:

    BROOKLYN BRIDGE        305 observed casualties,  16 in cells, coverage 0.05
    NEW ENGLAND THRUWAY    468                       52            0.11
    NASSAU EXPY            395                       61            0.15
    HUTCHINSON RIVER PKWY  918                      445            0.48

Colour a map by cell-level EB and the Brooklyn Bridge reads as near-harmless.
That is the same class of error as the one §2.6 is built to expose — a whole
category of harm dropped because of how the paperwork was filled in — and it
arrives through the EB layer rather than through the borough column.

**This is unresolved and it is a decision, not a bug to patch quietly.** The
options are to carry no-coordinate harm into the corridor estimate explicitly
(labelled, never silently), to mark bridges and tunnels as un-estimatable and let
their observed counts speak, or to accept a cell-only ranking and state that it
under-ranks limited-access facilities. `coverage` is emitted so that whichever is
chosen, the shortfall is visible rather than absorbed. See NEXT-SESSION.md.

EXPOSURE IS STILL NOT TRAFFIC VOLUME. NYC does not publish AADT at this
granularity (TODOS.md). It means a busy cell and a quiet one of equal size look
equally exposed, so §3.3's caveat that counts are not volume-adjusted stays
mandatory wherever this number is shown.

WHAT THE LOW-COUNT WIN IS, AND WHAT IT IS NOT. The stratified table this script
prints shows a large lift over raw ranking where counts are small — at cell level
+14.6pp among the 30,966 cells with zero training casualties. That is a real
finding, and it is NOT an Empirical Bayes achievement. It belongs to the SPF.

When `observed` is 0 the estimate reduces to `w*mu`, and since `w = 1/(1+mu/k)`
that is `mu/(1+mu/k)` — strictly increasing in mu. So EB's ordering of zero-count
cells IS mu's ordering. Verified both ways: the identity holds to 3e-4, and
top-decile capture among those cells is 20.24% under either, identical to four
decimals. The `vs mu` column in the stratified table prints 0.00 there for
exactly this reason, and it is in the output so the claim cannot be made
carelessly.

The honest statement is therefore: **raw observed count cannot rank a cell that
has never had a casualty, and the SPF can.** 39.8% of the map's cells are in that
position. Empirical Bayes is what blends that prediction with a site's own
history once the site has one — which is a different, smaller, and separately
measured contribution. Quote the two separately or neither.

THE UNIT UNIVERSE IS CELLS THAT APPEAR IN THE TRAINING WINDOW, and that is a
real limitation stated rather than hidden. A cell only exists here because a
crash was recorded in it, so the model never sees the city's genuinely
crash-free ground. Both rankings are scored on the same universe, so the
comparison below is fair; but the absolute capture rates describe "of the harm
that lands where harm has landed before", not "of all harm".
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.streets import canonical_street  # noqa: E402

RECOVERED = ROOT / "data" / "raw" / "crashes_recovered.parquet"
FEATURES = ROOT / "data" / "raw" / "corridor_features.parquet"
OUT_CELLS = ROOT / "data" / "raw" / "eb_cells.parquet"
OUT = ROOT / "data" / "eb_corridors.csv"

# Trained on the settled years; held out on what came after. The holdout ends
# where the feed does, not where the calendar does — 2026-06-11 is the newest
# crash the API carries, re-verified live on 2026-08-16.
TRAIN_END = "2023-12-31"
HOLDOUT_START = "2024-01-01"
HOLDOUT_END = "2026-06-11"

# §2.1 bins the map at round(lat/lon, 3) ~ 110m. The EB unit is that same grid,
# so the map is coloured by the numbers it ranks on.
CELL_DP = 3


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (cells, corridors) keyed on the street-cell and the street.

    Both windows are aggregated on the SAME key so a cell that appears only in
    the holdout is visible as such rather than silently dropped.
    """
    con = duckdb.connect()
    cr = con.execute(f"""
        SELECT on_street_name, cross_street_name, crash_date, latitude, longitude,
               number_of_persons_injured AS inj, number_of_persons_killed AS kil
        FROM read_parquet('{RECOVERED.as_posix()}')
    """).df()

    cr["canonical"] = [canonical_street(a, b)[0]
                       for a, b in zip(cr["on_street_name"], cr["cross_street_name"])]
    cr = cr.dropna(subset=["canonical"])

    # A crash with no coordinate cannot be placed in a cell. It keeps its
    # corridor, so corridor OBSERVED counts stay whole, but it cannot be
    # modelled. Reported rather than dropped in silence — spec §4.2.
    no_coord = cr["latitude"].isna() | cr["longitude"].isna()
    print(f"  {int(no_coord.sum()):,} crashes carry a street but no coordinate "
          f"({no_coord.mean()*100:.1f}%) — excluded from cells, kept in corridor totals")

    cr["cas"] = cr["inj"].fillna(0) + cr["kil"].fillna(0)
    cr["crash_date"] = pd.to_datetime(cr["crash_date"])
    cr["is_train"] = cr["crash_date"] <= TRAIN_END
    cr["is_hold"] = cr["crash_date"] >= HOLDOUT_START

    # Masked columns rather than a lambda per group: the lambda form indexes the
    # parent frame once per group, which at this row count is minutes instead of
    # seconds and produces exactly the same numbers.
    cr["cas_train"] = cr["cas"].where(cr["is_train"], 0.0)
    cr["cas_hold"] = cr["cas"].where(cr["is_hold"], 0.0)
    cr["n_train"] = cr["is_train"].astype(int)

    geo = cr[~no_coord].copy()
    geo["lat_c"] = geo["latitude"].round(CELL_DP)
    geo["lon_c"] = geo["longitude"].round(CELL_DP)

    agg = dict(observed=("cas_train", "sum"), crashes=("n_train", "sum"),
               holdout=("cas_hold", "sum"))
    cells = geo.groupby(["canonical", "lat_c", "lon_c"]).agg(**agg).reset_index()

    # Cells first seen in the holdout are not scorable — the model has no history
    # for them. They are held aside explicitly so the validation denominator can
    # say what it excludes.
    cells["in_train"] = cells["crashes"] > 0

    corridors = cr.groupby("canonical").agg(**agg).reset_index()

    feats = pd.read_parquet(FEATURES)[
        ["canonical", "n_units", "length_ft", "speed", "lanes", "width",
         "is_highway", "limited_access_share"]]
    cells = cells.merge(feats, on="canonical", how="left")
    corridors = corridors.merge(feats, on="canonical", how="left")
    return cells, corridors


def fit(cells: pd.DataFrame) -> pd.DataFrame:
    """Fit the SPF on training cells that carry road attributes.

    Covariates are properties of the STREET, so every cell on one street shares a
    prediction. That is intentional: the SPF answers "what does a road of this
    kind produce in a 110m cell", and the cell's own history is what EB then
    blends against. Putting anything cell-specific and outcome-derived in here
    would leak the label into its own prediction.
    """
    scorable = cells["in_train"]
    ok = (scorable
          & cells["lanes"].notna() & cells["speed"].notna()
          & cells["width"].notna() & cells["is_highway"].notna())
    fitset = cells[ok].copy()
    print(f"  fitting on {len(fitset):,} training cells with road attributes")
    print(f"  ({int((scorable & ~ok).sum()):,} training cells unmatched to LION, "
          f"labelled; {int((~scorable).sum()):,} cells first seen in holdout)")

    X = pd.DataFrame({
        "log_lanes": np.log(fitset["lanes"].clip(lower=1)),
        "speed": fitset["speed"],
        "limited_access_share": fitset["limited_access_share"].fillna(0.0),
        "log_width": np.log(fitset["width"].clip(lower=1)),
    }, index=fitset.index)
    X = sm.add_constant(X)
    y = fitset["observed"].astype(float)

    print(f"  casualties per cell: mean {y.mean():.2f}, median {y.median():.0f}, "
          f"max {y.max():.0f}, share zero {(y == 0).mean()*100:.1f}%")

    # Estimate the dispersion first; the GLM needs alpha supplied. No offset:
    # cells are equal-size, so exposure is a constant and lives in the intercept.
    nb = sm.NegativeBinomial(y, X).fit(disp=0, maxiter=500)
    alpha = float(nb.params.get("alpha", np.nan))
    if not np.isfinite(alpha) or alpha <= 0:
        raise SystemExit("negative binomial did not return a usable dispersion")
    k = 1.0 / alpha
    print(f"  NB dispersion alpha={alpha:.4f}  ->  k={k:.3f}")

    glm = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit()
    mu = glm.predict(X)

    # HSM Empirical Bayes weight. At this granularity mu is small, so w is
    # substantial and the shrinkage does real work — the whole reason the unit
    # changed. A cell with a long quiet history keeps more of its own count; a
    # rarely-observed one is pulled toward what the model expects for a road of
    # its kind.
    w = 1.0 / (1.0 + mu / k)
    fitset["spf_prediction"] = mu
    fitset["eb_weight"] = w
    fitset["eb_estimate"] = w * mu + (1.0 - w) * fitset["observed"]
    print(f"  EB weight: mean {w.mean():.3f}, median {np.median(w):.3f} "
          f"(at corridor level this was 0.0002)")

    out = cells.merge(
        fitset[["canonical", "lat_c", "lon_c",
                "spf_prediction", "eb_weight", "eb_estimate"]],
        on=["canonical", "lat_c", "lon_c"], how="left")
    out["eb_matched"] = out["eb_estimate"].notna()
    return out


def rollup(cells: pd.DataFrame, corridors: pd.DataFrame) -> pd.DataFrame:
    """A corridor's estimate is the SUM of its cells' shrunken estimates.

    Only scored cells contribute. A corridor with no scored cell at all is
    labelled unmatched rather than silently handed its raw observed count while
    still being presented as an estimate — spec §4.2 and §2.7.
    """
    scored = cells[cells["eb_matched"]]
    agg = scored.groupby("canonical").agg(
        eb_estimate=("eb_estimate", "sum"),
        spf_prediction=("spf_prediction", "sum"),
        cells_scored=("eb_estimate", "size"),
        observed_in_cells=("observed", "sum"),
        holdout_in_cells=("holdout", "sum"),
        eb_weight=("eb_weight", "mean"),
    ).reset_index()

    out = corridors.merge(agg, on="canonical", how="left")
    out["eb_matched"] = out["eb_estimate"].notna()
    out["cells_scored"] = out["cells_scored"].fillna(0).astype(int)
    out["observed_in_cells"] = out["observed_in_cells"].fillna(0.0)
    out["holdout_in_cells"] = out["holdout_in_cells"].fillna(0.0)

    # The share of a corridor's observed harm the estimate actually covers. A
    # corridor whose crashes largely lack coordinates gets an estimate over a
    # fraction of its harm, and the product must say so rather than let the
    # missing part read as an EB correction. See THE FOOTPRINT RULE above.
    out["coverage"] = (out["observed_in_cells"]
                       / out["observed"].where(out["observed"] > 0)).astype(float)
    return out


def footprint_report(corr: pd.DataFrame) -> None:
    """Show how much corridor harm the estimate covers, and prove it is coverage.

    This block exists so the retracted result cannot come back quietly. If
    `eb_estimate` and `observed_in_cells` agree citywide, then whatever separates
    `eb_estimate` from `observed` is missing coordinates and not shrinkage, and
    ranking against `observed` would measure the coordinates.
    """
    m = corr[corr["eb_matched"]]
    obs = m["observed"].sum()
    in_cells = m["observed_in_cells"].sum()
    eb = m["eb_estimate"].sum()
    gap = obs - in_cells

    print(f"\n  --- footprint check ---")
    print(f"  corridor observed          {obs:>12,.0f}")
    print(f"  corridor observed_in_cells {in_cells:>12,.0f}")
    print(f"  footprint gap              {gap:>12,.0f}  ({gap/obs*100:.1f}%)")
    print(f"  eb_estimate                {eb:>12,.0f}   "
          f"net shrinkage vs in-cells {in_cells - eb:>+,.0f}")

    if "is_highway" in m.columns:
        la = m["is_highway"].fillna(0) == 1
        for label, sel in (("limited-access", la), ("surface", ~la)):
            o = m.loc[sel, "observed"].sum()
            c = m.loc[sel, "observed_in_cells"].sum()
            if o > 0:
                print(f"    {label:<15} n={int(sel.sum()):>5}  "
                      f"observed {o:>9,.0f}  gap {o-c:>8,.0f} = {(o-c)/o*100:5.1f}%")

    # Restricted to corridors with real volume. Ranked purely by coverage, the
    # list fills with streets that had one crash and no coordinate for it —
    # arithmetically the worst coverage in the city and of no consequence to
    # anybody. The corridors that matter are the ones carrying enough harm to be
    # ranked and shown.
    material = m[m["observed"] >= 250]
    worst = material.nsmallest(8, "coverage")[
        ["canonical", "observed", "observed_in_cells", "coverage", "is_highway"]]
    print(f"\n  Lowest coverage among the {len(material):,} corridors with 250+ "
          f"observed casualties.")
    print(f"  These carry a real estimate over an incomplete footprint and MUST be "
          f"labelled in the UI (§4.2), not silently ranked:")
    print(worst.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))


def rate_adjustment() -> float:
    """Holdout years divided by training years.

    The training window is five years and the holdout is about two and a half, so
    a training count is roughly twice a holdout count for the same site. Any
    predicted-versus-actual error metric has to put them on one scale first, or it
    measures the window lengths rather than the model.
    """
    train_days = (pd.Timestamp(TRAIN_END) - pd.Timestamp("2019-01-01")).days + 1
    hold_days = (pd.Timestamp(HOLDOUT_END) - pd.Timestamp(HOLDOUT_START)).days + 1
    return hold_days / train_days


def capture(df: pd.DataFrame, col: str, n: int, holdout_col: str) -> float:
    """Share of holdout casualties sitting in the top-n units by `col`."""
    total = df[holdout_col].sum()
    if total <= 0:
        raise SystemExit("holdout window has no casualties; the split is wrong")
    return df.nlargest(n, col)[holdout_col].sum() / total * 100


def capture_lift_ci(df: pd.DataFrame, n: int, holdout_col: str, baseline: str,
                    draws: int = 400, seed: int = 20260816) -> tuple[float, float, float]:
    """Capture lift of EB over `baseline`, with a percentile bootstrap interval.

    Resampling units — rather than holding the top-N sets fixed — lets the
    ranking itself move between draws, which is part of the uncertainty. A lift
    quoted to two decimals with no interval implies precision this data does not
    support: the intervals below routinely straddle zero.
    """
    rng = np.random.default_rng(seed)
    eb = capture(df, "eb_estimate", n, holdout_col)
    raw = capture(df, baseline, n, holdout_col)
    point = eb - raw

    idx = np.arange(len(df))
    lifts = np.empty(draws)
    for i in range(draws):
        sample = df.iloc[rng.choice(idx, size=len(idx), replace=True)]
        lifts[i] = (capture(sample, "eb_estimate", n, holdout_col)
                    - capture(sample, baseline, n, holdout_col))
    lo, hi = np.percentile(lifts, [2.5, 97.5])
    return point, lo, hi


def error_metrics(df: pd.DataFrame, holdout_col: str, baseline: str, R: float) -> None:
    """Rate-adjusted predicted-versus-actual holdout error.

    This is the test an Empirical Bayes estimate is actually for. Top-N capture
    asks which ranking finds the worst sites; it cannot see whether the estimate
    of how much harm they will produce is any better. EB's claim is about the
    second thing.

    RMSE, not MAE. MAE is minimised by the conditional median, and for a unit
    whose mean count is below one that median is exactly zero — so MAE rewards a
    predictor for saying "nothing will happen here", which is not the property
    being tested.
    """
    actual = df[holdout_col].to_numpy(dtype=float)
    print(f"  {'predictor':>22} {'RMSE':>10} {'MAE':>10}")
    for label, col in (("raw observed count", baseline),
                       ("SPF alone (mu)", "spf_prediction"),
                       ("EB estimate", "eb_estimate")):
        pred = df[col].to_numpy(dtype=float) * R
        rmse = float(np.sqrt(np.mean((pred - actual) ** 2)))
        mae = float(np.mean(np.abs(pred - actual)))
        print(f"  {label:>22} {rmse:>10.4f} {mae:>10.4f}")


def stratified_lift(df: pd.DataFrame, holdout_col: str, baseline: str) -> None:
    """Where does EB help? Stratify by how much history the unit has.

    Empirical Bayes corrects small-sample noise, so its benefit should be largest
    where counts are smallest and vanish where they are large. A single global
    number averages those two regimes together and reports something that is true
    of neither.

    The zero-count stratum is reported against the SPF alone as well, because raw
    observed count cannot order units that all have the same count of zero — and
    "EB beats a baseline that cannot rank" is not a claim worth making.
    """
    bins = [(-0.5, 0.5, "0"), (0.5, 2.5, "1-2"), (2.5, 5.5, "3-5"),
            (5.5, 10.5, "6-10"), (10.5, 25.5, "11-25"), (25.5, np.inf, "26+")]
    print(f"  {'stratum':>8} {'units':>9} {'holdout':>10} "
          f"{'EB':>9} {'raw':>9} {'lift':>8} {'vs mu':>8}")
    for lo, hi, label in bins:
        sel = df[(df[baseline] > lo) & (df[baseline] <= hi)]
        if len(sel) < 20:
            continue
        held = sel[holdout_col].sum()
        if held <= 0:
            continue
        n = max(1, int(len(sel) * 0.20))
        eb = capture(sel, "eb_estimate", n, holdout_col)
        raw = capture(sel, baseline, n, holdout_col)
        mu = capture(sel, "spf_prediction", n, holdout_col)
        print(f"  {label:>8} {len(sel):>9,} {held:>10,.0f} "
              f"{eb:>8.2f}% {raw:>8.2f}% {eb - raw:>+7.2f} {eb - mu:>+7.2f}")


def validate(df: pd.DataFrame, level: str, sizes: tuple[int, ...],
             holdout_col: str, baseline: str, R: float) -> None:
    """Does EB beat the raw observed count, and at what?

    Both rankings are restricted to units the model could score, because a
    ranking that silently drops its unmatched units is scoring an easier problem
    than the one the product faces.

    `baseline` and `holdout_col` exist so the comparison can be made
    footprint-consistent at corridor level — see THE FOOTPRINT RULE in the module
    docstring. Comparing an estimate built on geocoded cells against a count that
    includes crashes with no coordinate measures the coordinates, not the model.
    """
    m = df[df["eb_matched"]].copy()
    print(f"\n  === {level} ===")
    print(f"  {len(m):,} scored units, {m[holdout_col].sum():,.0f} holdout "
          f"casualties, baseline `{baseline}`")

    print(f"\n  Top-N capture of holdout harm, with 95% bootstrap intervals:")
    print(f"  {'top-N':>8} {'EB':>9} {'raw':>9} {'lift (pp)':>11} {'95% CI':>20}")
    for n in sizes:
        if n > len(m):
            continue
        eb = capture(m, "eb_estimate", n, holdout_col)
        raw = capture(m, baseline, n, holdout_col)
        point, lo, hi = capture_lift_ci(m, n, holdout_col, baseline)
        straddles = "" if (lo > 0 or hi < 0) else "  (straddles 0)"
        print(f"  {n:>8} {eb:>8.2f}% {raw:>8.2f}% {point:>+10.2f} "
              f"  [{lo:+.2f}, {hi:+.2f}]{straddles}")

    print(f"\n  Rate-adjusted predicted-vs-actual holdout error (R={R:.5f}):")
    error_metrics(m, holdout_col, baseline, R)

    print(f"\n  Lift by how much history the unit has (top 20% within stratum):")
    stratified_lift(m, holdout_col, baseline)


def main() -> int:
    print("Loading...")
    cells, corridors = load()
    print(f"  {len(cells):,} street-cells, {len(corridors):,} corridors")
    print(f"  {corridors['observed'].sum():,.0f} train casualties, "
          f"{corridors['holdout'].sum():,.0f} holdout casualties")

    print("Fitting SPF at cell level...")
    cells = fit(cells)

    print("Rolling cells up to corridors...")
    corr = rollup(cells, corridors)
    print(f"  {int(corr['eb_matched'].sum()):,} corridors scored, "
          f"{int((~corr['eb_matched']).sum()):,} unmatched")

    footprint_report(corr)

    R = rate_adjustment()
    validate(cells, "CELL level", (500, 1000, 2500, 5000),
             holdout_col="holdout", baseline="observed", R=R)
    # Corridor level compares like with like: an estimate summed over geocoded
    # cells against a count over the same cells. See THE FOOTPRINT RULE.
    validate(corr, "CORRIDOR level (coverage-fair)", (50, 100, 250, 500),
             holdout_col="holdout_in_cells", baseline="observed_in_cells", R=R)

    cells.to_parquet(OUT_CELLS, index=False)
    print(f"\nWrote {OUT_CELLS} ({OUT_CELLS.stat().st_size/1e6:.1f} MB)")

    cols = ["canonical", "crashes", "observed", "observed_in_cells", "holdout",
            "holdout_in_cells", "coverage", "cells_scored",
            "length_ft", "lanes", "speed", "is_highway", "limited_access_share",
            "n_units", "spf_prediction", "eb_weight", "eb_estimate", "eb_matched"]
    corr[cols].sort_values("eb_estimate", ascending=False).to_csv(OUT, index=False)
    print(f"Wrote {OUT}")

    print("\nTop 10 corridors by EB expected all-mode casualties:")
    print(corr.nlargest(10, "eb_estimate")[
        ["canonical", "observed", "observed_in_cells", "coverage", "cells_scored",
         "spf_prediction", "eb_estimate"]]
        .to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
