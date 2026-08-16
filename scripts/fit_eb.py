"""Fit a Safety Performance Function and Empirical Bayes estimate.

    .venv/Scripts/python scripts/fit_eb.py

!!! UNFINISHED — HALF-REWORKED. READ THIS BEFORE RUNNING IT. !!!

    The docstring below describes the STREET-CELL unit, which is where this
    needs to end up and why. The CODE below still fits at WHOLE-CORRIDOR level,
    which was measured on 2026-08-16 and does not work: EB came out equal to the
    observed count to four significant figures and the lift over raw ranking was
    +0.00pp.

    So this script currently RUNS and produces data/eb_corridors.csv, but that
    output is NOT usable for §2.7 ranking — it is raw observed harm wearing an
    EB label, which is precisely what the spec forbids.

    What is left: rewrite load() to group by
    (canonical, round(lat,3), round(lon,3)), drop the log-length offset since
    the cells are equal-size, fit on that, then sum each corridor's cell-level
    eb_estimate back up. Validation should print capture at BOTH cell and
    corridor level. See NEXT-SESSION.md.

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

METHOD (Highway Safety Manual, part B):

    SPF     negative binomial, casualties ~ road attributes, equal-size cells
    EB      w = 1 / (1 + mu/k),  estimate = w*mu + (1-w)*observed
            where k is the NB dispersion, Var = mu + mu^2/k

EB shrinks a corridor's observed count toward what the model expects for a road
of its kind. That correction is the entire point: high-crash sites regress
toward the mean, so ranking on raw observed harm over-credits whichever sites
had a bad three years, and a naive before-and-after over-credits any treatment
applied to them (§3.3).

EXPOSURE IS SEGMENT LENGTH, NOT TRAFFIC VOLUME. NYC does not publish AADT at
this granularity (TODOS.md). Length is the same proxy the sibling repo uses. It
means a busy corridor and a quiet one of equal length look equally exposed, so
§3.3's caveat that counts are not volume-adjusted stays mandatory wherever this
number is shown.
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
OUT = ROOT / "data" / "eb_corridors.csv"

# Trained on the settled years; held out on what came after. The holdout ends
# where the feed does, not where the calendar does.
TRAIN_END = "2023-12-31"
HOLDOUT_START = "2024-01-01"


def load() -> pd.DataFrame:
    con = duckdb.connect()
    cr = con.execute(f"""
        SELECT on_street_name, cross_street_name, crash_date,
               number_of_persons_injured AS inj, number_of_persons_killed AS kil
        FROM read_parquet('{RECOVERED.as_posix()}')
    """).df()
    cr["canonical"] = [canonical_street(a, b)[0]
                       for a, b in zip(cr["on_street_name"], cr["cross_street_name"])]
    cr = cr.dropna(subset=["canonical"])
    cr["cas"] = cr["inj"].fillna(0) + cr["kil"].fillna(0)
    cr["crash_date"] = pd.to_datetime(cr["crash_date"])

    train = cr[cr["crash_date"] <= TRAIN_END]
    hold = cr[cr["crash_date"] >= HOLDOUT_START]

    g = train.groupby("canonical").agg(
        observed=("cas", "sum"), crashes=("cas", "size")).reset_index()
    h = hold.groupby("canonical").agg(holdout=("cas", "sum")).reset_index()

    feats = pd.read_parquet(FEATURES)[
        ["canonical", "n_units", "length_ft", "speed", "lanes", "width", "is_highway"]]
    df = g.merge(h, on="canonical", how="left").merge(feats, on="canonical", how="left")
    df["holdout"] = df["holdout"].fillna(0)
    return df


def fit(df: pd.DataFrame) -> pd.DataFrame:
    """Fit on corridors that have road attributes; label the rest unmatched."""
    ok = (df["length_ft"].notna() & (df["length_ft"] > 0)
          & df["lanes"].notna() & df["speed"].notna())
    fitset = df[ok].copy()
    print(f"  fitting on {len(fitset):,} corridors with road attributes "
          f"({(~ok).sum():,} unmatched, labelled)")

    X = pd.DataFrame({
        "log_lanes": np.log(fitset["lanes"].clip(lower=1)),
        "speed": fitset["speed"].fillna(fitset["speed"].median()),
        "is_highway": fitset["is_highway"].fillna(0).astype(float),
        "log_width": np.log(fitset["width"].clip(lower=1).fillna(1)),
    })
    X = sm.add_constant(X)
    offset = np.log(fitset["length_ft"].clip(lower=1))
    y = fitset["observed"].astype(float)

    # Estimate the dispersion first; the GLM needs alpha supplied.
    nb = sm.NegativeBinomial(y, X, offset=offset).fit(disp=0, maxiter=200)
    alpha = float(nb.params.get("alpha", np.nan))
    if not np.isfinite(alpha) or alpha <= 0:
        raise SystemExit("negative binomial did not return a usable dispersion")
    k = 1.0 / alpha
    print(f"  NB dispersion alpha={alpha:.4f}  ->  k={k:.3f}")

    glm = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha),
                 offset=offset).fit()
    mu = glm.predict(X, offset=offset)

    # HSM Empirical Bayes weight. A long, well-observed corridor gets a weight
    # near zero and keeps its own history; a short or rarely-hit one is pulled
    # toward what the model expects for a road of its kind.
    w = 1.0 / (1.0 + mu / k)
    fitset["spf_prediction"] = mu
    fitset["eb_weight"] = w
    fitset["eb_estimate"] = w * mu + (1.0 - w) * fitset["observed"]

    out = df.merge(
        fitset[["canonical", "spf_prediction", "eb_weight", "eb_estimate"]],
        on="canonical", how="left")
    out["eb_matched"] = out["eb_estimate"].notna()
    return out


def capture(df: pd.DataFrame, col: str, n: int) -> float:
    """Share of holdout casualties sitting in the top-n corridors by `col`."""
    total = df["holdout"].sum()
    if total <= 0:
        raise SystemExit("holdout window has no casualties; the split is wrong")
    top = df.nlargest(n, col)
    return top["holdout"].sum() / total * 100


def validate(df: pd.DataFrame) -> None:
    """Does ranking by EB beat ranking by raw observed count?

    The honest comparison: both rankings are restricted to corridors the model
    could score, because a ranking that silently drops its unmatched corridors is
    scoring an easier problem than the one the product faces.
    """
    m = df[df["eb_matched"]].copy()
    print(f"\n  validating on {len(m):,} scored corridors, "
          f"{m['holdout'].sum():,.0f} holdout casualties")
    print(f"  {'top-N':>8} {'EB':>10} {'raw count':>12} {'lift (pp)':>11}")
    for n in (50, 100, 250, 500):
        eb = capture(m, "eb_estimate", n)
        raw = capture(m, "observed", n)
        print(f"  {n:>8} {eb:>9.2f}% {raw:>11.2f}% {eb - raw:>+10.2f}")


def main() -> int:
    print("Loading...")
    df = load()
    print(f"  {len(df):,} corridors, {df['observed'].sum():,.0f} train casualties, "
          f"{df['holdout'].sum():,.0f} holdout casualties")

    print("Fitting SPF...")
    df = fit(df)
    validate(df)

    cols = ["canonical", "crashes", "observed", "holdout", "length_ft", "lanes",
            "speed", "is_highway", "n_units", "spf_prediction", "eb_weight",
            "eb_estimate", "eb_matched"]
    df[cols].sort_values("eb_estimate", ascending=False).to_csv(OUT, index=False)
    print(f"\nWrote {OUT}  ({int(df['eb_matched'].sum()):,} scored, "
          f"{int((~df['eb_matched']).sum()):,} unmatched)")
    print("\nTop 10 corridors by EB expected all-mode casualties:")
    print(df.nlargest(10, "eb_estimate")[
        ["canonical", "observed", "spf_prediction", "eb_estimate"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
