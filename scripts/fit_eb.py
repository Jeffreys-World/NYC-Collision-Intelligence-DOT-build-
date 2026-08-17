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
is one canonical street within one ~110m cell — `round(lat, 3), round(lon, 3)` —
which is the same grid §2.1 bins the map on, and close in size to the sibling
repo's 150ft segments. Most cells carry 0-5 casualties, which is exactly the
regime EB was built for. A corridor's estimate is then the SUM of its cells'
shrunken estimates, so the corridor figure inherits a real correction instead of
a rounding error, and the map can be coloured by the same numbers it ranks on.

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
a `round(lat/lon, 3)` cell is ~110m on a side everywhere in the city, so the
exposure term is a constant and belongs in the intercept. Keeping the offset here
would make the model explain a cell's harm by the length of the whole street it
sits on, which is not a property of the cell.

EXPOSURE IS STILL NOT TRAFFIC VOLUME. NYC does not publish AADT at this
granularity (TODOS.md). It means a busy cell and a quiet one of equal size look
equally exposed, so §3.3's caveat that counts are not volume-adjusted stays
mandatory wherever this number is shown.

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
# where the feed does, not where the calendar does.
TRAIN_END = "2023-12-31"
HOLDOUT_START = "2024-01-01"

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
        eb_weight=("eb_weight", "mean"),
    ).reset_index()

    out = corridors.merge(agg, on="canonical", how="left")
    out["eb_matched"] = out["eb_estimate"].notna()
    out["cells_scored"] = out["cells_scored"].fillna(0).astype(int)
    return out


def capture(df: pd.DataFrame, col: str, n: int) -> float:
    """Share of holdout casualties sitting in the top-n units by `col`."""
    total = df["holdout"].sum()
    if total <= 0:
        raise SystemExit("holdout window has no casualties; the split is wrong")
    return df.nlargest(n, col)["holdout"].sum() / total * 100


def validate(df: pd.DataFrame, level: str, sizes: tuple[int, ...]) -> None:
    """Does ranking by EB beat ranking by raw observed count?

    Both rankings are restricted to units the model could score, because a
    ranking that silently drops its unmatched units is scoring an easier problem
    than the one the product faces.
    """
    m = df[df["eb_matched"]].copy()
    print(f"\n  {level}: {len(m):,} scored, "
          f"{m['holdout'].sum():,.0f} holdout casualties on them")
    print(f"  {'top-N':>8} {'EB':>10} {'raw count':>12} {'lift (pp)':>11}")
    for n in sizes:
        if n > len(m):
            continue
        eb = capture(m, "eb_estimate", n)
        raw = capture(m, "observed", n)
        print(f"  {n:>8} {eb:>9.2f}% {raw:>11.2f}% {eb - raw:>+10.2f}")


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

    validate(cells, "CELL level", (500, 1000, 2500, 5000))
    validate(corr, "CORRIDOR level", (50, 100, 250, 500))

    cells.to_parquet(OUT_CELLS, index=False)
    print(f"\nWrote {OUT_CELLS} ({OUT_CELLS.stat().st_size/1e6:.1f} MB)")

    cols = ["canonical", "crashes", "observed", "holdout", "cells_scored",
            "length_ft", "lanes", "speed", "is_highway", "limited_access_share",
            "n_units", "spf_prediction", "eb_weight", "eb_estimate", "eb_matched"]
    corr[cols].sort_values("eb_estimate", ascending=False).to_csv(OUT, index=False)
    print(f"Wrote {OUT}")

    print("\nTop 10 corridors by EB expected all-mode casualties:")
    print(corr.nlargest(10, "eb_estimate")[
        ["canonical", "observed", "cells_scored", "spf_prediction", "eb_estimate"]]
        .to_string(index=False, float_format=lambda v: f"{v:,.1f}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
